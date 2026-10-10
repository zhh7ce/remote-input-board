import json
import re
import tempfile
import unittest
from pathlib import Path

from py_remote_input.server import build_history_recorder


class HistoryRecorderTests(unittest.TestCase):
    def test_writes_to_daily_hourly_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            recorder = build_history_recorder(log_dir)

            recorder({"kind": "text", "text": "记录"})

            files = sorted((log_dir / "history").rglob("*.log"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["text"], "记录")
            self.assertRegex(payload["createdAt"], r"^\d{4}-\d{2}-\d{2}T.*Z$")
            self.assertRegex(files[0].parent.name, r"^\d{4}-\d{2}-\d{2}$")
            self.assertRegex(files[0].name, r"^\d{2}\.log$")

    def test_appends_one_line_per_item(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            recorder = build_history_recorder(log_dir)

            recorder({"kind": "text", "text": "你好"})
            recorder({"kind": "key", "key": "Return"})

            lines = [
                json.loads(line)
                for path in sorted((log_dir / "history").rglob("*.log"))
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([line["kind"] for line in lines], ["text", "key"])
            self.assertEqual(lines[1]["key"], "Return")


if __name__ == "__main__":
    unittest.main()
