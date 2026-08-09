import importlib
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from starlette.exceptions import StarletteDeprecationWarning

warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)
from fastapi.testclient import TestClient


class FakeRuntime:
    def __init__(self, segments=None, error=None):
        self.segments = (
            [{"start_ms": 0, "end_ms": 1200, "text": "xin chao"}]
            if segments is None
            else segments
        )
        self.error = error

    def health(self):
        return {
            "model_ready": True,
            "aligner_ready": True,
            "device": "cpu",
            "error_code": None,
        }

    def transcribe(self, audio_path, language):
        if self.error:
            raise self.error
        return self.segments


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = importlib.import_module("app")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs_root = Path(self.temp.name) / "jobs"
        self.jobs_root.mkdir()
        self.audio_path = self.jobs_root / "audio.wav"
        self.audio_path.write_bytes(b"fake")
        self.original_root = self.service.JOBS_ROOT
        self.original_runtime = self.service.runtime
        self.service.JOBS_ROOT = self.jobs_root

    def tearDown(self):
        self.service.JOBS_ROOT = self.original_root
        self.service.runtime = self.original_runtime
        self.temp.cleanup()

    def client(self, runtime=None, *, raise_server_exceptions=True):
        self.service.runtime = runtime or FakeRuntime()
        return TestClient(
            self.service.app, raise_server_exceptions=raise_server_exceptions
        )

    def test_import_does_not_load_qwen_dependency(self):
        self.assertNotIn("qwen_asr", sys.modules)

    def test_health_reports_readiness_without_loading_models(self):
        runtime = self.service.QwenRuntime()
        self.service.runtime = runtime

        response = TestClient(self.service.app).get("/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "model_ready": False,
                "aligner_ready": False,
                "device": "uninitialized",
                "error_code": None,
            },
            response.json(),
        )

    def test_transcribe_returns_fixed_contract(self):
        runtime = FakeRuntime(
            segments=[{"start_ms": 0, "end_ms": 1200, "text": "你好"}]
        )
        response = self.client(runtime).post(
            "/v1/transcribe",
            json={"audio_path": str(self.audio_path), "language": "Chinese"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "provider": "qwen3-asr-local",
                "model": "Qwen/Qwen3-ASR-0.6B",
                "device": "cpu",
                "language": "Chinese",
                "segments": [
                    {"start_ms": 0, "end_ms": 1200, "text": "你好"}
                ],
            },
            response.json(),
        )

    def test_rejects_path_outside_jobs_root(self):
        outside = Path(self.temp.name) / "outside.wav"
        outside.write_bytes(b"fake")

        response = self.client().post(
            "/v1/transcribe",
            json={"audio_path": str(outside), "language": "Vietnamese"},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("INVALID_AUDIO_PATH", response.json()["error_code"])

    def test_rejects_path_traversal(self):
        traversal = self.jobs_root / ".." / "outside.wav"
        traversal.resolve().write_bytes(b"fake")

        response = self.client().post(
            "/v1/transcribe",
            json={"audio_path": str(traversal), "language": "Vietnamese"},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("INVALID_AUDIO_PATH", response.json()["error_code"])

    def test_rejects_empty_language(self):
        response = self.client().post(
            "/v1/transcribe",
            json={"audio_path": str(self.audio_path), "language": "  "},
        )

        self.assertEqual(422, response.status_code)

    def test_dependency_failure_returns_clear_code(self):
        runtime = self.service.QwenRuntime()
        self.service.runtime = runtime

        with patch.object(runtime, "_load_models", side_effect=ImportError("missing")):
            response = TestClient(self.service.app).post(
                "/v1/transcribe",
                json={"audio_path": str(self.audio_path), "language": "Vietnamese"},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("DEPENDENCY_MISSING", response.json()["error_code"])
        self.assertEqual("DEPENDENCY_MISSING", runtime.health()["error_code"])

    def test_rejects_invalid_model_segments(self):
        invalid_cases = {
            "empty cue": [{"start_ms": 0, "end_ms": 1, "text": " "}],
            "negative timestamp": [
                {"start_ms": -1, "end_ms": 1, "text": "bad"}
            ],
            "end before start": [
                {"start_ms": 2, "end_ms": 1, "text": "bad"}
            ],
            "zero duration": [
                {"start_ms": 1, "end_ms": 1, "text": "bad"}
            ],
            "non monotonic": [
                {"start_ms": 0, "end_ms": 10, "text": "one"},
                {"start_ms": 9, "end_ms": 20, "text": "two"},
            ],
        }

        for name, segments in invalid_cases.items():
            with self.subTest(name=name):
                response = self.client(FakeRuntime(segments=segments)).post(
                    "/v1/transcribe",
                    json={
                        "audio_path": str(self.audio_path),
                        "language": "Vietnamese",
                    },
                )
                self.assertEqual(502, response.status_code)
                self.assertEqual(
                    "INVALID_MODEL_OUTPUT", response.json()["error_code"]
                )

    def test_rejects_non_mapping_model_cue_with_controlled_error(self):
        response = self.client(
            FakeRuntime(segments=[None]), raise_server_exceptions=False
        ).post(
            "/v1/transcribe",
            json={"audio_path": str(self.audio_path), "language": "Chinese"},
        )

        self.assertEqual(502, response.status_code)
        self.assertEqual("INVALID_MODEL_OUTPUT", response.json()["error_code"])

    def test_rejects_empty_model_segments(self):
        response = self.client(FakeRuntime(segments=[])).post(
            "/v1/transcribe",
            json={"audio_path": str(self.audio_path), "language": "Chinese"},
        )

        self.assertEqual(502, response.status_code)
        self.assertEqual("INVALID_MODEL_OUTPUT", response.json()["error_code"])

    def test_runtime_chunks_audio_at_240_seconds_and_offsets_timestamps(self):
        sample_rate = 10
        audio = np.zeros(sample_rate * 241, dtype=np.float32)

        class FakeModel:
            def __init__(self):
                self.chunk_sizes = []

            def transcribe(self, *, audio, **kwargs):
                chunk, current_rate = audio
                self.chunk_sizes.append(len(chunk))
                duration = len(chunk) / current_rate
                return [
                    SimpleNamespace(
                        time_stamps=[
                            SimpleNamespace(
                                start_time=0.0,
                                end_time=duration,
                                text=f"chunk {len(self.chunk_sizes)}",
                            )
                        ]
                    )
                ]

        model = FakeModel()
        runtime = self.service.QwenRuntime()
        runtime._model = model
        runtime._aligner_ready = True
        runtime._device = "cpu"

        with patch.object(
            self.service, "load_audio", return_value=(audio, sample_rate)
        ):
            segments = runtime.transcribe(self.audio_path, "Vietnamese")

        self.assertEqual([2400, 10], model.chunk_sizes)
        self.assertEqual(
            [
                {"start_ms": 0, "end_ms": 240000, "text": "chunk 1"},
                {"start_ms": 240000, "end_ms": 241000, "text": "chunk 2"},
            ],
            segments,
        )

    def test_runtime_loads_aligner_through_official_from_pretrained_api(self):
        calls = []
        loaded_model = object()

        class FakeModelClass:
            @classmethod
            def from_pretrained(cls, model_id, **kwargs):
                calls.append((model_id, kwargs))
                return loaded_model

        fake_torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False),
            bfloat16="bfloat16",
            float32="float32",
        )
        fake_qwen = SimpleNamespace(Qwen3ASRModel=FakeModelClass)

        with patch.dict(
            sys.modules, {"torch": fake_torch, "qwen_asr": fake_qwen}
        ):
            model, device = self.service.QwenRuntime()._load_models()

        self.assertIs(loaded_model, model)
        self.assertEqual("cpu", device)
        self.assertEqual("Qwen/Qwen3-ASR-0.6B", calls[0][0])
        self.assertEqual(
            "Qwen/Qwen3-ForcedAligner-0.6B",
            calls[0][1]["forced_aligner"],
        )
        self.assertEqual(
            {"dtype": "float32", "device_map": "cpu"},
            calls[0][1]["forced_aligner_kwargs"],
        )

    def test_successful_transcription_clears_previous_runtime_error(self):
        class FlakyModel:
            def __init__(self):
                self.calls = 0

            def transcribe(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("temporary failure")
                return [
                    SimpleNamespace(
                        time_stamps=[
                            SimpleNamespace(
                                start_time=0.0,
                                end_time=1.0,
                                text="recovered",
                            )
                        ]
                    )
                ]

        runtime = self.service.QwenRuntime()
        runtime._model = FlakyModel()
        runtime._aligner_ready = True
        runtime._device = "cpu"

        with patch.object(
            self.service,
            "load_audio",
            return_value=(np.zeros(10, dtype=np.float32), 10),
        ):
            with self.assertRaises(self.service.ServiceError):
                runtime.transcribe(self.audio_path, "English")
            runtime.transcribe(self.audio_path, "English")

        self.assertIsNone(runtime.health()["error_code"])

    def test_container_contract_pins_models_and_cache(self):
        service_dir = Path(__file__).parent
        requirements = (service_dir / "requirements.txt").read_text()
        constraints = (service_dir / "constraints.txt").read_text()
        dockerfile = (service_dir / "Dockerfile").read_text()

        self.assertIn("fastapi==0.141.1", requirements)
        self.assertIn("uvicorn[standard]==0.52.1", requirements)
        self.assertIn("qwen-asr==0.0.6", requirements)
        self.assertIn("transformers==4.57.6", requirements)
        self.assertRegex(constraints, r"(?m)^starlette==\S+$")
        self.assertRegex(constraints, r"(?m)^pydantic==\S+$")
        pins = [
            line
            for line in constraints.splitlines()
            if line and not line.startswith(("#", " "))
        ]
        self.assertTrue(all("==" in pin for pin in pins))
        self.assertIn("COPY requirements.txt constraints.txt ./", dockerfile)
        self.assertIn(
            "pip install --no-cache-dir -r requirements.txt -c constraints.txt",
            dockerfile,
        )
        self.assertIn("HF_HOME=/models", dockerfile)
        self.assertIn('CMD ["uvicorn", "app:app"', dockerfile)


if __name__ == "__main__":
    unittest.main()
