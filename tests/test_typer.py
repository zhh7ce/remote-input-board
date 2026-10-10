import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import unittest
from unittest import mock

from py_remote_input import typer


def _serve_once(sock_path: Path, reply: dict):
    """Accept one connection in a background thread; return its server socket,
    that thread, and the list that will hold the received JSON request."""
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


class FlattenLineBreaksTests(unittest.TestCase):
    def test_lf_becomes_single_space(self):
        self.assertEqual(typer.flatten_line_breaks("a\nb"), "a b")

    def test_crlf_and_cr_become_single_space(self):
        self.assertEqual(typer.flatten_line_breaks("a\r\nb\rc"), "a b c")

    def test_newline_runs_collapse_into_one_space(self):
        self.assertEqual(typer.flatten_line_breaks("a\n\n\nb"), "a b")

    def test_blank_text_becomes_single_space(self):
        self.assertEqual(typer.flatten_line_breaks("\n\n"), " ")


class InjectorSocketPathTests(unittest.TestCase):
    def test_env_override_wins(self):
        with mock.patch.dict(os.environ, {"TEXT_INJECTOR_SOCKET": "/tmp/custom.sock", "XDG_RUNTIME_DIR": "/run/user/1000"}, clear=False):
            self.assertEqual(typer.injector_socket_path(), "/tmp/custom.sock")

    def test_uses_xdg_runtime_dir(self):
        env = {"XDG_RUNTIME_DIR": "/run/user/1000"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("TEXT_INJECTOR_SOCKET", None)
            self.assertEqual(typer.injector_socket_path(), "/run/user/1000/text-injector.sock")

    def test_falls_back_to_tmp_with_uid(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(typer.injector_socket_path(), f"/tmp/text-injector-{os.getuid()}.sock")


class TypeTextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sock_path = self.tmp / "text-injector.sock"
        self.enterContext(
            mock.patch.dict(os.environ, {"TEXT_INJECTOR_SOCKET": str(self.sock_path)}, clear=False)
        )

    def test_commits_flattened_text_and_reports_fcitx5_method(self):
        thread, received = _serve_once(self.sock_path, {"success": True})
        result = typer.type_text("你好\n世界")
        thread.join(timeout=5)

        self.assertEqual(received, [{"type": "commit", "text": "你好 世界"}])
        self.assertEqual(result["method"], "fcitx5")
        self.assertEqual(result["charCount"], 5)

    def test_server_failure_becomes_text_injector_error(self):
        thread, _ = _serve_once(self.sock_path, {"success": False, "error": "empty text"})
        with self.assertRaises(typer.TextInjectorError):
            typer.type_text("   ")
        thread.join(timeout=5)

    def test_missing_socket_raises_clear_error(self):
        with self.assertRaises(typer.TextInjectorUnavailableError) as caught:
            typer.type_text("你好")
        self.assertIn("fcitx5-text-injector", str(caught.exception))


class WtypeKeyTests(unittest.TestCase):
    def test_press_key_invokes_wtype_return(self):
        with (
            mock.patch.object(typer, "ensure_wtype_available", return_value="/usr/bin/wtype"),
            mock.patch.object(typer.subprocess, "run") as run,
        ):
            result = typer.press_key("Return")

        self.assertEqual(run.call_args.args[0], ["wtype", "-k", "Return"])
        self.assertEqual(result["key"], "Return")
        self.assertEqual(result["method"], "wtype")

    def test_press_key_rejects_non_whitelisted_keysym(self):
        with self.assertRaises(ValueError):
            typer.press_key("Escape")

    def test_press_return_helper(self):
        with (
            mock.patch.object(typer, "ensure_wtype_available", return_value="/usr/bin/wtype"),
            mock.patch.object(typer.subprocess, "run") as run,
        ):
            typer.press_return()

        self.assertEqual(run.call_args.args[0], ["wtype", "-k", "Return"])

    def test_missing_wtype_raises_clear_error(self):
        with mock.patch.object(typer.shutil, "which", return_value=None):
            with self.assertRaises(typer.WtypeNotFoundError):
                typer.press_key("Return")


if __name__ == "__main__":
    unittest.main()
