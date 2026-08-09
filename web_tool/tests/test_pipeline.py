import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_tool.config import Settings
from web_tool.pipeline import (
    build_job_command,
    build_job_environment,
    read_job_status,
)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings.for_test(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_builds_allowlisted_bilibili_command(self):
        source = "https://www.bilibili.com/video/BV1?vd_source=tracking"
        self.assertEqual(
            [
                "bash",
                str(
                    self.settings.repo_root
                    / "skills"
                    / "bilibili-vietnamese-dubber"
                    / "run.sh"
                ),
                source,
            ],
            build_job_command(
                {"platform": "bilibili", "source": source},
                self.settings,
            ),
        )

    def test_rejects_unsafe_sources_and_resume_directories(self):
        uploads = self.settings.jobs_dir / "uploads"
        uploads.mkdir()
        good_upload = uploads / "input.mp4"
        good_upload.write_bytes(b"video")
        command = build_job_command(
            {"platform": "upload", "source": str(good_upload)},
            self.settings,
        )
        self.assertEqual(str(good_upload.resolve()), command[-1])

        bad_jobs = (
            {"platform": "unknown", "source": "https://example.com/video"},
            {
                "platform": "bilibili",
                "source": "https://user:pass@www.bilibili.com/video/BV1",
            },
            {"platform": "bilibili", "source": "https://example.com/video/BV1"},
            {"platform": "douyin", "source": "https://www.douyin.com/video/1\nx"},
            {"platform": "upload", "source": str(Path(self.tmp.name) / "outside.mp4")},
            {
                "platform": "douyin",
                "source": "https://www.douyin.com/video/1",
                "resume_job_dir": str(Path(self.tmp.name) / "outside"),
            },
        )
        for job in bad_jobs:
            with self.subTest(job=job), self.assertRaises(ValueError):
                build_job_command(job, self.settings)

    def test_maps_validated_ollama_and_ai33_environment(self):
        cookie_path = self.settings.secrets_dir / "bilibili-cookies.txt"
        cookie_path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        environment = build_job_environment(
            {
                "id": "job-test",
                "platform": "bilibili",
                "voice": "ai33:vbee_hn_female_ngochuyen_full_48k-fhg",
            },
            {
                "translation": {
                    "kind": "ollama",
                    "endpoint": "http://host.docker.internal:11434",
                    "model": "qwen2.5:3b",
                },
                "tts": {
                    "kind": "ai33",
                    "endpoint": "https://api.ai33.pro",
                    "api_key": "tts-secret",
                },
            },
            self.settings,
        )
        self.assertEqual("ollama", environment["OPENCLAW_AI_PROVIDER"])
        self.assertEqual(
            "http://host.docker.internal:11434",
            environment["OPENCLAW_AI_API_BASE"],
        )
        self.assertEqual("qwen2.5:3b", environment["OPENCLAW_AI_MODEL"])
        self.assertEqual("https://api.ai33.pro", environment["AI33_API_BASE"])
        self.assertEqual("tts-secret", environment["AI33_API_KEY"])
        self.assertEqual("3", environment["AI33_TTS_WORKERS"])
        self.assertEqual(
            str(cookie_path),
            environment["BILIBILI_COOKIES_FILE"],
        )
        self.assertEqual(
            "ai33:vbee_hn_female_ngochuyen_full_48k-fhg",
            environment["VOICE"],
        )

    def test_job_model_overrides_translation_provider_model(self):
        environment = build_job_environment(
            {
                "id": "job-model-override",
                "request": {"model": "qwen3:8b"},
            },
            {
                "translation": {
                    "name": "Ollama",
                    "kind": "ollama",
                    "endpoint": "http://host.docker.internal:11434",
                    "model": "qwen2.5:3b",
                    "timeout_seconds": 90,
                },
            },
            self.settings,
        )
        self.assertEqual("qwen3:8b", environment["OPENCLAW_AI_MODEL"])
        self.assertEqual("qwen3:8b", environment["OLLAMA_MODEL"])

    def test_job_selects_allowlisted_local_whisper_model(self):
        environment = build_job_environment(
            {
                "id": "job-whisper-medium",
                "request": {"whisper_model": "medium"},
            },
            {},
            self.settings,
        )
        self.assertTrue(environment["WHISPER_MODEL"].endswith("ggml-medium.bin"))
        with self.assertRaises(ValueError):
            build_job_environment(
                {
                    "id": "job-whisper-invalid",
                    "request": {"whisper_model": "../../secret"},
                },
                {},
                self.settings,
            )

    def test_maps_job_runtime_selection_and_hardware_profile(self):
        environment = build_job_environment(
            {
                "id": "job-local-runtime",
                "request": {
                    "asr_engine": "qwen3",
                    "vieneu_style": "story",
                    "default_voice": "vieneu:hong-chau",
                    "hardware_profile": "hybrid",
                },
            },
            {},
            self.settings,
        )
        self.assertEqual("qwen3", environment["ASR_PROVIDER"])
        self.assertEqual("http://qwen-asr:8000", environment["QWEN_ASR_ENDPOINT"])
        self.assertEqual("http://vieneu:8000", environment["VIENEU_ENDPOINT"])
        self.assertEqual("story", environment["VIENEU_STYLE"])
        self.assertEqual(
            "vieneu:hong-chau",
            environment["OPENCLAW_DEFAULT_TTS_VOICE"],
        )
        self.assertEqual("vieneu:hong-chau", environment["VOICE"])
        self.assertEqual("hybrid", environment["OPENCLAW_HARDWARE_PROFILE"])
        self.assertEqual("vieneu:hong-chau", environment["EDGE_TTS_VOICE_PRESET"])

        defaults = build_job_environment(
            {"id": "job-vieneu-defaults", "request": {}},
            {},
            self.settings,
        )
        self.assertEqual("story", defaults["VIENEU_STYLE"])
        self.assertEqual("hong-chau", defaults["VIENEU_DEFAULT_VOICE"])

        legacy = build_job_environment(
            {"id": "job-legacy-voice", "request": {"voice": "nu"}},
            {},
            self.settings,
        )
        self.assertEqual("nu", legacy["VOICE"])
        self.assertNotIn("OPENCLAW_DEFAULT_TTS_VOICE", legacy)

        with self.assertRaises(ValueError):
            build_job_environment(
                {
                    "id": "job-invalid-asr",
                    "request": {"asr_engine": "remote\nINJECTED=1"},
                },
                {},
                self.settings,
            )

    def test_inherits_hardware_profile_when_job_omits_profile(self):
        with patch.dict(os.environ, {"OPENCLAW_HARDWARE_PROFILE": "hybrid"}):
            environment = build_job_environment(
                {"id": "job-inherited-profile", "request": {}},
                {},
                self.settings,
            )
        self.assertEqual("hybrid", environment["OPENCLAW_HARDWARE_PROFILE"])

    def test_managed_brand_logo_enables_required_bilibili_branding(self):
        logo = self.settings.data_dir / "branding-logo.png"
        logo.write_bytes(b"png")
        environment = build_job_environment(
            {"id": "job-brand-logo", "request": {}},
            {},
            self.settings,
        )
        self.assertEqual(str(logo), environment["BILIBILI_BRAND_LOGO"])
        self.assertEqual("1", environment["BILIBILI_BRAND_REQUIRED"])

    def test_reads_only_sanitized_structured_status(self):
        job_dir = Path(self.tmp.name) / "job"
        job_dir.mkdir()
        (job_dir / "job_status.json").write_text(
            json.dumps(
                {
                    "state": "error",
                    "phase": "tts",
                    "progress_percent": 66,
                    "error_code": "TTSGenerationFailed",
                    "error_message": (
                        "Authorization: Bearer secret "
                        "https://media.example/file?signature=abc"
                    ),
                    "private": "must-not-return",
                }
            ),
            encoding="utf-8",
        )
        status = read_job_status(job_dir)
        self.assertEqual("TTSGenerationFailed", status["error_code"])
        self.assertNotIn("secret", repr(status))
        self.assertNotIn("abc", repr(status))
        self.assertNotIn("private", status)

    def test_bilibili_wrapper_uses_managed_cookie_file_without_cdp(self):
        wrapper = (
            self.settings.repo_root
            / "skills"
            / "bilibili-vietnamese-dubber"
            / "run.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("BILIBILI_COOKIES_FILE", wrapper)
        self.assertIn(
            '--cookies "$COOKIES_TXT" --dump-single-json',
            wrapper,
        )


if __name__ == "__main__":
    unittest.main()
