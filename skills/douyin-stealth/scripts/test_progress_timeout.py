import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("fetch_douyin_v2.py").read_text(encoding="utf-8")


class ProgressTimeoutTests(unittest.TestCase):
    def test_timeout_triggers_only_after_240_seconds(self):
        self.assertIn("if elapsed > 240:", SOURCE)
        self.assertNotIn("elapsed > 180", SOURCE)
        self.assertEqual(1, SOURCE.count('task_data["timeout_triggered"] = True'))


if __name__ == "__main__":
    unittest.main()
