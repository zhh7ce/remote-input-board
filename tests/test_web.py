import json
import unittest
from importlib import resources

import py_remote_input
from py_remote_input.auth import AuthStore
from py_remote_input.web import handle_realtime_message, handle_request


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, meta=None):
        self.messages.append(("info", message, meta))

    def warn(self, message, meta=None):
        self.messages.append(("warn", message, meta))

    def error(self, message, meta=None):
        self.messages.append(("error", message, meta))


class FakeTextStats:
    def __init__(self, total=0):
        self.total = total

    def get_total_chars(self):
        return self.total

    def add_text(self, _text):
        return self.total

    def save_total_chars(self, total):
        self.total = total
        return self.total


class HttpEndpointTests(unittest.TestCase):
    def test_serves_mobile_page(self):
        response = handle_request("GET", "/", b"", lambda _text: {}, FakeLogger())
        template = resources.files(py_remote_input).joinpath("templates", "index.html").read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body.decode("utf-8"), template)
        self.assertIn("textarea", response.body.decode("utf-8"))

    def test_type_request_calls_typer(self):
        calls = []

        def type_text(text):
            calls.append(text)
            return {"method": "wtype", "durationMs": 12, "charCount": 2}

        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"text": "你好"}).encode("utf-8"),
            type_text,
            FakeLogger(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["你好"])
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sentChars"], 2)
        self.assertEqual(payload["method"], "wtype")

    def test_type_request_records_history(self):
        records = []
        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"text": "重要内容"}).encode("utf-8"),
            lambda _text: {"method": "wtype"},
            FakeLogger(),
            record_history=lambda item: records.append(item),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(records, [{"kind": "text", "text": "重要内容"}])

    def test_type_request_includes_total_chars(self):
        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"text": "字"}).encode("utf-8"),
            lambda _text: {"method": "wtype"},
            FakeLogger(),
            text_stats=FakeTextStats(99),
        )

        self.assertEqual(json.loads(response.body.decode("utf-8"))["totalChars"], 99)

    def test_rejects_empty_text(self):
        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"text": "   "}).encode("utf-8"),
            lambda _text: {},
            FakeLogger(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Text is required", response.body.decode("utf-8"))

    def test_rejects_invalid_json(self):
        response = handle_request("POST", "/api/type", b"not json", lambda _text: {}, FakeLogger())

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid JSON body", response.body.decode("utf-8"))

    def test_typer_failure_returns_500(self):
        def type_text(_text):
            raise RuntimeError("wtype exploded")

        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"text": "hi"}).encode("utf-8"),
            type_text,
            FakeLogger(),
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn("wtype exploded", response.body.decode("utf-8"))

    def test_stats_endpoint_returns_total(self):
        response = handle_request(
            "GET",
            "/api/stats",
            b"",
            lambda _text: {},
            FakeLogger(),
            text_stats=FakeTextStats(42),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode("utf-8"))["totalChars"], 42)

    def test_unknown_route_returns_404(self):
        response = handle_request("GET", "/api/mouse/click", b"", lambda _text: {}, FakeLogger())

        self.assertEqual(response.status_code, 404)


class RealtimeMessageTests(unittest.TestCase):
    def test_ping_returns_pong(self):
        result = handle_realtime_message({"type": "ping"}, FakeLogger())

        self.assertEqual(result, {"ok": True, "type": "pong"})

    def test_type_message_calls_typer_and_records_history(self):
        calls = []
        records = []
        result = handle_realtime_message(
            {"type": "type", "text": "你好"},
            FakeLogger(),
            type_text=lambda text: calls.append(text) or {"method": "wtype", "charCount": 2},
            record_history=lambda item: records.append(item),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["type"], "type")
        self.assertEqual(result["sentChars"], 2)
        self.assertEqual(calls, ["你好"])
        self.assertEqual(records, [{"kind": "text", "text": "你好"}])

    def test_type_message_rejects_empty_text(self):
        result = handle_realtime_message(
            {"type": "type", "text": "  "},
            FakeLogger(),
            type_text=lambda _text: {},
        )

        self.assertFalse(result["ok"])
        self.assertIn("Text is required", result["error"])

    def test_type_message_when_unconfigured(self):
        result = handle_realtime_message({"type": "type", "text": "hi"}, FakeLogger())

        self.assertFalse(result["ok"])
        self.assertIn("not configured", result["error"])

    def test_get_stats_returns_total(self):
        result = handle_realtime_message(
            {"type": "getStats"},
            FakeLogger(),
            text_stats=FakeTextStats(12345),
        )

        self.assertEqual(result["type"], "stats")
        self.assertEqual(result["totalChars"], 12345)

    def test_set_stats_saves_total(self):
        stats = FakeTextStats(100)
        result = handle_realtime_message(
            {"type": "setStats", "totalChars": 500},
            FakeLogger(),
            text_stats=stats,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["totalChars"], 500)
        self.assertEqual(stats.get_total_chars(), 500)

    def test_set_stats_rejects_non_numeric(self):
        result = handle_realtime_message(
            {"type": "setStats", "totalChars": "abc"},
            FakeLogger(),
            text_stats=FakeTextStats(),
        )

        self.assertFalse(result["ok"])
        self.assertIn("numeric totalChars", result["error"])

    def test_unknown_message_is_rejected(self):
        result = handle_realtime_message({"type": "mouseMove", "dx": 1}, FakeLogger())

        self.assertFalse(result["ok"])
        self.assertIn("Unsupported realtime message", result["error"])

    def test_non_object_payload_is_rejected(self):
        result = handle_realtime_message(["nope"], FakeLogger())

        self.assertFalse(result["ok"])

    def test_typer_exception_is_caught(self):
        def type_text(_text):
            raise RuntimeError("boom")

        result = handle_realtime_message(
            {"type": "type", "text": "hi"},
            FakeLogger(),
            type_text=type_text,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "boom")


class PinGateTests(unittest.TestCase):
    IP = "192.168.1.50"

    def setUp(self):
        self.auth = AuthStore("482915")
        self.logger = FakeLogger()

    def request(self, method, path, body=b"", *, token=None, ip=IP):
        return handle_request(
            method,
            path,
            body,
            lambda _text: {"method": "wtype"},
            self.logger,
            auth=self.auth,
            client_ip=ip,
            token=token,
        )

    def test_page_and_auth_info_are_public(self):
        page = self.request("GET", "/")
        info = self.request("GET", "/api/auth-info")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(json.loads(info.body.decode("utf-8"))["pinLength"], 6)

    def test_stats_requires_pin(self):
        response = self.request("GET", "/api/stats")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(json.loads(response.body.decode("utf-8"))["authRequired"])

    def test_type_requires_pin(self):
        response = self.request("POST", "/api/type", json.dumps({"text": "hi"}).encode("utf-8"))
        self.assertEqual(response.status_code, 401)

    def test_wrong_pin_rejected(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "000000"}).encode("utf-8"))
        self.assertEqual(response.status_code, 401)

    def test_correct_pin_returns_token_and_unlocks_api(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        self.assertEqual(response.status_code, 200)
        token = json.loads(response.body.decode("utf-8"))["token"]

        stats = self.request("GET", "/api/stats", token=token)
        self.assertEqual(stats.status_code, 200)

    def test_token_works_from_other_ip(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        token = json.loads(response.body.decode("utf-8"))["token"]

        foreign = self.request("GET", "/api/stats", token=token, ip="10.0.0.7")
        self.assertEqual(foreign.status_code, 200)

    def test_logout_revokes_token(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        token = json.loads(response.body.decode("utf-8"))["token"]
        self.assertEqual(self.request("GET", "/api/stats", token=token).status_code, 200)

        logout = self.request("POST", "/api/logout", token=token)
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.request("GET", "/api/stats", token=token).status_code, 401)

    def test_empty_pin_is_bad_request(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "  "}).encode("utf-8"))
        self.assertEqual(response.status_code, 400)

    def test_rate_limit_returns_429(self):
        for _ in range(5):
            self.request("POST", "/api/auth", json.dumps({"pin": "111111"}).encode("utf-8"))
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        self.assertEqual(response.status_code, 429)
        self.assertIn("retryAfter", json.loads(response.body.decode("utf-8")))


if __name__ == "__main__":
    unittest.main()
