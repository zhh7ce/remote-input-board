import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest
from unittest import mock

from py_remote_input.auth import AuthStore
from py_remote_input.server import (
    build_handler,
    create_servers,
    maybe_wrap_tls,
    resolve_tls_files,
    serve_websocket_messages,
)
from py_remote_input.websocket import (
    build_websocket_accept,
    encode_websocket_frame,
    read_websocket_frame,
)


TLS_ENV = {key: value for key, value in os.environ.items()
           if key not in {"SSL_CERT_FILE", "SSL_KEY_FILE"}}


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, meta=None):
        self.messages.append(("info", message, meta))

    def warn(self, message, meta=None):
        self.messages.append(("warn", message, meta))

    def error(self, message, meta=None):
        self.messages.append(("error", message, meta))


def build_masked_client_frame(opcode: int, payload: bytes = b"") -> bytes:
    mask = b"\x01\x02\x03\x04"
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked


class WebSocketProtocolTests(unittest.TestCase):
    def test_builds_rfc_accept_key(self):
        accept = build_websocket_accept("dGhlIHNhbXBsZSBub25jZQ==")

        self.assertEqual(accept, "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_reads_masked_text_frame(self):
        payload = b'{"type":"key","key":"up"}'
        mask = b"\x01\x02\x03\x04"
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        stream = io.BytesIO(bytes([0x81, 0x80 | len(payload)]) + mask + masked)

        frame = read_websocket_frame(stream)

        self.assertIsNotNone(frame)
        self.assertEqual(frame.opcode, 0x1)
        self.assertEqual(frame.payload, payload)

    def test_encodes_unmasked_server_text_frame(self):
        payload = b'{"ok":true}'

        frame = encode_websocket_frame(0x1, payload)

        self.assertEqual(frame, bytes([0x81, len(payload)]) + payload)

    def _run_loop(self, messages, auth, client_ip="1.2.3.4", pressed=None):
        stream = b"".join(
            build_masked_client_frame(0x1, json.dumps(message).encode("utf-8")) for message in messages
        )
        reader = io.BytesIO(stream + build_masked_client_frame(0x8))
        writer = io.BytesIO()

        def press_key(key):
            if pressed is not None:
                pressed.append(key)
            return {"method": "wtype", "key": key}

        serve_websocket_messages(
            reader,
            writer,
            FakeLogger(),
            type_text=lambda text: {"method": "wtype", "charCount": len(text)},
            press_key=press_key,
            auth=auth,
            client_ip=client_ip,
        )
        responses = []
        response_stream = io.BytesIO(writer.getvalue())
        while True:
            frame = read_websocket_frame(response_stream)
            if frame is None:
                break
            if frame.opcode == 0x1:
                responses.append(json.loads(frame.payload.decode("utf-8")))
        return responses

    def test_websocket_requires_auth_before_other_messages(self):
        auth = AuthStore("482915")
        responses = self._run_loop([{"type": "type", "id": 1, "text": "你好"}], auth)

        self.assertEqual(len(responses), 1)
        self.assertFalse(responses[0]["ok"])
        self.assertTrue(responses[0]["authRequired"])

    def test_websocket_message_loop_dispatches_type_message_after_auth(self):
        auth = AuthStore("482915")
        token = auth.authenticate("1.2.3.4", "482915")
        responses = self._run_loop(
            [
                {"type": "auth", "id": 1, "token": token},
                {"type": "type", "id": 2, "text": "你好"},
            ],
            auth,
        )

        self.assertEqual(responses[0], {"ok": True, "type": "auth", "id": 1})
        self.assertTrue(responses[1]["ok"])
        self.assertEqual(responses[1]["type"], "type")
        self.assertEqual(responses[1]["id"], 2)
        self.assertEqual(responses[1]["sentChars"], 2)

    def test_websocket_message_loop_dispatches_key_message_after_auth(self):
        auth = AuthStore("482915")
        token = auth.authenticate("1.2.3.4", "482915")
        pressed = []
        responses = self._run_loop(
            [
                {"type": "auth", "id": 1, "token": token},
                {"type": "key", "id": 2, "key": "Return"},
            ],
            auth,
            pressed=pressed,
        )

        self.assertEqual(pressed, ["Return"])
        self.assertTrue(responses[1]["ok"])
        self.assertEqual(responses[1]["type"], "key")
        self.assertEqual(responses[1]["key"], "Return")
        self.assertEqual(responses[1]["id"], 2)

    def test_websocket_accepts_trusted_token_from_any_ip(self):
        auth = AuthStore("482915")
        token = auth.authenticate("1.2.3.4", "482915")

        accepted = self._run_loop(
            [{"type": "auth", "id": 1, "token": token}],
            auth,
            client_ip="9.9.9.9",
        )
        self.assertEqual(accepted[0], {"ok": True, "type": "auth", "id": 1})

        rejected = self._run_loop(
            [{"type": "auth", "id": 2, "token": "stale-token"}],
            auth,
            client_ip="9.9.9.9",
        )
        self.assertFalse(rejected[0]["ok"])
        self.assertTrue(rejected[0]["authRequired"])

    def test_handler_speaks_http_1_1_for_browser_websocket_upgrade(self):
        # Browsers reject an upgrade response that is not HTTP/1.1 101.
        handler = build_handler(FakeLogger(), None, None, lambda _text: {}, AuthStore("482915"))
        self.assertEqual(handler.protocol_version, "HTTP/1.1")

    def test_tls_disabled_when_no_cert_files_and_no_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, TLS_ENV, clear=True):
                self.assertFalse(maybe_wrap_tls(None, FakeLogger(), Path(tmp)))

    def test_tls_defaults_to_cert_pem_in_base_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "cert.pem").write_bytes(b"fake")
            (base / "key.pem").write_bytes(b"fake")
            fake_context = mock.Mock()
            with mock.patch.dict(os.environ, TLS_ENV, clear=True), \
                 mock.patch("py_remote_input.server.ssl.SSLContext", return_value=fake_context):
                server = mock.Mock()
                enabled = maybe_wrap_tls(server, FakeLogger(), base)

            self.assertTrue(enabled)
            self.assertEqual(
                fake_context.load_cert_chain.call_args.args,
                (str(base / "cert.pem"), str(base / "key.pem")),
            )

    def test_tls_env_overrides_default_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "cert.pem").write_bytes(b"fake")
            (base / "key.pem").write_bytes(b"fake")
            env_cert = base / "other-cert.pem"
            env_key = base / "other-key.pem"
            env_cert.write_bytes(b"fake")
            env_key.write_bytes(b"fake")
            fake_context = mock.Mock()
            env = dict(TLS_ENV, SSL_CERT_FILE=str(env_cert), SSL_KEY_FILE=str(env_key))
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch("py_remote_input.server.ssl.SSLContext", return_value=fake_context):
                enabled = maybe_wrap_tls(mock.Mock(), FakeLogger(), base)

            self.assertTrue(enabled)
            self.assertEqual(
                fake_context.load_cert_chain.call_args.args,
                (str(env_cert), str(env_key)),
            )

    def test_tls_missing_one_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "cert.pem").write_bytes(b"fake")
            with mock.patch.dict(os.environ, TLS_ENV, clear=True):
                with self.assertRaises(RuntimeError):
                    maybe_wrap_tls(None, FakeLogger(), base)

    def test_create_servers_binds_http_only_without_cert(self):
        handler = build_handler(FakeLogger(), None, None, lambda _text: {}, AuthStore("482915"))
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, TLS_ENV, clear=True):
                servers, https_port = create_servers(handler, 0, None, Path(tmp), FakeLogger())
            try:
                self.assertEqual(len(servers), 1)
                self.assertIsNone(https_port)
                self.assertNotIsInstance(servers[0].socket, ssl.SSLSocket)
            finally:
                for srv in servers:
                    srv.server_close()

    def test_create_servers_binds_http_and_https_with_cert(self):
        handler = build_handler(FakeLogger(), None, None, lambda _text: {}, AuthStore("482915"))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._generate_cert(base)
            with mock.patch.dict(os.environ, TLS_ENV, clear=True):
                # Port 0 twice: two distinct ephemeral ports.
                servers, https_port = create_servers(handler, 0, 0, base, FakeLogger())
            try:
                self.assertEqual(len(servers), 2)
                self.assertIsNotNone(https_port)
                self.assertNotIsInstance(servers[0].socket, ssl.SSLSocket)
                self.assertIsInstance(servers[1].socket, ssl.SSLSocket)
            finally:
                for srv in servers:
                    srv.server_close()

    def test_create_servers_rejects_same_port_for_http_and_https(self):
        handler = build_handler(FakeLogger(), None, None, lambda _text: {}, AuthStore("482915"))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._generate_cert(base)
            with mock.patch.dict(os.environ, TLS_ENV, clear=True):
                with self.assertRaises(RuntimeError):
                    create_servers(handler, 32199, 32199, base, FakeLogger())

    @staticmethod
    def _generate_cert(base: Path) -> None:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(base / "key.pem"), "-out", str(base / "cert.pem"),
                "-days", "1", "-subj", "/CN=test",
            ],
            check=True, capture_output=True,
        )

    def test_resolve_tls_files_uses_default_then_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with mock.patch.dict(os.environ, TLS_ENV, clear=True):
                cert, key = resolve_tls_files(base)
            self.assertEqual(cert, str(base / "cert.pem"))
            self.assertEqual(key, str(base / "key.pem"))

            env = dict(TLS_ENV, SSL_CERT_FILE="/x/custom.pem")
            with mock.patch.dict(os.environ, env, clear=True):
                cert, key = resolve_tls_files(base)
            self.assertEqual(cert, "/x/custom.pem")
            self.assertEqual(key, str(base / "key.pem"))


if __name__ == "__main__":
    unittest.main()
