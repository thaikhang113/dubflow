"""Kiểm chứng việc bấm Dừng không bị nuốt thành cảnh báo.

Mỗi test ở đây mô phỏng đúng đường mà PipelineCancelled đi qua một handler
`except Exception` trong mã sản phẩm. Test chỉ kiểm chứng HÀNH VI: nếu gỡ nhánh
`except PipelineCancelled: raise` ra khỏi chỗ vá thì test đỏ (lệnh hủy biến
thành cảnh báo/đường dự phòng), chứ không kiểm tra chuỗi nguồn.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from autodub.cancel import (
    cancel_processes,
    clear_cancel_request,
    run_registered,
)
from autodub.media import douyin, downloader, retime, video2x, vsr
from autodub.media import ocr as ocr_mod
from autodub.progress import PipelineCancelled
from autodub.speech import align, paraformer_transcriber, transcriber


@pytest.fixture(autouse=True)
def _clean_cancel_state():
    """Không để cờ hủy của test này rò sang test khác."""
    clear_cancel_request()
    yield
    cancel_processes()
    clear_cancel_request()


def _blow_up():
    raise PipelineCancelled("Pipeline cancelled by user")


def _cancel_first_run(monkeypatch, module, cancelled_run):
    """Thay lệnh ngoài THẬT bằng hàm coi như tiến trình bị Dừng giết.

    Trả về danh sách đếm số lần gọi. Test khẳng định: lần đầu raise
    PipelineCancelled; các lần sau đếm được > 0 nghĩa là chỗ gọi đã đi tiếp
    sang đường dự phòng thay vì ném lệnh hủy đi.
    """
    calls = []

    def _run(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            cancelled_run()
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(module, "run_registered", _run)
    return calls


# --------------------------------------------------------------------------
# autodub/media/vsr.py — dùng thật run_registered của autodub.cancel
# --------------------------------------------------------------------------

def test_vsr_falls_back_when_command_fails_honestly(monkeypatch, tmp_path):
    """Đối chứng: lỗi VSR thật (không phải hủy) VẪN được hạ cấp thành fallback."""
    calls = []

    def _broken(cmd):
        calls.append(cmd)
        raise RuntimeError("worker sập")

    result = vsr.run_vsr_or_fallback(
        "video.mp4", str(tmp_path / "vsr.mp4"),
        [{"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.2}],
        run_command=_broken,
        command=["unused"],
        fallback=lambda: str(tmp_path / "fallback.mp4"))
    assert result.used_vsr is False
    assert result.error and "worker sập" in result.error
    assert len(calls) == 1


def test_vsr_reraises_cancellation(monkeypatch, tmp_path):
    """Bấm Dừng trong lúc VSR chạy thì hàng đợi video không được đi tiếp."""
    calls = []

    def _cancelled(cmd):
        calls.append(cmd)
        raise PipelineCancelled("worker VSR bị Dừng giết")

    with pytest.raises(PipelineCancelled):
        vsr.run_vsr_or_fallback(
            "video.mp4", str(tmp_path / "vsr.mp4"),
            [{"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.2}],
            run_command=_cancelled,
            command=["unused"],
            fallback=lambda: (_ for _ in ()).throw(
                AssertionError("đã chạy đường dự phòng sau khi bị hủy")))
    assert len(calls) == 1, "đã lặng lẽ chạy đường dự phòng sau khi bị hủy"


def test_run_registered_raises_pipeline_cancelled_for_this_seam(monkeypatch):
    """Chốt lại cơ chế: run_registered ném PipelineCancelled (không phải lỗi tạm)."""
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))
    try:
        cancel_processes()
        with pytest.raises(PipelineCancelled):
            run_registered(["ffmpeg", "-version"])
    finally:
        clear_cancel_request()


# --------------------------------------------------------------------------
# autodub/media/video2x.py
# --------------------------------------------------------------------------

def test_video2x_reraises_cancellation(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")
    calls = []

    def _cancelled(cmd):
        calls.append(cmd)
        raise PipelineCancelled("tiến trình Video2X bị Dừng giết")

    with pytest.raises(PipelineCancelled):
        video2x.run_video2x_or_fallback(
            str(video), str(tmp_path / "up2x.mp4"),
            command=["unused"], run_command=_cancelled)
    assert len(calls) == 1


def test_video2x_keeps_fallback_for_real_failure(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")

    def _broken(cmd):
        raise RuntimeError("video2x failed")

    result = video2x.run_video2x_or_fallback(
        str(video), str(tmp_path / "up2x.mp4"),
        command=["unused"], run_command=_broken)
    assert result.output_path == str(video) and result.used_video2x is False


# --------------------------------------------------------------------------
# autodub/media/ocr.py
# --------------------------------------------------------------------------

#: Một phát hiện OCR hợp lệ: chữ Hán, nằm dải phụ đề dưới, tỷ lệ khung hợp lý.
#: detections_to_regions lọc theo đúng những điều kiện đó (cao <= 14% khung,
#: rộng/cao >= 1.3) nên fake phải khớp thì mới đi qua được bộ lọc.
_CJK_DETECTION = {
    "text": "字幕",
    "confidence": 0.99,
    "box": [[100.0, 820.0], [900.0, 820.0], [900.0, 880.0], [100.0, 880.0]],
    "time": 0.0,
    "t_end": 1.0,
}

def _ocr_settings(tmp_path):
    from types import SimpleNamespace

    return SimpleNamespace(
        ocr_backend="hybrid",
        ocr_enabled=True,
        deepseek_ocr_enabled=True,
        ocr_sample_interval=1.0,
        ocr_min_confidence=0.8,
        ocr_max_region_area=0.25,
        ocr_subtitle_y_min=0.65,
        ocr_venv_python_path=lambda: "python",
        ocr_model_dir_path=lambda: str(tmp_path / "model"),
        ocr_configured=lambda: True,
        deepseek_ocr_configured=lambda: True,
        deepseek_ocr_venv_python_path=lambda: "python",
        deepseek_ocr_model_dir_path=lambda: str(tmp_path / "ds-model"),
    )


def _ocr_worker_factory(monkeypatch, cancellation):
    """Giả lập _run_engine_detections: engine chính bị hủy, engine dự phòng đếm."""
    seen = []
    state = {"first": True}

    def fake_worker(video_path, duration, settings, *, backend):
        seen.append(backend)
        if backend == "paddle" and state["first"]:
            state["first"] = False
            raise cancellation
        return [_CJK_DETECTION]

    monkeypatch.setattr(ocr_mod, "_run_engine_detections", fake_worker)
    return seen


def test_ocr_reraises_when_primary_engine_cancelled(monkeypatch, tmp_path):
    seen = _ocr_worker_factory(monkeypatch, PipelineCancelled("hủy"))
    with pytest.raises(PipelineCancelled):
        ocr_mod.detect_regions_with_logo("video.mp4", 1000, 1000, 2.0,
                                         _ocr_settings(tmp_path))
    assert seen == ["paddle"], "đã chạy tiếp engine DeepSeek sau khi bị hủy"


def test_ocr_falls_back_to_deepseek_on_real_failure(monkeypatch, tmp_path):
    seen = _ocr_worker_factory(monkeypatch, RuntimeError("paddle chưa cài"))
    ocr_mod.detect_regions_with_logo("video.mp4", 1000, 1000, 2.0,
                                     _ocr_settings(tmp_path))
    assert seen == ["paddle", "deepseek"]


def test_ocr_reraises_when_fallback_engine_cancelled(monkeypatch, tmp_path):
    def fake_worker(video_path, duration, settings, *, backend):
        if backend == "deepseek":
            raise PipelineCancelled("hủy")
        return []

    monkeypatch.setattr(ocr_mod, "_run_engine_detections", fake_worker)
    with pytest.raises(PipelineCancelled):
        ocr_mod.detect_regions_with_logo("video.mp4", 1000, 1000, 2.0,
                                         _ocr_settings(tmp_path))


def test_ocr_fallback_failure_still_warns(monkeypatch, tmp_path):
    def fake_worker(video_path, duration, settings, *, backend):
        if backend == "deepseek":
            raise RuntimeError("deepseek chưa cài")
        return [_CJK_DETECTION]

    monkeypatch.setattr(ocr_mod, "_run_engine_detections", fake_worker)
    regions, _logo = ocr_mod.detect_regions_with_logo(
        "video.mp4", 1000, 1000, 2.0, _ocr_settings(tmp_path))
    assert len(regions) == 1
    assert regions[0]["text"] == "字幕" and regions[0]["source"] == "ocr"


@pytest.mark.skipif(os.environ.get("DUBFLOW_OCR_E2E") != "1",
                    reason="cần model OCR thật (bật bằng DUBFLOW_OCR_E2E=1)")
def test_ocr_real_worker_cancellation_is_raised(tmp_path):
    from autodub.config import Settings

    video = tmp_path / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
                    "-pix_fmt", "yuv420p", str(video)], check=True,
                   capture_output=True)
    settings = Settings()
    settings.ocr_enabled = True
    settings.ocr_backend = "paddle"
    duration = 1.0
    monkeypatch = pytest.MonkeyPatch()
    try:
        cancel_processes()
        with pytest.raises(PipelineCancelled):
            ocr_mod.detect_regions_with_logo(str(video), 64, 64, duration, settings)
    finally:
        clear_cancel_request()
        monkeypatch.undo()


# --------------------------------------------------------------------------
# autodub/media/retime.py — dùng thật run_registered của autodub.cancel
# --------------------------------------------------------------------------

def _retime_settings():
    from autodub.config import Settings

    return Settings(video_speed=0.8)


def test_apply_video_speed_reraises_cancellation(monkeypatch, tmp_path):
    monkeypatch.setattr(retime, "probe_video_info", lambda p: (10.0, "25"))
    monkeypatch.setattr(retime, "probe_duration", lambda p: 12.6)
    calls = _cancel_first_run(monkeypatch, retime, _blow_up)
    with pytest.raises(PipelineCancelled):
        retime.apply_video_speed(str(tmp_path / "v.mp4"), None, [],
                                 str(tmp_path), _retime_settings())
    assert len(calls) == 1, "đã trả None để pipeline xuất trên video gốc"


def test_defer_video_speed_reraises_cancellation(monkeypatch, tmp_path):
    """Đường làm chậm nhạc nền cũng phải để lệnh hủy đi qua."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    background = tmp_path / "bg.wav"
    background.write_bytes(b"RIFF")
    monkeypatch.setattr(retime, "probe_video_info", lambda p: (10.0, "25"))
    # slow_background() gọi probe_duration() trước khi chạy ffmpeg; máy không
    # có ffprobe thì nó ném FileNotFoundError và test lạc đề (kiểm tra môi
    # trường chứ không kiểm tra lệnh hủy).
    monkeypatch.setattr(retime, "probe_duration", lambda p: 10.0)
    calls = _cancel_first_run(monkeypatch, retime, _blow_up)
    with pytest.raises(PipelineCancelled):
        retime.defer_video_speed(str(video), str(background), [],
                                 str(tmp_path), _retime_settings())
    assert len(calls) == 1


# --------------------------------------------------------------------------
# autodub/media/douyin.py
# --------------------------------------------------------------------------

def test_douyin_reraises_cancellation_before_browser_fallback(monkeypatch, tmp_path):
    """Bấm Dừng trong lúc tải luồng trực tiếp thì KHÔNG được mở trình duyệt.

    Lưu ý về độ "có răng": hai nhánh vá trong douyin.py đứng trước
    `except (requests.RequestException, RuntimeError)`, mà PipelineCancelled
    chỉ kế thừa Exception nên chúng chưa bao giờ bắt được nó. Test này vì thế
    xanh cả khi gỡ bản vá; nó ghi lại BẤT BIẾN hành vi (hủy thì không mở
    trình duyệt) chứ không phải bằng chứng cho bản vá. Xem báo cáo task để
    biết danh sách chỗ vá thừa.
    """
    monkeypatch.setattr(douyin, "resolve_video_id", lambda url, cookies=None: "123")
    monkeypatch.setattr(
        douyin, "_fetch_share_info",
        lambda video_id, cookies=None: {"uri": "https://cdn/x.mp4", "title": "t"})
    seen = []

    def cancelled_download(*_args, **_kwargs):
        seen.append("play_url")
        raise PipelineCancelled("Video download cancelled")

    def browser_fallback(*_args, **_kwargs):
        seen.append("playwright")
        raise AssertionError("đã mở trình duyệt tải lại sau khi người dùng Dừng")

    monkeypatch.setattr(douyin, "_download_play_url", cancelled_download)
    monkeypatch.setattr(douyin, "_download_via_playwright", browser_fallback)
    with pytest.raises(PipelineCancelled):
        douyin.download_douyin("https://v.douyin.com/abc/", str(tmp_path))
    assert seen == ["play_url"]


# --------------------------------------------------------------------------
# autodub/media/downloader.py — retry KHÔNG được thử lại sau khi bị hủy
# --------------------------------------------------------------------------

def test_downloader_retry_does_not_sleep_or_retry_after_cancel(monkeypatch):
    """Bấm Dừng giữa lúc yt-dlp lấy metadata thì phải dừng ngay, không ngủ chờ.

    Về độ "có răng": bản thân PipelineCancelled KHÔNG bị
    is_transient_download_error xếp là lỗi tạm thời, nên kể cả khi gỡ nhánh
    `except PipelineCancelled: raise` thì nó vẫn được ném tiếp và test vẫn
    xanh. Vì vậy test dùng một lớp con VỪA mang nghĩa "đã hủy" VỪA khớp mẫu
    lỗi tạm thời — đúng tình huống mà nhánh vá là thứ duy nhất giữ cho ta
    khỏi ngủ 2-30 s rồi thử tải lại trong khi người dùng đã bấm Dừng.
    """
    attempts = []
    sleeps = []

    class _TransientLookingCancel(PipelineCancelled):
        """Lệnh hủy nhưng thông điệp khớp mẫu lỗi tạm thời của yt-dlp."""

    class _FakeYdl:
        def extract_info(self, url, download=True):
            attempts.append(url)
            raise _TransientLookingCancel("HTTP Error 503: Service Unavailable")

    monkeypatch.setattr(downloader.time, "sleep", lambda s: sleeps.append(s))
    with pytest.raises(PipelineCancelled):
        downloader._extract_info_with_retry(_FakeYdl(), "https://x/y")
    assert len(attempts) == 1, "đã thử lại tải sau khi người dùng bấm Dừng"
    assert sleeps == [], "đã ngủ chờ rồi thử lại sau khi người dùng bấm Dừng"


def test_downloader_retry_still_retries_real_transient_error(monkeypatch):
    """Đối chứng: lỗi tạm thời THẬT vẫn được thử lại như trước."""
    attempts = []
    sleeps = []

    class _FakeYdl:
        def extract_info(self, url, download=True):
            attempts.append(url)
            if len(attempts) < 2:
                raise RuntimeError("HTTP Error 503: Service Unavailable")
            return {"id": "ok"}

    monkeypatch.setattr(downloader.time, "sleep", lambda s: sleeps.append(s))
    info = downloader._extract_info_with_retry(_FakeYdl(), "https://x/y")
    assert info == {"id": "ok"}
    assert len(attempts) == 2 and sleeps == [2]


# --------------------------------------------------------------------------
# autodub/speech/transcriber.py
# --------------------------------------------------------------------------

class _WhisperSettings:
    """Cấu hình tối thiểu để transcribe() đi vào nhánh subprocess worker."""

    asr_engine = "whisper"

    def whisper_venv_configured(self):
        return True


def test_transcriber_reraises_cancellation_from_subprocess(monkeypatch):
    """Hủy ở worker Whisper không được biến thành "thử in-process" rồi chạy tiếp.

    _transcribe_whisper_subprocess đã tự ném PipelineCancelled khi cờ hủy bật,
    nhưng để test có răng ta cho nó ném trong lúc cờ TẮT: khi đó nếu thiếu nhánh
    `except PipelineCancelled: raise` ở transcriber.py, ngoại lệ rơi vào
    `except Exception` -> `_should_retry_whisper_cpu` không khớp (thông điệp
    không có cublas/cudnn/...) -> ghi cảnh báo rồi gọi _transcribe_whisper.
    """
    fallback_calls = []

    def _cancelled_subprocess(*_args, **_kwargs):
        raise PipelineCancelled("worker Whisper bị Dừng giết")

    def _in_process(*_args, **_kwargs):
        fallback_calls.append("in-process")
        return [{"id": 1, "text": "x", "start": 0.0, "end": 1.0,
                 "duration": 1.0}]

    monkeypatch.setattr(transcriber, "_transcribe_whisper_subprocess",
                        _cancelled_subprocess)
    monkeypatch.setattr(transcriber, "_transcribe_whisper", _in_process)
    monkeypatch.setattr(transcriber, "is_cancel_requested", lambda *a, **k: False)
    with pytest.raises(PipelineCancelled):
        transcriber.transcribe("audio.wav", "vi", _WhisperSettings())
    assert fallback_calls == [], "đã chạy tiếp Whisper in-process sau khi bị hủy"


def test_transcriber_reraises_cancellation_from_cpu_retry(monkeypatch):
    """Nhánh retry CPU cũng phải để lệnh hủy đi qua nguyên vẹn."""
    calls = []
    fallback_calls = []

    def _subprocess(*_args, **kwargs):
        calls.append(kwargs.get("force_cpu", False))
        if kwargs.get("force_cpu"):
            raise PipelineCancelled("worker CPU bị Dừng giết")
        # Lỗi CUDA thật -> được phép retry CPU (đối chứng cho nhánh dưới).
        raise RuntimeError("cublas64_12.dll not found")

    def _in_process(*_args, **_kwargs):
        fallback_calls.append("in-process")
        return []

    monkeypatch.setattr(transcriber, "_transcribe_whisper_subprocess", _subprocess)
    monkeypatch.setattr(transcriber, "_transcribe_whisper", _in_process)
    monkeypatch.setattr(transcriber, "is_cancel_requested", lambda *a, **k: False)
    with pytest.raises(PipelineCancelled):
        transcriber.transcribe("audio.wav", "vi", _WhisperSettings())
    assert calls == [False, True], "chưa đi hết đường GPU -> retry CPU"
    assert fallback_calls == [], "đã chạy tiếp Whisper in-process sau khi bị hủy"


def test_transcriber_paraformer_cancel_is_not_downgraded(monkeypatch):
    """Paraformer báo hủy thì không được hạ cấp thành "chuyển sang Whisper".

    transcriber.py:261-265 bọc lời gọi transcribe_paraformer trong
    `except Exception`; thiếu nhánh PipelineCancelled ở đó thì lệnh hủy bị
    nuốt và pipeline chạy tiếp bước dài nhất sau khi người dùng đã bấm Dừng.
    """
    subprocess_calls = []

    class _ParaSettings(_WhisperSettings):
        asr_engine = "paraformer"

        def paraformer_configured(self):
            return True

    def _cancelled_paraformer(*_args, **_kwargs):
        raise PipelineCancelled("Đã hủy trong lúc nghe-chép (Paraformer)")

    def _subprocess(*_args, **_kwargs):
        subprocess_calls.append("whisper")
        return []

    monkeypatch.setattr(paraformer_transcriber, "transcribe_paraformer",
                        _cancelled_paraformer)
    monkeypatch.setattr(transcriber, "_transcribe_whisper_subprocess", _subprocess)
    with pytest.raises(PipelineCancelled):
        transcriber.transcribe("audio.wav", "zh", _ParaSettings())
    assert subprocess_calls == [], "đã chuyển sang Whisper sau khi bị hủy"


def test_transcriber_paraformer_real_failure_still_falls_back(monkeypatch):
    """Đối chứng: lỗi Paraformer THẬT vẫn được hạ cấp sang Whisper."""
    subprocess_calls = []

    class _ParaSettings(_WhisperSettings):
        asr_engine = "paraformer"

        def paraformer_configured(self):
            return True

    def _broken_paraformer(*_args, **_kwargs):
        raise RuntimeError("Paraformer worker thoát bất thường (exit 1)")

    def _subprocess(*_args, **_kwargs):
        subprocess_calls.append("whisper")
        return [{"id": 1, "text": "x", "start": 0.0, "end": 1.0,
                 "duration": 1.0}]

    monkeypatch.setattr(paraformer_transcriber, "transcribe_paraformer",
                        _broken_paraformer)
    monkeypatch.setattr(transcriber, "_transcribe_whisper_subprocess", _subprocess)
    segments = transcriber.transcribe("audio.wav", "zh", _ParaSettings())
    assert subprocess_calls == ["whisper"]
    assert segments and segments[0]["text"] == "x"


# --------------------------------------------------------------------------
# autodub/speech/paraformer_transcriber.py
# --------------------------------------------------------------------------

class _FakePopen:
    """Tiến trình con giả: thoát giữa chừng, không in dòng 'done'."""

    def __init__(self, *args, **kwargs):
        self.returncode = 1
        self.stdout = _FakeStream([])
        self.stderr = _FakeStream([])

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pass


class _FakeStream:
    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        pass


def _write_tiny_wav(path):
    """WAV 16 kHz mono 16-bit hợp lệ để nhánh chuẩn hóa của Paraformer bị bỏ qua."""
    import wave

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)


def _paraformer_settings(tmp_path):
    from autodub.config import Settings

    settings = Settings()
    settings.asr_venv_python = "python"
    settings.paraformer_model_dir = str(tmp_path / "model")
    return settings


def test_paraformer_worker_exit_with_cancel_flag_raises_cancellation(monkeypatch, tmp_path):
    """Cờ hủy bật + worker thoát giữa chừng => PipelineCancelled, không phải RuntimeError.

    Đây là chỗ paraformer_transcriber.py:168-169 dịch "worker thoát vì bị
    Dừng giết" thành lệnh hủy thật, thay vì để nơi gọi hạ cấp thành
    "Paraformer lỗi — chuyển Whisper" rồi chạy tiếp bước dài nhất.
    """
    audio = tmp_path / "a.wav"
    _write_tiny_wav(audio)
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(paraformer_transcriber, "register_process", lambda p: None)
    monkeypatch.setattr(paraformer_transcriber, "unregister_process", lambda p: None)
    monkeypatch.setattr("autodub.media.audio.wav_duration_s", lambda p: 10.0)
    monkeypatch.setattr(paraformer_transcriber, "is_cancel_requested",
                        lambda *a, **k: True)
    with pytest.raises(PipelineCancelled):
        paraformer_transcriber.transcribe_paraformer(
            str(audio), _paraformer_settings(tmp_path))


def test_paraformer_worker_exit_without_cancel_flag_is_a_real_error(monkeypatch, tmp_path):
    """Đối chứng: không có cờ hủy thì thoát bất thường vẫn là lỗi thật."""
    audio = tmp_path / "a.wav"
    _write_tiny_wav(audio)
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(paraformer_transcriber, "register_process", lambda p: None)
    monkeypatch.setattr(paraformer_transcriber, "unregister_process", lambda p: None)
    monkeypatch.setattr("autodub.media.audio.wav_duration_s", lambda p: 10.0)
    monkeypatch.setattr(paraformer_transcriber, "is_cancel_requested",
                        lambda *a, **k: False)
    with pytest.raises(RuntimeError):
        paraformer_transcriber.transcribe_paraformer(
            str(audio), _paraformer_settings(tmp_path))


# --------------------------------------------------------------------------
# autodub/speech/align.py
# --------------------------------------------------------------------------

def _align_fixture(monkeypatch, tmp_path, n_workers):
    """Dựng 2 clip giả + model giả để align_segments chạy tới nhánh cần kiểm."""
    merge_dir = tmp_path / "merge"
    merge_dir.mkdir()
    segments = []
    for sid in (1, 2):
        wav = align.seg_wav_path(str(merge_dir), sid)
        with open(wav, "wb") as f:
            f.write(b"RIFF")
        segments.append({"id": sid, "text": "xin chào các bạn",
                         "start": float(sid), "end": float(sid) + 2.0,
                         "duration": 2.0})

    monkeypatch.setattr(align, "_load_align_model",
                        lambda: (object(), "cpu", n_workers))
    monkeypatch.setattr(align, "wav_duration_s", lambda p: 2.0, raising=False)
    monkeypatch.setattr("autodub.media.audio.wav_duration_s", lambda p: 2.0)
    return segments, str(merge_dir)


def test_align_reraises_cancellation_single_worker(monkeypatch, tmp_path):
    """n_workers=1: nhánh _one phải để lệnh hủy đi qua nguyên vẹn."""
    segments, merge_dir = _align_fixture(monkeypatch, tmp_path, n_workers=1)

    def _cancelled(model, wav):
        raise PipelineCancelled("hủy giữa lúc canh phụ đề")

    monkeypatch.setattr(align, "_asr_words", _cancelled)
    with pytest.raises(PipelineCancelled):
        align.align_segments(segments, merge_dir, "text")


def test_align_reraises_cancellation_multi_worker(monkeypatch, tmp_path):
    """n_workers>1: pool.map phát lại lệnh hủy, phải đóng pool rồi mới ném tiếp."""
    segments, merge_dir = _align_fixture(monkeypatch, tmp_path, n_workers=3)

    def _cancelled(model, wav):
        raise PipelineCancelled("hủy giữa lúc canh phụ đề")

    monkeypatch.setattr(align, "_asr_words", _cancelled)
    with pytest.raises(PipelineCancelled):
        align.align_segments(segments, merge_dir, "text")


def test_align_real_asr_failure_still_estimates(monkeypatch, tmp_path):
    """Đối chứng: lỗi ASR thật vẫn được hạ cấp thành ước lượng, không ném."""
    segments, merge_dir = _align_fixture(monkeypatch, tmp_path, n_workers=1)

    def _broken(model, wav):
        raise RuntimeError("model lỗi")

    monkeypatch.setattr(align, "_asr_words", _broken)
    result = align.align_segments(segments, merge_dir, "text")
    assert result == {}
