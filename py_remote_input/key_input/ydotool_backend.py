"""ydotool 按键后端：通过内核 uinput 写按键事件，Wayland 与 X11 都可用。"""

from __future__ import annotations

from py_remote_input.key_input.base import KeyInputBackend

# 来自 linux/input-event-codes.h，ydotool 的 key 子命令按数字键码工作。
KEY_ENTER = 28

KEYCODES: dict[str, int] = {"Return": KEY_ENTER}


class YdotoolBackend(KeyInputBackend):
    name = "ydotool"
    binary = "ydotool"
    install_hint = (
        "ydotool was not found on PATH. Install it, e.g. Arch: sudo pacman -S ydotool; "
        "Debian/Ubuntu: sudo apt install ydotool. To use wtype instead, set KEY_BACKEND=wtype."
    )
    failure_hint = (
        " ydotoold must be running (systemctl start ydotoold) and the user needs access "
        "to /dev/uinput (input group or the ydotool group)."
    )

    def build_command(self, keysym: str) -> list[str]:
        keycode = KEYCODES.get(keysym)
        if keycode is None:
            raise ValueError(f"Unsupported key for ydotool: {keysym}")
        # 一次按下、一次放开，等价于一次完整按键。
        return [self.binary, "key", f"{keycode}:1", f"{keycode}:0"]
