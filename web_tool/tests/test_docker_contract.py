import re
import unittest
from pathlib import Path


class DockerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.compose = (cls.root / "compose.yaml").read_text(encoding="utf-8")
        cls.dockerfile = (cls.root / "Dockerfile").read_text(encoding="utf-8")
        cls.readme = (cls.root / "README.md").read_text(encoding="utf-8")
        cls.entrypoint = (cls.root / "docker" / "entrypoint.sh").read_text(
            encoding="utf-8"
        )

    def test_compose_keeps_web_local_and_runtime_persistent(self):
        self.assertIn("tool:", self.compose)
        self.assertIn('127.0.0.1:18793:18793', self.compose)
        self.assertIn("init: true", self.compose)
        self.assertIn("healthcheck:", self.compose)
        for volume in (
            "tool-data",
            "tool-secrets",
            "tool-jobs",
            "tool-output",
            "tool-models",
            "tool-browser",
        ):
            with self.subTest(volume=volume):
                self.assertIn(volume, self.compose)
        self.assertNotRegex(self.compose, r"9222:")
        self.assertNotRegex(self.compose, r"(?i)(api[_-]?key|cookie|token):\s*\S+")

    def test_optional_profiles_and_secret_backed_trend_database(self):
        self.assertIn('profiles: ["ollama"]', self.compose)
        self.assertIn('profiles: ["trend"]', self.compose)
        self.assertIn("POSTGRES_PASSWORD_FILE", self.compose)
        self.assertIn("trend-db-password", self.compose)

    def test_image_contains_pipeline_runtime_and_non_root_execution(self):
        self.assertIn("FROM python:3.11-bookworm", self.dockerfile)
        for dependency in (
            "chromium",
            "ffmpeg",
            "cmake",
            "git",
            "tini",
            "demucs",
            "inaSpeechSegmenter",
            "whisper.cpp",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, self.dockerfile)
        self.assertRegex(self.dockerfile, r"useradd|adduser")
        self.assertIn("exec gosu app uvicorn", self.entrypoint)
        self.assertNotRegex(self.entrypoint, re.compile(r"uvicorn.*&"))
        self.assertIn("--remote-debugging-address=127.0.0.1", self.entrypoint)

    def test_image_normalizes_windows_shell_line_endings(self):
        self.assertIn(
            "find /app/skills /app/docker -type f -name '*.sh' "
            "-exec sed -i 's/\\r$//' {} +",
            self.dockerfile,
        )

    def test_default_image_uses_cpu_ml_runtime(self):
        self.assertIn("https://download.pytorch.org/whl/cpu", self.dockerfile)
        self.assertIn("tensorflow-cpu", self.dockerfile)
        self.assertIn("onnxruntime", self.dockerfile)
        self.assertIn("--target whisper-cli", self.dockerfile)
        self.assertNotIn("tensorflow[and-cuda]", self.dockerfile)
        self.assertNotRegex(self.dockerfile, re.compile(r"onnxruntime-gpu"))

    def test_readme_documents_end_user_docker_workflow(self):
        for text in (
            "docker compose up -d --build tool",
            "http://127.0.0.1:18793",
            "Docker Desktop",
            "host.docker.internal:11434",
            "--profile ollama",
            "--profile trend",
            "Bilibili QR",
            "docker compose restart tool",
            "tool-data",
            "HyperFrames",
            "captcha",
        ):
            with self.subTest(text=text):
                self.assertIn(text, self.readme)


if __name__ == "__main__":
    unittest.main()
