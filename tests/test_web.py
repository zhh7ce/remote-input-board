import json
import unittest
from importlib import resources

import py_remote_input
from py_remote_input.auth import AuthStore
from py_remote_input.web import MAX_GET_TEXT_CHARS, handle_request


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, meta=None):
        self.messages.append(("info", message, meta))

    def warn(self, message, meta=None):
        self.messages.append(("warn", message, meta))

    def error(self, message, meta=None):
        self.messages.append(("error", message, meta))


class HttpEndpointTests(unittest.TestCase):
    def test_serves_mobile_page(self):
        response = handle_request("GET", "/", b"", lambda _text: {}, FakeLogger())
        template = resources.files(py_remote_input).joinpath("templates", "index.html").read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body.decode("utf-8"), template)
        self.assertIn("textarea", response.body.decode("utf-8"))

    def test_type_request_calls_text_input(self):
        calls = []

        def type_text(text):
            calls.append(text)
            return {"method": "fcitx5", "durationMs": 12, "charCount": 2}

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
        self.assertEqual(payload["method"], "fcitx5")

    def test_type_request_records_history(self):
        records = []
        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"text": "重要内容"}).encode("utf-8"),
            lambda _text: {"method": "fcitx5"},
            FakeLogger(),
            record_history=lambda item: records.append(item),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(records, [{"kind": "text", "text": "重要内容"}])

    def test_type_request_returns_only_its_own_length(self):
        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"text": "字"}).encode("utf-8"),
            lambda _text: {"method": "fcitx5"},
            FakeLogger(),
        )

        self.assertEqual(json.loads(response.body.decode("utf-8"))["sentChars"], 1)
        self.assertNotIn("totalChars", json.loads(response.body.decode("utf-8")))

    def test_key_request_presses_return(self):
        pressed = []

        def press_key(key):
            pressed.append(key)
            return {"method": "wtype", "key": key}

        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"key": "Return"}).encode("utf-8"),
            lambda _text: {},
            FakeLogger(),
            press_key=press_key,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(pressed, ["Return"])
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["key"], "Return")

    def test_key_request_records_history(self):
        records = []
        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"key": "Return"}).encode("utf-8"),
            lambda _text: {},
            FakeLogger(),
            press_key=lambda key: {"method": "wtype", "key": key},
            record_history=lambda item: records.append(item),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(records, [{"kind": "key", "key": "Return"}])
        self.assertNotIn("totalChars", json.loads(response.body.decode("utf-8")))

    def test_rejects_unsupported_key(self):
        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"key": "Super_L"}).encode("utf-8"),
            lambda _text: {},
            FakeLogger(),
            press_key=lambda key: {},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported key", response.body.decode("utf-8"))

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

    def test_text_injector_failure_returns_500(self):
        def type_text(_text):
            raise RuntimeError("text injector unreachable")

        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"text": "hi"}).encode("utf-8"),
            type_text,
            FakeLogger(),
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn("text injector unreachable", response.body.decode("utf-8"))

    def test_stats_endpoint_is_gone(self):
        # The cumulative char counter was removed; the route must 404, not
        # silently keep serving a stale total.
        response = handle_request("GET", "/api/stats", b"", lambda _text: {}, FakeLogger())

        self.assertEqual(response.status_code, 404)

    def test_unknown_route_returns_404(self):
        response = handle_request("GET", "/api/mouse/click", b"", lambda _text: {}, FakeLogger())

        self.assertEqual(response.status_code, 404)


class UrlApiTests(unittest.TestCase):
    """GET /api/type: token + text/key all carried in the URL."""

    def test_get_type_calls_text_input_and_records_history(self):
        calls = []
        records = []
        response = handle_request(
            "GET",
            "/api/type",
            b"",
            lambda text: calls.append(text) or {"method": "fcitx5"},
            FakeLogger(),
            record_history=records.append,
            query={"token": "t", "text": "链接发送"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["链接发送"])
        self.assertEqual(records, [{"kind": "text", "text": "链接发送"}])
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sentChars"], 4)

    def test_get_type_key_presses_return(self):
        pressed = []
        records = []
        response = handle_request(
            "GET",
            "/api/type",
            b"",
            lambda _text: {},
            FakeLogger(),
            press_key=lambda key: pressed.append(key) or {"method": "wtype", "key": key},
            record_history=records.append,
            query={"key": "Return"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(pressed, ["Return"])
        self.assertEqual(records, [{"kind": "key", "key": "Return"}])
        self.assertNotIn("totalChars", json.loads(response.body.decode("utf-8")))

    def test_get_type_rejects_unsupported_key(self):
        response = handle_request(
            "GET", "/api/type", b"", lambda _text: {}, FakeLogger(),
            press_key=lambda key: {}, query={"key": "Escape"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported key", response.body.decode("utf-8"))

    def test_get_type_rejects_missing_params(self):
        response = handle_request(
            "GET", "/api/type", b"", lambda _text: {}, FakeLogger(), query={},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("text or key", response.body.decode("utf-8"))

    def test_get_type_rejects_empty_text(self):
        response = handle_request(
            "GET", "/api/type", b"", lambda _text: {}, FakeLogger(), query={"text": "  "},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Text is required", response.body.decode("utf-8"))

    def test_get_type_caps_url_text_length(self):
        response = handle_request(
            "GET",
            "/api/type",
            b"",
            lambda _text: {},
            FakeLogger(),
            query={"text": "好" * (MAX_GET_TEXT_CHARS + 1)},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("too long", response.body.decode("utf-8"))

    def test_get_type_allows_text_at_limit(self):
        response = handle_request(
            "GET",
            "/api/type",
            b"",
            lambda _text: {"method": "fcitx5"},
            FakeLogger(),
            query={"text": "好" * MAX_GET_TEXT_CHARS},
        )

        self.assertEqual(response.status_code, 200)

    def test_ping_endpoint_exists(self):
        response = handle_request("GET", "/api/ping", b"", lambda _text: {}, FakeLogger())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.body.decode("utf-8"))["ok"])


class PinGateTests(unittest.TestCase):
    IP = "192.168.1.50"

    def setUp(self):
        self.auth = AuthStore("482915")
        self.logger = FakeLogger()

    def request(self, method, path, body=b"", *, token=None, ip=IP, query=None):
        return handle_request(
            method,
            path,
            body,
            lambda _text: {"method": "fcitx5"},
            self.logger,
            auth=self.auth,
            client_ip=ip,
            token=token,
            query=query,
        )

    def test_page_and_auth_info_are_public(self):
        page = self.request("GET", "/")
        info = self.request("GET", "/api/auth-info")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(json.loads(info.body.decode("utf-8"))["pinLength"], 6)

    def test_type_requires_pin(self):
        response = self.request("POST", "/api/type", json.dumps({"text": "hi"}).encode("utf-8"))
        self.assertEqual(response.status_code, 401)

    def test_get_type_and_ping_require_pin(self):
        get_type = self.request("GET", "/api/type", query={"text": "hi"})
        ping = self.request("GET", "/api/ping")
        self.assertEqual(get_type.status_code, 401)
        self.assertEqual(ping.status_code, 401)
        self.assertTrue(json.loads(get_type.body.decode("utf-8"))["authRequired"])

    def test_wrong_pin_rejected(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "000000"}).encode("utf-8"))
        self.assertEqual(response.status_code, 401)

    def test_correct_pin_returns_token_and_unlocks_api(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        self.assertEqual(response.status_code, 200)
        token = json.loads(response.body.decode("utf-8"))["token"]

        ping = self.request("GET", "/api/ping", token=token)
        self.assertEqual(ping.status_code, 200)

    def test_bearer_token_still_works(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        token = json.loads(response.body.decode("utf-8"))["token"]

        response = handle_request(
            "POST",
            "/api/type",
            json.dumps({"text": "头令牌"}).encode("utf-8"),
            lambda _text: {"method": "fcitx5"},
            self.logger,
            auth=self.auth,
            client_ip=self.IP,
            token=token,
        )
        self.assertEqual(response.status_code, 200)

    def test_query_token_unlocks_get_and_post(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        token = json.loads(response.body.decode("utf-8"))["token"]

        get_type = self.request("GET", "/api/type", query={"token": token, "text": "查令牌"})
        self.assertEqual(get_type.status_code, 200)

        post_type = self.request("POST", "/api/type", json.dumps({"text": "hi"}).encode("utf-8"), query={"token": token})
        self.assertEqual(post_type.status_code, 200)

        ping = self.request("GET", "/api/ping", query={"token": token})
        self.assertEqual(ping.status_code, 200)

    def test_invalid_query_token_rejected(self):
        response = self.request("GET", "/api/type", query={"token": "forged", "text": "hi"})
        self.assertEqual(response.status_code, 401)

    def test_bearer_takes_precedence_over_query_token(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        good = json.loads(response.body.decode("utf-8"))["token"]

        # A bad query token must not downgrade a valid Bearer header.
        response = self.request("GET", "/api/ping", token=good, query={"token": "forged"})
        self.assertEqual(response.status_code, 200)

    def test_token_works_from_other_ip(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        token = json.loads(response.body.decode("utf-8"))["token"]

        foreign = self.request("GET", "/api/ping", token=token, ip="10.0.0.7")
        self.assertEqual(foreign.status_code, 200)

    def test_logout_revokes_token(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        token = json.loads(response.body.decode("utf-8"))["token"]
        self.assertEqual(self.request("GET", "/api/ping", token=token).status_code, 200)

        logout = self.request("POST", "/api/logout", token=token)
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.request("GET", "/api/ping", token=token).status_code, 401)

    def test_logout_accepts_query_token(self):
        response = self.request("POST", "/api/auth", json.dumps({"pin": "482915"}).encode("utf-8"))
        token = json.loads(response.body.decode("utf-8"))["token"]

        logout = self.request("POST", "/api/logout", query={"token": token})
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.request("GET", "/api/ping", query={"token": token}).status_code, 401)

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
