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

    def test_keeps_local_history(self):
        self.assertIn("remoteInput.history", self.html)
        self.assertIn('id="historyList"', self.html)

    def test_removed_windows_features_are_gone(self):
        self.assertNotIn("trackpad", self.html)
        self.assertNotIn("/api/key", self.html)
        self.assertNotIn("/api/paste", self.html)
        self.assertNotIn("/api/mouse", self.html)
        self.assertNotIn("snippet", self.html.lower())


if __name__ == "__main__":
    unittest.main()
