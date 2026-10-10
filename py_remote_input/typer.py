"""Linux text input via ydotool (uinput-based, works on Wayland and X11).

ydotool simulates keyboard input through the kernel's uinput interface, so it
does not depend on a specific display server protocol. A typed line break
presses Enter in the focused window, which would submit/execute half a
message early (e.g. run a half-typed shell command) — so line breaks are
flattened to single spaces before typing, and Return is only ever pressed
explicitly via ``press_key``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time

YDOTOOL_BIN = "ydotool"
RETURN_KEYCODE = 28  # linux/input-event-codes.h: KEY_ENTER

# Keep each ydotool invocation well below the OS argv length limit (ARG_MAX).
CHUNK_CHAR_LIMIT = 4000
# Per-chunk timeout; ydotool is fast, but leave headroom for slow systems.
CHUNK_TIMEOUT_SECONDS = 30


class YdotoolNotFoundError(RuntimeError):
    """Raised when the ydotool executable cannot be found on PATH."""


def flatten_line_breaks(text: str) -> str:
    """Collapse CR/LF/CRLF runs into a single space.

    Typed newlines press Enter in the focused window; a remote text message
    must never press Enter on its own — that is what ``press_key`` is for.
    """
    return re.sub(r"[\r\n]+", " ", text)


def build_ydotool_batches(text: str, char_limit: int = CHUNK_CHAR_LIMIT) -> list[list[str]]:
    """Split flattened text into argv-tail chunks bounded by text length."""
    flat = flatten_line_breaks(text)
    return [[flat[i : i + char_limit]] for i in range(0, len(flat), char_limit)]


def ensure_ydotool_available() -> str:
    path = shutil.which(YDOTOOL_BIN)
    if path is None:
        raise YdotoolNotFoundError(
            "ydotool was not found on PATH. Install it first, e.g. "
            "Debian/Ubuntu: sudo apt install ydotool; Arch: sudo pacman -S ydotool; "
            "Fedora: sudo dnf install ydotool."
        )
    return path


def type_text(text: str) -> dict:
    """Type ``text`` into the focused window using ydotool (never presses Enter)."""
    ensure_ydotool_available()
    flat = flatten_line_breaks(text)
    started_at = time.perf_counter()
    for args in build_ydotool_batches(flat, CHUNK_CHAR_LIMIT):
        subprocess.run(
            [YDOTOOL_BIN, "type", "--delay", "0", "--", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=CHUNK_TIMEOUT_SECONDS,
        )
    return {
        "method": "ydotool",
        "charCount": len(flat),
        "durationMs": int((time.perf_counter() - started_at) * 1000),
    }


# Keys the phone is allowed to press remotely (whitelist; arbitrary keycodes
# from the network must not be passed straight to ydotool).
ALLOWED_KEYSYMS = frozenset({"Return"})


def press_key(keysym: str) -> dict:
    """Press a single whitelisted keysym (e.g. ``Return``) in the focused window."""
    if keysym not in ALLOWED_KEYSYMS:
        raise ValueError(f"Unsupported key: {keysym}")
    ensure_ydotool_available()
    started_at = time.perf_counter()
    subprocess.run(
        [YDOTOOL_BIN, "key", str(RETURN_KEYCODE)],
        check=True,
        capture_output=True,
        text=True,
        timeout=CHUNK_TIMEOUT_SECONDS,
    )
    return {
        "method": "ydotool",
        "key": keysym,
        "durationMs": int((time.perf_counter() - started_at) * 1000),
    }


def press_return() -> dict:
    """Press Enter/Return in the focused window."""
    return press_key("Return")
