import io
import json
import os
import unittest
from unittest import mock

from py_remote_input.server import build_handler, maybe_wrap_tls, serve_websocket_messages
from py_remote_input.websocket import (
    build_websocket_accept,
    encode_websocket_frame,
    read_websocket_frame,
)


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

    def test_websocket_message_loop_dispatches_type_message(self):
        calls = []
        payload = json.dumps({"type": "type", "id": 7, "text": "你好"}).encode("utf-8")
        reader = io.BytesIO(build_masked_client_frame(0x1, payload) + build_masked_client_frame(0x8))
        writer = io.BytesIO()

        serve_websocket_messages(
            reader,
            writer,
            FakeLogger(),
            type_text=lambda text: calls.append(text) or {"method": "wtype", "charCount": 2},
        )

        self.assertEqual(calls, ["你好"])
        response_frame = read_websocket_frame(io.BytesIO(writer.getvalue()))
        response = json.loads(response_frame.payload.decode("utf-8"))
        self.assertTrue(response["ok"])
        self.assertEqual(response["type"], "type")
        self.assertEqual(response["id"], 7)
        self.assertEqual(response["sentChars"], 2)


    def test_handler_speaks_http_1_1_for_browser_websocket_upgrade(self):
        # Browsers reject an upgrade response that is not HTTP/1.1 101.
        handler = build_handler(FakeLogger(), None, None, lambda _text: {})
        self.assertEqual(handler.protocol_version, "HTTP/1.1")

    def test_tls_requires_both_cert_and_key(self):
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": "cert.pem", "SSL_KEY_FILE": ""}, clear=False):
            with self.assertRaises(RuntimeError):
                maybe_wrap_tls(None, FakeLogger())

    def test_tls_disabled_without_env(self):
        env = {key: value for key, value in os.environ.items()
               if key not in {"SSL_CERT_FILE", "SSL_KEY_FILE"}}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(maybe_wrap_tls(None, FakeLogger()))


if __name__ == "__main__":
    unittest.main()
