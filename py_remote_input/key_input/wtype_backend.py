"""wtype 按键后端：Wayland 专用，按 keysym 名投递按键事件。"""

from __future__ import annotations

from py_remote_input.key_input.base import KeyInputBackend


class WtypeBackend(KeyInputBackend):
    name = "wtype"
    binary = "wtype"
    install_hint = (
        "wtype was not found on PATH. Install it, e.g. Arch: sudo pacman -S wtype; "
        "Debian/Ubuntu: sudo apt install wtype. To use ydotool instead, unset KEY_BACKEND."
    )
    failure_hint = " wtype only works on Wayland; on X11 set KEY_BACKEND=ydotool."

    def build_command(self, keysym: str) -> list[str]:
        return ["wtype", "-k", keysym]
