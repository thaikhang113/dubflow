import json
from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi.testclient import TestClient

from web_tool.app import create_app
from web_tool.config import Settings
from web_tool.integrations import (
    run_series_action,
    run_trend_action,
    runtime_doctor,
)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings.for_test(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def completed(self, payload=None):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload or {"ok": True}),
            stderr="",
        )

    def test_series_actions_use_fixed_state_and_reject_unsafe_selector(self):
        with patch(
            "web_tool.integrations.subprocess.run",
            return_value=self.completed({"manifests": []}),
        ) as run:
            result = run_series_action(
                "plan",
                {"series_id": "series-one", "selector": "latest:3"},
                self.settings,
            )
        self.assertEqual([], result["manifests"])
        command = run.call_args.args[0]
        self.assertIn(str(self.settings.data_dir / "series" / "series.json"), command)
        self.assertNotIn(";", " ".join(command))

        for action, payload in (
            ("unknown", {}),
            ("plan", {"series_id": "series-one", "selector": "all; rm -rf /"}),
            ("compile", {"compilation_id": "../../outside"}),
            ("add", {"name": "x", "keyword": "x", "source_url": "file:///etc/passwd"}),
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                run_series_action(action, payload, self.settings)

    def test_trend_actions_validate_query_mode_days_and_identifiers(self):
        runner = self.settings.root / "host-runner"
        runner.write_text("fake", encoding="utf-8")
        with patch.dict(
            "os.environ",
            {"OPENCLAW_HOST_RUNNER": str(runner)},
        ), patch(
            "web_tool.integrations.subprocess.run",
            return_value=self.completed(
                {"ok": True, "stdout": json.dumps({"scan_id": "scan-1"})}
            ),
        ) as run:
            result = run_trend_action(
                "scan",
                {"query": "anime dài tập", "days": 7, "mode": "trend"},
                self.settings,
            )
        self.assertEqual("scan-1", result["scan_id"])
        self.assertEqual(
            ["trend-start-scan", "anime dài tập", "7", "trend"],
            run.call_args.args[0][1:],
        )

        for payload in (
            {"query": "$(bad)", "days": 7, "mode": "trend"},
            {"query": "anime", "days": 31, "mode": "trend"},
            {"query": "anime", "days": 181, "mode": "archive"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                run_trend_action("scan", payload, self.settings)
        with self.assertRaises(ValueError):
            run_trend_action("video-risk", {"bvid": "../../bad"}, self.settings)

    def test_settings_keep_telegram_token_out_of_api_and_database(self):
        app = create_app(self.settings)
        app.state.monitor.discovery = lambda *_args, **_kwargs: []
        with TestClient(app) as client:
            provider = client.post(
                "/api/providers",
                json={
                    "name": "Ollama",
                    "kind": "ollama",
                    "endpoint": "http://host.docker.internal:11434",
                    "model": "provider-model",
                },
            ).json()
            response = client.put(
                "/api/settings",
                json={
                    "default_provider_id": provider["id"],
                    "default_model": "qwen3:8b",
                    "default_voice": "voice-one",
                    "queue_poll_seconds": 2,
                    "telegram_chat_id": "123456",
                    "telegram_thread_id": "77",
                    "telegram_bot_token": "123456:secret-token-value",
                },
            )
            self.assertEqual(200, response.status_code, response.text)
            loaded = client.get("/api/settings")
            self.assertTrue(loaded.json()["telegram_configured"])
            self.assertNotIn("secret-token-value", loaded.text)
            self.assertEqual(2, app.state.worker.poll_seconds)
            app.state.store.set_queue_paused(True)
            loaded = client.get("/api/settings")
            self.assertNotIn("queue_paused", loaded.json())

            job = client.post(
                "/api/jobs",
                json={
                    "platform": "bilibili",
                    "source": "https://www.bilibili.com/video/BV1DEFAULT",
                },
            )
            self.assertEqual(201, job.status_code, job.text)
            request = job.json()["request"]
            self.assertEqual(provider["id"], request["translation_provider_id"])
            self.assertEqual("qwen3:8b", request["model"])
            self.assertEqual("voice-one", request["voice"])
            self.assertNotIn(
                "secret-token-value",
                self.settings.database_path.read_bytes().decode("utf-8", errors="ignore"),
            )

    def test_runtime_doctor_reports_required_tools_without_secrets(self):
        report = runtime_doctor(self.settings, [])
        self.assertIn("ffmpeg", report["checks"])
        self.assertIn("yt_dlp", report["checks"])
        self.assertIn("whisper", report["checks"])
        self.assertIn("demucs", report["checks"])
        self.assertIn("volumes", report["checks"])
        self.assertNotIn("token", repr(report).lower())

    @patch("web_tool.integrations.os.access", return_value=True)
    @patch("web_tool.integrations.importlib.util.find_spec", return_value=object())
    @patch("web_tool.integrations.shutil.which", side_effect=lambda name: f"/bin/{name}")
    def test_runtime_doctor_explains_workflow_requirements(
        self,
        _which,
        _find_spec,
        _access,
    ):
        whisper = (
            self.settings.models_dir
            / "whisper.cpp"
            / "build"
            / "bin"
            / "whisper-cli"
        )
        whisper.parent.mkdir(parents=True, exist_ok=True)
        whisper.write_bytes(b"binary")
        providers = [
            {
                "id": "provider-ollama",
                "kind": "ollama",
                "configured": False,
                "endpoint": "http://ollama:11434",
            },
            {
                "id": "provider-ai33",
                "kind": "ai33",
                "configured": False,
                "endpoint": "https://api.ai33.pro",
            },
        ]
        report = runtime_doctor(
            self.settings,
            providers,
            runtime_settings={
                "default_provider_id": "provider-ollama",
                "default_voice": "ai33:vbee_voice",
                "telegram_chat_id": "",
            },
            login_status={"logged_in": False},
            telegram_configured=False,
            host_helper_available=False,
            ollama_available=True,
        )
        workflows = {item["id"]: item for item in report["workflows"]}
        self.assertEqual("ready", workflows["ollama_translation"]["status"])
        self.assertIn("AI33_API_KEY", workflows["ai33_voice"]["missing"])
        self.assertIn("AI33_API_KEY", workflows["local_video"]["missing"])
        self.assertIn("Bilibili cookie", workflows["bilibili"]["optional"])
        self.assertIn("Host login helper", workflows["bilibili"]["optional"])
        self.assertEqual("optional", workflows["telegram"]["status"])
        self.assertNotIn("api.ai33.pro", repr(report))
        self.assertNotIn("token", repr(report).lower())

    @patch("web_tool.integrations.os.access", return_value=True)
    @patch("web_tool.integrations.importlib.util.find_spec", return_value=object())
    @patch("web_tool.integrations.shutil.which", side_effect=lambda name: f"/bin/{name}")
    def test_runtime_doctor_reports_unreachable_ollama(
        self,
        _which,
        _find_spec,
        _access,
    ):
        whisper = (
            self.settings.models_dir
            / "whisper.cpp"
            / "build"
            / "bin"
            / "whisper-cli"
        )
        whisper.parent.mkdir(parents=True, exist_ok=True)
        whisper.write_bytes(b"binary")
        report = runtime_doctor(
            self.settings,
            [
                {
                    "id": "provider-ollama",
                    "kind": "ollama",
                    "configured": False,
                    "endpoint": "http://ollama:11434",
                }
            ],
            runtime_settings={
                "default_provider_id": "provider-ollama",
                "default_voice": "vi-VN-HoaiMyNeural",
            },
            ollama_available=False,
        )
        workflows = {item["id"]: item for item in report["workflows"]}
        self.assertIn(
            "Ollama endpoint không kết nối được",
            workflows["ollama_translation"]["missing"],
        )
        self.assertFalse(report["ready"])

    def test_output_export_contains_only_managed_output(self):
        output = self.settings.output_dir / "job-one"
        output.mkdir()
        (output / "final_video_vi.mp4").write_bytes(b"video")
        (self.settings.secrets_dir / "private.secret").write_text(
            "must-not-export",
            encoding="utf-8",
        )
        app = create_app(self.settings)
        app.state.monitor.discovery = lambda *_args, **_kwargs: []
        with TestClient(app) as client:
            response = client.get("/api/runtime/export")
        self.assertEqual(200, response.status_code, response.text)
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(["job-one/final_video_vi.mp4"], archive.namelist())
            self.assertNotIn("must-not-export", repr(archive.namelist()))


if __name__ == "__main__":
    unittest.main()
