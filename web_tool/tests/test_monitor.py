import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_tool.app import create_app
from web_tool.config import Settings
from web_tool.monitor import MonitorAttention, MonitorScheduler
from web_tool.store import Store


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings.for_test(Path(self.tmp.name))
        self.store = Store(self.settings.database_path)

    def tearDown(self):
        self.tmp.cleanup()

    def add_channel(self, **overrides):
        values = {
            "name": "Kênh test",
            "platform": "bilibili",
            "url": "https://space.bilibili.com/123",
            "interval_minutes": 60,
            "enabled": True,
            "provider_id": "",
            "model": "qwen2.5:3b",
            "voice": "ai33:vbee_hn_female_ngochuyen_full_48k-fhg",
            "series_id": "series-one",
            "preset": {"mode": "exact_sync"},
        }
        values.update(overrides)
        return self.store.create_channel(values)

    def test_due_channel_runs_once_and_inherits_preset(self):
        provider = self.store.create_provider(
            {
                "name": "Ollama",
                "kind": "ollama",
                "endpoint": "http://host.docker.internal:11434",
                "model": "qwen2.5:3b",
                "timeout_seconds": 90,
            },
            has_secret=False,
        )
        ai33 = self.store.create_provider(
            {
                'name': 'AI33',
                'kind': 'ai33',
                'endpoint': 'https://api.ai33.pro',
                'model': '',
                'timeout_seconds': 90,
            },
            has_secret=True,
        )
        channel = self.add_channel(provider_id=provider["id"])
        calls = []

        def discover(candidate, count=10):
            calls.append((candidate["id"], count))
            return [{
                "id": "bilibili:BV1TEST",
                "url": "https://www.bilibili.com/video/BV1TEST",
                "title": "Tập mới",
            }]

        scheduler = MonitorScheduler(self.store, self.settings, discovery=discover)
        self.assertEqual(1, scheduler.run_due_once()["checked"])
        self.assertEqual(0, scheduler.run_due_once()["checked"])
        self.assertEqual([(channel["id"], 10)], calls)

        jobs = self.store.list_jobs()
        self.assertEqual(1, len(jobs))
        request = jobs[0]["request"]
        self.assertEqual(provider["id"], request["translation_provider_id"])
        self.assertEqual("qwen2.5:3b", request["model"])
        self.assertEqual(
            "ai33:vbee_hn_female_ngochuyen_full_48k-fhg",
            request["voice"],
        )
        self.assertEqual("series-one", request["series_id"])
        self.assertEqual({"mode": "exact_sync"}, request["preset"])
        self.assertEqual("Tập mới", request["source_title"])

        self.assertEqual(ai33['id'], request['tts_provider_id'])

    def test_duplicate_video_is_enqueued_once_across_scheduler_restart(self):
        channel = self.add_channel()
        video = [{
            "id": "bilibili:BV1SAME",
            "url": "https://www.bilibili.com/video/BV1SAME",
            "title": "Một video",
        }]
        MonitorScheduler(
            self.store,
            self.settings,
            discovery=lambda *_args, **_kwargs: video,
        ).run_channel_once(channel["id"])
        MonitorScheduler(
            Store(self.settings.database_path),
            self.settings,
            discovery=lambda *_args, **_kwargs: video,
        ).run_channel_once(channel["id"])
        self.assertEqual(1, len(self.store.list_jobs()))

    def test_disabled_channel_does_not_run(self):
        channel = self.add_channel(enabled=False)
        self.assertEqual("disabled", channel["state"])
        calls = []
        scheduler = MonitorScheduler(
            self.store,
            self.settings,
            discovery=lambda *_args, **_kwargs: calls.append(True),
        )
        self.assertEqual(0, scheduler.run_due_once()["checked"])
        self.assertEqual([], calls)

    def test_login_or_captcha_marks_channel_needs_attention(self):
        channel = self.add_channel()

        def discover(*_args, **_kwargs):
            raise MonitorAttention("BilibiliCaptchaRequired")

        result = MonitorScheduler(
            self.store,
            self.settings,
            discovery=discover,
        ).run_channel_once(channel["id"])
        self.assertEqual("needs_attention", result["state"])
        self.assertEqual("BilibiliCaptchaRequired", result["error_code"])
        saved = self.store.get_channel(channel["id"])
        self.assertEqual("needs_attention", saved["state"])
        self.assertEqual("BilibiliCaptchaRequired", saved["error_code"])

    def test_delete_during_discovery_does_not_crash_scheduler(self):
        channel = self.add_channel()

        def discover(*_args, **_kwargs):
            self.store.delete_channel(channel["id"])
            return []

        result = MonitorScheduler(
            self.store,
            self.settings,
            discovery=discover,
        ).run_channel_once(channel["id"])
        self.assertIsNone(result)

    def test_channel_api_manages_and_schedules_channels(self):
        app = create_app(self.settings)
        app.state.monitor.discovery = lambda *_args, **_kwargs: []
        with TestClient(app) as client:
            payload = {
                "name": "Bilibili",
                "platform": "bilibili",
                "url": "https://space.bilibili.com/123",
                "interval_minutes": 30,
                "enabled": True,
                "model": "qwen3:8b",
                "preset": {"mode": "exact_sync"},
            }
            created = client.post("/api/channels", json=payload)
            self.assertEqual(201, created.status_code, created.text)
            channel_id = created.json()["id"]
            self.assertEqual(
                [channel_id],
                [channel["id"] for channel in client.get("/api/channels").json()],
            )

            payload["name"] = "Bilibili mới"
            payload["enabled"] = False
            updated = client.put(f"/api/channels/{channel_id}", json=payload)
            self.assertEqual("Bilibili mới", updated.json()["name"])
            self.assertEqual("disabled", updated.json()["state"])
            self.assertFalse(
                client.post(f"/api/channels/{channel_id}/disable").json()["enabled"]
            )
            self.assertTrue(
                client.post(f"/api/channels/{channel_id}/enable").json()["enabled"]
            )
            self.assertEqual(
                200,
                client.post(f"/api/channels/{channel_id}/run").status_code,
            )
            self.assertEqual(
                204,
                client.delete(f"/api/channels/{channel_id}").status_code,
            )


if __name__ == "__main__":
    unittest.main()
