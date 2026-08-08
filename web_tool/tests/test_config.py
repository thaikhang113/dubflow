import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette\.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient

from web_tool.app import create_app
from web_tool.config import Settings


class ConfigTests(unittest.TestCase):
    def test_settings_create_private_runtime_directories(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"TOOL_ROOT": tmp, "TOOL_BIND_HOST": "127.0.0.1"},
            clear=False,
        ):
            settings = Settings.from_env()
            self.assertEqual(Path(tmp).resolve(), settings.root)
            for path in (
                settings.data_dir,
                settings.secrets_dir,
                settings.jobs_dir,
                settings.output_dir,
                settings.models_dir,
                settings.browser_dir,
            ):
                self.assertTrue(path.is_dir())

    def test_health_endpoint_uses_local_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Settings.for_test(Path(tmp)))
            response = TestClient(app).get("/api/health")
            self.assertEqual(200, response.status_code)
            self.assertEqual({"ok": True, "version": 1}, response.json())


if __name__ == "__main__":
    unittest.main()
