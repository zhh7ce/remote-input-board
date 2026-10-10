"""文字输入功能测试：注入协议、换行处理、失败映射。

用真实的临时 Unix socket 扮演 fcitx5-text-injector，不依赖 fcitx5 本身。
"""

import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import unittest
from unittest import mock

from py_remote_input import text_input


def _serve_once(sock_path: Path, reply: dict) -> tuple[threading.Thread, list[dict]]:
    """后台接受一个连接：读完请求 JSON 后回 reply，记录收到的内容。"""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    received: list[dict] = []

    def run() -> None:
        connection, _ = server.accept()
        try:
            chunks = []
            while True:
                data = connection.recv(4096)
                if not data:
                    break
                chunks.append(data)
            received.append(json.loads(b"".join(chunks).decode("utf-8")))
            connection.sendall(json.dumps(reply, ensure_ascii=False).encode("utf-8"))
        finally:
            connection.close()
            server.close()

    thread = threading.Thread(target=run)
    thread.start()
    return thread, received


class LineEndingTests(unittest.TestCase):
    def test_line_breaks_are_kept(self):
        self.assertEqual(text_input.normalize_line_endings("a\nb"), "a\nb")
        self.assertEqual(text_input.normalize_line_endings("a\n\n\nb"), "a\n\n\nb")

    def test_crlf_and_lone_cr_become_lf(self):
        self.assertEqual(text_input.normalize_line_endings("a\r\nb"), "a\nb")
        self.assertEqual(text_input.normalize_line_endings("a\rb"), "a\nb")


class SocketPathTests(unittest.TestCase):
    def test_env_override_wins(self):
        env = {"TEXT_INJECTOR_SOCKET": "/tmp/custom.sock", "XDG_RUNTIME_DIR": "/run/user/1000"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(text_input.injector_socket_path(), "/tmp/custom.sock")

    def test_xdg_runtime_dir_is_preferred(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}, clear=False):
            os.environ.pop("TEXT_INJECTOR_SOCKET", None)
            self.assertEqual(text_input.injector_socket_path(), "/run/user/1000/text-injector.sock")

    def test_falls_back_to_tmp_with_uid(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(text_input.injector_socket_path(), f"/tmp/text-injector-{os.getuid()}.sock")


class CommitTextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sock_path = self.tmp / "text-injector.sock"
        self.enterContext(
            mock.patch.dict(os.environ, {"TEXT_INJECTOR_SOCKET": str(self.sock_path)}, clear=False)
        )

    def test_text_is_committed_with_line_breaks(self):
        thread, received = _serve_once(self.sock_path, {"success": True})
        result = text_input.type_text("你好\n世界")
        thread.join(timeout=5)

        self.assertEqual(received, [{"type": "commit", "text": "你好\n世界"}])
        self.assertEqual(result["method"], "fcitx5")
        self.assertEqual(result["charCount"], 5)
        self.assertIsInstance(result["durationMs"], int)

    def test_line_endings_are_normalized_before_committing(self):
        thread, received = _serve_once(self.sock_path, {"success": True})
        text_input.type_text("a\r\nb\rc")
        thread.join(timeout=5)

        self.assertEqual(received, [{"type": "commit", "text": "a\nb\nc"}])

    def test_rejected_commit_becomes_text_injector_error(self):
        thread, _ = _serve_once(self.sock_path, {"success": False, "error": "empty text"})
        with self.assertRaises(text_input.TextInjectorError):
            text_input.type_text("   ")
        thread.join(timeout=5)

    def test_unreachable_injector_raises_clear_error(self):
        with self.assertRaises(text_input.TextInjectorUnavailableError) as caught:
            text_input.type_text("你好")
        self.assertIn("fcitx5-text-injector", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
