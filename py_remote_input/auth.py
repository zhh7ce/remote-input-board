"""PIN authentication with persistent trusted devices.

Model used by phone/desktop pairing apps (e.g. KDE Connect) and web "remember
this device" flows: the PIN is entered once per device. On success the phone
receives an opaque random token it keeps in localStorage; the server remembers
the device on disk. Trust is **not** tied to the phone's IP (LAN IPs change all
the time: DHCP renewals, iOS/Android private Wi-Fi addresses) and survives
server restarts, until the device is explicitly unpaired.

Only SHA-256 hashes of tokens are stored, so a leaked trusted_devices.json does
not reveal usable tokens. PIN brute force is still rate limited per source IP.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time

PIN_LENGTH = 6
PIN_FILE_NAME = "pin.txt"
TRUSTED_DEVICES_FILE_NAME = "trusted_devices.json"

MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 10 * 60
LOCKOUT_BASE_SECONDS = 15
LOCKOUT_CAP_SECONDS = 5 * 60
# Persist "last used" bookkeeping at most this often.
USAGE_FLUSH_INTERVAL_SECONDS = 60


class InvalidPin(Exception):
    """Raised when the supplied PIN does not match."""


class RateLimited(Exception):
    """Raised when too many failed attempts come from one IP."""

    def __init__(self, retry_after: int):
        super().__init__(f"Too many attempts, retry in {retry_after}s.")
        self.retry_after = retry_after


def generate_pin(length: int = PIN_LENGTH) -> str:
    upper = 10 ** length
    return str(secrets.randbelow(upper)).zfill(length)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_pin(base_dir: Path) -> tuple[str, Path, bool]:
    """Resolve the PIN from PIN_CODE env or pin.txt, generating one if needed.

    Returns (pin, source_path, generated).
    """
    env_pin = os.environ.get("PIN_CODE", "").strip()
    if env_pin:
        if not env_pin.isdigit():
            raise RuntimeError("PIN_CODE must contain digits only (e.g. 482915).")
        return env_pin, base_dir / PIN_FILE_NAME, False

    pin_path = base_dir / PIN_FILE_NAME
    if pin_path.exists():
        pin = pin_path.read_text(encoding="utf-8").strip()
        if not pin.isdigit():
            raise RuntimeError(f"{pin_path} must contain digits only.")
        return pin, pin_path, False

    pin = generate_pin(PIN_LENGTH)
    pin_path.write_text(pin + "\n", encoding="utf-8")
    pin_path.chmod(0o600)
    return pin, pin_path, True


class AuthStore:
    """PIN gate plus a persistent, IP-independent trusted-device registry."""

    def __init__(self, pin: str, trusted_path: Path | None = None):
        self._pin = pin
        self.pin_length = len(pin)
        self._trusted_path = trusted_path
        # hash -> {"createdAt", "lastUsedAt", "lastIp"}
        self._devices: dict[str, dict] = {}
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._last_flush = 0.0
        self._load_devices()

    def _load_devices(self) -> None:
        if self._trusted_path is None or not self._trusted_path.exists():
            return
        try:
            data = json.loads(self._trusted_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, list):
            for record in data:
                if isinstance(record, dict) and isinstance(record.get("hash"), str):
                    self._devices[record["hash"]] = {
                        "createdAt": record.get("createdAt", 0),
                        "lastUsedAt": record.get("lastUsedAt", 0),
                        "lastIp": record.get("lastIp", ""),
                    }

    def _flush_locked(self, *, force: bool = False) -> None:
        if self._trusted_path is None:
            return
        now = time.time()
        if not force and (not self._dirty or now - self._last_flush < USAGE_FLUSH_INTERVAL_SECONDS):
            return
        payload = [
            {"hash": token_hash, **record}
            for token_hash, record in self._devices.items()
        ]
        tmp_path = self._trusted_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.chmod(0o600)
        tmp_path.replace(self._trusted_path)
        self._trusted_path.chmod(0o600)
        self._dirty = False
        self._last_flush = now

    def flush(self) -> None:
        with self._lock:
            self._flush_locked(force=True)

    @property
    def device_count(self) -> int:
        with self._lock:
            return len(self._devices)

    def _check_lockout(self, ip: str) -> None:
        now = time.monotonic()
        fails = [t for t in self._failures.get(ip, []) if now - t < FAILURE_WINDOW_SECONDS]
        self._failures[ip] = fails
        if len(fails) >= MAX_FAILURES:
            backoff = min(
                LOCKOUT_CAP_SECONDS,
                LOCKOUT_BASE_SECONDS * (2 ** min(len(fails) - MAX_FAILURES, 4)),
            )
            retry_after = int(backoff - (now - fails[-1]))
            if retry_after > 0:
                raise RateLimited(retry_after)
            self._failures.pop(ip, None)

    def authenticate(self, ip: str, pin) -> str:
        """Verify the PIN and register/return a persistent token for this device."""
        if not isinstance(pin, str):
            pin = str(pin)
        with self._lock:
            self._check_lockout(ip)
            if not hmac.compare_digest(pin.strip(), self._pin):
                self._failures.setdefault(ip, []).append(time.monotonic())
                raise InvalidPin()
            self._failures.pop(ip, None)
            token = secrets.token_urlsafe(32)
            now = time.time()
            self._devices[hash_token(token)] = {
                "createdAt": now,
                "lastUsedAt": now,
                "lastIp": ip,
            }
            self._flush_locked(force=True)
            return token

    def validate(self, token: str | None, ip: str = "") -> bool:
        """Validate a trusted-device token. Deliberately IP independent."""
        if not token:
            return False
        token_hash = hash_token(token)
        with self._lock:
            record = self._devices.get(token_hash)
            if record is None:
                return False
            record["lastUsedAt"] = time.time()
            record["lastIp"] = ip
            self._dirty = True
            self._flush_locked()
            return True

    def revoke(self, token: str | None) -> bool:
        """Unpair the device presenting this token (logout)."""
        if not token:
            return False
        token_hash = hash_token(token)
        with self._lock:
            existed = self._devices.pop(token_hash, None) is not None
            if existed:
                self._flush_locked(force=True)
            return existed
