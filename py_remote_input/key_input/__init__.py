"""按键输入通道：按键模拟后端的接口、注册与选择。

文字由 ``text_input`` 经 fcitx5 提交，提交不了按键事件，所以回车等按键必须走
按键模拟。后端各自实现在独立模块里：

* ``ydotool_backend.YdotoolBackend``：通过内核 uinput 写按键事件，Wayland 与
  X11 都可用，需要 ydotoold 守护进程在运行，默认后端。
* ``wtype_backend.WtypeBackend``：Wayland 专用。

执行时按参数选择后端：``press_key(..., backend=...)`` 显式指定，未指定则读
``KEY_BACKEND``，再无则用默认后端。选中的后端不在 PATH 中时报错，不做静默回退。
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable

from py_remote_input.key_input.base import (
    COMMAND_TIMEOUT_SECONDS,
    KeyBackendNotFoundError,
    KeyInputBackend,
    KeyPressFailedError,
)
from py_remote_input.key_input.wtype_backend import WtypeBackend
from py_remote_input.key_input.ydotool_backend import YdotoolBackend

BACKEND_ENV = "KEY_BACKEND"
DEFAULT_BACKEND = "ydotool"

# 允许手机端按下的键；任意 keysym 不允许来自网络直接执行。
ALLOWED_KEYS = frozenset({"Return"})


class UnknownKeyBackendError(RuntimeError):
    """请求的后端不在已实现的后端列表里。"""


BACKENDS: dict[str, KeyInputBackend] = {
    backend.name: backend
    for backend in (YdotoolBackend(), WtypeBackend())
}


def get_backend(name: str | None = None) -> KeyInputBackend:
    """按名字取后端，名字为空时读 ``KEY_BACKEND``，再无则用默认后端。"""
    resolved = name if name is not None else os.environ.get(BACKEND_ENV, "")
    resolved = resolved.strip().lower() or DEFAULT_BACKEND
    backend = BACKENDS.get(resolved)
    if backend is None:
        raise UnknownKeyBackendError(
            f"Unknown {BACKEND_ENV}: {resolved}. "
            f"Supported backends: {', '.join(sorted(BACKENDS))}."
        )
    return backend


def active_backend() -> KeyInputBackend:
    """当前配置选择的后端。"""
    return get_backend()


def press_key(
    keysym: str,
    backend: str | None = None,
    run: Callable = subprocess.run,
) -> dict:
    """在当前焦点窗口按下白名单内的键。

    ``backend`` 指定使用哪个后端，为空时按配置选择；``run`` 是命令执行器，默认
    ``subprocess.run``，测试可传入替身。
    """
    if keysym not in ALLOWED_KEYS:
        raise ValueError(f"Unsupported key: {keysym}")
    return get_backend(backend).press(keysym, run=run)


def press_return(
    backend: str | None = None,
    run: Callable = subprocess.run,
) -> dict:
    """按下回车。"""
    return press_key("Return", backend=backend, run=run)


__all__ = [
    "ALLOWED_KEYS",
    "BACKENDS",
    "BACKEND_ENV",
    "COMMAND_TIMEOUT_SECONDS",
    "DEFAULT_BACKEND",
    "KeyBackendNotFoundError",
    "KeyInputBackend",
    "KeyPressFailedError",
    "UnknownKeyBackendError",
    "WtypeBackend",
    "YdotoolBackend",
    "active_backend",
    "get_backend",
    "press_key",
    "press_return",
]
