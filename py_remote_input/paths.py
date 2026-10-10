"""XDG-style filesystem layout for the installed application.

After packaging, the server can be started from any directory (e.g. the
``remote-input-board`` command or a systemd --user unit), so runtime files no
longer live in the working directory:

* Config (PIN, paired devices, TLS cert/key) ->
  ``$XDG_CONFIG_HOME/remote-input-board`` (default ``~/.config/...``)
* Mutable data (server log, input history) ->
  ``$XDG_DATA_HOME/remote-input-board`` (default ``~/.local/share/...``),
  keeping the ``logs/`` subdirectory layout.

``REMOTE_INPUT_CONFIG_DIR`` / ``REMOTE_INPUT_DATA_DIR`` override the roots
(useful for tests and power users).

Older versions stored everything in the working directory. When the new config
directory is still uninitialised, such legacy files are moved over exactly once
so existing PINs and pairings survive the relocation.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil

APP_NAME = "remote-input-board"

# Files older versions wrote into the working directory that now belong in
# the config directory.
LEGACY_CONFIG_FILES = ("pin.txt", "trusted_devices.json", "cert.pem", "key.pem")
# Presence of either means the new config directory is already initialised.
INITIALISED_MARKERS = ("pin.txt", "trusted_devices.json")


def _xdg_root(override_env: str, xdg_env: str, relative_fallback: Path) -> Path:
    override = os.environ.get(override_env)
    if override:
        return Path(override)
    base = os.environ.get(xdg_env)
    return (Path(base) if base else Path.home() / relative_fallback) / APP_NAME


def config_dir() -> Path:
    """Directory for pin.txt, trusted_devices.json and cert.pem/key.pem."""
    return _xdg_root("REMOTE_INPUT_CONFIG_DIR", "XDG_CONFIG_HOME", Path(".config"))


def data_dir() -> Path:
    """Directory for logs/ and history."""
    return _xdg_root("REMOTE_INPUT_DATA_DIR", "XDG_DATA_HOME", Path(".local/share"))


def ensure_app_dirs() -> tuple[Path, Path]:
    """Create the config/data trees and return (config_dir, data_dir).

    The config directory holds secrets (PIN, TLS key) and is created 0700.
    """
    config = config_dir()
    created_fresh = not config.exists()
    config.mkdir(parents=True, exist_ok=True)
    if created_fresh:
        config.chmod(0o700)
    data = data_dir()
    (data / "logs").mkdir(parents=True, exist_ok=True)
    return config, data


def migrate_legacy_files(
    config: Path,
    data: Path,
    cwd: Path | None = None,
) -> list[str]:
    """Move old working-directory files into the XDG layout, once.

    Returns a description of what was moved (for logging). Nothing is moved
    when the config directory is already initialised or the working directory
    has no legacy files, and existing files are never overwritten.
    """
    current = (cwd if cwd is not None else Path.cwd()).resolve()
    config = config.resolve()
    data = data.resolve()
    if current == config or current == data:
        return []
    if any((config / name).exists() for name in INITIALISED_MARKERS):
        return []

    moved: list[str] = []
    for name in LEGACY_CONFIG_FILES:
        source = current / name
        if not source.is_file() or (config / name).exists():
            continue
        config.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(config / name))
        moved.append(name)

    legacy_logs = current / "logs"
    target_logs = data / "logs"
    if legacy_logs.is_dir() and target_logs.is_dir() and not any(target_logs.iterdir()):
        # ensure_app_dirs() pre-created an empty target logs dir; swap it for
        # the legacy one so its history moves over wholesale.
        target_logs.rmdir()
        shutil.move(str(legacy_logs), str(target_logs))
        moved.append("logs/")

    return moved
