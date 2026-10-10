"""文字输入通道：通过 fcitx5-text-injector 提交文本。

文本经 Unix socket 交给 fcitx5 addon，由它调用 ``commitString()`` 提交成品
文字，因此不受输入法影响。按键事件由 ``key_input`` 负责，两者互不依赖。

``commitString()`` 提交的是字符而非按键，换行等同粘贴，不会触发回车，所以多行
文本原样提交；只把 CRLF 与裸 CR 归一为 LF。

socket 协议：一连接一请求，发送 JSON 后 ``shutdown(SHUT_WR)``，读到 EOF 取得
JSON 响应。
"""

from __future__ import annotations

import json
import os
import socket
import time

SOCKET_NAME = "text-injector.sock"
SOCKET_TIMEOUT_SECONDS = 5
REPLY_BUFFER_BYTES = 4096


class TextInjectorError(RuntimeError):
    """fcitx5-text-injector 返回失败。"""


class TextInjectorUnavailableError(TextInjectorError):
    """连不上 fcitx5-text-injector 的 socket。"""


def normalize_line_endings(text: str) -> str:
    """把 CRLF 与裸 CR 归一为 LF，换行本身保持不变。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def injector_socket_path() -> str:
    """返回 fcitx5-text-injector 的 socket 路径，与 addon 的默认规则一致。"""
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
    """把 ``text`` 提交到焦点应用，换行原样保留。"""
    committed = normalize_line_endings(text)
    started_at = time.perf_counter()
    response = _request({"type": "commit", "text": committed})
    if not response.get("success"):
        raise TextInjectorError(response.get("error") or "fcitx5-text-injector rejected the text")
    return {
        "method": "fcitx5",
        "charCount": len(committed),
        "durationMs": int((time.perf_counter() - started_at) * 1000),
    }
