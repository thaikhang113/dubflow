import re
import unittest
from pathlib import Path


class DockerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.compose = (cls.root / "compose.yaml").read_text(encoding="utf-8")
        cls.gpu_compose = (cls.root / "compose.gpu.yaml").read_text(
            encoding="utf-8"
        )
        cls.dockerfile = (cls.root / "Dockerfile").read_text(encoding="utf-8")
        cls.readme = (cls.root / "README.md").read_text(encoding="utf-8")
        cls.entrypoint = (cls.root / "docker" / "entrypoint.sh").read_text(
            encoding="utf-8"
        )

    def test_compose_keeps_web_local_and_runtime_persistent(self):
        self.assertIn("tool:", self.compose)
        self.assertIn('127.0.0.1:${TOOL_PORT:-18793}:18793', self.compose)
        self.assertIn("init: true", self.compose)
        self.assertIn("healthcheck:", self.compose)
        for volume in ("data", "secrets", "jobs", "output", "models", "browser"):
            self.assertIn(f"tool-{volume}:/data/{volume}", self.compose)
            self.assertRegex(self.compose, rf"(?m)^  tool-{volume}:$")
        self.assertIn("host.docker.internal:host-gateway", self.compose)
        self.assertNotRegex(self.compose, r"9222:")
        self.assertNotRegex(self.compose, r"(?i)(api[_-]?key|cookie|token):\s*\S+")

    def test_compose_uses_only_supported_non_secret_endpoints(self):
        for endpoint in (
            "OLLAMA_API_BASE: http://host.docker.internal:11434",
            "NINEROUTER_API_BASE: http://host.docker.internal:20128/v1",
            "OCR_VISION_API_BASE: http://host.docker.internal:20128/v1",
            "AI33_API_BASE: https://api.ai33.pro",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, self.compose)
        self.assertNotIn("env_file:", self.compose)

    def test_optional_profiles_and_secret_backed_trend_database_are_preserved(self):
        self.assertIn('profiles: ["ollama"]', self.compose)
        self.assertIn('profiles: ["trend"]', self.compose)
        ollama = self.compose.split("\n  ollama:\n", 1)[1].split("\n  trend-db:\n", 1)[0]
        self.assertIn('restart: "no"', ollama)
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

    def test_gpu_override_accelerates_only_ollama(self):
        self.assertNotIn("capabilities: [gpu]", self.compose)
        self.assertIn("ollama:", self.gpu_compose)
        self.assertIn("driver: nvidia", self.gpu_compose)
        self.assertIn("capabilities: [gpu]", self.gpu_compose)
        self.assertNotIn("tool:", self.gpu_compose)

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
            "Tự động (khuyên dùng)",
            "compose.gpu.yaml",
            "Whisper, Demucs và render vẫn chạy CPU",
        ):
            with self.subTest(text=text):
                self.assertIn(text, self.readme)


if __name__ == "__main__":
    unittest.main()
