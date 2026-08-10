import io
import os
import wave
from pathlib import Path
from threading import RLock

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

MODEL_ID = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
MODEL_REVISION = "75ff82a72f54d55ed389e1eeb12041d3c4bac7d4"
SAMPLE_RATE = 48_000
MAX_TEXT_LENGTH = 2_000
DEFAULT_VOICE = "vieneu:hong-chau"
DEFAULT_STYLE = "natural"
VOICES = {
    DEFAULT_VOICE: {
        "name": "Hồng Châu",
        "sdk_voice": "Ngọc Linh",
        "styles": {
            "natural": "tu_nhien",
            "story": "doc_truyen",
        },
    }
}


class ServiceError(Exception):
    def __init__(self, status_code, error_code, message):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE
    style: str = DEFAULT_STYLE
    reference_audio: str = ""


def encode_wav(audio):
    try:
        samples = np.asarray(audio, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ServiceError(502, "VieNeuWavInvalid", "VieNeu returned invalid audio") from exc
    if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
        raise ServiceError(502, "VieNeuWavInvalid", "VieNeu returned invalid mono audio")
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()


def validate_wav(data):
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if (
                wav.getnchannels() != 1
                or wav.getsampwidth() != 2
                or wav.getframerate() != SAMPLE_RATE
                or wav.getcomptype() != "NONE"
            ):
                raise ServiceError(
                    502, "VieNeuWavInvalid", "VieNeu WAV must be PCM16 mono 48000Hz"
                )
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    except ServiceError:
        raise
    except (EOFError, wave.Error) as exc:
        raise ServiceError(502, "VieNeuWavInvalid", "VieNeu returned invalid WAV") from exc
    if not pcm.size:
        raise ServiceError(502, "VieNeuWavInvalid", "VieNeu returned empty WAV")
    rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
    if rms < 128:
        raise ServiceError(502, "VieNeuWavSilent", "VieNeu WAV is silent")


class VieNeuRuntime:
    def __init__(self, models_dir=None):
        self.models_dir = Path(
            models_dir or os.environ.get("VIENEU_MODELS_DIR", "/models")
        )
        self._backend = "uninitialized"
        self._device = "uninitialized"
        self._model = None
        self._error_code = None
        # ponytail: serialize model load/inference; add queueing if throughput matters.
        self._lock = RLock()

    def health(self):
        return {
            "model": MODEL_ID,
            "revision": MODEL_REVISION,
            "backend": self._backend,
            "device": self._device,
            "sample_rate": SAMPLE_RATE,
            "voices": list(VOICES),
            "ready": self._model is not None,
            "error_code": self._error_code,
        }

    def _load_model(self):
        from huggingface_hub import snapshot_download
        from vieneu import Vieneu

        device = os.environ.get("VIENEU_DEVICE", "auto").strip().lower()
        if device.startswith("cuda"):
            import torch

            if not torch.cuda.is_available():
                raise RuntimeError("CUDA device requested but CUDA is unavailable")
        clone_enabled = os.environ.get("VIENEU_ENABLE_CLONE", "0") == "1"
        snapshot = snapshot_download(
            repo_id=MODEL_ID,
            revision=MODEL_REVISION,
            cache_dir=str(self.models_dir),
            allow_patterns=None
            if clone_enabled
            else ["config.json", "denoiser.onnx", "onnx_int8/*"],
        )
        return Vieneu(
            backbone_repo=snapshot,
            device=device,
            backend="pytorch" if clone_enabled else "auto",
            onnx_dir=str(Path(snapshot) / "onnx_int8"),
        )

    def _ensure_loaded(self):
        if self._model is not None:
            return
        try:
            model = self._load_model()
            backend = str(getattr(model, "backend", "")).lower()
            device = getattr(getattr(model, "engine", None), "device", None)
            device = str(getattr(device, "type", device or "")).lower()
            if backend not in {"onnx", "pytorch"} or not device:
                raise RuntimeError("VieNeu engine did not expose backend/device")
            self._model = model
            self._backend = backend
            self._device = device
            self._error_code = None
        except ImportError as exc:
            self._error_code = "VieNeuDependencyMissing"
            raise ServiceError(
                503, self._error_code, "VieNeu dependencies are unavailable"
            ) from exc
        except Exception as exc:
            self._error_code = "VieNeuModelLoadFailed"
            raise ServiceError(
                503, self._error_code, "VieNeu model could not be loaded"
            ) from exc

    def synthesize(self, text, sdk_voice, sdk_style, reference_audio=""):
        with self._lock:
            self._ensure_loaded()
            reference = str(reference_audio or "").strip()
            if reference:
                if self._device != "cuda":
                    raise ServiceError(
                        503,
                        "CloneRequiresGPU",
                        "VieNeu voice cloning requires a CUDA GPU",
                    )
                path = Path(reference).expanduser().resolve()
                if self.models_dir.resolve() not in path.parents or not path.is_file():
                    raise ServiceError(
                        422,
                        "VieNeuReferenceAudioInvalid",
                        "Reference audio must be an existing local model-volume file",
                    )
            last_error = None
            for _attempt in range(2):
                try:
                    options = {"voice": sdk_voice, "style": sdk_style}
                    if reference:
                        options.update(ref_audio=str(path), denoise=True)
                    data = encode_wav(self._model.infer(text, **options))
                    validate_wav(data)
                    self._error_code = None
                    return data
                except ServiceError as exc:
                    last_error = exc
                except Exception:
                    last_error = ServiceError(
                        502, "VieNeuInferenceFailed", "VieNeu inference failed"
                    )
            self._error_code = last_error.error_code
            raise last_error


app = FastAPI()
runtime = VieNeuRuntime()


@app.exception_handler(ServiceError)
async def service_error_handler(_request: Request, exc: ServiceError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message},
    )


@app.get("/health")
def health():
    status = runtime.health()
    if status["error_code"] is None:
        try:
            runtime._ensure_loaded()
        except ServiceError:
            pass
        status = runtime.health()
    return JSONResponse(
        status_code=200 if status["ready"] else 503,
        content=status,
    )


@app.get("/v1/voices")
def voices():
    return {
        "voices": [
            {
                "id": voice_id,
                "name": config["name"],
                "styles": list(config["styles"]),
                "default_style": DEFAULT_STYLE,
            }
            for voice_id, config in VOICES.items()
        ]
    }


@app.post("/v1/synthesize")
def synthesize(request: SynthesizeRequest):
    text = request.text.strip()
    if not text:
        raise ServiceError(422, "VieNeuTextEmpty", "Text must not be empty")
    if len(text) > MAX_TEXT_LENGTH:
        raise ServiceError(
            413,
            "VieNeuTextTooLong",
            f"Text must not exceed {MAX_TEXT_LENGTH} characters",
        )
    voice = VOICES.get(request.voice)
    if voice is None:
        raise ServiceError(422, "VieNeuVoiceUnknown", "Unknown VieNeu voice")
    sdk_style = voice["styles"].get(request.style)
    if sdk_style is None:
        raise ServiceError(422, "VieNeuStyleUnknown", "Unknown VieNeu style")
    return Response(
        runtime.synthesize(
            text,
            voice["sdk_voice"],
            sdk_style,
            request.reference_audio,
        ),
        media_type="audio/wav",
    )
