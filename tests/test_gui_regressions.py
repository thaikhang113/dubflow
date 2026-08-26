from __future__ import annotations

import ast
import inspect
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from autodub.cancel import (
    cancel_processes,
    clear_cancel_request,
    run_registered,
)
from autodub.progress import PipelineCancelled
from autodub_gui import tokens
from autodub_gui.ui.modal import ConfirmDialog
from autodub_gui.pages.batch_page import batch_finish_detail, batch_finish_ok
from autodub_gui.pages.batch_page import parse_batch_list_text
from autodub_gui.pages.download_page import (
    download_finish_detail, download_finish_ok,
)


ROOT = Path(__file__).parents[1]

def test_batch_summary_is_not_success_when_failed_or_pending() -> None:
    summary = type("Summary", (), {
        "success": 2, "total": 3, "failed": 1, "pending": 0, "skipped": 0,
    })()
    assert batch_finish_ok(summary) is False
    assert "1 lỗi" in batch_finish_detail(summary)

    summary.pending = 1
    summary.failed = 0
    assert batch_finish_ok(summary) is False
    assert "1 chờ dịch" in batch_finish_detail(summary)

def test_download_summary_is_not_success_when_any_link_failed() -> None:
    assert download_finish_ok(2, 0) is True
    assert download_finish_ok(1, 1) is False
    assert "1 liên kết lỗi" in download_finish_detail(1, 1)

def test_batch_file_import_preserves_voice_overrides() -> None:
    items = parse_batch_list_text(
        "https://example.com/a | Trúc Ly\n# ghi chú\nhttps://example.com/b"
    )
    assert [(item.url, item.voice) for item in items] == [
        ("https://example.com/a", "Trúc Ly"),
        ("https://example.com/b", None),
    ]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_translation_model_updates_labeled_line_edit_through_public_api() -> None:
    source = _source("autodub_gui/pages/translate_tool_page.py")
    assert "widget.setText(model)" not in source
    assert "widget.set_text(model)" in source


def test_header_exposes_manual_update_check() -> None:
    source = _source("autodub_gui/app.py")
    assert "Kiểm tra cập nhật" in source
    assert "def _on_update_check_finished" in source
    assert "_check_updates(manual=True)" in source


def test_smoke_report_checks_all_external_workers() -> None:
    source = _source("autodub_gui/app.py")
    assert "autodub.speech.tts.vieneu_vi" in source
    assert "autodub.media.vocal_separator" in source
    assert "asr_whisper_worker.py" in source
    assert "asr_paraformer_worker.py" in source

def test_ocr_refresh_queues_latest_editor_change() -> None:
    source = _source("autodub_gui/pages/editor_export.py")
    assert "self._ocr_refresh_pending = (" in source
    assert "settings, bool(enabled), float(y_min), source_logo_auto" in source
    assert "self._on_ocr_refresh_finished()" in source
    assert "self._start_ocr_refresh(*pending)" in source

def test_download_page_scrolls_full_results_area() -> None:
    source = _source("autodub_gui/pages/download_page.py")
    assert "QScrollArea" in source
    assert "self.table.setMinimumHeight(320)" in source


def test_zero_argument_changed_signals_discard_payload() -> None:
    for path in (
        "autodub_gui/pages/editor_panels.py",
        "autodub_gui/pages/new_project_steps.py",
    ):
        source = _source(path)
        assert ".changed.connect(self.changed.emit)" not in source


def test_cancel_path_uses_killable_subprocess_runner() -> None:
    source = _source("autodub_gui/workers.py")
    assert "cancel_processes" in source
    assert "self._cancel_event.set()" in source
    assert "run_registered" in source


def test_cancel_processes_stops_registered_child() -> None:
    clear_cancel_request()
    result: list[BaseException] = []

    def run() -> None:
        try:
            run_registered(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except BaseException as exc:
            result.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.2)
    cancel_processes()
    thread.join(5)
    clear_cancel_request()

    assert not thread.is_alive()
    assert result and isinstance(result[0], PipelineCancelled)


def test_download_worker_cancel_interrupts_retry_backoff(monkeypatch, tmp_path) -> None:
    from autodub_gui.workers import DownloadWorker

    calls: list[str] = []

    def fail_transient(*_args, **_kwargs):
        calls.append("download")
        raise RuntimeError("HTTP 503")

    monkeypatch.setattr("autodub.media.downloader.download_one", fail_transient)
    worker = DownloadWorker(["https://example.com/video"], str(tmp_path))

    thread = threading.Thread(target=worker.run)
    thread.start()
    deadline = time.monotonic() + 2
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.cancel()
    thread.join(1)

    assert not thread.is_alive()
    assert calls == ["download"]

def test_prefetch_worker_forwards_download_progress(monkeypatch, tmp_path) -> None:
    from autodub_gui.workers import PrefetchWorker

    received = []

    def fake_download(_url, _output_dir, **kwargs):
        kwargs["progress"]({
            "status": "downloading",
            "downloaded_bytes": 25,
            "total_bytes": 100,
            "speed_bytes_s": 10.0,
            "eta_s": 8,
            "percent": 25,
        })
        path = tmp_path / "video.mp4"
        path.write_bytes(b"video")
        return str(path)

    monkeypatch.setattr("autodub.media.downloader.download_video", fake_download)
    worker = PrefetchWorker("https://example.com/video", str(tmp_path))
    worker.progress.connect(received.append)

    worker.run()

    assert received == [{
        "status": "downloading",
        "downloaded_bytes": 25,
        "total_bytes": 100,
        "speed_bytes_s": 10.0,
        "eta_s": 8,
        "percent": 25,
    }]


def test_prefetch_worker_passes_cancel_event_to_downloader(monkeypatch, tmp_path) -> None:
    from autodub_gui.workers import PrefetchWorker

    received = {}

    def fake_download(_url, _output_dir, **kwargs):
        received["cancel_event"] = kwargs["cancel_event"]
        return str(tmp_path / "video.mp4")

    monkeypatch.setattr("autodub.media.downloader.download_video", fake_download)
    worker = PrefetchWorker("https://example.com/video", str(tmp_path))

    worker.cancel()
    worker.run()

    assert received["cancel_event"].is_set()


def test_prefetch_worker_does_not_emit_success_after_cancel(monkeypatch, tmp_path) -> None:
    from autodub_gui.workers import PrefetchWorker

    finished = []

    def fake_download(_url, _output_dir, **kwargs):
        kwargs["cancel_event"].set()
        return str(tmp_path / "video.mp4")

    monkeypatch.setattr("autodub.media.downloader.download_video", fake_download)
    worker = PrefetchWorker("https://example.com/video", str(tmp_path))
    worker.finished_ok.connect(finished.append)

    worker.run()

    assert finished == []


def test_video_step_shows_and_clears_download_progress(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from autodub_gui.pages.new_project_steps import VideoStep

    app = QApplication.instance() or QApplication([])
    step = VideoStep()

    step.set_download_progress({
        "status": "downloading",
        "downloaded_bytes": 25,
        "total_bytes": 100,
        "speed_bytes_s": 10.0,
        "eta_s": 8,
        "percent": 25,
    })

    assert not step.download_progress.isHidden()
    assert step.download_progress.value() == 25
    assert "25%" in step.download_progress_label.text()

    step.clear_download_progress()

    assert step.download_progress.isHidden()
    assert step.download_progress_label.text() == ""
    step.deleteLater()
    app.processEvents()


def test_error_modal_supports_recovery_actions() -> None:
    params = inspect.signature(ConfirmDialog.show_error).parameters

    assert "on_retry" in params
    assert "on_open_log" in params


def test_muted_text_has_readable_dark_theme_contrast() -> None:
    def channel(value: str) -> float:
        raw = int(value, 16) / 255
        return raw / 12.92 if raw <= 0.04045 else ((raw + 0.055) / 1.055) ** 2.4

    def luminance(color: str) -> float:
        value = color.lstrip("#")
        return (
            0.2126 * channel(value[0:2])
            + 0.7152 * channel(value[2:4])
            + 0.0722 * channel(value[4:6])
        )

    light = luminance(tokens.TEXT_MUTED)
    dark = luminance(tokens.BG_PANEL)
    ratio = (light + 0.05) / (dark + 0.05)

    assert ratio >= 4.5


def test_stop_buttons_keep_pending_state_until_worker_finishes() -> None:
    for path in (
        "autodub_gui/pages/download_page.py",
        "autodub_gui/pages/batch_page.py",
        "autodub_gui/pages/new_project_page.py",
    ):
        source = _source(path)
        assert 'setText("Đang dừng…")' in source
        assert 'setText("Dừng")' in source
        assert "finished.connect" in source


def test_help_page_exposes_system_doctor_and_repair_actions() -> None:
    source = _source("autodub_gui/pages/help_page.py")
    worker_source = _source("autodub_gui/workers_setup.py")

    assert "self._build_doctor()" in source
    assert "Kiểm tra hệ thống" in source
    assert "Tải lại" in source
    assert "DoctorWorker" in worker_source
    assert "run_doctor" in worker_source


def test_no_arg_changed_signals_use_no_arg_forwarders() -> None:
    new_project = _source("autodub_gui/pages/new_project_steps.py")
    assert "widget.changed.connect(lambda _value: self.changed.emit())" not in new_project
    assert "self.style.changed.connect(lambda _value: self.changed.emit())" not in new_project
    assert "self.picker.changed.connect(lambda _value: self.changed.emit())" not in new_project
    assert "self.mode.changed.connect(lambda _value: self.changed.emit())" not in new_project
    assert "self.preset.changed.connect(lambda _value: self.changed.emit())" not in new_project

    editor = _source("autodub_gui/pages/editor_panels.py")
    assert "self.mode.changed.connect(lambda _value: self.changed.emit())" not in editor
    assert "self.subtitle.changed.connect(lambda _value: self.changed.emit())" not in editor
    assert "self.preset.changed.connect(lambda _value: self.changed.emit())" not in editor

def test_new_project_runs_from_export_step() -> None:
    source = _source("autodub_gui/pages/new_project_page.py")
    assert "_RUN_INDEX = 5" in source
    assert "if index == _RUN_INDEX:\n            self._start()" in source

def test_new_project_keeps_detailed_settings_across_six_steps() -> None:
    steps = _source("autodub_gui/pages/new_project_steps.py")
    page = _source("autodub_gui/pages/new_project_page.py")
    for field in (
        "ocr_enabled", "ocr_device", "logo_path", "intro_path",
        "asr_threads", "beam_size", "translate_domain",
        "translate_context", "clone_voice", "video_speed",
        "soft_timing", "subtitle_mode", "audio_only",
    ):
        assert field in steps
    assert '"output_dir"' in page

def test_new_project_has_six_owned_pipeline_stages() -> None:
    steps = _source("autodub_gui/pages/new_project_steps.py")
    state = _source("autodub/pipeline_state.py")
    for label in ("Chuẩn bị", "Nhận dạng", "Dịch thuật",
                  "Giọng đọc", "Ghép tiếng", "Xuất video"):
        assert label in steps
    for group in ("prepare", "recognition", "translation",
                  "voice", "merge", "export"):
        assert f'"{group}"' in state
    groups_block = state.split("STEP_SETTING_GROUPS", 1)[1].split("}", 1)[0]
    assert '"audio":' not in groups_block
    assert '"parallel"' in groups_block
    assert '"karaoke"' in groups_block

def test_new_project_draft_persists_custom_style_and_blur_regions() -> None:
    source = _source("autodub_gui/pages/new_project_page.py")
    assert 'data["subtitle_style_custom"] = self._subtitle_style' in source
    assert 'data["blur_regions"] = self._blur_regions' in source
    assert 'self._subtitle_style = (' in source
    assert 'self._blur_regions = (' in source

def test_subtitle_editor_is_available_during_translation_step() -> None:
    steps = _source("autodub_gui/pages/new_project_steps.py")
    page = _source("autodub_gui/pages/new_project_page.py")
    translate_block = steps[steps.index("class TranslateStep"):steps.index("class VoiceStep")]
    assert "style_requested = Signal()" in translate_block
    assert "Tùy chỉnh phụ đề và vùng che" in translate_block
    assert "self.step_translate.style_requested.connect(self._open_style_dialog)" in page

def test_style_summary_uses_instance_style_after_summary_refactor() -> None:
    source = _source("autodub_gui/pages/new_project_page.py")
    start = source.index("    def _update_style_summary")
    end = source.index("    def _current_video_path", start)
    block = source[start:end]
    assert "self._subtitle_style" in block
    assert "if style and" not in block

def test_new_project_refreshes_next_button_after_step_navigation() -> None:
    source = _source("autodub_gui/pages/new_project_page.py")
    assert "self.btn_next.setEnabled(True)" in source
    assert "prefetch_running = (" in source
    assert "self._prefetch_worker.isRunning()" in source
    assert "prefetch_ready = bool(" in source
    assert "os.path.isfile(self._prefetched_path)" in source


def test_new_project_keeps_download_button_locked_while_prefetch_runs(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from autodub.config import Settings
    import autodub_gui.pages.new_project_page as page_module

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        page_module, "cache_dir", lambda: str(tmp_path / "cache"))
    page = page_module.NewProjectPage(lambda: Settings())

    class RunningWorker:
        def isRunning(self):
            return True

    page._prefetch_worker = RunningWorker()
    page.btn_next.setEnabled(True)
    page.btn_next.setText("Tiếp tục")
    page._refresh_footer()

    assert not page.btn_next.isEnabled()
    assert page.btn_next.text() == "Đang tải…"
    page.deleteLater()
    app.processEvents()


def test_new_project_keeps_pipeline_controls_in_ui_and_runtime() -> None:
    steps = _source("autodub_gui/pages/new_project_steps.py")
    page = _source("autodub_gui/pages/new_project_page.py")
    request = _source("autodub/pipeline.py")
    for field in (
        "ocr_enabled", "ocr_device", "ocr_min_confidence",
        "ocr_max_region_area", "ocr_subtitle_y_min", "ocr_sample_interval",
        "subtitle_mode", "subtitle_preset", "subtitle_style_custom",
        "blur_regions", "clone_voice", "clone_source",
        "clone_reference_audio", "skip_video", "video_speed",
        "soft_timing_fit", "timing_max_drift_s", "timing_min_gap_s",
        "timing_max_atempo", "voice_postprocess", "voice_target_lufs",
        "bg_duck_voice_db", "logo_path", "intro_path", "outro_path",
        "logo_region", "logo_opacity", "logo_scale", "vision_enabled",
    ):
        assert field in steps or field in page
    for field in (
        "ocr_enabled", "subtitle_mode", "subtitle_style", "blur_regions",
        "clone_voice", "skip_video", "mirror", "logo_path", "intro_path",
        "outro_path", "logo_region", "logo_opacity", "logo_scale",
        "vision_enabled",
    ):
        assert field in request
    for field in (
        '"ocr_enabled": bool(data["ocr_enabled"])',
        '"ocr_device": data["ocr_device"]',
        '"ocr_min_confidence": data["ocr_min_confidence"]',
        '"ocr_max_region_area": data["ocr_max_region_area"]',
        '"ocr_subtitle_y_min": data["ocr_subtitle_y_min"]',
        '"ocr_sample_interval": data["ocr_sample_interval"]',
        '"video_speed": data["video_speed"]',
        '"soft_timing_fit": bool(data["soft_timing_fit"])',
        '"timing_max_drift_s": data["timing_max_drift_s"]',
        '"timing_min_gap_s": data["timing_min_gap_s"]',
        '"timing_max_atempo": data["timing_max_atempo"]',
        '"voice_postprocess": bool(data["voice_postprocess"])',
        '"voice_target_lufs": data["voice_target_lufs"]',
        '"bg_duck_voice_db": data["bg_duck_voice_db"]',
    ):
        assert field in page

def test_clone_limits_validate_for_video_and_file_sources() -> None:
    source = _source("autodub_gui/pages/new_project_steps.py")
    start = source.index("def _clone_is_complete")
    end = source.index("    @staticmethod", start)
    block = source[start:end]
    assert block.index("clone_min_seconds") < block.index(
        'if self.clone_source.current_key() != "file"')

def test_new_project_validates_all_steps_before_starting_from_export() -> None:
    source = _source("autodub_gui/pages/new_project_page.py")
    start = source.index("    def _start(self) -> None:")
    end = source.index("    def _resume_after_translation", start)
    block = source[start:end]
    assert "for index, step in enumerate(self._steps):" in block
    assert "step.is_complete()" in block
    assert "self._go_to_step(index)" in block

def test_new_project_persists_clone_subtitle_and_output_choices() -> None:
    source = _source("autodub_gui/pages/new_project_page.py")
    start = source.index("        changes = {", source.index("def _run_settings"))
    end = source.index("        if merged !=", start)
    block = source[start:end]
    for field in (
        '"vieneu_clone_enabled": bool(data["clone_voice"])',
        '"vieneu_clone_source": data["clone_source"]',
        '"vieneu_clone_reference_audio": data["clone_reference_audio"]',
        '"subtitle_mode": data["subtitle_mode"]',
        '"subtitle_preset": data["subtitle_preset"]',
        '"output_dir": data["output_dir"]',
        '"auto_clean_intermediates": bool(data["auto_clean_intermediates"])',
    ):
        assert field in block

def test_new_project_runtime_round_trips_detailed_six_step_values(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from autodub.config import Settings
    import autodub_gui.pages.new_project_page as page_module

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        page_module, "cache_dir", lambda: str(tmp_path / "cache"))
    settings = Settings()
    page = page_module.NewProjectPage(lambda: settings)
    page.step_video.url.set_text("https://example.com/video")
    page.step_video.ocr_enabled.setChecked(False)
    page.step_video.logo_region.set_text(
        '{"x":0.8,"y":0.05,"w":0.18,"h":0.12}')
    page.step_recognize.asr_threads.set_value(7)
    page.step_recognize.beam_size.set_value(3)
    page.step_translate.video_title.set_text("Test title")
    page.step_translate.batch_size.set_value(9)
    page.step_voice.clone_voice.setChecked(True)
    page.step_voice.clone_min_seconds.set_value(2.0)
    page.step_voice.clone_max_seconds.set_value(6.0)
    page.step_run.parallel_workers.set_value(5)
    page.step_run.soft_timing.setChecked(False)
    page.step_summary.output_dir.set_text(str(tmp_path / "output"))
    page.step_summary.subtitle_mode.set_key("burn")

    values = page.values()
    assert values["ocr_enabled"] is False
    assert values["asr_threads"] == 7
    assert values["beam_size"] == 3
    assert values["translate_video_title"] == "Test title"
    assert values["translate_batch_size"] == 9
    assert values["clone_voice"] is True
    assert values["clone_min_seconds"] == 2.0
    assert values["clone_max_seconds"] == 6.0
    assert values["parallel_workers"] == 5
    assert values["soft_timing_fit"] is False
    assert values["subtitle_mode"] == "burn"

    page._persist_pricing_choices = lambda *_args: None
    updated = page._run_settings()
    assert updated.ocr_enabled is False
    assert updated.asr_num_threads == 7
    assert updated.whisper_beam_size == 3
    assert updated.translate_video_title == "Test title"
    assert updated.translate_batch_size == 9
    assert updated.vieneu_clone_enabled is True
    assert updated.vieneu_clone_min_seconds == 2.0
    assert updated.vieneu_clone_max_seconds == 6.0
    assert updated.parallel_workers == 5
    assert updated.soft_timing_fit is False
    assert updated.subtitle_mode == "burn"
    assert updated.output_dir == str(tmp_path / "output")

    page.deleteLater()
    app.processEvents()

def test_style_canvas_round_trips_source_logo_region(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from autodub_gui.style_dialog import _FrameCanvas

    app = QApplication.instance() or QApplication([])
    canvas = _FrameCanvas(QPixmap(160, 90), {}, allow_regions=True)
    canvas.resize(160, 90)
    regions = [
        {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.1},
        {"x": 0.7, "y": 0.05, "w": 0.2, "h": 0.1, "source": "logo"},
    ]

    canvas.set_rects_from_normalized(regions)
    restored = canvas.normalized_regions()

    assert len(canvas._rects) == 1
    assert restored[0] == regions[0]
    assert restored[1]["source"] == "logo"
    for key in ("x", "y", "w", "h"):
        assert restored[1][key] == pytest.approx(regions[1][key], abs=0.01)
    canvas.deleteLater()
    app.processEvents()

def test_style_canvas_clear_last_removes_last_manual_region(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from autodub_gui.style_dialog import _FrameCanvas

    app = QApplication.instance() or QApplication([])
    canvas = _FrameCanvas(QPixmap(160, 90), {}, allow_regions=True)
    canvas.resize(160, 90)
    canvas.set_rects_from_normalized([
        {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.1},
        {"x": 0.7, "y": 0.05, "w": 0.2, "h": 0.1, "source": "logo"},
    ])

    canvas.clear_last()

    assert canvas.normalized_regions() == [
        {"x": pytest.approx(0.7, abs=0.01),
         "y": pytest.approx(0.05, abs=0.01),
         "w": pytest.approx(0.2, abs=0.01),
         "h": pytest.approx(0.1, abs=0.01),
         "source": "logo"}
    ]
    canvas.deleteLater()
    app.processEvents()

def test_style_canvas_clear_last_prefers_manual_region_over_source_logo(
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from autodub_gui.style_dialog import _FrameCanvas

    app = QApplication.instance() or QApplication([])
    canvas = _FrameCanvas(QPixmap(160, 90), {}, allow_regions=True)
    canvas.resize(160, 90)
    canvas.set_rects_from_normalized([
        {"x": 0.7, "y": 0.05, "w": 0.2, "h": 0.1, "source": "logo"},
        {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.1},
    ])

    canvas.clear_last()

    assert len(canvas._rects) == 0
    assert not canvas._source_logo_rect.isNull()
    canvas.deleteLater()
    app.processEvents()

def test_ocr_refresh_worker_updates_regions_off_editor_core(monkeypatch, tmp_path):
    from autodub.config import Settings
    from autodub_gui.workers import OCRRefreshWorker

    expected = [{"x": 0.2, "y": 0.75, "w": 0.3, "h": 0.1, "source": "ocr"}]
    monkeypatch.setattr(
        "autodub.editor.load_work_dir",
        lambda _work_dir, _target: object(),
    )
    monkeypatch.setattr(
        "autodub.editor._refresh_ocr_regions",
        lambda _work_dir, _settings, _state, _regions, **_kwargs: expected,
    )
    worker = OCRRefreshWorker(Settings(), str(tmp_path), "vi", [])
    received = []
    worker.finished_ok.connect(received.append)

    worker.run()

    assert received == [expected]

def test_download_page_keeps_table_visible(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from autodub_gui.pages.download_page import DownloadPage

    app = QApplication.instance() or QApplication([])
    page = DownloadPage()

    assert page.table.minimumHeight() >= 200
    assert page.table.table.verticalHeader().defaultSectionSize() <= 48
    assert page.log.maximumHeight() <= 80
    page.deleteLater()
    app.processEvents()

def test_help_page_documents_ocr_and_uses_bundled_readme_name():
    from autodub_gui.pages import help_page

    names = [item[0] for item in help_page.INSTALL_ITEMS]
    assert any("Whisper" in name for name in names)
    assert any("PaddleOCR" in name for name in names)
    source = (help_page.__file__ and open(
        help_page.__file__, encoding="utf-8").read())
    assert "HUONG_DAN_CAI_DAT.md" in source
    assert "Sao chép lệnh cài" not in source
    assert "SetupScriptWorker" in source
    assert "VoiceSetupDialog.ensure_voices" in source
    assert "CUDA/NVIDIA" not in source
    assert "AMD dùng ROCm" in source
    assert "DirectML" in source

def test_help_page_install_rows_use_in_app_buttons(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from autodub.config import Settings
    from autodub_gui.pages import help_page
    from autodub_gui.pages.help_page import HelpPage

    app = QApplication.instance() or QApplication([])
    page = HelpPage(lambda: Settings())

    assert len(page._install_rows) == len(help_page.INSTALL_ITEMS)
    assert {row["button"].text() for row in page._install_rows.values()} == {
        "Tải và cài",
    }
    page.deleteLater()
    app.processEvents()

def test_openclaw_page_is_app_managed(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from autodub.openclaw_runtime import OpenClawRuntime
    from autodub_gui.pages.openclaw_page import OpenClawPage

    app = QApplication.instance() or QApplication([])
    runtime = OpenClawRuntime(data_dir=tmp_path)
    page = OpenClawPage(runtime)

    assert "Bật kết nối OpenClaw" in page.enable_box.text()
    assert page.endpoint_edit.isReadOnly()
    assert page.token_edit.isReadOnly()
    assert page.prompt_edit.isReadOnly()
    assert "GET /health" in page.prompt_edit.toPlainText()
    assert "py -m" not in (page.toolTip() or "")
    page.deleteLater()
    runtime.stop()
    app.processEvents()

def test_app_registers_openclaw_as_a_tool_page():
    source = _source("autodub_gui/app.py")
    assert "ROW_OPENCLAW" in source
    assert "OpenClawPage" in source
    assert "self._openclaw_runtime" in source

def test_logo_region_parser_accepts_empty_values() -> None:
    from autodub_gui.pages.new_project_page import NewProjectPage

    assert NewProjectPage._parse_logo_region(None) is None
    assert NewProjectPage._parse_logo_region("") is None
    assert NewProjectPage._parse_logo_region({"x": 0.1}) == {"x": 0.1}


def test_batch_queue_preserves_voice_and_completed_state(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from autodub.batch import BatchItem
    from autodub.config import Settings
    import autodub_gui.pages.batch_page as page_module
    import autodub_gui.pages.new_project_page as new_project_module

    app = QApplication.instance() or QApplication([])
    new_project_module.cache_dir = lambda: str(tmp_path / "cache")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    key = "https://example.test/video"
    done_dir = tmp_path / "done"
    (done_dir / "data").mkdir(parents=True)
    video_path = done_dir / "dubbed_video.mp4"
    audio_path = done_dir / "dub_audio.wav"
    video_path.write_bytes(b"video")
    audio_path.write_bytes(b"audio")
    (done_dir / "data" / "report.json").write_text(
        json.dumps({"output_dir": str(done_dir), "files": {
            "dubbed_video": str(video_path),
            "dub_audio": str(audio_path),
        }}),
        encoding="utf-8",
    )
    (output_dir / "batch_state.json").write_text(
        json.dumps({"videos": [{
            "video_url": key,
            "status": "success",
            "output_folder": str(done_dir),
        }]}),
        encoding="utf-8",
    )
    queue_path = tmp_path / "cache" / page_module.QUEUE_FILE
    queue_path.parent.mkdir()
    queue_path.write_text(json.dumps({"items": [{
        "url": key,
        "file_path": None,
        "voice": "Trúc Ly",
        "state": "running",
        "detail": "",
    }]}), encoding="utf-8")

    page = page_module.BatchPage(lambda: Settings(output_dir=str(output_dir)))

    assert page._items[0].voice == "Trúc Ly"
    assert page._state[key] == page_module.DONE
    page.deleteLater()
    app.processEvents()


def test_batch_does_not_chain_new_items_after_failed_run(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from autodub.config import Settings
    import autodub_gui.pages.batch_page as page_module
    import autodub_gui.pages.new_project_page as new_project_module

    app = QApplication.instance() or QApplication([])
    new_project_module.cache_dir = lambda: str(tmp_path / "cache")
    page = page_module.BatchPage(lambda: Settings(output_dir=str(tmp_path)))
    page._pending_adds = {"new-video"}

    summary = type("Summary", (), {
        "total": 2, "success": 1, "failed": 1, "pending": 0, "skipped": 0,
    })()
    page._on_finished(summary)

    assert page._chain_next is False
    page.deleteLater()
    app.processEvents()


def test_batch_chain_keeps_completed_items_in_next_state_run(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from autodub.batch import BatchItem
    from autodub.config import Settings
    import autodub_gui.pages.batch_page as page_module
    import autodub_gui.pages.new_project_page as new_project_module

    app = QApplication.instance() or QApplication([])
    new_project_module.cache_dir = lambda: str(tmp_path / "cache")
    page = page_module.BatchPage(lambda: Settings(output_dir=str(tmp_path)))
    old = BatchItem(file_path=str(tmp_path / "old.mp4"))
    new = BatchItem(file_path=str(tmp_path / "new.mp4"))
    page._items = [old, new]
    page._pending_adds = {new.key}
    page._state = {old.key: page_module.DONE, new.key: page_module.WAITING}

    launched = []
    page._set_running = lambda _running: None
    page._launch = lambda items: launched.append(items)
    page._on_finished(type("Summary", (), {
        "total": 2, "success": 2, "failed": 0, "pending": 0, "skipped": 0,
    })())
    page._on_worker_done()
    app.processEvents()

    assert [[item.key for item in items] for items in launched] == [
        [old.key, new.key],
    ]
    page.deleteLater()
    app.processEvents()


def test_new_project_has_separate_persistent_pipeline_defaults() -> None:
    source = _source("autodub_gui/pages/new_project_page.py")
    assert 'PIPELINE_DEFAULTS_FILE = "pipeline_defaults.json"' in source
    assert "def _defaults_path(self)" in source
    assert "def _save_pipeline_defaults(self)" in source
    assert "def _load_pipeline_defaults(self)" in source
    assert "self._save_pipeline_defaults()" in source
    assert "self._load_pipeline_defaults()" in source
    assert 'for key in ("source", "url", "file_path", "resume_dir")' in source
    assert "data.pop(key, None)" in source
