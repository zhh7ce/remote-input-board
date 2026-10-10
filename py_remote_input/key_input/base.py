"""按键后端接口：命令执行、可用性检查与异常在这里定义。

子类只需说明自己是谁、依赖哪个可执行文件、如何把 keysym 变成命令行参数，
以及失败时给用户的提示文案。
"""

from __future__ import annotations

import abc
import shutil
import subprocess
import time
from typing import Callable

COMMAND_TIMEOUT_SECONDS = 5


class KeyBackendNotFoundError(RuntimeError):
    """后端的可执行文件不在 PATH 中。"""


class KeyPressFailedError(RuntimeError):
    """后端执行失败，例如命令非零退出或超时。"""


class KeyInputBackend(abc.ABC):
    """把一个按键模拟工具抽象成后端。"""

    name: str
    binary: str
    install_hint: str
    failure_hint: str

    @abc.abstractmethod
    def build_command(self, keysym: str) -> list[str]:
        """构造按下该键的命令行参数。"""

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def press(self, keysym: str, run: Callable = subprocess.run) -> dict:
        if not self.is_available():
            raise KeyBackendNotFoundError(self.install_hint)
        command = self.build_command(keysym)
        started_at = time.perf_counter()
        try:
            run(command, check=True, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise KeyPressFailedError(
                f"{self.binary} could not press {keysym}: "
                f"{detail or f'exit code {exc.returncode}'}." + self.failure_hint
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise KeyPressFailedError(
                f"{self.binary} timed out after {COMMAND_TIMEOUT_SECONDS}s pressing {keysym}."
                + self.failure_hint
            ) from exc
        return {
            "method": self.name,
            "key": keysym,
            "durationMs": int((time.perf_counter() - started_at) * 1000),
        }
