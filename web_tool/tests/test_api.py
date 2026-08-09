import asyncio
import json
import io
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

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

    def test_job_uses_only_available_ai33_provider(self):
        ai33 = self.client.post(
            "/api/providers",
            json={
                "name": "AI33",
                "kind": "ai33",
                "endpoint": "https://api.ai33.pro",
                "api_key": "secret",
            },
        ).json()
        job = self.create_job()
        self.assertEqual(ai33["id"], job["request"]["tts_provider_id"])

    def test_updates_provider_without_echoing_or_clearing_existing_key(self):
        created = self.client.post(
            "/api/providers",
            json={
                "name": "Main",
                "kind": "openai_compatible",
                "endpoint": "https://api.example.com/v1",
                "model": "old-model",
                "api_key": "super-secret",
            },
        ).json()
        response = self.client.put(
            f"/api/providers/{created['id']}",
            json={
                "name": "Main updated",
                "kind": "openai_compatible",
                "endpoint": "https://api.example.com/v1",
                "model": "new-model",
                "api_key": "",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        updated = response.json()
        self.assertEqual("new-model", updated["model"])
        self.assertTrue(updated["configured"])
        self.assertNotIn("super-secret", repr(updated))

    def test_upload_uses_server_generated_managed_path(self):
        response = self.client.post(
            "/api/uploads",
            files={"file": ("personal-name.mp4", b"small-video", "video/mp4")},
        )
        self.assertEqual(201, response.status_code, response.text)
        source = Path(response.json()["source"])
        self.assertTrue(source.is_file())
        self.assertEqual(self.settings.jobs_dir / "uploads", source.parent)
        self.assertNotEqual("personal-name.mp4", source.name)

        rejected = self.client.post(
            "/api/uploads",
            files={"file": ("secret.txt", b"no", "text/plain")},
        )
        self.assertEqual(422, rejected.status_code)

    def test_brand_logo_upload_persists_and_can_be_removed(self):
        image = io.BytesIO()
        Image.new("RGBA", (48, 48), (0, 255, 0, 255)).save(image, "PNG")
        uploaded = self.client.post(
            "/api/branding/logo",
            files={"file": ("my-logo.png", image.getvalue(), "image/png")},
        )
        self.assertEqual(201, uploaded.status_code, uploaded.text)
        self.assertTrue(uploaded.json()["configured"])
        self.assertEqual(200, self.client.get("/api/branding/logo/image").status_code)
        restarted = create_app(self.settings)
        restarted.state.store.set_queue_paused(True)
        with TestClient(restarted) as client:
            self.assertTrue(client.get("/api/branding/logo").json()["configured"])
        self.assertEqual(204, self.client.delete("/api/branding/logo").status_code)
        self.assertFalse(self.client.get("/api/branding/logo").json()["configured"])

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

    def test_resume_preserves_nested_pipeline_checkpoint(self):
        job = self.create_job()
        job_dir = self.settings.jobs_dir / job["id"]
        checkpoint = job_dir / "Bilibili" / "input-20260809-053120"
        checkpoint.mkdir(parents=True)
        (checkpoint / "input.mp4").write_bytes(b"video")
        self.app.state.store.update_job(
            job["id"],
            state="needs_attention",
            action="resume",
            job_dir=str(job_dir),
        )

        resumed = self.client.post(f"/api/jobs/{job['id']}/resume")

        self.assertEqual(200, resumed.status_code, resumed.text)
        self.assertEqual(
            str(checkpoint.resolve()),
            resumed.json()["request"]["resume_job_dir"],
        )
    def test_resume_fills_missing_default_and_ai33_providers(self):
        job = self.create_job()
        ollama = self.app.state.store.create_provider(
            {
                'name': 'Ollama', 'kind': 'ollama',
                'endpoint': 'http://host.docker.internal:11434',
                'model': 'qwen2.5:3b', 'timeout_seconds': 90,
            },
            has_secret=False,
        )
        ai33 = self.app.state.store.create_provider(
            {
                'name': 'AI33', 'kind': 'ai33',
                'endpoint': 'https://api.ai33.pro',
                'model': '', 'timeout_seconds': 90,
            },
            has_secret=True,
        )
        self.app.state.store.set_settings({'default_provider_id': ollama['id']})
        job_dir = self.settings.jobs_dir / job['id'] / 'output'
        job_dir.mkdir(parents=True)
        self.app.state.store.update_job(
            job['id'], state='failed', job_dir=str(job_dir)
        )

        path = '/api/jobs/{}/resume'.format(job['id'])
        resumed = self.client.post(path).json()

        self.assertEqual(ollama['id'], resumed['request']['translation_provider_id'])
        self.assertEqual(ai33['id'], resumed['request']['tts_provider_id'])

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

    def test_settings_persist_allowlisted_hardware_profile(self):
        response = self.client.put(
            "/api/settings",
            json={
                "hardware_mode": "auto",
                "hardware_profile": "hybrid",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("auto", response.json()["hardware_mode"])
        self.assertEqual("hybrid", response.json()["hardware_profile"])
        self.assertEqual(
            422,
            self.client.put(
                "/api/settings",
                json={"hardware_mode": "fastest"},
            ).status_code,
        )


    def test_settings_support_asr_and_vieneu_without_breaking_existing_fields(self):
        defaults = self.client.get("/api/settings").json()
        self.assertEqual("auto", defaults["asr_engine"])
        self.assertEqual("medium", defaults["whisper_model"])
        self.assertEqual("vieneu:hong-chau", defaults["default_voice"])
        self.assertEqual("story", defaults["vieneu_style"])

        response = self.client.put(
            "/api/settings",
            json={
                "asr_engine": "qwen3",
                "whisper_model": "small",
                "default_voice": "vieneu:hong-chau",
                "vieneu_style": "story",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("qwen3", response.json()["asr_engine"])
        self.assertEqual("small", response.json()["whisper_model"])
        self.assertEqual("vieneu:hong-chau", response.json()["default_voice"])
        self.assertEqual("story", response.json()["vieneu_style"])

        for payload in (
            {"asr_engine": "other"},
            {"vieneu_style": "news"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    422,
                    self.client.put("/api/settings", json=payload).status_code,
                )

    def test_job_can_inherit_or_override_asr_and_vieneu_style(self):
        saved = self.client.put(
            "/api/settings",
            json={
                "asr_engine": "qwen3",
                "default_voice": "vieneu:hong-chau",
                "vieneu_style": "story",
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)

        inherited = self.client.post(
            "/api/jobs",
            json={
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1ASR",
            },
        )
        self.assertEqual(201, inherited.status_code, inherited.text)
        self.assertEqual("qwen3", inherited.json()["request"]["asr_engine"])
        self.assertEqual("story", inherited.json()["request"]["vieneu_style"])
        self.assertEqual("vieneu:hong-chau", inherited.json()["request"]["voice"])

        overridden = self.client.post(
            "/api/jobs",
            json={
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1WHISPER",
                "asr_engine": "whisper",
                "vieneu_style": "story",
            },
        )
        self.assertEqual(201, overridden.status_code, overridden.text)
        self.assertEqual("whisper", overridden.json()["request"]["asr_engine"])

    def test_vieneu_voice_does_not_bind_ai33_default_provider(self):
        ai33 = self.client.post(
            "/api/providers",
            json={
                "name": "AI33",
                "kind": "ai33",
                "endpoint": "https://api.ai33.pro",
                "api_key": "secret",
            },
        ).json()
        saved = self.client.put(
            "/api/settings",
            json={
                "default_provider_id": ai33["id"],
                "default_voice": "vieneu:hong-chau",
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)

        job = self.client.post(
            "/api/jobs",
            json={
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1VIENEU",
            },
        )
        self.assertEqual(201, job.status_code, job.text)
        self.assertEqual("", job.json()["request"]["tts_provider_id"])

if __name__ == "__main__":
    unittest.main()
