import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_tool.app import create_app
from web_tool.config import Settings


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings.for_test(Path(self.tmp.name))
        self.app = create_app(self.settings)
        self.app.state.store.set_queue_paused(True)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def create_job(self, source: str = "https://www.bilibili.com/video/BV1") -> dict:
        response = self.client.post(
            "/api/jobs",
            json={
                "platform": "bilibili",
                "source": source,
                "voice": "ai33:vbee_hn_female_ngochuyen_full_48k-fhg",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def test_create_list_and_validation(self):
        first = self.create_job("https://www.bilibili.com/video/BV1")
        second = self.create_job("https://www.bilibili.com/video/BV2")
        self.assertEqual("queued", first["state"])
        self.assertNotIn("api_key", repr(first))
        listed = self.client.get("/api/jobs").json()
        self.assertEqual([second["id"], first["id"]], [job["id"] for job in listed])

        invalid = self.client.post(
            "/api/jobs",
            json={"platform": "bilibili", "source": "https://example.com/video/BV1"},
        )
        self.assertEqual(422, invalid.status_code)
        invalid_voice = self.client.post(
            "/api/jobs",
            json={
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1",
                "voice": "voice\nINJECTED=1",
            },
        )
        self.assertEqual(422, invalid_voice.status_code)

    def test_rejects_provider_in_wrong_pipeline_role(self):
        ollama = self.client.post(
            "/api/providers",
            json={
                "name": "Ollama",
                "kind": "ollama",
                "endpoint": "http://host.docker.internal:11434",
                "model": "qwen2.5:3b",
            },
        ).json()
        ai33 = self.client.post(
            "/api/providers",
            json={
                "name": "AI33",
                "kind": "ai33",
                "endpoint": "https://api.ai33.pro",
            },
        ).json()
        for payload in (
            {
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1",
                "translation_provider_id": ai33["id"],
            },
            {
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1",
                "tts_provider_id": ollama["id"],
            },
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    422,
                    self.client.post("/api/jobs", json=payload).status_code,
                )

    def test_resume_reuses_checkpoint_and_retry_links_new_job(self):
        job = self.create_job()
        job_dir = self.settings.jobs_dir / job["id"] / "output"
        job_dir.mkdir(parents=True)
        self.app.state.store.update_job(
            job["id"],
            state="needs_attention",
            action="resume",
            job_dir=str(job_dir),
            error_code="TTSGenerationFailed",
        )

        resumed = self.client.post(f"/api/jobs/{job['id']}/resume")
        self.assertEqual(200, resumed.status_code, resumed.text)
        self.assertEqual(job["id"], resumed.json()["id"])
        self.assertEqual("queued", resumed.json()["state"])
        self.assertEqual(
            str(job_dir.resolve()),
            resumed.json()["request"]["resume_job_dir"],
        )

        self.app.state.store.update_job(job["id"], state="failed")
        retried = self.client.post(f"/api/jobs/{job['id']}/retry")
        self.assertEqual(201, retried.status_code, retried.text)
        self.assertNotEqual(job["id"], retried.json()["id"])
        self.assertEqual(job["id"], retried.json()["request"]["retry_of"])
        self.assertNotIn("resume_job_dir", retried.json()["request"])

    def test_cancel_queued_job(self):
        job = self.create_job()
        response = self.client.post(f"/api/jobs/{job['id']}/cancel")
        self.assertEqual(200, response.status_code)
        self.assertEqual("cancelled", response.json()["state"])

    def test_artifacts_use_allowlist_and_block_traversal(self):
        job = self.create_job()
        job_dir = self.settings.jobs_dir / job["id"] / "output"
        job_dir.mkdir(parents=True)
        (job_dir / "vietnamese.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chao\n")
        (job_dir / "log.txt").write_text("private")
        (job_dir / "voice_sync_quality_report.json").write_text(
            json.dumps(
                {
                    "status": "fail",
                    "detail": "Authorization: Bearer secret",
                    "url": "https://media.example/file?signature=abc",
                }
            ),
            encoding="utf-8",
        )
        self.app.state.store.update_job(
            job["id"],
            state="completed",
            job_dir=str(job_dir),
        )

        allowed = self.client.get(f"/api/jobs/{job['id']}/artifacts/vietnamese.srt")
        self.assertEqual(200, allowed.status_code)
        self.assertEqual(404, self.client.get(
            f"/api/jobs/{job['id']}/artifacts/log.txt"
        ).status_code)
        self.assertEqual(404, self.client.get(
            f"/api/jobs/{job['id']}/artifacts/%2E%2E%2F%2E%2E%2Fsecret"
        ).status_code)
        report = self.client.get(
            f"/api/jobs/{job['id']}/artifacts/voice_sync_quality_report.json"
        )
        self.assertEqual(200, report.status_code)
        self.assertNotIn("secret", report.text)
        self.assertNotIn("abc", report.text)

    def test_queue_pause_resume_and_event_publish(self):
        self.assertEqual(
            {"paused": True},
            self.client.post("/api/queue/pause").json(),
        )
        self.assertEqual(
            {"paused": False},
            self.client.post("/api/queue/resume").json(),
        )

        async def receive():
            loop = asyncio.get_running_loop()
            queue = self.app.state.events.subscribe(loop)
            try:
                job = self.create_job()
                event = await asyncio.wait_for(queue.get(), timeout=2)
                self.assertEqual(job["id"], event["id"])
                self.assertEqual("queued", event["state"])
            finally:
                self.app.state.events.unsubscribe(queue)

        asyncio.run(receive())


if __name__ == "__main__":
    unittest.main()
