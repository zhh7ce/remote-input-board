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

    def test_connects_websocket_and_falls_back_to_http(self):
        self.assertIn('"/ws"', self.html)
        self.assertIn("new WebSocket", self.html)
        self.assertIn('"/api/type"', self.html)
        self.assertIn("connectRealtime", self.html)
        self.assertIn("sendViaHttp", self.html)

    def test_sends_type_message_with_text(self):
        self.assertIn('type: "type"', self.html)
        self.assertIn("sendText", self.html)

    def test_empty_send_can_press_enter_via_checkbox(self):
        self.assertIn('id="enterWhenEmpty"', self.html)
        self.assertIn("remoteInput.enterWhenEmpty", self.html)
        self.assertIn('type: "key", key: "Return"', self.html)

    def test_total_char_counter_is_removed(self):
        self.assertNotIn("totalChars", self.html)
        self.assertNotIn("累计", self.html)
        self.assertNotIn("/api/stats", self.html)

    def test_status_bar_shows_fixed_connection_state(self):
        self.assertIn("setConnectionState", self.html)
        self.assertIn("已连接（实时通道）", self.html)
        self.assertIn("未连接（HTTP 发送）", self.html)
        self.assertIn("正在连接…", self.html)

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

    def test_pin_auth_flow_and_bearer_token(self):
        self.assertIn('"/api/auth"', self.html)
        self.assertIn('"/api/auth-info"', self.html)
        self.assertIn('"/api/logout"', self.html)
        self.assertIn("remoteInput.token", self.html)
        self.assertIn("Authorization", self.html)
        self.assertIn('type: "auth"', self.html)
        self.assertIn("authRequired", self.html)
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
