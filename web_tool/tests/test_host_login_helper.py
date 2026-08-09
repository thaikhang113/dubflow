import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock


class HostLoginHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.helper_path = (
            cls.root / "tools" / "bilibili-host-login" / "helper.py"
        )

    def load_helper(self):
        self.assertTrue(self.helper_path.is_file(), "host login helper is missing")
        spec = importlib.util.spec_from_file_location(
            "bilibili_host_login_helper",
            self.helper_path,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_helper_binds_localhost_and_allows_only_local_web_origins(self):
        helper = self.load_helper()
        self.assertEqual(("127.0.0.1", 18794), helper.SERVER_ADDRESS)
        self.assertTrue(helper.origin_allowed("http://127.0.0.1:18793"))
        self.assertTrue(helper.origin_allowed("http://localhost:18793"))
        self.assertFalse(helper.origin_allowed("https://evil.example"))

    def test_chrome_command_uses_fixed_profile_extension_and_login_url(self):
        helper = self.load_helper()
        command = helper.build_chrome_command(Path("/chrome"))
        joined = "\n".join(str(value) for value in command)
        self.assertEqual(str(Path("/chrome")), command[0])
        self.assertIn("--user-data-dir=", joined)
        self.assertIn("--load-extension=", joined)
        self.assertIn("--disable-extensions-except=", joined)
        self.assertIn("https://passport.bilibili.com/login", command)
        self.assertNotIn("--remote-debugging-address", joined)
        self.assertNotIn("--remote-debugging-port", joined)

    def test_extension_does_not_restore_cookie_after_user_clears_tool_login(self):
        extension = (
            self.root / "tools" / "bilibili-host-login" / "extension"
        )
        manifest = (extension / "manifest.json").read_text(encoding="utf-8")
        background = (extension / "background.js").read_text(encoding="utf-8")
        self.assertNotIn('"alarms"', manifest)
        self.assertNotIn("chrome.alarms", background)

    def test_ollama_install_uses_only_fixed_compose_commands(self):
        helper = self.load_helper()
        run = Mock(
            side_effect=[
                Mock(returncode=0),
                Mock(returncode=0),
            ]
        )
        result = helper.install_ollama(run=run, docker="docker")
        self.assertTrue(result["ok"])
        self.assertEqual(
            [
                [
                    "docker",
                    "compose",
                    "--profile",
                    "ollama",
                    "up",
                    "-d",
                    "ollama",
                ],
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "ollama",
                    "ollama",
                    "pull",
                    "qwen2.5:3b",
                ],
            ],
            [call.args[0] for call in run.call_args_list],
        )

    def test_ollama_install_failure_does_not_return_process_output(self):
        helper = self.load_helper()
        run = Mock(return_value=Mock(returncode=1, stdout="secret", stderr="secret"))
        result = helper.install_ollama(run=run, docker="docker")
        self.assertFalse(result["ok"])
        self.assertEqual("OllamaServiceStartFailed", result["error_code"])
        self.assertNotIn("secret", repr(result))


if __name__ == "__main__":
    unittest.main()
