import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from web_tool.app import create_app
from web_tool.config import Settings
from web_tool.secrets import SecretStore, sanitize, validate_provider


class SecretTests(unittest.TestCase):
    def test_secret_status_never_returns_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets = SecretStore(Path(tmp))
            secrets.write("provider-main", "super-secret")
            status = secrets.read_status("provider-main")
            self.assertEqual({"configured": True}, status)
            self.assertNotIn("super-secret", repr(status))
            self.assertEqual(
                {"PROVIDER_API_KEY": "super-secret"},
                secrets.environment("provider-main"),
            )

    def test_failed_secret_replace_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secrets = SecretStore(root)
            with patch("web_tool.secrets.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    secrets.write("provider-main", "super-secret")
            self.assertEqual([], list(root.iterdir()))

    def test_sanitize_removes_authorization_and_signed_query(self):
        value = (
            "Authorization: Bearer super-secret "
            "https://cdn.example/file?signature=abc&token=def"
        )
        cleaned = sanitize(value)
        self.assertNotIn("super-secret", cleaned)
        self.assertNotIn("abc", cleaned)
        self.assertNotIn("def", cleaned)
        self.assertIn("Authorization: Bearer <redacted>", cleaned)

    def test_provider_validation_accepts_local_http_and_rejects_unsafe_urls(self):
        provider = validate_provider(
            {
                "name": "Ollama",
                "kind": "ollama",
                "endpoint": "http://host.docker.internal:11434",
                "model": "qwen3:8b",
                "timeout_seconds": 90,
            }
        )
        self.assertEqual("http://host.docker.internal:11434", provider["endpoint"])
        for endpoint in (
            "file:///etc/passwd",
            "https://user:pass@example.com",
            "ftp://example.com",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_provider(
                    {
                        "name": "Bad",
                        "kind": "openai_compatible",
                        "endpoint": endpoint,
                        "model": "model",
                    }
                )

    def test_provider_api_never_echoes_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Settings.for_test(Path(tmp)))
            with TestClient(app) as client:
                response = client.post(
                    "/api/providers",
                    json={
                        "name": "Main",
                        "kind": "openai_compatible",
                        "endpoint": "https://api.example.com/v1",
                        "model": "model",
                        "api_key": "super-secret",
                    },
                )
                self.assertEqual(201, response.status_code)
                provider = response.json()
                self.assertTrue(provider["configured"])
                self.assertNotIn("api_key", provider)
                listed = client.get("/api/providers").json()
                self.assertNotIn("super-secret", repr(listed))

                with patch(
                    "web_tool.app.test_provider_connection",
                    return_value={"ok": True, "message": "connected"},
                ):
                    tested = client.post(f"/api/providers/{provider['id']}/test")
                self.assertEqual({"ok": True, "message": "connected"}, tested.json())


if __name__ == "__main__":
    unittest.main()
