"""Text input via the fcitx5-text-injector module; Enter via wtype.

Text is committed through fcitx5's ``commitString()`` over a Unix socket, so it
reaches the focused app as finished text no matter which input method is active.
Key simulation (wtype/ydotool) cannot do this: an IME intercepts the synthesized
keystrokes and mangles them.

Enter is a real key event rather than committed text, so it still goes to wtype.

Socket protocol (one request per connection): send JSON, half-close the write
side, read the JSON reply until EOF.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time

WTYPE_BIN = "wtype"
RETURN_KEYSYM = "Return"

SOCKET_NAME = "text-injector.sock"
SOCKET_TIMEOUT_SECONDS = 5
REPLY_BUFFER_BYTES = 4096

# Keys the phone is allowed to press remotely (whitelist; arbitrary keysyms
# from the network must not be passed straight to wtype).
ALLOWED_KEYSYMS = frozenset({RETURN_KEYSYM})


class TextInjectorError(RuntimeError):
    """Raised when fcitx5-text-injector reports a failure."""


class TextInjectorUnavailableError(TextInjectorError):
    """Raised when the fcitx5-text-injector socket cannot be reached."""


class WtypeNotFoundError(RuntimeError):
    """Raised when the wtype executable cannot be found on PATH."""


def flatten_line_breaks(text: str) -> str:
    """Collapse CR/LF/CRLF runs into a single space.

    A committed line break acts like Enter in most apps, which would submit or
    execute half a message early; a remote text message must never press Enter
    on its own — that is what ``press_key`` is for.
    """
    return re.sub(r"[\r\n]+", " ", text)


def injector_socket_path() -> str:
    """Socket path of fcitx5-text-injector, mirroring the addon's own default."""
    override = os.environ.get("TEXT_INJECTOR_SOCKET")
    if override:
        return override
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and runtime_dir.startswith("/"):
        return os.path.join(runtime_dir, SOCKET_NAME)
    return f"/tmp/text-injector-{os.getuid()}.sock"


def _request(payload: dict) -> dict:
    path = injector_socket_path()
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(SOCKET_TIMEOUT_SECONDS)
    try:
        connection.connect(path)
        connection.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        connection.shutdown(socket.SHUT_WR)
        parts = []
        while True:
            chunk = connection.recv(REPLY_BUFFER_BYTES)
            if not chunk:
                break
            parts.append(chunk)
    except OSError as exc:
        raise TextInjectorUnavailableError(
            f"Cannot reach fcitx5-text-injector at {path} ({exc.strerror or exc}). "
            "Install the text_injector addon and restart fcitx5, or set "
            "TEXT_INJECTOR_SOCKET if the module uses a custom path."
        ) from exc
    finally:
        connection.close()

    reply = b"".join(parts).strip()
    if not reply:
        raise TextInjectorUnavailableError(
            f"fcitx5-text-injector accepted the connection on {path} but sent no reply — "
            "is fcitx5 running with the text_injector module enabled?"
        )
    try:
        return json.loads(reply.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TextInjectorError(f"Unparsable reply from fcitx5-text-injector: {reply!r}") from exc


def type_text(text: str) -> dict:
    """Commit ``text`` to the focused app through fcitx5 (never presses Enter)."""
    flat = flatten_line_breaks(text)
    started_at = time.perf_counter()
    response = _request({"type": "commit", "text": flat})
    if not response.get("success"):
        raise TextInjectorError(response.get("error") or "fcitx5-text-injector rejected the text")
    return {
        "method": "fcitx5",
        "charCount": len(flat),
        "durationMs": int((time.perf_counter() - started_at) * 1000),
    }


def ensure_wtype_available() -> str:
    path = shutil.which(WTYPE_BIN)
    if path is None:
        raise WtypeNotFoundError(
            "wtype was not found on PATH. It is required for remote Enter presses; "
            "install it, e.g. Debian/Ubuntu: sudo apt install wtype; "
            "Arch: sudo pacman -S wtype."
        )
    return path


def press_key(keysym: str) -> dict:
    """Press a single whitelisted keysym (e.g. ``Return``) in the focused window."""
    if keysym not in ALLOWED_KEYSYMS:
        raise ValueError(f"Unsupported key: {keysym}")
    ensure_wtype_available()
    started_at = time.perf_counter()
    subprocess.run(
        [WTYPE_BIN, "-k", keysym],
        check=True,
        capture_output=True,
        text=True,
        timeout=SOCKET_TIMEOUT_SECONDS,
    )
    return {
        "method": "wtype",
        "key": keysym,
        "durationMs": int((time.perf_counter() - started_at) * 1000),
    }


def press_return() -> dict:
    """Press Enter/Return in the focused window."""
    return press_key(RETURN_KEYSYM)
