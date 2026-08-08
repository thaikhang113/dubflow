import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from web_tool.app import create_app
from web_tool.config import Settings


FIXTURE = Path(__file__).with_name("fixtures") / "fake_pipeline.py"


def wait_for_job(client, job_id, states, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {states}")


def fake_command(job, _settings):
    request = job.get("request") or job
    return [sys.executable, str(FIXTURE), request["source"]]


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings.for_test(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_fifo_failure_resume_restart_and_secret_isolation(self):
        secret = "test-secret-must-never-leak"
        app = create_app(self.settings)
        with patch("web_tool.worker.build_job_command", side_effect=fake_command):
            with TestClient(app) as client:
                client.post("/api/queue/pause")
                provider = client.post(
                    "/api/providers",
                    json={
                        "name": "Test translation",
                        "kind": "openai_compatible",
                        "endpoint": "https://api.example.com/v1",
                        "model": "test-model",
                        "api_key": secret,
                    },
                ).json()
                first = client.post(
                    "/api/jobs",
                    json={
                        "platform": "bilibili",
                        "source": "https://www.bilibili.com/video/BVSUCCESS",
                        "translation_provider_id": provider["id"],
                    },
                ).json()
                second = client.post(
                    "/api/jobs",
                    json={
                        "platform": "bilibili",
                        "source": "https://www.bilibili.com/video/BVFAIL",
                        "translation_provider_id": provider["id"],
                    },
                ).json()

                client.post("/api/queue/resume")
                running = wait_for_job(client, first["id"], {"running", "completed"})
                if running["state"] == "running":
                    self.assertEqual(
                        "queued",
                        client.get(f"/api/jobs/{second['id']}").json()["state"],
                    )

                completed = wait_for_job(client, first["id"], {"completed"})
                video = client.get(
                    f"/api/jobs/{first['id']}/artifacts/final_video_vi.mp4"
                )
                self.assertEqual(200, video.status_code)
                self.assertGreater(len(video.content), 0)

                failed = wait_for_job(client, second["id"], {"needs_attention"})
                self.assertEqual("FakeCueFailed", failed["error_code"])
                self.assertEqual("resume", failed["action"])
                resumed = client.post(f"/api/jobs/{second['id']}/resume")
                self.assertEqual(200, resumed.status_code, resumed.text)
                self.assertEqual(
                    "completed",
                    wait_for_job(client, second["id"], {"completed"})["state"],
                )

                public = repr(
                    {
                        "providers": client.get("/api/providers").json(),
                        "jobs": client.get("/api/jobs").json(),
                    }
                )
                self.assertNotIn(secret, public)

        database = self.settings.database_path.read_bytes()
        self.assertNotIn(secret.encode(), database)
        for path in self.settings.jobs_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes())

        restarted = create_app(self.settings)
        restarted.state.store.set_queue_paused(True)
        with TestClient(restarted) as client:
            jobs = client.get("/api/jobs").json()
            self.assertEqual(2, len(jobs))
            self.assertTrue(all(job["state"] == "completed" for job in jobs))
            self.assertNotIn(secret, repr(jobs))

    def test_channel_discovery_deduplicates_and_trend_absence_is_explicit(self):
        app = create_app(self.settings)
        app.state.store.set_queue_paused(True)
        app.state.monitor.discovery = lambda *_args, **_kwargs: [
            {
                "id": "bilibili:BVCHANNEL",
                "url": "https://www.bilibili.com/video/BVCHANNEL",
                "title": "Tap moi",
            }
        ]
        with patch.dict(
            os.environ,
            {"OPENCLAW_HOST_RUNNER": str(self.settings.root / "missing-runner")},
        ):
            with TestClient(app) as client:
                channel = client.post(
                    "/api/channels",
                    json={
                        "name": "Kenh test",
                        "platform": "bilibili",
                        "url": "https://space.bilibili.com/123",
                        "interval_minutes": 60,
                    },
                ).json()
                app.state.monitor.run_channel_once(channel["id"])
                app.state.store.schedule_channel_now(channel["id"])
                app.state.monitor.run_channel_once(channel["id"])
                self.assertEqual(1, len(client.get("/api/jobs").json()))

                trend = client.post(
                    "/api/trend/status",
                    json={"payload": {"scan_id": "scan-test"}},
                )
                self.assertEqual(200, trend.status_code, trend.text)
                self.assertEqual(
                    {
                        "ok": False,
                        "configured": False,
                        "error_code": "TrendRuntimeUnavailable",
                    },
                    trend.json(),
                )


if __name__ == "__main__":
    unittest.main()
