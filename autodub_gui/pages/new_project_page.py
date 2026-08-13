"""Trang Tạo dự án: sáu bước lưỡng dụng.

Trước khi chạy, sáu bước là một trình hướng dẫn để cấu hình. Trong khi chạy,
chính sáu bước đó phản ánh tiến độ thật của quá trình xử lý, nên người dùng
không phải học thêm cách đọc nào khác.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import fields, replace

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from autodub.media.subtitle import PRESET_CHOICES
from autodub.pipeline import DubRequest, DubResult
from autodub_gui import dub_constants as consts
from autodub_gui import icons, tokens
from autodub_gui.pages import BasePage
from autodub_gui.pages.new_project_steps import (
    STEP_NAMES, ExportSummaryStep, RecognizeStep, RunStep, TranslateStep,
    VideoStep, VoiceStep,
)
from autodub_gui.run_state import LEVEL_INFO, REGISTRY, ActiveJob
from autodub_gui.system_open import open_file, open_folder
from autodub_gui.ui.buttons import DangerButton, GhostButton, PrimaryButton
from autodub_gui.ui.cards import Card
from autodub_gui.ui.empty import EmptyState
from autodub_gui.ui.modal import ConfirmDialog
from autodub_gui.ui.stepper import Stepper
from autodub_gui.ui.style import clear_background
from autodub_gui.ui.toast import TOASTS
from autodub_gui.log_text import Narrator, error_line
from autodub_gui.voice_preview import VoicePreview
from autodub_gui.widgets import Banner, LogPanel, RunStatsPanel, StepTracker
from autodub_gui.workers import DubWorker, PrefetchWorker

DRAFT_FILE = "draft_project.json"
PIPELINE_DEFAULTS_FILE = "pipeline_defaults.json"
_DRAFT_DEBOUNCE_MS = 800
_PAGE_MARGIN = 28
_FORM_MAX_W = 460
_FORM_MIN_W = 390          # đủ chỗ cho bước rộng nhất — không thì cắt mép phải
_PREVIEW_STRETCH = 6
_FORM_STRETCH = 4

# Bước nào của quá trình xử lý ứng với ô nào trên thanh sáu bước.
# Toàn bộ phần chạy (nghe, dịch, đọc, ghép tiếng) nằm trong bước 5 «Chạy
# dịch»; bước 6 «Xuất video» chỉ sáng lên khi ghép hình và viết nội dung.
_STEP_TO_INDEX = {
    "acquire": 0, "extract": 0,
    "separate": 1, "asr": 1,
    "translate": 2,
    "tts": 3,
    "merge_audio": 4,
    "merge_video": 5, "content": 5,
}

# Chỉ số hai bước đặc biệt của trình hướng dẫn.
_RUN_INDEX = 5
_EXPORT_INDEX = 5

def cache_dir() -> str:
    """Thư mục lưu bản nháp và dữ liệu tạm của giao diện."""
    path = os.path.join(os.path.expanduser("~"), ".voxdub_cache")
    os.makedirs(path, exist_ok=True)
    return path


class NewProjectPage(BasePage):
    """Trình hướng dẫn tạo một dự án lồng tiếng."""

    settings_needed = Signal(str)
    edit_requested = Signal(str)
    home_requested = Signal()
    balance_changed = Signal(int)

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._worker: DubWorker | None = None
        self._prefetch_worker: PrefetchWorker | None = None
        self._prefetched_path: str = ""   # file đã tải sẵn khi nguồn là URL
        self._result: DubResult | None = None
        self._blur_regions: list[dict] = []
        self._subtitle_style: dict | None = None
        # Dự án đang làm dở của phiên này: thư mục + lý do dừng. Được lưu vào
        # bản nháp để lần mở app sau vẫn mời chạy tiếp thay vì tạo dự án mới
        # (dự án mới = job_id mới = trừ Vox lần nữa).
        self._active_work_dir: str = ""
        self._active_status: str = ""
        self._resume_request_snapshot: dict = {}
        self._resume_settings_snapshot: dict = {}
        self._auto_resume_scheduled = False
        self._preview = VoicePreview(self)
        self._narrator = Narrator()
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(_DRAFT_DEBOUNCE_MS)
        self._draft_timer.timeout.connect(self._save_draft)
        self._build()
        self._load_draft()
        REGISTRY.job_changed.connect(self._sync_live_stepper)

    # -- Dựng giao diện ------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(_PAGE_MARGIN, tokens.SP_2,
                                _PAGE_MARGIN, tokens.SP_5)
        root.setSpacing(tokens.SP_4)

        self.stepper = Stepper(list(STEP_NAMES))
        self.stepper.step_clicked.connect(self._go_to_step)
        root.addWidget(self.stepper)

        body = QHBoxLayout()
        body.setSpacing(18)
        body.addWidget(self._build_left(), _PREVIEW_STRETCH)
        body.addWidget(self._build_form(), _FORM_STRETCH)
        root.addLayout(body, 1)
        root.addLayout(self._build_footer())

    def _build_left(self) -> QWidget:
        """Cột trái: trước khi chạy là phần xem trước, khi chạy là tiến trình."""
        card = Card(padding=tokens.SP_4)
        self._left_title = card.add_header("Video sẽ được lồng tiếng")

        # Phần xem trước: chỉ hiện trước khi bấm chạy.
        self.preview = EmptyState(
            "Chưa chọn video nào",
            "Chọn nguồn video ở bước 1. Khi bắt đầu chạy, chỗ này sẽ hiện "
            "tiến trình từng bước và nhật ký xử lý.",
            icon=icons.upload_cloud())
        card.body.addWidget(self.preview, 1)

        self.steps = StepTracker()
        self.steps.setVisible(False)
        card.body.addWidget(self.steps)
        self.run_stats = RunStatsPanel()
        self.run_stats.setVisible(False)
        card.body.addWidget(self.run_stats)
        self.log = LogPanel()
        self.log.setVisible(False)
        card.body.addWidget(self.log, 1)

        self.pending_banner = Banner("warning", "Đang chờ bản dịch tiếng Việt")
        btn_hint = GhostButton("Mở hướng dẫn dịch")
        btn_hint.clicked.connect(self._open_hint)
        btn_dir = GhostButton("Mở thư mục dự án")
        btn_dir.clicked.connect(self._open_result_folder)
        self.btn_resume_after = PrimaryButton("Đã dịch xong, tiếp tục")
        self.btn_resume_after.clicked.connect(self._resume_after_translation)
        for button in (btn_hint, btn_dir, self.btn_resume_after):
            self.pending_banner.add_button(button)
        card.body.addWidget(self.pending_banner)

        self.done_banner = Banner("success", "Đã lồng tiếng xong")
        btn_video = GhostButton("Mở video")
        btn_video.clicked.connect(self._open_result_video)
        btn_folder = GhostButton("Mở thư mục")
        btn_folder.clicked.connect(self._open_result_folder)
        btn_edit = PrimaryButton("Chỉnh sửa dự án")
        btn_edit.clicked.connect(self._open_editor)
        for button in (btn_video, btn_folder, btn_edit):
            self.done_banner.add_button(button)
        card.body.addWidget(self.done_banner)
        return card

    def _build_form(self) -> QWidget:
        holder = QWidget()
        clear_background(holder)
        holder.setMaximumWidth(_FORM_MAX_W)
        # Cột biểu mẫu không được co hẹp hơn bước rộng nhất — khi cửa sổ nhỏ
        # thì phần xem trước bên trái nhường chỗ, không phải cắt ô nhập.
        holder.setMinimumWidth(_FORM_MIN_W)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card(padding=tokens.SP_5)
        scroll = QScrollArea()
        clear_background(scroll)
        scroll.viewport().setStyleSheet("background: transparent;")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self.pages = QStackedWidget()
        clear_background(self.pages)
        self.step_video = VideoStep()
        try:
            self.step_video.ocr_enabled.setChecked(
                bool(self._settings_provider().ocr_enabled))
        except Exception:
            pass
        self.step_recognize = RecognizeStep()
        self.step_translate = TranslateStep()
        self.step_voice = VoiceStep()
        self.step_run = RunStep()
        self.step_summary = ExportSummaryStep()
        self._steps = (self.step_video, self.step_recognize,
                       self.step_translate, self.step_voice,
                       self.step_run, self.step_summary)
        for step in self._steps:
            step.changed.connect(self._on_form_changed)
            self.pages.addWidget(step)
        self.step_voice.preview_requested.connect(self._preview_voice)
        self.step_translate.style_requested.connect(self._open_style_dialog)
        self.step_summary.style_requested.connect(self._open_style_dialog)
        self._preview.status_changed.connect(self.step_voice.set_status)
        # Khi URL thay đổi, bỏ file đã tải sẵn để tải lại lần sau.
        self.step_video.url.changed.connect(self._on_url_changed)

        scroll.setWidget(self.pages)
        card.body.addWidget(scroll, 1)
        layout.addWidget(card)
        return holder

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        self.btn_back = GhostButton("Quay lại")
        self.btn_back.clicked.connect(self._go_back)
        self.btn_clear_draft = GhostButton("Xóa nháp")
        self.btn_clear_draft.setToolTip(
            "Xóa những lựa chọn đã lưu tạm và quay về giá trị mặc định")
        self.btn_clear_draft.clicked.connect(self._clear_draft)
        self.btn_next = PrimaryButton("Tiếp tục")
        self.btn_next.clicked.connect(self._go_next)
        self.btn_stop = DangerButton("Dừng")
        self.btn_stop.clicked.connect(self._cancel)
        self.btn_stop.setVisible(False)
        row.addWidget(self.btn_back)
        row.addWidget(self.btn_clear_draft)
        row.addStretch()
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_next)
        return row

    # -- Điều hướng giữa các bước --------------------------------------
    def _go_to_step(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if not self.is_running():
            self.stepper.set_current(index)
        self._refresh_footer()
        if index == 2:
            self.step_translate.set_source_language(self._source_lang_label())
        if index == _RUN_INDEX:
            self.step_summary.set_summary(self._summary_rows())

    def _go_next(self) -> None:
        index = self.pages.currentIndex()
        ok, reason = self._steps[index].is_complete()
        if not ok:
            TOASTS.warn(reason)
            return
        if index == _RUN_INDEX:
            self._start()
            return
        # Bước 1 nguồn URL: tải ngầm trước, khi xong mới chuyển bước 2
        if index == 0 and self.step_video.source.current_key() == "url":
            url = self.step_video.url.text().strip()
            # File đã tải sẵn và chưa bị xóa thì chuyển ngay
            if self._prefetched_path and os.path.isfile(self._prefetched_path):
                self.stepper.set_max_reached(0)
                self._go_to_step(1)
                return
            self._start_prefetch(url)
            return
        self.stepper.set_max_reached(index)
        self._go_to_step(index + 1)

    def _go_back(self) -> None:
        index = self.pages.currentIndex()
        if index == 0:
            self.home_requested.emit()
            return
        self._go_to_step(index - 1)

    def _on_url_changed(self, _text: str) -> None:
        """URL thay đổi → file tải sẵn không còn hợp lệ, hủy tải nếu đang tải."""
        if self._prefetch_worker is not None and self._prefetch_worker.isRunning():
            self._prefetch_worker.cancel()
            self._prefetch_worker.wait(1000)
            self._prefetch_worker = None
        self._prefetched_path = ""
        self._restore_next_button()

    def _prefetch_temp_dir(self) -> str:
        """Thư mục tạm riêng để lưu video tải trước."""
        import tempfile
        return os.path.join(tempfile.gettempdir(), "voxdub_prefetch")

    def _start_prefetch(self, url: str) -> None:
        """Khởi động tải ngầm — block nút Tiếp tục, tự chuyển bước khi xong."""
        if self._prefetch_worker is not None and self._prefetch_worker.isRunning():
            return
        self.btn_next.setEnabled(False)
        self.btn_next.setText("Đang tải…")
        worker = PrefetchWorker(url, self._prefetch_temp_dir(), self)
        worker.finished_ok.connect(self._on_prefetch_done)
        worker.failed.connect(self._on_prefetch_failed)
        self._prefetch_worker = worker
        worker.start()

    def _on_prefetch_done(self, path: str) -> None:
        self._prefetched_path = path
        self._restore_next_button()
        self.stepper.set_max_reached(0)
        self._go_to_step(1)

    def _on_prefetch_failed(self, message: str) -> None:
        self._restore_next_button()
        TOASTS.warn(f"Tải video thất bại: {message[:120]}")

    def _next_label(self) -> str:
        index = self.pages.currentIndex()
        if index == _RUN_INDEX:
            # Nguồn «Tiếp tục dang dở» = chạy tiếp dự án cũ, không tạo mới.
            if self.step_video.source.current_key() == "resume":
                return "Tiếp tục lồng tiếng"
            return "Bắt đầu lồng tiếng"
        return "Tiếp tục"

    def _restore_next_button(self) -> None:
        self.btn_next.setEnabled(True)
        self.btn_next.setText(self._next_label())

    def _refresh_footer(self) -> None:
        # `finished_ok` fires before QThread.finished. Ready path must win,
        # otherwise navigating to step 2 immediately locks this button again.
        prefetch_ready = bool(
            self._prefetched_path and os.path.isfile(self._prefetched_path))
        if prefetch_ready or (
            self._prefetch_worker is None
            or not self._prefetch_worker.isRunning()):
            self.btn_next.setEnabled(True)
        self.btn_next.setText(self._next_label())

    def _on_form_changed(self) -> None:
        self._draft_timer.start()
        self._refresh_preview()
        if self.pages.currentIndex() == _RUN_INDEX:
            self.step_summary.set_summary(self._summary_rows())

    def _refresh_preview(self) -> None:
        """Nhắc lại nguồn video đang chọn ở cột trái cho dễ đối chiếu."""
        if self.is_running():
            return
        data = self.values()
        source = {"url": data["url"],
                  "file": os.path.basename(data["file_path"]),
                  "resume": data["resume_dir"]}.get(data["source"], "")
        if source:
            self.preview.set_message(
                source, "Chọn video, đặt tùy chọn nhanh rồi bấm Bắt đầu lồng tiếng. "
                        "Tiến trình từng bước sẽ hiện ngay tại đây.")
        else:
            self.preview.set_message(
                "Chưa chọn video nào",
                "Chọn nguồn video ở bước 1. Khi bắt đầu chạy, chỗ này sẽ hiện "
                "tiến trình từng bước và nhật ký xử lý.")

    # -- Gom dữ liệu ---------------------------------------------------
    def values(self) -> dict:
        data: dict = {}
        for step in self._steps:
            data.update(step.values())
        source = self.step_video.values()
        for key in (
            "logo_path", "intro_path", "outro_path", "logo_region",
            "vision_enabled", "vision_model", "logo_opacity", "logo_scale",
        ):
            if not data.get(key) and source.get(key):
                data[key] = source[key]
        return data

    def _source_lang_label(self) -> str:
        if self.step_recognize.auto_detect.isChecked():
            return "Tự nhận ra từ video"
        code = self.step_recognize.language.current_key()
        return next((label for label, key in consts.SOURCE_LANGS
                     if key == code), code)

    def _summary_rows(self) -> list[tuple[str, str]]:
        """Bảng tóm tắt hiện ở bước cuối, viết bằng lời thường."""
        data = self.values()

        def label_of(options, key, default="—"):
            return next((text for text, value in options if value == key), default)

        source = {"url": data["url"], "file": os.path.basename(data["file_path"]),
                  "resume": data["resume_dir"]}.get(data["source"], "")
        return [
            ("Video", source or "chưa chọn"),
            ("Ngôn ngữ gốc", self._source_lang_label()),
            ("Độ chính xác khi nghe",
             label_of(consts.WHISPER_MODELS, data["whisper_model"])),
            ("Cách dịch",
             "tự động (12 Vox/câu)" if data["auto_translate"]
             else "dịch tay có hướng dẫn (10 Vox/câu)"),
            ("Phong cách dịch",
             label_of([(a, b) for a, b, _c in consts.TRANSLATE_STYLES],
                      data["translate_style"])
             if data["auto_translate"] else "—"),
            ("Tiêu đề + mô tả đăng bài",
             "có (+20 Vox)" if data["generate_metadata"] else "không"),
            ("Giọng đọc",
             f"{data['voice'] or 'theo cài đặt chung'} · "
            f"tốc độ {data['voice_speed']:.2f}x"),
            ("Clone giọng",
             ("bật, " + ("từ file mẫu" if data["clone_source"] == "file"
                          else "từ video"))
             if data["clone_voice"] else "tắt"),
            ("Phụ đề",
             f"{label_of(consts.SUBTITLE_MODES, data['subtitle_mode'])} · "
             f"kiểu {label_of(PRESET_CHOICES, data['subtitle_preset'])}"),
            ("Lật ngang video", "có" if data["mirror"] else "không"),
            ("OCR làm mờ chữ Trung", "có" if data["ocr_enabled"] else "không"),
            ("Nhạc nền", label_of(consts.BG_MODES, data["bg_mode"])),
            ("Chỉ xuất âm thanh", "có" if data["skip_video"] else "không"),
        ]

    def preload_file(self, path: str) -> None:
        """Điền sẵn tệp video khi người dùng kéo thả ở Trang chủ."""
        self.step_video.set_file(path)
        self._go_to_step(0)

    # -- Bản nháp ------------------------------------------------------
    def _draft_path(self) -> str:
        return os.path.join(cache_dir(), DRAFT_FILE)

    def _defaults_path(self) -> str:
        return os.path.join(cache_dir(), PIPELINE_DEFAULTS_FILE)

    def _save_pipeline_defaults(self) -> None:
        """Remember pipeline choices without retaining previous video source."""
        try:
            data = self.values()
            for key in ("source", "url", "file_path", "resume_dir"):
                data.pop(key, None)
            data["subtitle_style_custom"] = self._subtitle_style
            data["blur_regions"] = self._blur_regions
            with open(self._defaults_path(), "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
        except OSError:
            pass

    def _load_pipeline_defaults(self) -> None:
        try:
            with open(self._defaults_path(), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for step in self._steps:
            step.load(data)
        style = data.get("subtitle_style_custom")
        self._subtitle_style = (
            dict(style) if isinstance(style, dict) else self._subtitle_style)
        regions = data.get("blur_regions")
        if isinstance(regions, list):
            self._blur_regions = list(regions)
        if self._subtitle_style or self._blur_regions:
            self._update_style_summary()

    def _save_draft(self) -> None:
        try:
            self._save_pipeline_defaults()
            data = self.values()
            data["subtitle_style_custom"] = self._subtitle_style
            data["blur_regions"] = self._blur_regions
            # Kèm dự án đang dở (nếu có) để mở lại app vẫn mời chạy tiếp.
            if self._active_work_dir:
                data["active_work_dir"] = self._active_work_dir
                data["active_status"] = self._active_status
            with open(self._draft_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except OSError:
            pass      # không lưu được nháp thì cũng không cản trở việc chính

    def _load_draft(self) -> None:
        try:
            with open(self._draft_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        if data:
            for step in self._steps:
                step.load(data)
            style = data.get("subtitle_style_custom")
            self._subtitle_style = (
                dict(style) if isinstance(style, dict) else None)
            regions = data.get("blur_regions")
            self._blur_regions = (
                list(regions) if isinstance(regions, list) else [])
            if self._subtitle_style or self._blur_regions:
                self._update_style_summary()
        else:
            self._apply_defaults_from_settings()
            self._load_pipeline_defaults()
        self._restore_active_session(data)
        self._go_to_step(0)

    def _restore_active_session(self, data: dict) -> None:
        """Nhớ lại dự án dở dang của phiên trước (nếu thư mục còn trên đĩa).

        Phiên trước dừng giữa chừng — lỗi, hết Vox, chờ dịch tay hay app bị
        tắt đột ngột — thì phiên này chuyển thẳng bước 1 sang «Tiếp tục dang
        dở» trỏ vào đúng thư mục cũ, để bấm chạy là đi tiếp chứ không tạo
        dự án mới (dự án mới = trừ Vox lần nữa).
        """
        work_dir = str(data.get("active_work_dir") or "")
        status = str(data.get("active_status") or "")
        if not work_dir or not os.path.isdir(work_dir):
            return
        self._active_work_dir = work_dir
        self._active_status = status or "running"
        self.step_video.set_resume(work_dir)
        try:
            from autodub.pipeline_state import load_pipeline_state
            state = load_pipeline_state(work_dir)
            pipeline = state.get("pipeline") or {}
            if pipeline.get("status") == "completed":
                self._active_work_dir = ""
                self._active_status = ""
                return
            settings = state.get("settings") or {}
            self._resume_request_snapshot = (
                settings.get("request") if isinstance(settings, dict)
                else {}) or {}
            self._resume_settings_snapshot = (
                settings.get("runtime") if isinstance(settings, dict)
                else {}) or {}
        except Exception:  # noqa: BLE001 — manifest hỏng không chặn mở app
            self._resume_request_snapshot = {}
            self._resume_settings_snapshot = {}
        hints = {
            "translate_pending": "đang chờ bản dịch tiếng Việt",
            "failed": "dừng vì gặp lỗi",
        }
        hint = hints.get(self._active_status, "dừng giữa chừng")
        # Hàm này chạy trong __init__, trước khi cửa sổ chính hiện — toast
        # bắn ngay sẽ bị nuốt. Đợi qua vòng lặp sự kiện đầu tiên rồi mới báo.
        QTimer.singleShot(0, lambda: TOASTS.info(
            f"Có dự án làm dở lần trước ({hint}). Bước 1 đã trỏ sẵn "
            "vào dự án đó — bấm chạy sẽ đi tiếp, không tạo dự án mới."))
        if self._active_status != "translate_pending":
            self._auto_resume_scheduled = True
            QTimer.singleShot(0, self._auto_resume_project)

    def _auto_resume_project(self) -> None:
        if (not self._auto_resume_scheduled
                or self.is_running()
                or not self._active_work_dir):
            return
        self._auto_resume_scheduled = False
        if REGISTRY.is_busy():
            return
        self._start()

    def _apply_defaults_from_settings(self) -> None:
        """Lần đầu mở thì lấy giá trị mặc định từ tệp cấu hình."""
        try:
            settings = self._settings_provider()
        except Exception:  # noqa: BLE001 — cấu hình hỏng thì dùng mặc định sẵn
            return
        self.step_recognize.engine.set_key(settings.asr_engine)
        self.step_recognize.model.set_key(settings.whisper_model)
        self.step_recognize.quality.set_key(settings.quality_preset)
        self.step_recognize.language.set_key(settings.default_source_lang)
        self.step_recognize.asr_threads.set_value(settings.asr_num_threads)
        self.step_recognize.beam_size.set_value(settings.whisper_beam_size)
        self.step_recognize.sample_rate.set_key(
            str(settings.audio_sample_rate))
        self.step_video.ocr_enabled.setChecked(settings.ocr_enabled)
        self.step_video.ocr_device.set_key(settings.ocr_device)
        self.step_video.ocr_confidence.set_value(settings.ocr_min_confidence)
        self.step_video.ocr_region_area.set_value(settings.ocr_max_region_area)
        self.step_video.ocr_y_min.set_value(settings.ocr_subtitle_y_min)
        self.step_video.ocr_interval.set_value(settings.ocr_sample_interval)
        self.step_video.logo_edit.set_text(settings.branding_logo_path)
        self.step_video.intro_edit.set_text(settings.branding_intro_path)
        self.step_video.outro_edit.set_text(settings.branding_outro_path)
        self.step_video.logo_region.set_text(settings.branding_logo_region)
        self.step_video.vision_enabled.setChecked(settings.branding_vision_enabled)
        self.step_video.vision_model.set_text(settings.branding_vision_model)
        self.step_video.logo_opacity.set_value(settings.branding_logo_opacity)
        self.step_video.logo_scale.set_value(settings.branding_logo_scale)
        self.step_translate.auto_translate.setChecked(settings.translate_enabled)
        self.step_translate.metadata.setChecked(settings.generate_metadata)
        self.step_translate.domain.set_text(settings.translate_domain)
        self.step_translate.video_title.set_text(settings.translate_video_title)
        self.step_translate.context.set_text(settings.translate_context)
        self.step_translate.pronouns.set_text(settings.translate_pronouns)
        self.step_translate.glossary.set_text(settings.translate_glossary)
        self.step_translate.cps_budget.set_value(settings.translate_cps_budget)
        self.step_translate.batch_size.set_value(settings.translate_batch_size)
        self.step_voice.picker.reload(settings)
        self.step_voice.picker.set_voice(settings.vieneu_voice)
        self.step_voice.speed.set_value(settings.voice_speed)
        self.step_voice.voice_style.set_key(settings.vieneu_style)
        self.step_voice.clone_voice.setChecked(settings.vieneu_clone_enabled)
        self.step_voice.clone_source.set_key(settings.vieneu_clone_source)
        self.step_voice.clone_reference_audio.set_text(
            settings.vieneu_clone_reference_audio)
        self.step_voice._on_clone_toggled(
            self.step_voice.clone_voice.isChecked())
        self.step_voice.clone_min_seconds.set_value(
            settings.vieneu_clone_min_seconds)
        self.step_voice.clone_max_seconds.set_value(
            settings.vieneu_clone_max_seconds)
        self.step_voice.clone_workers.set_value(settings.vieneu_max_workers)
        self.step_run.background.set_key(settings.bg_mode
                                         if hasattr(settings, "bg_mode")
                                         else "demucs")
        self.step_run.duck.set_value(getattr(settings, "bg_duck_db", -12.0))
        self.step_run.hq_background.setChecked(settings.hq_background)
        self.step_run.video_speed.set_value(settings.video_speed)
        self.step_run.soft_timing.setChecked(settings.soft_timing_fit)
        self.step_run.timing_drift.set_value(settings.timing_max_drift_s)
        self.step_run.timing_gap.set_value(settings.timing_min_gap_s)
        self.step_run.timing_atempo.set_value(settings.timing_max_atempo)
        self.step_run.voice_postprocess.setChecked(settings.voice_postprocess)
        self.step_run.voice_target_lufs.set_value(settings.voice_target_lufs)
        self.step_run.bg_duck_voice_db.set_value(settings.bg_duck_voice_db)
        self.step_run.parallel_workers.set_value(settings.parallel_workers)
        self.step_summary.output_dir.set_text(settings.output_dir)
        self.step_summary.auto_clean.setChecked(settings.auto_clean_intermediates)
        self.step_summary.subtitle_mode.set_key(settings.subtitle_mode)
        self.step_summary.subtitle_preset.set_key(settings.subtitle_preset)
        self.step_summary.karaoke_alignment.setChecked(
            settings.karaoke_alignment)

    def _clear_draft(self) -> None:
        confirmed, _ = ConfirmDialog.ask(
            self, "Xóa bản nháp",
            "Những lựa chọn đang lưu tạm sẽ bị xóa và các bước quay về giá trị "
            "mặc định. Bạn có chắc không?",
            kind="warning", confirm_label="Xóa nháp")
        if not confirmed:
            return
        try:
            os.remove(self._draft_path())
        except OSError:
            pass
        self._active_work_dir = ""
        self._active_status = ""
        for step in self._steps:
            step.load({})
        self._apply_defaults_from_settings()
        self._go_to_step(0)
        TOASTS.info("Đã xóa bản nháp.")

    # -- Nghe thử và kiểu phụ đề ---------------------------------------
    def _preview_voice(self, voice: str) -> None:
        try:
            settings = self._settings_provider()
        except Exception as e:  # noqa: BLE001 — báo lên giao diện
            self.step_voice.set_status(f"Không đọc được cấu hình: {e}")
            return
        self._preview.play(settings, voice)

    def _base_style(self, preset: str) -> dict:
        """Kiểu nền cho bộ đang chọn — TÔN TRỌNG tinh chỉnh trong Cài đặt.

        Nếu người dùng giữ nguyên bộ kiểu mặc định của Cài đặt thì lấy đủ
        mọi tinh chỉnh (font, bóng, nền chữ…) từ đó; chọn bộ khác thì dùng
        bộ dựng sẵn tương ứng. Giống hệt trang Hàng loạt để hai nơi ra
        cùng một chữ trên video.
        """
        from autodub.media.subtitle import preset_style
        try:
            settings = self._settings_provider()
            if preset == settings.subtitle_preset:
                return settings.subtitle_style()
        except Exception:  # noqa: BLE001 — cấu hình hỏng thì dùng bộ sẵn
            pass
        return preset_style(preset)

    def _open_style_dialog(self) -> None:
        from autodub_gui.style_dialog import StyleDialog

        video = self._current_video_path()
        # Chưa tự chỉnh gì thì mở ra với đúng bộ kiểu đang chọn ở bước này,
        # để cửa sổ xem trước khớp với thứ người dùng vừa chọn.
        style = self._subtitle_style or self._base_style(
            self.step_summary.subtitle_preset.current_key())
        try:
            dialog = StyleDialog(video, style, self._blur_regions, self)
        except Exception as e:  # noqa: BLE001 — thường do thiếu ffmpeg
            ConfirmDialog.show_error(
                self, "Không mở được khung xem trước",
                "Ứng dụng cần lấy một khung hình từ video để bạn canh chữ, "
                "nhưng lần này không lấy được. Hãy kiểm tra video còn trên máy "
                "và máy đã cài FFmpeg chưa.", detail=str(e))
            return
        if not dialog.exec():
            return
        self._subtitle_style = dict(dialog.style(), preset="custom")
        # Ô chọn bộ kiểu nhảy về "Tự chỉnh" cho khớp với kiểu vừa sửa.
        self.step_translate.subtitle_style_summary.setText(
            self._style_summary_text())
        self.step_summary.subtitle_preset.set_key("custom")
        # Lưu vùng che kể cả khi nguồn là liên kết (chưa có tệp trên máy):
        # tọa độ đã chuẩn hóa 0..1 nên áp đúng lên video sau khi tải về.
        self._blur_regions = dialog.regions()
        self._update_style_summary()

    def _style_summary_text(self) -> str:
        style = self._subtitle_style
        parts: list[str] = []
        if style:
            position = {"bottom": "dưới", "middle": "giữa",
                        "top": "trên"}.get(style.get("position", "bottom"), "dưới")
            parts.append(f"cỡ chữ {style.get('font_size', 22)}, đặt ở {position}")
            if style.get("display") == "karaoke":
                parts.append(f"hiện theo cụm {style.get('words_per_cue', 3)} chữ")
        else:
            parts.append("kiểu mặc định")
        count = len(self._blur_regions)
        parts.append(f"che {count} vùng" if count else "chưa che vùng nào")
        return ", ".join(parts).capitalize()

    def _update_style_summary(self) -> None:
        summary = self._style_summary_text()
        self.step_translate.subtitle_style_summary.setText(summary)
        self.step_summary.set_style_summary(summary)
        if (self._subtitle_style
                and self.step_summary.subtitle_mode.current_key() != "burn"):
            self.step_summary.subtitle_mode.set_key("burn")
            TOASTS.info("Kiểu chữ tự chỉnh cần ghi thẳng vào hình, nên phụ đề "
                        "đã chuyển sang Ghi thẳng vào hình.")

    def _current_video_path(self) -> str:
        data = self.values()
        # Ưu tiên file đã chọn trực tiếp
        path = data["file_path"]
        if path and os.path.isfile(path):
            return path
        # URL đã tải sẵn bởi PrefetchWorker
        if self._prefetched_path and os.path.isfile(self._prefetched_path):
            return self._prefetched_path
        work_dir = data["resume_dir"] or (
            self._result.work_dir if self._result else "")
        if work_dir and os.path.isdir(work_dir):
            from autodub.pipeline import source_video_path
            return source_video_path(work_dir) or ""
        return ""

    # -- Chạy ----------------------------------------------------------
    def _build_request(self) -> DubRequest | None:
        ok, reason = self.step_video.is_complete()
        if not ok:
            TOASTS.warn(reason)
            self._go_to_step(0)
            return None

        data = self.values()
        snapshot = (self._resume_request_snapshot
                    if data["source"] == "resume"
                    else {})
        if snapshot:
            data = {**data, **snapshot, "source": "resume",
                    "resume_dir": self._active_work_dir or data["resume_dir"]}
        source = data["source"]

        # Nếu nguồn là URL nhưng file đã tải sẵn, truyền file_path trực tiếp
        # vào pipeline (tránh tải lại), giữ url để pipeline ghi metadata.
        prefetched = (self._prefetched_path
                      if source == "url"
                         and self._prefetched_path
                         and os.path.isfile(self._prefetched_path)
                      else None)

        return DubRequest(
            url=data["url"] if source == "url" and not prefetched else None,
            file_path=(prefetched if prefetched
                       else data["file_path"] if source in ("file", "resume")
                       else None),
            output_dir=data["output_dir"] or None,
            source_lang=("" if data["auto_detect"] else data["source_lang"]),
            voice=data["voice"] or None,
            bg_mode=data["bg_mode"],
            bg_duck_db=data["bg_duck_db"],
            skip_video=data["skip_video"],
            resume_dir=data["resume_dir"] if source == "resume" else None,
            subtitle_mode=data["subtitle_mode"],
            blur_regions=list(self._blur_regions),
            mirror=bool(data["mirror"]),
            ocr_enabled=bool(data["ocr_enabled"]),
             subtitle_style=(self._subtitle_style
                             or self._base_style(data["subtitle_preset"])),
             clone_voice=data["clone_voice"],
             clone_source=data["clone_source"],
             clone_reference_audio=data["clone_reference_audio"] or None,
            logo_path=data["logo_path"] or None,
            intro_path=data["intro_path"] or None,
            outro_path=data["outro_path"] or None,
            logo_region=self._parse_logo_region(data["logo_region"]),
            logo_opacity=float(data["logo_opacity"]),
            logo_scale=float(data["logo_scale"]),
            vision_enabled=bool(data["vision_enabled"]),
        )

    @staticmethod
    def _parse_logo_region(value: str) -> dict | None:
        if not value.strip():
            return None
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _run_settings(self):
        """Cấu hình cho lần chạy này, đã ghép phong cách dịch và tốc độ đọc.

        Hai lựa chọn quyết định giá (dịch tự động, gói đăng bài) được LƯU
        LẠI vào tệp cấu hình — video sau mở trình hướng dẫn là thấy đúng
        lựa chọn lần trước, Cài đặt và trình hướng dẫn không lệch nhau.
        """
        data = self.values()
        settings = self._settings_provider()
        if self._resume_settings_snapshot and data["source"] == "resume":
            allowed = {field.name for field in fields(settings)}
            saved = {
                key: value for key, value in self._resume_settings_snapshot.items()
                if key in allowed and key not in {
                    "translation_api_key", "bilibili_cookies_file",
                }
            }
            if saved:
                settings = replace(settings, **saved)
        note = consts.style_note(data["translate_style"])
        extra = data["translate_note"].strip()
        merged = "\n".join(
            part for part in (settings.translate_style_notes, note, extra)
            if part).strip()
        changes = {
            "voice_speed": data["voice_speed"],
            "vieneu_style": data["voice_style"],
            "quality_preset": data["quality_preset"],
            "video_speed": data["video_speed"],
            "soft_timing_fit": bool(data["soft_timing_fit"]),
            "timing_max_drift_s": data["timing_max_drift_s"],
            "timing_min_gap_s": data["timing_min_gap_s"],
            "timing_max_atempo": data["timing_max_atempo"],
            "hq_background": bool(data["hq_background"]),
            "voice_postprocess": bool(data["voice_postprocess"]),
            "voice_target_lufs": data["voice_target_lufs"],
            "bg_duck_voice_db": data["bg_duck_voice_db"],
            "parallel_workers": int(data["parallel_workers"]),
            "ocr_enabled": bool(data["ocr_enabled"]),
            "ocr_device": data["ocr_device"],
            "ocr_min_confidence": data["ocr_min_confidence"],
            "ocr_max_region_area": data["ocr_max_region_area"],
            "ocr_subtitle_y_min": data["ocr_subtitle_y_min"],
            "ocr_sample_interval": data["ocr_sample_interval"],
            "asr_num_threads": int(data["asr_threads"]),
            "whisper_beam_size": int(data["beam_size"]),
            "audio_sample_rate": int(data["audio_sample_rate"]),
            "translate_cps_budget": data["translate_cps_budget"],
            "translate_batch_size": int(data["translate_batch_size"]),
            "translate_enabled": bool(data["auto_translate"]),
            "generate_metadata": bool(data["generate_metadata"]),
            "auto_clean_intermediates": bool(data["auto_clean_intermediates"]),
            "translate_domain": data["translate_domain"],
            "translate_video_title": data["translate_video_title"],
            "translate_context": data["translate_context"],
            "translate_pronouns": data["translate_pronouns"],
            "translate_glossary": data["translate_glossary"],
            "branding_logo_path": data["logo_path"],
            "branding_intro_path": data["intro_path"],
            "branding_outro_path": data["outro_path"],
            "branding_logo_region": data["logo_region"],
            "branding_logo_opacity": data["logo_opacity"],
            "branding_logo_scale": data["logo_scale"],
            "branding_vision_enabled": bool(data["vision_enabled"]),
            "branding_vision_model": data["vision_model"],
            "vieneu_clone_min_seconds": data["clone_min_seconds"],
            "vieneu_clone_max_seconds": data["clone_max_seconds"],
            "vieneu_max_workers": int(data["clone_workers"]),
            "vieneu_clone_enabled": bool(data["clone_voice"]),
            "vieneu_clone_source": data["clone_source"],
            "vieneu_clone_reference_audio": data["clone_reference_audio"],
            "karaoke_alignment": bool(data["karaoke_alignment"]),
            "subtitle_mode": data["subtitle_mode"],
            "subtitle_preset": data["subtitle_preset"],
            "output_dir": data["output_dir"],
            "auto_clean_intermediates": bool(data["auto_clean_intermediates"]),
        }
        if merged != settings.translate_style_notes:
            changes["translate_style_notes"] = merged
        if data["asr_engine"]:
            changes["asr_engine"] = data["asr_engine"]
        if data["whisper_model"]:
            changes["whisper_model"] = data["whisper_model"]
        if data["voice"]:
            changes["vieneu_voice"] = data["voice"]
        self._persist_pricing_choices(settings, data)
        return replace(settings, **changes)

    def _persist_pricing_choices(self, settings, data: dict) -> None:
        """Ghi lựa chọn dịch tự động + gói đăng bài về tệp cấu hình."""
        from autodub_gui.env_store import bool_to_env, write_env
        updates: dict[str, str] = {}
        if bool(data["auto_translate"]) != settings.translate_enabled:
            updates["TRANSLATE_ENABLED"] = bool_to_env(data["auto_translate"])
        if bool(data["generate_metadata"]) != settings.generate_metadata:
            updates["GENERATE_METADATA"] = bool_to_env(data["generate_metadata"])
        if not updates:
            return
        try:
            write_env(updates)
        except OSError:
            pass   # không ghi được cấu hình thì lần chạy này vẫn đúng lựa chọn

    def _start(self) -> None:
        for index, step in enumerate(self._steps):
            ok, reason = step.is_complete()
            if not ok:
                TOASTS.warn(reason)
                self._go_to_step(index)
                return
        request = self._build_request()
        if request is not None:
            self._launch(request)

    def _resume_after_translation(self) -> None:
        if self._result is None:
            return
        request = self._build_request()
        if request is None:
            return
        request.resume_dir = self._result.work_dir
        request.url = None
        self._launch(request)

    def _launch(self, request: DubRequest) -> None:
        if self._worker is not None and self._worker.isRunning():
            TOASTS.warn("Đang có một video chạy dở. Hãy đợi xong hoặc bấm Dừng.")
            return
        if REGISTRY.is_busy():
            job = REGISTRY.current()
            TOASTS.warn(f"Đang chạy «{job.title}» ở trang khác. "
                        "Hãy đợi xong hoặc dừng việc đó trước.")
            return
        self.pending_banner.setVisible(False)
        self.done_banner.setVisible(False)
        self.steps.reset()
        self.log.reset_log()
        self.run_stats.reset()
        self._narrator.reset()
        # Lượt chạy mới bắt đầu: thư mục đang theo dõi là resume_dir (nếu
        # chạy tiếp) hoặc trống cho tới khi pipeline báo về qua acquire/start.
        # Không giữ thư mục của lượt trước — lỡ lỗi sớm thì trỏ nhầm dự án.
        self._active_work_dir = request.resume_dir or ""
        self._active_status = "running" if self._active_work_dir else ""
        self._set_running(True)

        worker = DubWorker(self._run_settings(), request)
        worker.progress.connect(self.steps.apply_event)
        worker.progress.connect(self.run_stats.apply_event)
        worker.progress.connect(REGISTRY.update_job)
        worker.progress.connect(self._on_progress_log)
        worker.progress.connect(self._on_progress_event)
        worker.log.connect(self.log.append_log)
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(lambda: self._set_running(False))
        self._worker = worker
        REGISTRY.start_job(
            ActiveJob(kind="dub", title=self._job_title(request),
                      work_dir=request.resume_dir or ""),
            on_cancel=self._cancel)
        worker.start()

    def _on_progress_event(self, event) -> None:
        """Ghi nhớ thư mục dự án ngay khi pipeline vừa tạo/chọn xong.

        Pipeline nhét work_dir vào ``detail`` của sự kiện «acquire/start» —
        nhờ đó nếu lượt chạy đổ giữa chừng (lỗi, hết Vox, chờ dịch tay) thì
        trang này vẫn biết dự án nằm đâu để mời chạy TIẾP đúng dự án cũ.
        Lưu luôn vào bản nháp: app có sập thì mở lại vẫn nhớ.
        """
        if (getattr(event, "step", "") == "acquire"
                and getattr(event, "status", "") == "start"
                and getattr(event, "detail", "")):
            self._active_work_dir = event.detail
            self._active_status = "running"
            job = REGISTRY.current()
            if job is not None and not job.work_dir:
                job.work_dir = event.detail
            self._save_draft()

    def _job_title(self, request: DubRequest) -> str:
        if request.file_path:
            return os.path.basename(request.file_path)
        if request.resume_dir:
            return os.path.basename(request.resume_dir.rstrip("\\/"))
        return request.url or "Video mới"

    def _cancel(self) -> None:
        worker = None
        if self._worker is not None and self._worker.isRunning():
            worker = self._worker
            # Dừng giữa chừng thì phần AI đã chạy không hoàn Vox — nói rõ
            # trước khi dừng để người dùng không bất ngờ.
        if worker is None:
            return
        worker.cancel()
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("Đang dừng…")

    def _set_running(self, running: bool) -> None:
        self.preview.setVisible(not running)
        self.steps.setVisible(running)
        self.run_stats.setVisible(running)
        self.log.setVisible(running)
        self._left_title.itemAt(0).widget().setText(
            "Tiến trình xử lý" if running else "Video sẽ được lồng tiếng")
        for step in self._steps:
            step.setEnabled(not running)
        self.btn_next.setVisible(not running)
        self.btn_back.setVisible(not running)
        self.btn_clear_draft.setVisible(not running)
        self.btn_stop.setVisible(running)
        self.btn_stop.setEnabled(True)
        self.btn_stop.setText("Dừng")
        self.stepper.set_live_mode(running)
        if not running:
            self.stepper.set_interactive(True)
            self.stepper.set_current(self.pages.currentIndex())
            self._refresh_footer()
        else:
            self.stepper.set_interactive(False)

    def _sync_live_stepper(self) -> None:
        """Đưa tiến độ thật lên thanh sáu bước khi đang chạy."""
        job = REGISTRY.current()
        if job is None or not self.is_running():
            return
        index = _STEP_TO_INDEX.get(job.step)
        if index is not None:
            self.stepper.set_live_progress(index)

    # -- Kết quả -------------------------------------------------------
    def _mark_interrupted(self, status: str, work_dir: str = "") -> None:
        """Lượt chạy dừng giữa chừng: nhớ dự án + trỏ bước 1 vào «Tiếp tục».

        Nhờ vậy nút chạy tiếp theo đi TIẾP đúng dự án cũ — không tạo thư mục
        mới, không nghe-chép lại từ đầu, không bị trừ Vox lần nữa. Trạng
        thái được lưu vào bản nháp để tắt app mở lại vẫn nhớ.
        """
        if work_dir:
            self._active_work_dir = work_dir
        if not self._active_work_dir:
            return
        self._active_status = status
        self.step_video.set_resume(self._active_work_dir)
        self._go_to_step(_RUN_INDEX)
        self.stepper.set_max_reached(_RUN_INDEX)
        self._save_draft()

    def _reset_session(self) -> None:
        """Dự án đã xong: dọn phiên làm việc để lần bấm sau là dự án MỚI."""
        self._active_work_dir = ""
        self._active_status = ""
        self._resume_request_snapshot = {}
        self._resume_settings_snapshot = {}
        self._auto_resume_scheduled = False
        self._prefetched_path = ""
        self._blur_regions = []
        self._subtitle_style = None
        for step in self._steps:
            step.load({})
        self._apply_defaults_from_settings()
        self._load_pipeline_defaults()
        self._update_style_summary()
        try:
            os.remove(self._draft_path())
        except OSError:
            pass
        # step.load() vừa kích hoạt lần lưu nợ — dừng lại kẻo nó ghi đè
        # bản nháp vừa xóa bằng dữ liệu của dự án đã xong.
        self._draft_timer.stop()
        self.stepper.set_max_reached(0)
        self.stepper.set_current(0)
        self._go_to_step(0)

    def _on_finished(self, result: DubResult) -> None:
        self._result = result
        if result.status == "translate_pending":
            self._mark_interrupted("translate_pending", result.work_dir)
            self._show_pending(result)
            REGISTRY.finish_job(False, "đang chờ bản dịch tiếng Việt")
            return
        self._show_completed(result)

    def _show_completed(self, result: DubResult) -> None:
        self.stepper.mark_all_done()
        report = result.report or {}
        files = report.get("files") or {}
        self.done_banner.set_text(
            f"Video kết quả: {files.get('dubbed_video') or 'chỉ có âm thanh'}\n"
            f"Số câu thoại: {report.get('total_segments', '—')}\n"
            f"Thư mục dự án: {result.work_dir}")
        self.done_banner.setVisible(True)
        REGISTRY.finish_job(True)
        # Dự án đã xong hẳn — dọn phiên để lần bấm chạy sau là dự án MỚI,
        # không dựng lại dự án vừa xong thành bản sao. Giữ nguyên banner và
        # self._result nên Mở video / Mở thư mục / Chỉnh sửa vẫn hoạt động.
        self._reset_session()
        TOASTS.success("Đã lồng tiếng xong.", action_label="Mở video",
                       on_action=self._open_result_video)

    def _show_pending(self, result: DubResult) -> None:
        self.pending_banner.set_text(
            "Video đang chờ bản dịch tiếng Việt. Bấm Mở hướng dẫn dịch rồi làm "
            "theo ba bước, mất khoảng hai đến ba phút. Lưu bản dịch xong thì "
            "quay lại đây bấm Đã dịch xong, tiếp tục.\n\n"
            "Mẹo: điền API Key Gemini miễn phí trong Cài đặt để ứng dụng tự "
            "dịch, khỏi làm tay.\n\n"
            f"Thư mục dự án: {result.work_dir}")
        self.pending_banner.setVisible(True)

    def _on_failed(self, message: str) -> None:
        import logging as _log
        text, level = error_line(message)
        self.log.append_log(text, level)
        REGISTRY.finish_job(False, message[:120])
        # Đã biết thư mục dự án (pipeline báo lúc khởi động) → trỏ bước 1
        # vào «Tiếp tục dang dở» để bấm chạy lại là đi tiếp, không tạo mới.
        self._mark_interrupted("failed")
        if "Missing required setting" in message:
            ConfirmDialog.show_error(
                self, "Thiếu cấu hình",
                "Còn vài mục bắt buộc chưa điền nên chưa chạy được. Hãy mở "
                "trang Cài đặt và điền nốt, rồi bấm chạy lại.", detail=message)
            self.settings_needed.emit(message)
            return
        friendly = consts.friendly_error(message)
        if friendly is not None:
            title, advice = friendly
            ConfirmDialog.show_error(self, title, advice, detail=message)
            return
        if self._active_work_dir:
            advice = ("Có lỗi ngoài dự tính nên ứng dụng phải dừng lại. Tiến "
                      "độ đã lưu trên đĩa vẫn còn — bước 1 đã trỏ sẵn vào dự "
                      "án này, bấm Tiếp tục lồng tiếng để chạy tiếp từ chỗ "
                      "dừng (không bị trừ Vox lần nữa).")
        else:
            advice = ("Có lỗi ngoài dự tính nên ứng dụng phải dừng lại. Tiến "
                      "độ đã lưu trên đĩa vẫn còn: bạn có thể chọn Tiếp tục "
                      "dang dở ở bước 1 để chạy tiếp từ chỗ dừng.")
        ConfirmDialog.show_error(
            self, "Quá trình xử lý dừng giữa chừng", advice, detail=message)

    def _on_cancelled(self) -> None:
        import logging as _log
        self.log.append_log("Đã dừng theo yêu cầu của bạn.", _log.WARNING)
        REGISTRY.add_activity(LEVEL_INFO, "Đã dừng việc lồng tiếng theo yêu cầu")
        REGISTRY.finish_job(False, "bạn đã bấm dừng")
        # Dừng tay cũng là dở dang: trỏ bước 1 vào dự án này để chạy tiếp
        # dùng lại phần đã làm (đã dịch rồi thì không trừ Vox lần nữa).
        self._mark_interrupted("cancelled")

    def _on_progress_log(self, event) -> None:
        """Kể lại tiến trình bằng lời thường vào Nhật ký."""
        result = self._narrator.narrate(event)
        if result is None:
            return
        text, level, is_progress = result
        self.log.append_log(text, level, is_progress=is_progress)

    # -- Mở kết quả ----------------------------------------------------
    def _open_hint(self) -> None:
        if self._result is None:
            return
        path = os.path.join(self._result.work_dir, "TRANSLATE_PENDING.txt")
        ok, message = open_file(path)
        if not ok:
            TOASTS.warn(message)

    def _open_result_folder(self) -> None:
        if self._result is None:
            return
        ok, message = open_folder(self._result.work_dir)
        if not ok:
            TOASTS.warn(message)

    def _open_result_video(self) -> None:
        if self._result is None:
            return
        files = (self._result.report or {}).get("files") or {}
        ok, message = open_file(files.get("dubbed_video", ""))
        if not ok:
            self._open_result_folder()

    def _open_editor(self) -> None:
        if self._result is not None:
            self.edit_requested.emit(self._result.work_dir)

    # -- Vòng đời ------------------------------------------------------
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def shutdown(self) -> None:
        if self._prefetch_worker is not None and self._prefetch_worker.isRunning():
            self._prefetch_worker.cancel()
            self._prefetch_worker.wait(3000)
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)

    def cleanup(self) -> None:
        self._save_draft()
        self._preview.cleanup()
