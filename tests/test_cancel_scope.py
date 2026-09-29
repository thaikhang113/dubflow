import sys
import threading
import time
from autodub.cancel import (
    cancel_processes,
    cancel_scope,
    clear_cancel_request,
    is_cancel_requested,
    run_registered,
)
from autodub.progress import PipelineCancelled


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
    import pytest

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

    import pytest

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
