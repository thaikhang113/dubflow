import importlib.util
from pathlib import Path
import tempfile
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
                    "translategemma:4b",
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

    def test_whisper_install_accepts_only_fixed_models(self):
        helper = self.load_helper()
        run = Mock(return_value=Mock(returncode=0))
        result = helper.install_whisper("medium", run=run, docker="docker")
        self.assertTrue(result["ok"])
        self.assertEqual(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "tool",
                "bash",
                "/opt/whisper.cpp/models/download-ggml-model.sh",
                "medium",
                "/data/models/whisper.cpp/models",
            ],
            run.call_args.args[0],
        )
        self.assertEqual(
            "WhisperModelInvalid",
            helper.install_whisper("../../secret", run=run, docker="docker")["error_code"],
        )
    def test_hardware_detection_selects_profiles_from_verified_vram(self):
        helper = self.load_helper()
        for memory_mb, expected in ((4096, "hybrid"), (8192, "gpu")):
            with self.subTest(memory_mb=memory_mb):
                run = Mock(
                    side_effect=[
                        Mock(returncode=0, stdout=f"NVIDIA Test GPU, {memory_mb}\n"),
                        Mock(returncode=0),
                    ]
                )
                result = helper.detect_hardware(run=run, docker="docker")
                self.assertEqual(expected, result["recommended_profile"])
                self.assertTrue(result["docker_gpu"])
                self.assertEqual(
                    helper.subprocess.PIPE,
                    run.call_args_list[0].kwargs["stdout"],
                )
                self.assertEqual(
                    {"ollama": "gpu", "whisper": "cpu", "demucs": "cpu", "render": "cpu"},
                    result["stages"],
                )

    def test_hardware_detection_falls_back_when_gpu_or_docker_is_unavailable(self):
        helper = self.load_helper()
        no_gpu = helper.detect_hardware(
            run=Mock(return_value=Mock(returncode=1, stdout="")),
            docker="docker",
        )
        self.assertEqual("cpu", no_gpu["recommended_profile"])
        self.assertEqual("GpuNotFound", no_gpu["fallback_reason"])

        docker_fail = helper.detect_hardware(
            run=Mock(
                side_effect=[
                    Mock(returncode=0, stdout="NVIDIA Test GPU, 4096\n"),
                    Mock(returncode=1),
                ]
            ),
            docker="docker",
        )
        self.assertEqual("cpu", docker_fail["recommended_profile"])
        self.assertEqual("DockerGpuUnavailable", docker_fail["fallback_reason"])

    def test_apply_hardware_uses_only_fixed_compose_commands(self):
        helper = self.load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "hardware.json"
            run = Mock(
                side_effect=[
                    Mock(returncode=0, stdout="NVIDIA Test GPU, 4096\n"),
                    Mock(returncode=0),
                    Mock(returncode=0),
                ]
            )
            result = helper.apply_hardware_mode(
                "auto",
                run=run,
                docker="docker",
                state_path=state_path,
            )
            self.assertEqual("hybrid", result["selected_profile"])
            self.assertEqual(
                [
                    "docker", "compose",
                    "-f", "compose.yaml",
                    "-f", "compose.gpu.yaml",
                    "--profile", "ollama",
                    "up", "-d", "--force-recreate", "ollama",
                ],
                run.call_args_list[-1].args[0],
            )
            saved = state_path.read_text(encoding="utf-8")
            self.assertNotIn("stdout", saved)
            self.assertNotIn("stderr", saved)

    def test_hardware_status_keeps_fresh_detection_and_saved_selection(self):
        helper = self.load_helper()
        detection = {
            "gpu": {"name": "Fresh GPU", "memory_mb": 8192},
            "docker_gpu": True,
            "recommended_profile": "gpu",
            "fallback_reason": "",
            "stages": {"ollama": "gpu"},
        }
        saved = {
            "gpu": {"name": "Stale GPU", "memory_mb": 4096},
            "docker_gpu": False,
            "recommended_profile": "cpu",
            "requested_mode": "auto",
            "selected_profile": "hybrid",
        }

        result = helper.hardware_status(detection, saved)

        self.assertEqual("Fresh GPU", result["gpu"]["name"])
        self.assertTrue(result["docker_gpu"])
        self.assertEqual("gpu", result["recommended_profile"])
        self.assertEqual("auto", result["requested_mode"])
        self.assertEqual("hybrid", result["selected_profile"])

    def test_apply_forced_gpu_falls_back_to_cpu(self):
        helper = self.load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            run = Mock(
                side_effect=[
                    Mock(returncode=1, stdout=""),
                    Mock(returncode=0),
                ]
            )
            result = helper.apply_hardware_mode(
                "gpu",
                run=run,
                docker="docker",
                state_path=Path(tmp) / "hardware.json",
            )
            self.assertEqual("cpu", result["selected_profile"])
            self.assertEqual("GpuNotFound", result["fallback_reason"])
            self.assertEqual(
                [
                    "docker", "compose", "--profile", "ollama",
                    "up", "-d", "--force-recreate", "ollama",
                ],
                run.call_args_list[-1].args[0],
            )


if __name__ == "__main__":
    unittest.main()
