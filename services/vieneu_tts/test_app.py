import io
import sys
import tempfile
import types
import unittest
import warnings
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette\.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient

import app as service


class FakeModel:
    backend = "onnx"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def infer(self, text, *, voice, style):
        self.calls.append({"text": text, "voice": voice, "style": style})
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return output


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_runtime = service.runtime

    def tearDown(self):
        service.runtime = self.original_runtime

    def client_with_model(self, model):
        runtime = service.VieNeuRuntime()
        runtime._model = model
        runtime._backend = model.backend
        service.runtime = runtime
        return TestClient(service.app), runtime

    def test_import_does_not_import_or_load_vieneu(self):
        self.assertNotIn("vieneu", sys.modules)

    def test_health_reports_static_contract_without_loading_model(self):
        service.runtime = service.VieNeuRuntime()

        response = TestClient(service.app).get("/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "model": "pnnbao-ump/VieNeu-TTS-v3-Turbo",
                "revision": "75ff82a72f54d55ed389e1eeb12041d3c4bac7d4",
                "backend": "auto",
                "sample_rate": 48000,
                "voices": ["vieneu:hong-chau"],
                "ready": False,
                "error_code": None,
            },
            response.json(),
        )

    def test_health_returns_503_after_model_load_failure(self):
        runtime = service.VieNeuRuntime()
        service.runtime = runtime
        client = TestClient(service.app)

        with patch.object(
            runtime,
            "_load_model",
            side_effect=RuntimeError("broken model"),
        ):
            failed = client.post("/v1/synthesize", json={"text": "Xin chao"})

        response = client.get("/health")

        self.assertEqual(503, failed.status_code)
        self.assertEqual(503, response.status_code)
        self.assertFalse(response.json()["ready"])
        self.assertEqual("VieNeuModelLoadFailed", response.json()["error_code"])

    def test_voices_exposes_app_voice_and_story_style(self):
        response = TestClient(service.app).get("/v1/voices")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "voices": [
                    {
                        "id": "vieneu:hong-chau",
                        "name": "Hồng Châu",
                        "styles": ["story"],
                        "default_style": "story",
                    }
                ]
            },
            response.json(),
        )

    def test_synthesize_maps_to_official_voice_and_returns_pcm16_wav(self):
        model = FakeModel([np.full(4800, 0.25, dtype=np.float32)])
        client, _runtime = self.client_with_model(model)

        response = client.post("/v1/synthesize", json={"text": "Xin chào"})

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("audio/wav", response.headers["content-type"])
        self.assertEqual(
            [
                {
                    "text": "Xin chào",
                    "voice": "Ngọc Linh",
                    "style": "doc_truyen",
                }
            ],
            model.calls,
        )
        with wave.open(io.BytesIO(response.content), "rb") as wav:
            self.assertEqual(1, wav.getnchannels())
            self.assertEqual(2, wav.getsampwidth())
            self.assertEqual(48000, wav.getframerate())

    def test_rejects_empty_text_before_inference(self):
        model = FakeModel([np.full(100, 0.25, dtype=np.float32)])
        client, _runtime = self.client_with_model(model)

        response = client.post(
            "/v1/synthesize",
            json={
                "text": " \n ",
                "voice": "vieneu:hong-chau",
                "style": "story",
            },
        )

        self.assertEqual(422, response.status_code)
        self.assertEqual("VieNeuTextEmpty", response.json()["error_code"])
        self.assertEqual([], model.calls)

    def test_rejects_text_over_2000_characters_before_inference(self):
        model = FakeModel([np.full(100, 0.25, dtype=np.float32)])
        client, _runtime = self.client_with_model(model)

        response = client.post("/v1/synthesize", json={"text": "x" * 2001})

        self.assertEqual(413, response.status_code)
        self.assertEqual("VieNeuTextTooLong", response.json()["error_code"])
        self.assertEqual(
            "Text must not exceed 2000 characters",
            response.json()["message"],
        )
        self.assertEqual([], model.calls)

    def test_rejects_unknown_voice_before_inference(self):
        model = FakeModel([np.full(100, 0.25, dtype=np.float32)])
        client, _runtime = self.client_with_model(model)

        response = client.post(
            "/v1/synthesize",
            json={"text": "Xin chào", "voice": "vieneu:unknown", "style": "story"},
        )

        self.assertEqual(422, response.status_code)
        self.assertEqual("VieNeuVoiceUnknown", response.json()["error_code"])
        self.assertEqual([], model.calls)

    def test_rejects_unknown_style_before_inference(self):
        model = FakeModel([np.full(100, 0.25, dtype=np.float32)])
        client, _runtime = self.client_with_model(model)

        response = client.post(
            "/v1/synthesize",
            json={
                "text": "Xin chào",
                "voice": "vieneu:hong-chau",
                "style": "news",
            },
        )

        self.assertEqual(422, response.status_code)
        self.assertEqual("VieNeuStyleUnknown", response.json()["error_code"])
        self.assertEqual([], model.calls)

    def test_retries_inference_once_then_succeeds(self):
        model = FakeModel(
            [RuntimeError("first failure"), np.full(4800, 0.25, dtype=np.float32)]
        )
        client, _runtime = self.client_with_model(model)

        response = client.post("/v1/synthesize", json={"text": "Xin chào"})

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(2, len(model.calls))

    def test_retries_inference_exactly_once_then_returns_failure(self):
        model = FakeModel([RuntimeError("one"), RuntimeError("two")])
        client, runtime = self.client_with_model(model)

        response = client.post("/v1/synthesize", json={"text": "Xin chào"})

        self.assertEqual(502, response.status_code)
        self.assertEqual("VieNeuInferenceFailed", response.json()["error_code"])
        self.assertEqual(2, len(model.calls))
        self.assertEqual("VieNeuInferenceFailed", runtime.health()["error_code"])

    def test_rejects_stereo_sdk_output_after_one_retry(self):
        stereo = np.full((4800, 2), 0.25, dtype=np.float32)
        model = FakeModel([stereo, stereo])
        client, _runtime = self.client_with_model(model)

        response = client.post("/v1/synthesize", json={"text": "Xin chào"})

        self.assertEqual(502, response.status_code)
        self.assertEqual("VieNeuWavInvalid", response.json()["error_code"])
        self.assertEqual(2, len(model.calls))

    def test_rejects_wrong_wav_rate_after_one_retry(self):
        model = FakeModel(
            [
                np.full(4800, 0.25, dtype=np.float32),
                np.full(4800, 0.25, dtype=np.float32),
            ]
        )
        client, _runtime = self.client_with_model(model)

        with patch.object(
            service,
            "encode_wav",
            side_effect=lambda audio: make_wav(audio, sample_rate=24000),
        ):
            response = client.post("/v1/synthesize", json={"text": "Xin chào"})

        self.assertEqual(502, response.status_code)
        self.assertEqual("VieNeuWavInvalid", response.json()["error_code"])
        self.assertEqual(2, len(model.calls))

    def test_rejects_rms_below_128_with_required_code(self):
        silent = np.full(4800, 1 / 32767, dtype=np.float32)
        model = FakeModel([silent, silent])
        client, runtime = self.client_with_model(model)

        response = client.post("/v1/synthesize", json={"text": "Xin chào"})

        self.assertEqual(502, response.status_code)
        self.assertEqual("VieNeuWavSilent", response.json()["error_code"])
        self.assertEqual(2, len(model.calls))
        self.assertEqual("VieNeuWavSilent", runtime.health()["error_code"])

    def test_lazy_loader_uses_verified_snapshot_and_official_sdk_fields(self):
        calls = {}

        def snapshot_download(**kwargs):
            calls["snapshot"] = kwargs
            root = Path(temp.name)
            (root / "onnx_int8").mkdir()
            return str(root)

        def vieneu(**kwargs):
            calls["vieneu"] = kwargs
            return types.SimpleNamespace(backend="onnx")

        fake_hub = types.SimpleNamespace(snapshot_download=snapshot_download)
        fake_sdk = types.SimpleNamespace(Vieneu=vieneu)

        with tempfile.TemporaryDirectory() as tmp:
            temp = types.SimpleNamespace(name=tmp)
            runtime = service.VieNeuRuntime(models_dir=Path(tmp))
            with patch.dict(
                sys.modules,
                {"huggingface_hub": fake_hub, "vieneu": fake_sdk},
            ):
                model = runtime._load_model()

        self.assertEqual("onnx", model.backend)
        self.assertEqual(
            {
                "repo_id": "pnnbao-ump/VieNeu-TTS-v3-Turbo",
                "revision": "75ff82a72f54d55ed389e1eeb12041d3c4bac7d4",
                "cache_dir": str(runtime.models_dir),
                "allow_patterns": [
                    "config.json",
                    "denoiser.onnx",
                    "onnx_int8/*",
                ],
            },
            calls["snapshot"],
        )
        self.assertEqual(
            {
                "backbone_repo": tmp,
                "backend": "auto",
                "onnx_dir": str(Path(tmp) / "onnx_int8"),
            },
            calls["vieneu"],
        )

    def test_container_contract_pins_dependency_and_model_cache(self):
        service_dir = Path(__file__).parent
        requirements = (service_dir / "requirements.txt").read_text(encoding="utf-8")
        constraints = (service_dir / "constraints.txt").read_text(encoding="utf-8")
        dockerfile = (service_dir / "Dockerfile").read_text(encoding="utf-8")

        for package in (
            "fastapi",
            "uvicorn",
            "vieneu",
            "huggingface-hub",
            "numpy",
        ):
            self.assertIn(package, requirements.splitlines())
        for pin in (
            "fastapi==0.141.1",
            "uvicorn==0.52.1",
            "vieneu==3.2.4",
            "huggingface-hub==1.27.0",
            "numpy==2.3.4",
        ):
            self.assertIn(pin, constraints)
        self.assertIn(
            "FROM python:3.11-slim@sha256:"
            "90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff",
            dockerfile,
        )
        self.assertIn("COPY requirements.txt constraints.txt ./", dockerfile)
        self.assertIn(
            "pip install --no-cache-dir -r requirements.txt -c constraints.txt",
            dockerfile,
        )
        self.assertIn("HF_HOME=/models", dockerfile)
        self.assertIn("VIENEU_MODELS_DIR=/models", dockerfile)
        self.assertIn('CMD ["uvicorn", "app:app"', dockerfile)


def make_wav(audio, sample_rate=48000):
    pcm = np.clip(np.asarray(audio), -1, 1)
    pcm = (pcm * 32767).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()
