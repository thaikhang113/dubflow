"""Demucs worker bền phải nằm trong registry huỷ (nút Dừng giết được).

Worker ``demucs_worker --serve`` sống suốt cả lô video. Trước đây nó không
ghi danh nên ``cancel_processes()`` không thấy, bấm Dừng phải chờ Demucs tách
xong video hiện tại. Ba test dưới khoá đúng hành vi đó:

1. worker ghi danh với scope hiện hành và bị giết thật khi huỷ scope đó;
2. đóng cache thì gỡ khỏi registry (không giữ handle Popen đã chết);
3. pipeline chuyền scope qua ``ThreadPoolExecutor`` — contextvar không tự
   sang luồng mới, thiếu bước này worker lại ghi danh với scope ``None``.
"""
from __future__ import annotations

import json
import sys
import time

import pytest

from autodub import cancel
from autodub.cancel import cancel_processes, cancel_scope, clear_cancel_request
from autodub.media import vocal_separator


@pytest.fixture(autouse=True)
def _clean_cancel_state():
    clear_cancel_request()
    yield
    cancel_processes()
    clear_cancel_request()


def _serve_worker_gia(tmp_path) -> str:
    """Tiến trình THẬT: chào một dòng JSON rồi sống chờ lệnh qua stdin."""
    path = tmp_path / "demucs_worker_gia.py"
    path.write_text(
        "import json, sys, time\n"
        "print(json.dumps({\"ready\": True, \"device\": \"cpu\"}), flush=True)\n"
        "for _line in sys.stdin:\n"
        "    time.sleep(30)\n",
        encoding="utf-8",
    )
    return str(path)


def _cache_voi_worker_that(tmp_path, monkeypatch) -> vocal_separator.DemucsCache:
    monkeypatch.setattr(vocal_separator, "_WORKER_SCRIPT",
                        _serve_worker_gia(tmp_path))
    monkeypatch.setattr(vocal_separator, "demucs_venv_python",
                        lambda: sys.executable)
    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: 32.0)
    return vocal_separator.DemucsCache()


def test_worker_serve_ghi_danh_va_bi_giet_khi_huy_scope(tmp_path, monkeypatch):
    cache = _cache_voi_worker_that(tmp_path, monkeypatch)
    try:
        with cancel_scope("gui"):
            assert cache._ensure() is True
        proc = cache._proc
        assert proc is not None and proc.poll() is None
        assert cancel._ACTIVE_BY_SCOPE.get(proc) == "gui", (
            "worker sống mà không có scope: nút Dừng không giết được nó")

        cancel_processes(scope="gui")

        deadline = time.monotonic() + 5.0
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert proc.poll() is not None, "huỷ scope không giết được worker"
    finally:
        cache.close()


def test_dong_cache_thi_go_khoi_registry(tmp_path, monkeypatch):
    cache = _cache_voi_worker_that(tmp_path, monkeypatch)
    with cancel_scope("gui"):
        assert cache._ensure() is True
    proc = cache._proc
    assert proc in cancel._ACTIVE

    cache.close()

    assert proc not in cancel._ACTIVE
    assert proc not in cancel._ACTIVE_BY_SCOPE


def test_pipeline_chuyen_scope_qua_luong_nen(tmp_path, monkeypatch):
    """``_resolve_background`` chạy ở luồng khác — scope phải được chép tay."""
    from autodub.config import Settings
    from autodub.pipeline import DubPipeline, DubRequest
    from autodub.worker_plan import build_worker_plan

    work = tmp_path / "video_vi"
    data = work / "data"
    data.mkdir(parents=True)
    (work / "source.mp4").write_bytes(b"source")
    (data / "original_audio.wav").write_bytes(b"audio")
    (data / "transcript_original.json").write_text(
        json.dumps([{"id": 1, "text": "hello", "start": 0.0, "end": 2.0,
                    "duration": 2.0}]),
        encoding="utf-8",
    )
    pipeline = DubPipeline(Settings(
        translate_enabled=False, hq_background=False, ocr_enabled=False,
        branding_vision_enabled=False,
    ))
    monkeypatch.setattr(pipeline, "_log_machine_info",
                        lambda _s: build_worker_plan(
                            cpu_count=2, available_ram_gb=4,
                            gpu_available=False))
    monkeypatch.setattr(pipeline, "_warm_tts_early", lambda *_a: None)
    monkeypatch.setattr(pipeline, "_get_synth", lambda *_a: None)

    seen: list[str | None] = []

    def _gia(bg_mode, bg_duck_db, audio_path, work_dir):
        seen.append(cancel.CURRENT_CANCEL_SCOPE.get())
        return None, 0.0

    monkeypatch.setattr(pipeline, "_resolve_background", _gia)
    request = DubRequest(file_path=str(work / "source.mp4"),
                         resume_dir=str(work), bg_mode="demucs",
                         source_lang="en")
    with cancel_scope("gui"):
        pipeline.run(request)

    assert seen == ["gui"], (
        "luồng nền thấy scope " + repr(seen)
        + " thay vì gui — worker Demucs sẽ không huỷ được")
