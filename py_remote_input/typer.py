"""Linux text input via the wtype virtual-keyboard client.

wtype types unicode text into the currently focused Wayland surface using the
virtual-keyboard protocol. A typed line break presses Enter in the focused
window, which would submit/execute half a message early (e.g. run a
half-typed shell command) — so line breaks are flattened to single spaces
before typing, and Return is only ever pressed explicitly via ``press_key``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time

WTYPE_BIN = "wtype"
RETURN_KEYSYM = "Return"

# Keep each wtype invocation well below the OS argv length limit (ARG_MAX).
CHUNK_CHAR_LIMIT = 4000
# Per-chunk timeout; wtype is fast, but leave headroom for slow compositors.
CHUNK_TIMEOUT_SECONDS = 30


class WtypeNotFoundError(RuntimeError):
    """Raised when the wtype executable cannot be found on PATH."""


def flatten_line_breaks(text: str) -> str:
    """Collapse CR/LF/CRLF runs into a single space.

    Typed newlines press Enter in the focused window; a remote text message
    must never press Enter on its own — that is what ``press_key`` is for.
    """
    return re.sub(r"[\r\n]+", " ", text)


def build_wtype_batches(text: str, char_limit: int = CHUNK_CHAR_LIMIT) -> list[list[str]]:
    """Split flattened text into argv-tail chunks bounded by text length."""
    flat = flatten_line_breaks(text)
    return [[flat[i : i + char_limit]] for i in range(0, len(flat), char_limit)]


def ensure_wtype_available() -> str:
    path = shutil.which(WTYPE_BIN)
    if path is None:
        raise WtypeNotFoundError(
            "wtype was not found on PATH. Install it first, e.g. "
            "Debian/Ubuntu: sudo apt install wtype; Arch: sudo pacman -S wtype."
        )
    return path


def type_text(text: str) -> dict:
    """Type ``text`` into the focused window using wtype (never presses Enter)."""
    ensure_wtype_available()
    flat = flatten_line_breaks(text)
    started_at = time.perf_counter()
    for args in build_wtype_batches(flat, CHUNK_CHAR_LIMIT):
        subprocess.run(
            [WTYPE_BIN, *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=CHUNK_TIMEOUT_SECONDS,
        )
    return {
        "method": "wtype",
        "charCount": len(flat),
        "durationMs": int((time.perf_counter() - started_at) * 1000),
    }


# Keys the phone is allowed to press remotely (whitelist; arbitrary keysyms
# from the network must not be passed straight to wtype).
ALLOWED_KEYSYMS = frozenset({RETURN_KEYSYM})


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
        timeout=CHUNK_TIMEOUT_SECONDS,
    )
    return {
        "method": "wtype",
        "key": keysym,
        "durationMs": int((time.perf_counter() - started_at) * 1000),
    }


def press_return() -> dict:
    """Press Enter/Return in the focused window."""
    return press_key(RETURN_KEYSYM)
