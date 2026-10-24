import os
import subprocess as sp
import sys
import threading
import time
import wave

import pytest

from autodub.cancel import (
    CURRENT_CANCEL_SCOPE,
    cancel_processes,
    cancel_scope,
    clear_cancel_request,
    is_cancel_requested,
    run_registered,
)
from autodub.progress import PipelineCancelled


@pytest.fixture(autouse=True)
def _clean_cancel_state():
    """Cờ hủy là event dùng chung cả tiến trình và không tự tắt: dọn trước và
    sau MỖI test để file này không phụ thuộc thứ tự chạy, và không để lại cờ
    hủy cho các file chạy sau."""
    clear_cancel_request()
    yield
    clear_cancel_request()


def test_scoped_cancellation_isolates_workers() -> None:
    clear_cancel_request()
    gui_result: list[BaseException | str] = []
    remote_result: list[BaseException | str] = []

    gui_started = threading.Event()
    remote_started = threading.Event()

    def run_gui() -> None:
        with cancel_scope("gui"):
            gui_started.set()
            try:
                run_registered(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    timeout=20,
                )
                gui_result.append("finished")
            except BaseException as exc:
                gui_result.append(exc)

    def run_remote() -> None:
        with cancel_scope("remote"):
            remote_started.set()
            try:
                run_registered(
                    [sys.executable, "-c", "import time; time.sleep(1)"],
                    timeout=10,
                )
                remote_result.append("finished")
            except BaseException as exc:
                remote_result.append(exc)

    t_gui = threading.Thread(target=run_gui)
    t_remote = threading.Thread(target=run_remote)

    t_gui.start()
    t_remote.start()

    assert gui_started.wait(timeout=5)
    assert remote_started.wait(timeout=5)
    time.sleep(0.2)

    # Cancel ONLY gui scope
    cancel_processes(scope="gui")

    t_gui.join(timeout=5)
    assert not t_gui.is_alive()
    assert gui_result and isinstance(gui_result[0], PipelineCancelled)

    # Remote should still be running and finish successfully
    t_remote.join(timeout=5)
    assert not t_remote.is_alive()
    assert remote_result == ["finished"]

    clear_cancel_request()
    assert not is_cancel_requested("gui")
    assert not is_cancel_requested("remote")


def test_in_process_transcription_stops_on_cancel(monkeypatch) -> None:
    """Đường Whisper in-process phải dừng khi người dùng bấm Dừng.

    Model trả về generator: chỉ khi vòng lặp rút phần tử kế tiếp thì công
    việc mới thực sự chạy, nên đây là điểm kiểm cờ hủy duy nhất.
    """


    from autodub.speech import transcriber

    consumed: list[int] = []

    class _Seg:
        def __init__(self, index: int) -> None:
            self.text = f"cau {index}"
            self.start = float(index)
            self.end = float(index) + 1.0
            self.words = []

    def _segments():
        for index in range(1, 6):
            consumed.append(index)
            # Người dùng bấm Dừng sau khi câu thứ hai đã xong.
            if index == 2:
                cancel_processes()
            yield _Seg(index)

    class _Info:
        language = "vi"
        language_probability = 1.0

    class _Model:
        def transcribe(self, *_args, **_kwargs):
            return _segments(), _Info()

    monkeypatch.setattr(transcriber, "_load_whisper_model",
                        lambda *_args, **_kwargs: (_Model(), "cpu"))
    monkeypatch.setattr(transcriber, "_release_vram", lambda: None)

    class _Settings:
        whisper_model = "medium"
        whisper_beam_size = 1

    clear_cancel_request()
    try:
        with pytest.raises(PipelineCancelled):
            transcriber._transcribe_whisper("audio.wav", "vi", _Settings())
    finally:
        clear_cancel_request()

    # Không được rút hết generator sau khi đã có lệnh hủy.
    assert consumed == [1, 2]


def test_subprocess_transcription_reports_cancel(monkeypatch) -> None:
    """Worker thoát vì bị giết phải báo 'đã hủy', không phải lỗi nhận dạng."""
    import json
    import subprocess as sp



    from autodub.speech import transcriber

    class _Stream:
        def __init__(self, lines) -> None:
            self._lines = list(lines)

        def readline(self):
            return self._lines.pop(0) if self._lines else ""

        def __iter__(self):
            return iter(self._lines)

        def close(self):
            return None

    class _Proc:
        returncode = 1

        def __init__(self) -> None:
            self.stdout = _Stream([json.dumps({"ready": True}) + "\n"])
            self.stderr = _Stream([])
            self.stdin = type("_In", (), {
                "write": staticmethod(lambda _data: None),
                "flush": staticmethod(lambda: None),
                "close": staticmethod(lambda: None),
            })()

        def wait(self, timeout=None):
            return 1

        def kill(self):
            return None

        def poll(self):
            return 1

    monkeypatch.setattr(sp, "Popen", lambda *_args, **_kwargs: _Proc())
    monkeypatch.setattr(transcriber, "register_process", lambda _p: None)
    monkeypatch.setattr(transcriber, "unregister_process", lambda _p: None)

    class _Settings:
        whisper_model = "medium"
        whisper_beam_size = 1

        @staticmethod
        def whisper_venv_python_path():
            return "python.exe"

        @staticmethod
        def whisper_model_dir_path():
            return "models"

    clear_cancel_request()
    cancel_processes()
    try:
        with pytest.raises(PipelineCancelled):
            transcriber._transcribe_whisper_subprocess("audio.wav", "vi", _Settings())
    finally:
        clear_cancel_request()


# --- Vòng 34: các pool ThreadPoolExecutor của bước audio/timing phải mang theo
# phạm vi hủy của nơi gọi, và không được coi file dở của lượt đã Dừng là xong.


def _write_wav(path: str, seconds: float, rate: int = 8000) -> None:
    """WAV im lặng thật — wav_duration_s đọc được header."""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    # Ghi hụt (đĩa đầy lúc chạy full suite) làm wav_duration_s trả None và mọi
    # test dưới đây lặng lẽ kiểm nhánh khác — báo lỗi ngay tại chỗ ghi.
    assert os.path.getsize(path) > 44, f"WAV ghi không đủ: {path}"


def _recorder(seen: list, seconds: float = 0.5):
    """Thay lệnh ffmpeg: ghi lại scope mà LUỒNG POOL nhìn thấy."""
    def fake(args, **_kwargs):
        seen.append(CURRENT_CANCEL_SCOPE.get())
        _write_wav(str(args[-1]), seconds)
        return sp.CompletedProcess(args, 0, "", "")
    return fake


def _src_dir(root, n: int, seconds: float = 0.5):
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    for i in range(1, n + 1):
        _write_wav(os.path.join(src, f"seg_{i:05d}.wav"), seconds)
    return src, [{"id": i} for i in range(1, n + 1)]


def test_slow_segments_pool_keeps_caller_scope(monkeypatch, tmp_path) -> None:
    """ThreadPoolExecutor không mang contextvar: phải chép tay.

    Thiếu nó, mọi ffmpeg của lượt atempo ghi danh với scope None và nút Dừng
    (scope 'gui') bỏ sót chúng (probe round 34: 34 tiến trình còn sống).
    """
    from autodub.media import audio

    src, segs = _src_dir(str(tmp_path), 3)
    seen: list = []
    monkeypatch.setattr(audio, "run_registered", _recorder(seen))
    dst = os.path.join(str(tmp_path), "slow")

    clear_cancel_request()
    with cancel_scope("gui"):
        out = audio.slow_segments(segs, src, dst, 1.2, max_workers=2)

    assert seen == ["gui"] * 3
    assert out == dst
    assert len(os.listdir(dst)) == 3


def test_postprocess_pool_keeps_caller_scope(monkeypatch, tmp_path) -> None:
    """Cùng lỗi, cùng cách kiểm — pool hậu kỳ giọng."""
    from autodub.media import audio

    src, segs = _src_dir(str(tmp_path), 3)
    seen: list = []

    def fake_clip(_src, dst, _lufs, speed=1.0):
        seen.append(CURRENT_CANCEL_SCOPE.get())
        _write_wav(dst, 0.5)
        return True

    monkeypatch.setattr(audio, "postprocess_voice_clip", fake_clip)
    dst = os.path.join(str(tmp_path), "clean")

    clear_cancel_request()
    with cancel_scope("gui"):
        audio.postprocess_voice_clips(segs, src, dst, max_workers=2)

    assert seen == ["gui"] * 3
    assert len(os.listdir(dst)) == 3


def test_soft_timing_pool_keeps_caller_scope(monkeypatch, tmp_path) -> None:
    """Cùng lỗi, cùng cách kiểm — lượt atempo của soft timing."""
    from autodub.media import audio, timing

    src, _ = _src_dir(str(tmp_path), 2, seconds=1.0)
    seen: list = []

    def fake_atempo(_src, dst, _speed):
        seen.append(CURRENT_CANCEL_SCOPE.get())
        _write_wav(dst, 0.9)
        return True

    class _Settings:
        timing_max_drift_s = 0.5
        timing_min_gap_s = 0.05
        timing_max_atempo = 1.1

    monkeypatch.setattr(audio, "apply_atempo", fake_atempo)
    # Thời lượng clip đọc từ header file thật: chỉ một lần ghi hụt là cả bước
    # này lặng lẽ rơi vào nhánh "mọi câu đều vừa khít", pool không chạy và test
    # mất đúng thứ nó định kiểm. Ghim số đo để lượt này chỉ còn kiểm một việc:
    # luồng pool có mang theo scope của nơi gọi hay không.
    monkeypatch.setattr(audio, "wav_duration_s", lambda _p: 1.0)
    dst = os.path.join(str(tmp_path), "slow")

    clear_cancel_request()
    with cancel_scope("gui"):
        out, rep = timing.apply_soft_timing(
            [{"id": 1, "start": 0.0, "end": 1.0, "duration": 1.0},
             {"id": 2, "start": 0.3, "end": 1.3, "duration": 1.0}],
            src, dst, _Settings(), max_workers=2)

    assert rep.segments_compressed == 1, \
        "kế hoạch không cần nén — lượt này không kiểm được scope"
    assert seen == ["gui"]
    assert os.path.exists(os.path.join(out, "seg_00001.wav"))


def test_stop_kills_pool_children_and_leaves_no_cache(monkeypatch, tmp_path) -> None:
    """Dừng giữa lượt atempo: con đang chạy bị giết, HÀNG ĐỢI phải thoát,
    và không còn file dở nào ở chỗ cache."""
    from autodub.media import audio

    src, segs = _src_dir(str(tmp_path), 4, seconds=1.0)
    calls: list = []

    def fake(args, **_kwargs):
        # Tiến trình con thật, ngủ 10 s: đúng đường ghi danh thật của repo.
        calls.append(str(args[-1]))
        result = run_registered(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            capture_output=True, text=True, timeout=60, check=False)
        _write_wav(str(args[-1]), 0.8)
        return result

    monkeypatch.setattr(audio, "run_registered", fake)
    dst = os.path.join(str(tmp_path), "slow")
    outcome: list = []

    def run_pass() -> None:
        try:
            with cancel_scope("gui"):
                audio.slow_segments(segs, src, dst, 1.2, max_workers=1)
            outcome.append("returned")
        except PipelineCancelled:
            outcome.append("cancelled")

    clear_cancel_request()
    thread = threading.Thread(target=run_pass)
    thread.start()
    time.sleep(1.0)
    cancel_processes(scope="gui")  # đúng cái nút Dừng gọi
    thread.join(timeout=5)
    clear_cancel_request()

    assert not thread.is_alive(), "lượt atempo vẫn chạy sau khi Dừng"
    assert outcome == ["cancelled"]
    # Chỉ câu đang chạy dở mới được spawn; câu còn trong hàng đợi phải thoát.
    assert len(calls) == 1
    assert os.listdir(dst) == []


def test_halfwritten_clip_is_not_reused(monkeypatch, tmp_path) -> None:
    """Clip dở của lượt bị Dừng có mtime mới hơn nguồn nhưng thiếu dữ liệu."""
    from autodub.media import audio

    src, _ = _src_dir(str(tmp_path), 1, seconds=1.0)
    dst = os.path.join(str(tmp_path), "slow")
    os.makedirs(dst)
    raw = open(os.path.join(src, "seg_00001.wav"), "rb").read()
    keep = 44 + int((len(raw) - 44) * 0.3)
    partial = os.path.join(dst, "seg_00001.wav")
    with open(partial, "wb") as fh:
        fh.write(raw[:keep])
    os.utime(partial, (time.time() + 5, time.time() + 5))  # mới hơn nguồn

    seen: list = []
    monkeypatch.setattr(audio, "run_registered", _recorder(seen, seconds=0.8))

    clear_cancel_request()
    audio.slow_segments([{"id": 1}], src, dst, 1.2, max_workers=1)

    assert len(seen) == 1, "ffmpeg không chạy lại cho clip thiếu dữ liệu"
    assert os.path.getsize(partial) > keep


def test_align_stops_at_once_when_cancel_is_set(monkeypatch, tmp_path) -> None:
    """Dừng TRƯỚC lượt canh phụ đề: không nghe thêm clip nào, không ghi cache."""


    from autodub.speech import align

    merge = os.path.join(str(tmp_path), "merge")
    os.makedirs(merge)
    _write_wav(os.path.join(merge, "seg_00001.wav"), 1.0)
    cache_path = os.path.join(str(tmp_path), "align_cache.json")
    asr_calls: list = []

    monkeypatch.setattr(align, "_load_align_model",
                        lambda: (object(), "cpu", 1))
    monkeypatch.setattr(align, "_asr_words",
                        lambda _model, wav: asr_calls.append(wav) or [])

    clear_cancel_request()
    cancel_processes(scope="gui")
    try:
        with pytest.raises(PipelineCancelled):
            with cancel_scope("gui"):
                align.align_segments(
                    [{"id": 1, "text": "xin chào", "start": 0.0, "end": 1.0}],
                    merge, "text", cache_path)
    finally:
        clear_cancel_request()

    assert asr_calls == []
    assert not os.path.exists(cache_path)


def test_align_pool_threads_see_the_caller_scope(monkeypatch, tmp_path) -> None:
    """Luồng pool của bước canh phụ đề cũng không mang contextvar.

    Dừng theo scope 'gui' phải tới được các luồng đang nghe clip — không thì
    pool nghe hết cả video rồi mới xuất.
    """


    from autodub.speech import align

    merge = os.path.join(str(tmp_path), "merge")
    os.makedirs(merge)
    segs = []
    for i in range(1, 5):
        _write_wav(os.path.join(merge, f"seg_{i:05d}.wav"), 1.0)
        segs.append({"id": i, "text": "xin chào",
                     "start": float(i - 1), "end": float(i)})
    cache_path = os.path.join(str(tmp_path), "align_cache.json")
    asr_calls: list = []

    def fake_asr(_model, wav):
        asr_calls.append(wav)
        if len(asr_calls) == 1:
            cancel_processes(scope="gui")  # người dùng bấm Dừng ngay sau câu 1
        time.sleep(0.05)
        return [("xin", 0.1, 0.4), ("chào", 0.5, 0.9)]

    monkeypatch.setattr(align, "_load_align_model",
                        lambda: (object(), "cpu", 2))
    monkeypatch.setattr(align, "_asr_words", fake_asr)

    clear_cancel_request()
    try:
        with pytest.raises(PipelineCancelled):
            with cancel_scope("gui"):
                align.align_segments(segs, merge, "text", cache_path)
    finally:
        clear_cancel_request()

    assert len(asr_calls) <= 2, "luồng pool vẫn nghe tiếp sau khi Dừng"
    assert not os.path.exists(cache_path)


def test_align_does_not_cache_a_cancelled_pass(monkeypatch, tmp_path) -> None:
    """Dừng đến giữa lượt: ném hủy và ĐỪNG ghi cache của lượt bỏ dở."""


    from autodub.speech import align

    merge = os.path.join(str(tmp_path), "merge")
    os.makedirs(merge)
    _write_wav(os.path.join(merge, "seg_00001.wav"), 1.0)
    cache_path = os.path.join(str(tmp_path), "align_cache.json")

    def fake_asr(_model, _wav):
        # Người dùng bấm Dừng sau khi câu này đã nghe xong.
        cancel_processes(scope="gui")
        return [("xin", 0.1, 0.4), ("chào", 0.5, 0.9)]

    monkeypatch.setattr(align, "_load_align_model",
                        lambda: (object(), "cpu", 1))
    monkeypatch.setattr(align, "_asr_words", fake_asr)

    clear_cancel_request()
    try:
        with pytest.raises(PipelineCancelled):
            with cancel_scope("gui"):
                align.align_segments(
                    [{"id": 1, "text": "xin chào", "start": 0.0, "end": 1.0}],
                    merge, "text", cache_path)
    finally:
        clear_cancel_request()

    assert not os.path.exists(cache_path)
