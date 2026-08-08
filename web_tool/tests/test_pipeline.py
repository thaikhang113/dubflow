import json
import tempfile
import unittest
from pathlib import Path

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
            "ai33:vbee_hn_female_ngochuyen_full_48k-fhg",
            environment["VOICE"],
        )

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


if __name__ == "__main__":
    unittest.main()
