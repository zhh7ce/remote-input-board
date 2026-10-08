"""Linux text input via the wtype virtual-keyboard client.

wtype types unicode text into the currently focused Wayland surface using the
virtual-keyboard protocol. Line breaks cannot be sent as plain unicode, so they
are mapped to ``-k Return`` keysym events.
"""

from __future__ import annotations

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


def _split_segments(text: str) -> list[tuple[str, str]]:
    """Split text into [("text", s) | ("key", "Return")] segments."""
    segments: list[tuple[str, str]] = []
    for line in text.splitlines(keepends=True):
        if line.endswith("\r\n"):
            body, has_newline = line[:-2], True
        elif line.endswith(("\n", "\r")):
            body, has_newline = line[:-1], True
        else:
            body, has_newline = line, False
        if body:
            segments.append(("text", body))
        if has_newline:
            segments.append(("key", RETURN_KEYSYM))
    return segments


def build_wtype_args(text: str) -> list[str]:
    """Build the argv tail for one ``wtype`` invocation."""
    args: list[str] = []
    for kind, value in _split_segments(text):
        if kind == "text":
            args.append(value)
        else:
            args.extend(["-k", value])
    return args


def build_wtype_batches(text: str, char_limit: int = CHUNK_CHAR_LIMIT) -> list[list[str]]:
    """Split the argv into multiple invocations bounded by total text length."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_size = 0
    for kind, value in _split_segments(text):
        if kind == "text" and current and current_size + len(value) > char_limit:
            batches.append(current)
            current = []
            current_size = 0
        if kind == "text":
            current.append(value)
            current_size += len(value)
        else:
            current.extend(["-k", value])
    if current:
        batches.append(current)
    return batches


def ensure_wtype_available() -> str:
    path = shutil.which(WTYPE_BIN)
    if path is None:
        raise WtypeNotFoundError(
            "wtype was not found on PATH. Install it first, e.g. "
            "Debian/Ubuntu: sudo apt install wtype; Arch: sudo pacman -S wtype."
        )
    return path


def type_text(text: str) -> dict:
    """Type ``text`` into the focused window using wtype."""
    ensure_wtype_available()
    started_at = time.perf_counter()
    batches = build_wtype_batches(text, CHUNK_CHAR_LIMIT)
    for args in batches:
        subprocess.run(
            [WTYPE_BIN, *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=CHUNK_TIMEOUT_SECONDS,
        )
    return {
        "method": "wtype",
        "charCount": len(text),
        "durationMs": int((time.perf_counter() - started_at) * 1000),
    }
