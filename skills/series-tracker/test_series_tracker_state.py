import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import redirect_stdout


MODULE_PATH = Path(__file__).with_name("series-tracker.py")
SPEC = importlib.util.spec_from_file_location("series_tracker", MODULE_PATH)
series_tracker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(series_tracker)


class SeriesTrackerStateTests(unittest.TestCase):
    def test_parse_duration_seconds(self):
        self.assertEqual(754, series_tracker.parse_duration_seconds("12:34"))
        self.assertEqual(3723, series_tracker.parse_duration_seconds("01:02:03"))
        self.assertEqual(90, series_tracker.parse_duration_seconds(90))

    def test_migrate_v1_preserves_unknown_data_and_adds_v2_episode_fields(self):
        legacy = {
            "custom_root": {"keep": True},
            "series": [{
                "series_id": "s1",
                "custom_series": "keep",
                "episodes": [{
                    "url": "https://www.bilibili.com/video/BV1abc",
                    "episode_number": 7,
                    "duration": "12:34",
                    "status": "done",
                    "legacy_note": "keep",
                }],
            }],
        }

        migrated = series_tracker.migrate_state_v2(legacy)

        episode = migrated["series"][0]["episodes"][0]
        self.assertEqual(2, migrated["version"])
        self.assertEqual({"keep": True}, migrated["custom_root"])
        self.assertEqual("keep", migrated["series"][0]["custom_series"])
        self.assertEqual("keep", episode["legacy_note"])
        self.assertEqual(754, episode["duration_seconds"])
        self.assertEqual("done", episode["download_status"])
        self.assertIn("localization_status", episode)
        self.assertIsNone(episode["last_job_id"])
        self.assertIsNone(episode["last_output_dir"])
        self.assertIsNone(episode["final_video_path"])
        self.assertEqual([], episode["compilations_used"])

    def test_migration_preserves_existing_duration_seconds(self):
        legacy = {"series": [{"episodes": [{"duration": "12:34", "duration_seconds": 99}]}]}
        migrated = series_tracker.migrate_state_v2(legacy)
        self.assertEqual(99, migrated["series"][0]["episodes"][0]["duration_seconds"])

    def test_job_status_maps_done_to_completed_stage_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_file = root / "series.json"
            queue_dir = root / "queue"
            (queue_dir / "logs").mkdir(parents=True)
            job_id = "job-done"
            state_file.write_text(json.dumps({"series": [{"episodes": [{"last_job_id": job_id}]}]}), encoding="utf-8")
            output_video = root / "out" / "final_video_vi.mp4"
            output_video.parent.mkdir()
            output_video.write_bytes(b"video")
            (queue_dir / "logs" / f"{job_id}.req.log").write_text(f"final_video: {output_video}\n", encoding="utf-8")
            output = io.StringIO()
            with patch.object(series_tracker, "STATE_DIR", root), \
                 patch.object(series_tracker, "STATE_FILE", state_file), \
                 patch.object(series_tracker, "QUEUE_DIR", queue_dir), \
                 redirect_stdout(output):
                series_tracker.cmd_job_status(SimpleNamespace(job_id=job_id))
                episode = series_tracker.load_state()["series"][0]["episodes"][0]
            self.assertEqual("done", json.loads(output.getvalue())["status"])
            self.assertEqual("done", episode["status"])
            self.assertEqual("completed", episode["download_status"])
            self.assertEqual("completed", episode["localization_status"])

    def test_job_status_marker_without_output_needs_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state_file = root / "series.json"; queue_dir = root / "queue"
            (queue_dir / "logs").mkdir(parents=True)
            job_id = "job-missing"
            state_file.write_text(json.dumps({"series": [{"episodes": [{"last_job_id": job_id}]}]}), encoding="utf-8")
            (queue_dir / "logs" / f"{job_id}.req.log").write_text("final_video: /missing/final_video_vi.mp4\n", encoding="utf-8")
            with patch.object(series_tracker, "STATE_DIR", root), patch.object(series_tracker, "STATE_FILE", state_file), patch.object(series_tracker, "QUEUE_DIR", queue_dir), redirect_stdout(io.StringIO()):
                series_tracker.cmd_job_status(SimpleNamespace(job_id=job_id))
                episode = series_tracker.load_state()["series"][0]["episodes"][0]
            self.assertEqual("needs_attention", episode["status"])
            self.assertEqual("needs_attention", episode["localization_status"])

    def test_refresh_merges_by_url_and_keeps_existing_episodes_when_discovery_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            state_file = state_dir / "series.json"
            state_file.write_text(
                '{"version": 1, "series": [{"series_id": "s1", "source_url": "https://example.test", '
                '"keyword": "show", "episodes": [{"url": "https://www.bilibili.com/video/BVold", '
                '"episode_number": 1, "status": "done", "last_job_id": "job-old", '
                '"final_video_path": "/out/final_video_vi.mp4"}]}]}',
                encoding="utf-8",
            )
            async def fetched(*_args):
                return {"items": ["ignored"], "title": "Show", "url": "https://example.test"}

            discovered = [{
                "url": "https://www.bilibili.com/video/BVold",
                "episode_number": 1,
                "status": "ready",
            }, {
                "url": "https://www.bilibili.com/video/BVnew",
                "episode_number": 2,
                "status": "ready",
            }, {
                "url": "https://www.bilibili.com/video/BVnew",
                "episode_number": 2,
                "status": "ready",
            }]
            with patch.object(series_tracker, "STATE_DIR", state_dir), \
                 patch.object(series_tracker, "STATE_FILE", state_file), \
                 patch.object(series_tracker, "fetch_bilibili_items", fetched), \
                 patch.object(series_tracker, "items_to_episodes", return_value=discovered):
                series_tracker.cmd_refresh(SimpleNamespace(series_id="s1", limit=10))
                refreshed = series_tracker.load_state()["series"][0]
                old = next(ep for ep in refreshed["episodes"] if ep["url"].endswith("BVold"))
                self.assertEqual("done", old["status"])
                self.assertEqual("job-old", old["last_job_id"])
                self.assertEqual("/out/final_video_vi.mp4", old["final_video_path"])
                self.assertEqual(2, len(refreshed["episodes"]))
                new = next(ep for ep in refreshed["episodes"] if ep["url"].endswith("BVnew"))
                self.assertEqual("new", new["status"])

                with patch.object(series_tracker, "fetch_bilibili_items", fetched), \
                     patch.object(series_tracker, "items_to_episodes", return_value=[]):
                    series_tracker.cmd_refresh(SimpleNamespace(series_id="s1", limit=10))
                retained = series_tracker.load_state()["series"][0]
                self.assertEqual(2, len(retained["episodes"]))
                self.assertTrue(retained["last_error"].startswith("needs_attention:"))


if __name__ == "__main__":
    unittest.main()
