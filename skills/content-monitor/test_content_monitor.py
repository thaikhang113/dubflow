import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("content-monitor.py")
SPEC = importlib.util.spec_from_file_location("content_monitor", MODULE_PATH)
content_monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(content_monitor)


class ContentMonitorTests(unittest.TestCase):
    def test_failed_telegram_delivery_does_not_mark_video_seen(self):
        channels = [{"name": "test", "url": "https://example.test"}]
        videos = [{"id": "video-1", "url": "https://example.test/video-1", "title": "one"}]
        logs = []
        with patch.object(content_monitor, "load_channels", return_value=channels), \
             patch.object(content_monitor, "fetch_latest_videos_for_channel", return_value=videos), \
             patch.object(content_monitor, "is_seen", return_value=False), \
             patch.object(content_monitor, "analyze_video", return_value=None), \
             patch.object(content_monitor, "send_telegram", return_value=False), \
             patch.object(content_monitor, "mark_seen") as mark_seen, \
             patch.object(content_monitor, "log", side_effect=lambda message, *_args: logs.append(message)), \
             patch.object(content_monitor.time, "sleep"):
            content_monitor.run_check_cycle()

        mark_seen.assert_not_called()
        self.assertFalse(any("da xu ly 1 video" in message for message in logs))

    def test_save_json_replaces_complete_temporary_file_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            real_replace = os.replace
            with patch.object(content_monitor.os, "replace", wraps=real_replace) as replace:
                content_monitor.save_json(str(target), {"value": "ok"})

            self.assertEqual({"value": "ok"}, json.loads(target.read_text(encoding="utf-8")))
            self.assertEqual(target, Path(replace.call_args.args[1]))
            self.assertEqual([], list(Path(tmp).glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
