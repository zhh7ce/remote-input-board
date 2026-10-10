from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "py_remote_input" / "templates" / "index.html"


class FrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_core_text_input_controls_exist(self):
        self.assertIn('<textarea id="text"', self.html)
        self.assertIn('id="sendButton"', self.html)
        self.assertIn('id="clearButton"', self.html)

    def test_uses_stateless_http_no_websocket(self):
        self.assertNotIn("new WebSocket", self.html)
        self.assertNotIn('"/ws"', self.html)
        self.assertNotIn("connectRealtime", self.html)
        # Sends carry the token in the URL: POST /api/type?token=...
        self.assertIn('"/api/type?token="', self.html)
        self.assertIn("sendRequest", self.html)

    def test_sends_text_and_key_as_plain_payloads(self):
        self.assertIn("sendRequest({ text: payloadText })", self.html)
        self.assertIn("sendRequest({ key: \"Return\" })", self.html)
        self.assertNotIn('type: "type"', self.html)
        self.assertNotIn('type: "key"', self.html)

    def test_empty_send_can_press_enter_via_checkbox(self):
        self.assertIn('id="enterWhenEmpty"', self.html)
        self.assertIn("remoteInput.enterWhenEmpty", self.html)

    def test_total_char_counter_is_removed(self):
        self.assertNotIn("totalChars", self.html)
        self.assertNotIn("累计", self.html)
        self.assertNotIn("/api/stats", self.html)

    def test_pair_status_bar_is_removed(self):
        # Stateless HTTP: the lock screen covers "unpaired", 401 auto-locks,
        # so a persistent status bar carries no information.
        self.assertNotIn("statusbar", self.html)
        self.assertNotIn("setPairState", self.html)
        self.assertNotIn("已配对", self.html)
        self.assertNotIn("未配对", self.html)
        # Ping is still used at boot to validate a stored token.
        self.assertIn("/api/ping?token=", self.html)

    def test_line_breaks_are_sent_verbatim_without_a_warning(self):
        # commitString() delivers newlines as text, never as Enter events, so the
        # old "换行已转为空格" hint would be an outright lie.
        self.assertNotIn("换行已转为空格", self.html)
        self.assertIn("const payloadText = text.value;", self.html)
        self.assertNotIn("payloadText.replace(", self.html)

    def test_url_token_auto_pairs(self):
        self.assertIn("adoptUrlToken", self.html)
        self.assertIn("history.replaceState", self.html)
        self.assertIn("URLSearchParams", self.html)

    def test_keeps_local_history(self):
        self.assertIn("remoteInput.history", self.html)
        self.assertIn('id="historyList"', self.html)

    def test_pin_lock_screen_uses_on_screen_keypad_without_text_input(self):
        self.assertIn('id="lockOverlay"', self.html)
        self.assertIn('id="lockDots"', self.html)
        self.assertIn('id="keypad"', self.html)
        self.assertIn("renderKeypad", self.html)
        self.assertIn("pressDigit", self.html)
        # Digits come from button taps, not a system-keyboard input.
        lock_section = self.html.split('id="lockOverlay"', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<input", lock_section)
        self.assertNotIn('contenteditable', lock_section)

    def test_pin_auth_flow_and_token_storage(self):
        self.assertIn('"/api/auth"', self.html)
        self.assertIn('"/api/auth-info"', self.html)
        self.assertIn('"/api/logout"', self.html)
        self.assertIn("remoteInput.token", self.html)
        self.assertIn("response.status === 401", self.html)
        self.assertIn('id="lockButton"', self.html)
        self.assertIn("lockDevice", self.html)

    def test_removed_windows_features_are_gone(self):
        self.assertNotIn("trackpad", self.html)
        self.assertNotIn("/api/key", self.html)
        self.assertNotIn("/api/paste", self.html)
        self.assertNotIn("/api/mouse", self.html)
        self.assertNotIn("snippet", self.html.lower())


if __name__ == "__main__":
    unittest.main()
