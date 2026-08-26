"""asr_will_use_gpu — quyết định có cho Demucs chạy song song với ASR."""
from unittest import mock

from autodub.config import Settings
from autodub.speech import transcriber


def _settings(**kw) -> Settings:
    s = Settings.load()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_paraformer_zh_configured_means_cpu():
    s = _settings(asr_engine="paraformer")
    with mock.patch.object(Settings, "paraformer_configured",
                           return_value=True), \
         mock.patch.object(transcriber, "_enable_cuda_dlls",
                           return_value=True):
        assert transcriber.asr_will_use_gpu(s, "zh") is False


def test_paraformer_wrong_language_falls_back_to_whisper_probe():
    s = _settings(asr_engine="paraformer")
    with mock.patch.object(Settings, "paraformer_configured",
                           return_value=True), \
         mock.patch.object(transcriber, "_enable_cuda_dlls",
                           return_value=True):
        # Tiếng Anh → Paraformer không nhận, Whisper GPU sẽ chạy
        assert transcriber.asr_will_use_gpu(s, "en") is True


def test_paraformer_not_installed_falls_back_to_whisper_probe():
    s = _settings(asr_engine="paraformer")
    with mock.patch.object(Settings, "paraformer_configured",
                           return_value=False), \
         mock.patch.object(transcriber, "_enable_cuda_dlls",
                           return_value=True):
        assert transcriber.asr_will_use_gpu(s, "zh") is True


def test_whisper_no_cuda_means_cpu():
    s = _settings(asr_engine="whisper")
    with mock.patch.object(transcriber, "_enable_cuda_dlls",
                           return_value=False):
        assert transcriber.asr_will_use_gpu(s, "zh") is False


def test_whisper_with_cuda_means_gpu():
    s = _settings(asr_engine="whisper")
    with mock.patch.object(transcriber, "_enable_cuda_dlls",
                           return_value=True):
        assert transcriber.asr_will_use_gpu(s, "en") is True

def test_whisper_gpu_runtime_error_retries_in_cpu_worker():
    error = RuntimeError(
        "Whisper worker thoát bất thường\n"
        "Library cublas64_12.dll is not found or cannot be loaded"
    )
    assert transcriber._should_retry_whisper_cpu(error) is True

def test_unrelated_whisper_error_does_not_force_cpu_worker():
    assert transcriber._should_retry_whisper_cpu(
        RuntimeError("Whisper worker không nhận dạng được câu nào")
    ) is False


def test_whisper_worker_detects_rocm_when_ctranslate2_and_rocminfo_are_ready():
    from autodub.speech import asr_whisper_worker

    with mock.patch.object(asr_whisper_worker, "_ctranslate2_gpu_ready",
                           return_value=True), \
         mock.patch.object(asr_whisper_worker, "_rocminfo_ready",
                           return_value=True):
        assert asr_whisper_worker._detect_backend(force_cpu=False) == "rocm"


def test_whisper_worker_falls_back_to_cpu_when_rocm_probe_fails():
    from autodub.speech import asr_whisper_worker

    with mock.patch.object(asr_whisper_worker, "_ctranslate2_gpu_ready",
                           return_value=False), \
         mock.patch.object(asr_whisper_worker, "_rocminfo_ready",
                           return_value=True):
        assert asr_whisper_worker._detect_backend(force_cpu=False) == "cpu"
