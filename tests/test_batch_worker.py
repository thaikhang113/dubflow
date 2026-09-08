"""Kiểm tra BatchWorker — đường chạy batch mà người dùng thật bấm trên GUI.

Trước đây lớp này không có test nào: unit test batch gọi `run_batch` trực tiếp
với pipeline giả, còn nhánh GUI tự dựng `DubPipeline` với bộ nhớ đệm riêng
(SynthCache / DemucsCache / WhisperCache) rồi phải đóng chúng lại. Chính chỗ nối
đó đã từng thiếu — GUI quên giữ worker Demucs nên nạp lại model mỗi video.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6.QtWidgets")

from autodub.batch import BatchItem  # noqa: E402
from autodub.config import Settings  # noqa: E402
from autodub.pipeline import DubRequest  # noqa: E402
from autodub.progress import PipelineCancelled  # noqa: E402


class FakeCache:
    """Vật thay cho SynthCache / DemucsCache / WhisperCache, có close() như thật."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


@pytest.fixture()
def caches(monkeypatch):
    """Chèn cache giả vào đúng chỗ `BatchWorker.run` tham chiếu cục bộ."""
    import autodub.media.vocal_separator as vs
    import autodub.speech.transcriber as tr
    import autodub.speech.tts as tts

    made = {"synth": FakeCache("synth"), "demucs": FakeCache("demucs"),
            "whisper": FakeCache("whisper")}
    monkeypatch.setattr(vs, "DemucsCache", lambda: made["demucs"])
    monkeypatch.setattr(tr, "WhisperCache", lambda: made["whisper"])
    monkeypatch.setattr(tts, "SynthCache", lambda: made["synth"])
    # Khong cho tai truoc qua mang trong test
    monkeypatch.setattr("autodub.batch._Prefetcher.take",
                        lambda self, i, **kw: None)
    return made


@pytest.fixture()
def fake_pipeline(monkeypatch):
    """Thay DubPipeline mà `workers` đã nhập khẩu, ghi lại cách nó được nối."""
    import autodub_gui.workers as workers

    seen: dict = {"ctor": None, "runs": [], "raise": None, "result": None}

    class Pipeline:
        last_work_dir = ""

        def __init__(self, settings, progress=None, cancel_event=None,
                     synth_cache=None, demucs_cache=None, whisper_cache=None):
                seen["ctor"] = {"synth_cache": synth_cache,
                                "demucs_cache": demucs_cache,
                                "whisper_cache": whisper_cache,
                                "cancel_event": cancel_event,
                                "progress": progress}

        def run(self, req):
            seen["runs"].append(req)
            if seen["raise"] is not None:
                raise seen["raise"]
            override = seen.get("override")
            if override is not None:
                return override(req, seen)
            return seen["result"]

    monkeypatch.setattr(workers, "DubPipeline", Pipeline)
    return seen


def _completed(tmp_path: object) -> object:
    """DubResult gia nhưng vừa đủ để validate_batch_report chấp nhận."""
    video = tmp_path / "dubbed_video.mp4"
    video.write_bytes(b"video")
    audio = tmp_path / "audio_vi_full.wav"
    audio.write_bytes(b"audio")
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    report = {"output_dir": str(tmp_path), "total_segments": 2,
              "total_original_duration": 4.0, "total_tts_duration": 4.1,
              "processing_time_seconds": 0.5,
              "files": {"dubbed_video": str(video), "dub_audio": str(audio)}}
    (data / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return type("Res", (), {"status": "completed", "work_dir": str(tmp_path),
                            "report": report})()


def _worker(items, tmp_path, reuse_tts=True):
    from autodub_gui.workers import BatchWorker

    settings = Settings(output_dir=str(tmp_path))
    template = DubRequest(source_lang="vi", voice="Truc Ly", bg_mode="none",
                          skip_video=True, subtitle_mode="none",
                          output_dir=str(tmp_path))
    return BatchWorker(settings, template, items, reuse_tts=reuse_tts)


def _file(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"x")
    return str(path)


def test_one_video_does_not_wire_cross_video_caches(fake_pipeline, caches,
                                                   tmp_path):
    fake_pipeline["result"] = _completed(tmp_path)
    worker = _worker([BatchItem(file_path=_file(tmp_path, "a.mp4"))], tmp_path)
    done = []
    worker.finished_ok.connect(lambda s: done.append(s))
    worker.run()

    ctor = fake_pipeline["ctor"]
    assert ctor["synth_cache"] is caches["synth"]
    assert ctor["demucs_cache"] is None
    assert ctor["whisper_cache"] is None
    assert done and done[0].success == 1
    assert caches["synth"].closed == 1, "phai dong bo nho dem o finally"


def test_two_videos_wire_all_three_caches(fake_pipeline, caches, tmp_path):
    fake_pipeline["result"] = _completed(tmp_path)
    items = [BatchItem(file_path=_file(tmp_path, "a.mp4")),
             BatchItem(file_path=_file(tmp_path, "b.mp4"))]
    worker = _worker(items, tmp_path)
    done = []
    worker.finished_ok.connect(lambda s: done.append(s))
    worker.run()

    ctor = fake_pipeline["ctor"]
    assert ctor["synth_cache"] is caches["synth"]
    assert ctor["demucs_cache"] is caches["demucs"]
    assert ctor["whisper_cache"] is caches["whisper"]
    assert done and done[0].success == 2
    assert len(fake_pipeline["runs"]) == 2
    assert all(c.closed == 1 for c in caches.values())


def test_reuse_tts_off_leaves_synth_cache_none(fake_pipeline, caches, tmp_path):
    fake_pipeline["result"] = _completed(tmp_path)
    worker = _worker([BatchItem(file_path=_file(tmp_path, "a.mp4"))], tmp_path,
                     reuse_tts=False)
    worker.run()
    assert fake_pipeline["ctor"]["synth_cache"] is None
    assert caches["synth"].closed == 0


def test_cancel_reports_cancelled_not_failed(fake_pipeline, caches, tmp_path):
    fake_pipeline["raise"] = PipelineCancelled("ng\u01b0\u1eddi d\u00f9ng b\u1ea5m d\u1eebng")
    worker = _worker([BatchItem(file_path=_file(tmp_path, "a.mp4"))], tmp_path)
    got = {"cancelled": [], "failed": []}
    worker.cancelled.connect(lambda: got["cancelled"].append(True))
    worker.failed.connect(lambda m: got["failed"].append(m))
    worker.run()

    assert got["cancelled"], "PipelineCancelled phai phat cancelled"
    assert not got["failed"], "dung giua chung khong bi tinh la loi"
    assert caches["synth"].closed == 1


def test_per_video_error_is_a_failed_row_not_a_crashed_worker(
        fake_pipeline, caches, tmp_path):
    """Lỗi ở một video được ghi vào dòng đó, lượt batch vẫn kết thúc bình thường.

    Người dùng phải thấy "Lỗi" trên bảng và đọc được lý do, không phải một hộp
    thoại báo riêng "không chạy được danh sách" khi chỉ một video trở lại.
    """
    fake_pipeline["raise"] = RuntimeError("het bong den")
    worker = _worker([BatchItem(file_path=_file(tmp_path, "a.mp4"))], tmp_path)
    got = {"failed": [], "cancelled": [], "ok": [], "statuses": []}
    worker.failed.connect(lambda m: got["failed"].append(m))
    worker.cancelled.connect(lambda: got["cancelled"].append(True))
    worker.finished_ok.connect(lambda s: got["ok"].append(s))
    worker.item_status.connect(lambda i, total, key, status, detail:
                               got["statuses"].append((status, detail)))
    worker.run()

    assert not got["failed"] and not got["cancelled"]
    assert got["ok"] and got["ok"][0].failed == 1
    assert got["statuses"][0][0] == "start"
    assert got["statuses"][-1][0] == "failed"
    assert "het bong den" in got["statuses"][-1][1]


def test_per_line_voice_and_template_reach_pipeline(fake_pipeline, caches,
                                                    tmp_path):
    fake_pipeline["result"] = _completed(tmp_path)
    items = [BatchItem(file_path=_file(tmp_path, "a.mp4"), voice="Phamuyen"),
             BatchItem(file_path=_file(tmp_path, "b.mp4"))]
    worker = _worker(items, tmp_path)
    worker.run()

    voices = [r.voice for r in fake_pipeline["runs"]]
    assert voices == ["Phamuyen", "Truc Ly"], \
        "dong khong ghi giong phai nhan giong cua template"
    assert all(r.source_lang == "vi" for r in fake_pipeline["runs"])
    assert all(r.skip_video is True for r in fake_pipeline["runs"])


def test_progress_events_reach_the_gui_signal(fake_pipeline, caches, tmp_path):
    """Đường tiến độ phải tới được signal để ô "Đang xử lý" sáng theo dòng."""
    from autodub.progress import ProgressEvent

    result = _completed(tmp_path)

    def emit_then_finish(req, seen):
        seen["ctor"]["progress"](ProgressEvent("asr", "start"))
        seen["ctor"]["progress"](ProgressEvent("asr", "done",
                                               current=3, total=3))
        return result

    fake_pipeline["override"] = emit_then_finish
    worker = _worker([BatchItem(file_path=_file(tmp_path, "a.mp4"))], tmp_path)

    events: list[tuple[str, str]] = []
    worker.progress.connect(lambda e: events.append((e.step, e.status)))
    statuses = []
    worker.item_status.connect(lambda i, total, key, status, detail:
                               statuses.append(status))
    worker.run()

    assert events == [("asr", "start"), ("asr", "done")]
    assert statuses == ["start", "success"], "dòng batch phải bắt được trạng thái"
