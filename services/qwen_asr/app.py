import math
import os
from collections.abc import Mapping
from pathlib import Path
from threading import RLock

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, constr

MODEL_ID = "Qwen/Qwen3-ASR-0.6B"
ALIGNER_ID = "Qwen/Qwen3-ForcedAligner-0.6B"
MODEL_REVISION = "5eb144179a02acc5e5ba31e748d22b0cf3e303b0"
ALIGNER_REVISION = "c7cbfc2048c462b0d63a45797104fc9db3ad62b7"
PROVIDER = "qwen3-asr-local"
MAX_CHUNK_SECONDS = 240
JOBS_ROOT = Path("/data/jobs")


class ServiceError(Exception):
    def __init__(self, status_code, error_code, message):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


class TranscribeRequest(BaseModel):
    audio_path: str
    language: constr(strip_whitespace=True, min_length=1)


class Segment(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class TranscribeResponse(BaseModel):
    provider: str
    model: str
    device: str
    language: str
    segments: list[Segment]


def load_audio(audio_path):
    try:
        import librosa

        audio, sample_rate = librosa.load(str(audio_path), sr=None, mono=True)
    except ImportError as exc:
        raise ServiceError(
            503, "DEPENDENCY_MISSING", "Audio dependency is unavailable"
        ) from exc
    except Exception as exc:
        raise ServiceError(400, "AUDIO_DECODE_FAILED", "Audio could not be decoded") from exc
    if sample_rate <= 0 or not len(audio):
        raise ServiceError(400, "AUDIO_DECODE_FAILED", "Audio is empty or invalid")
    return np.asarray(audio, dtype=np.float32), sample_rate


class QwenRuntime:
    def __init__(self):
        self.models_dir = Path(
            os.environ.get("QWEN_ASR_MODELS_DIR", "/models")
        )
        self._model = None
        self._aligner_ready = False
        self._device = "uninitialized"
        self._error_code = None
        # ponytail: serialize inference; add request queue/batching if throughput matters.
        self._lock = RLock()

    def health(self):
        return {
            "model_ready": self._model is not None,
            "aligner_ready": self._aligner_ready,
            "device": self._device,
            "error_code": self._error_code,
        }

    def _load_models(self):
        from huggingface_hub import snapshot_download
        import torch
        from qwen_asr import Qwen3ASRModel

        device = os.environ.get("QWEN_ASR_DEVICE") or (
            "cuda:0" if torch.cuda.is_available() else "cpu"
        )
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA device requested but CUDA is unavailable")
        if device != "cpu" and not device.startswith("cuda"):
            raise RuntimeError("Unsupported Qwen ASR device")
        dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
        model_path = snapshot_download(
            repo_id=MODEL_ID,
            revision=MODEL_REVISION,
            cache_dir=str(self.models_dir),
        )
        aligner_path = snapshot_download(
            repo_id=ALIGNER_ID,
            revision=ALIGNER_REVISION,
            cache_dir=str(self.models_dir),
        )
        model = Qwen3ASRModel.from_pretrained(
            model_path,
            dtype=dtype,
            device_map=device,
            max_new_tokens=4096,
            forced_aligner=aligner_path,
            forced_aligner_kwargs={
                "dtype": dtype,
                "device_map": device,
            },
        )
        return model, device

    def _ensure_loaded(self):
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                model, device = self._load_models()
                if model is None or getattr(model, "forced_aligner", None) is None:
                    raise RuntimeError("Qwen forced aligner did not load")
                self._model, self._device = model, device
                self._aligner_ready = True
                self._error_code = None
            except ImportError as exc:
                self._error_code = "DEPENDENCY_MISSING"
                raise ServiceError(
                    503,
                    self._error_code,
                    "Qwen ASR dependencies are unavailable",
                ) from exc
            except Exception as exc:
                self._error_code = "MODEL_LOAD_FAILED"
                raise ServiceError(
                    503, self._error_code, "Qwen ASR models could not be loaded"
                ) from exc

    def transcribe(self, audio_path, language):
        with self._lock:
            self._ensure_loaded()
            audio, sample_rate = load_audio(audio_path)
            chunk_samples = sample_rate * MAX_CHUNK_SECONDS
            segments = []
            try:
                for offset in range(0, len(audio), chunk_samples):
                    chunk = audio[offset : offset + chunk_samples]
                    result = self._model.transcribe(
                        audio=(chunk, sample_rate),
                        language=language,
                        return_time_stamps=True,
                    )
                    offset_seconds = offset / sample_rate
                    for item in result:
                        for cue in item.time_stamps or []:
                            segments.append(
                                {
                                    "start_ms": round(
                                        (offset_seconds + cue.start_time) * 1000
                                    ),
                                    "end_ms": round(
                                        (offset_seconds + cue.end_time) * 1000
                                    ),
                                    "text": cue.text,
                                }
                            )
            except ServiceError:
                raise
            except Exception as exc:
                self._error_code = "TRANSCRIPTION_FAILED"
                raise ServiceError(
                    502, self._error_code, "Qwen ASR transcription failed"
                ) from exc
            self._error_code = None
            return segments


def resolve_audio_path(raw_path):
    try:
        root = JOBS_ROOT.resolve(strict=True)
        audio_path = Path(raw_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ServiceError(
            400, "INVALID_AUDIO_PATH", "Audio path does not exist"
        ) from exc
    if not audio_path.is_file() or not audio_path.is_relative_to(root):
        raise ServiceError(
            400, "INVALID_AUDIO_PATH", "Audio path must be under /data/jobs"
        )
    return audio_path


def validate_segments(segments):
    if not segments:
        raise ServiceError(502, "INVALID_MODEL_OUTPUT", "Model returned no cues")
    validated = []
    previous_end = 0
    for cue in segments:
        if not isinstance(cue, Mapping):
            raise ServiceError(
                502, "INVALID_MODEL_OUTPUT", "Model returned an invalid cue"
            )
        start_ms = cue.get("start_ms")
        end_ms = cue.get("end_ms")
        text = cue.get("text")
        if (
            not isinstance(start_ms, (int, float))
            or not isinstance(end_ms, (int, float))
            or not math.isfinite(start_ms)
            or not math.isfinite(end_ms)
            or start_ms < 0
            or end_ms <= start_ms
            or start_ms < previous_end
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ServiceError(
                502, "INVALID_MODEL_OUTPUT", "Model returned an invalid cue"
            )
        validated.append(
            {
                "start_ms": round(start_ms),
                "end_ms": round(end_ms),
                "text": text.strip(),
            }
        )
        previous_end = end_ms
    return validated


app = FastAPI()
runtime = QwenRuntime()


@app.exception_handler(ServiceError)
async def service_error_handler(_request: Request, exc: ServiceError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message},
    )


@app.get("/health")
def health():
    try:
        runtime._ensure_loaded()
    except ServiceError:
        pass
    status = runtime.health()
    ready = status["model_ready"] and status["aligner_ready"]
    return JSONResponse(status_code=200 if ready else 503, content=status)


@app.post("/v1/transcribe", response_model=TranscribeResponse)
def transcribe(request: TranscribeRequest):
    audio_path = resolve_audio_path(request.audio_path)
    segments = validate_segments(runtime.transcribe(audio_path, request.language))
    return {
        "provider": PROVIDER,
        "model": MODEL_ID,
        "device": runtime.health()["device"],
        "language": request.language,
        "segments": segments,
    }
