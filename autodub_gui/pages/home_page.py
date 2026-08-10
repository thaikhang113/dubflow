"""Trang chủ: kéo thả video, xem việc đang chạy, thống kê và dự án gần đây.

Đây là trang mở ra đầu tiên. Khi ứng dụng còn trống trơn, trang này vẫn phải
dùng được ngay và chỉ rõ ba bước để bắt đầu.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from autodub_gui import icons
from autodub_gui import projects as projects_mod
from autodub_gui import tokens
from autodub_gui.ui.style import clear_background
from autodub_gui.formatting import format_eta
from autodub_gui.pages import BasePage
from autodub_gui.run_state import REGISTRY
from autodub_gui.system_open import open_file, open_folder
from autodub_gui.ui.buttons import GhostButton
from autodub_gui.ui.cards import Card, ProcessingCard, QuickStartCard, StatGrid
from autodub_gui.ui.dropzone import DragDropZone, is_video_file
from autodub_gui.ui.empty import EmptyState
from autodub_gui.ui.grid import ProjectGrid
from autodub_gui.ui.labels import title_label
from autodub_gui.ui.toast import TOASTS

RECENT_COUNT = 4
_UPLOAD_STRETCH = 55
_SIDE_STRETCH = 45
_PAGE_MARGIN = 28

_STEPS_TEXT = (
    "1. Kéo một video vào ô bên trái, hoặc dán liên kết ở trang Tạo dự án.",
    "2. Chọn giọng đọc và kiểu phụ đề — mọi mục đều đã có sẵn giá trị hợp lý.",
    "3. Bấm Bắt đầu lồng tiếng rồi chờ. Bạn có thể tắt máy giữa chừng, "
    "lần sau chạy tiếp từ chỗ dừng.",
)


class HomePage(BasePage):
    """Trang chủ của ứng dụng."""

    create_requested = Signal(str)      # đường dẫn video đã chọn, có thể rỗng
    projects_requested = Signal()
    edit_requested = Signal(str)
    batch_requested = Signal()
    voices_requested = Signal()         # mở Cài đặt ở tab Giọng đọc
    settings_requested = Signal()

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._scan_worker = None
        self._projects: list = []
        self._build()
        REGISTRY.job_changed.connect(self._refresh_job)
        self._refresh_job()

    # -- Dựng giao diện ------------------------------------------------
    def _build(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        clear_background(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(_PAGE_MARGIN, tokens.SP_2,
                                  _PAGE_MARGIN, tokens.SP_5)
        layout.setSpacing(18)

        layout.addLayout(self._build_top_row())
        layout.addWidget(self._build_first_run_card())
        layout.addWidget(self._build_quick_start())
        layout.addLayout(self._build_recent_header())
        self.grid = ProjectGrid(max_items=RECENT_COUNT)
        self.grid.card_clicked.connect(self.edit_requested.emit)
        self.grid.edit_project.connect(self.edit_requested.emit)
        self.grid.open_video.connect(self._open_video)
        self.grid.open_folder.connect(self._open_folder)
        self.grid.delete_project.connect(self._hide_project)
        layout.addWidget(self.grid)

        self.empty = EmptyState(
            "Chưa có dự án nào", "Video bạn lồng tiếng xong sẽ hiện ở đây.",
            "Tạo dự án mới")
        self.empty.action_clicked.connect(lambda: self.create_requested.emit(""))
        layout.addWidget(self.empty)
        layout.addStretch()

        scroll.setWidget(body)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _build_top_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(18)
        self.dropzone = DragDropZone()
        self.dropzone.file_selected.connect(self._on_file_chosen)
        self.dropzone.files_rejected.connect(self._on_many_files)
        row.addWidget(self.dropzone, _UPLOAD_STRETCH)

        side = QVBoxLayout()
        side.setSpacing(14)
        self.processing = ProcessingCard()
        self.processing.create_requested.connect(
            lambda: self.create_requested.emit(""))
        self.processing.stop_requested.connect(self._stop_job)
        self.processing.details_requested.connect(self._open_job_details)
        side.addWidget(self.processing)
        self.stats = StatGrid("Thống kê nhanh")
        side.addWidget(self.stats)
        side.addStretch()
        row.addLayout(side, _SIDE_STRETCH)
        return row

    def _build_first_run_card(self) -> QWidget:
        """Thẻ hướng dẫn ba bước, chỉ hiện khi máy chưa có dự án nào."""
        card = Card(padding=tokens.SP_4)
        card.add_header("Bắt đầu trong ba bước")
        for line in _STEPS_TEXT:
            label = QLabel(line)
            label.setWordWrap(True)
            label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; "
                f"font-size: {tokens.FS_LABEL}px; background: transparent;")
            card.body.addWidget(label)
        self._first_run_card = card
        card.setVisible(False)
        return card

    def _build_quick_start(self) -> QWidget:
        """Hàng bốn ô "Bắt đầu nhanh"; xếp 2×2 khi cửa sổ hẹp."""
        wrap = QWidget()
        clear_background(wrap)
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(tokens.SP_3)
        col.addWidget(title_label("Bắt đầu nhanh"))

        self._quick_grid = QGridLayout()
        self._quick_grid.setSpacing(tokens.SP_3)
        specs = (
            ("Tạo dự án mới", "Lồng tiếng một video từ tệp hoặc liên kết",
             icons.file_plus, tokens.PRIMARY, tokens.PROCESSING_BG,
             lambda: self.create_requested.emit("")),
            ("Xử lý hàng loạt", "Lồng tiếng nhiều video cùng lúc",
             icons.layers, tokens.ACCENT_PURPLE, tokens.PURPLE_BG,
             self.batch_requested.emit),
            ("Thư viện giọng đọc", "Nghe thử và chọn giọng phù hợp",
             icons.user, tokens.SUCCESS, tokens.SUCCESS_BG,
             self.voices_requested.emit),
            ("Cài đặt", "Tùy chỉnh hệ thống theo nhu cầu",
             icons.gear, tokens.WARNING, tokens.WARNING_BG,
             self.settings_requested.emit),
        )
        self._quick_cards = []
        for title, desc, icon_fn, color, bg, handler in specs:
            card = QuickStartCard(title, desc, icon_fn, color, bg)
            card.clicked.connect(handler)
            self._quick_cards.append(card)
        self._layout_quick_cards(columns=4)
        col.addLayout(self._quick_grid)
        return wrap

    def _layout_quick_cards(self, columns: int) -> None:
        """Xếp lại các ô theo số cột (4 khi rộng, 2 khi hẹp)."""
        for i in reversed(range(self._quick_grid.count())):
            self._quick_grid.takeAt(i)
        for i, card in enumerate(self._quick_cards):
            self._quick_grid.addWidget(card, i // columns, i % columns)

    def _build_recent_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        row.addWidget(title_label("Dự án gần đây"))
        row.addStretch()
        button = GhostButton("Xem tất cả")
        button.clicked.connect(self.projects_requested.emit)
        row.addWidget(button)
        return row

    # -- Việc đang chạy ------------------------------------------------
    def _refresh_job(self) -> None:
        job = REGISTRY.current()
        if job is None:
            self.processing.show_idle()
            return
        self.processing.show_job(job.title, job.step_label, job.percent,
                                 format_eta(job.eta_s), job.thumbnail)

    def _stop_job(self) -> None:
        if not REGISTRY.request_cancel():
            TOASTS.info("Việc này được điều khiển ở trang khác. "
                        "Hãy mở đúng trang đó rồi bấm Dừng.")

    def _open_job_details(self) -> None:
        """Mở dự án đang chạy trong Trình chỉnh sửa để xem tiến trình chi tiết."""
        job = REGISTRY.current()
        if job is not None and job.work_dir:
            self.edit_requested.emit(job.work_dir)

    # -- Dữ liệu -------------------------------------------------------
    def on_shown(self) -> None:
        self.reload()

    def reload(self) -> None:
        """Quét lại thư mục kết quả ở luồng nền."""
        from autodub_gui.workers import ProjectScanWorker

        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        try:
            output_dir = self._settings_provider().output_dir
        except Exception:  # noqa: BLE001 — tệp cấu hình hỏng thì để trống
            output_dir = ""
        if not output_dir:
            self._apply([])
            return
        self.stats.set_loading()
        job = REGISTRY.current()
        worker = ProjectScanWorker(output_dir, job.work_dir if job else "", self)
        worker.ready.connect(self._apply)
        worker.failed.connect(self._on_scan_failed)
        self._scan_worker = worker
        worker.start()

    def _apply(self, found: list) -> None:
        self._projects = found
        self.stats.set_values(projects_mod.summarize(found))
        self.grid.set_projects(found)
        has_any = bool(found)
        self.grid.setVisible(has_any)
        self.empty.setVisible(not has_any)
        self._first_run_card.setVisible(not has_any)

    def _on_scan_failed(self, message: str) -> None:
        self._apply([])
        TOASTS.error("Không đọc được thư mục lưu video. Hãy kiểm tra lại "
                     "đường dẫn trong Cài đặt.", detail=message)

    def _project(self, key: str):
        return next((p for p in self._projects if p.key == key), None)

    # -- Thao tác trên thẻ ---------------------------------------------
    def _open_video(self, key: str) -> None:
        project = self._project(key)
        if project is None:
            return
        ok, message = open_file(project.output_path or project.video_path)
        if not ok:
            TOASTS.warn(message)

    def _open_folder(self, key: str) -> None:
        project = self._project(key)
        if project is None:
            return
        ok, message = open_folder(project.work_dir)
        if not ok:
            TOASTS.warn(message)

    def _hide_project(self, key: str) -> None:
        """Ở Trang chủ chỉ ẩn khỏi danh sách; muốn xóa hẳn thì vào Dự án của tôi."""
        self.grid.remove(key)
        TOASTS.info("Đã ẩn khỏi Trang chủ. Tệp trên máy vẫn còn nguyên.",
                    action_label="Mở Dự án của tôi",
                    on_action=self.projects_requested.emit)

    # -- Kéo thả -------------------------------------------------------
    def _on_file_chosen(self, path: str) -> None:
        """Kiểm tra nhanh rồi chuyển sang trang Tạo dự án với tệp đã điền sẵn."""
        if not os.path.isfile(path):
            self.dropzone.set_error("Không tìm thấy tệp này. Hãy thử chọn lại.")
            return
        if not is_video_file(path):
            self.dropzone.set_error(
                "Tệp này không phải video. Hãy chọn tệp MP4, MKV, MOV, AVI "
                "hoặc WebM.")
            return
        try:
            with open(path, "rb") as f:
                f.read(1)
        except OSError:
            self.dropzone.set_error(
                "Không đọc được tệp. Có thể tệp đang được chương trình khác "
                "sử dụng — hãy đóng chương trình đó rồi thử lại.")
            return
        self.dropzone.set_success(path)
        if os.path.getsize(path) > _large_file_limit():
            TOASTS.warn("Video này rất lớn, quá trình xử lý có thể mất "
                        "nhiều giờ.")
        self.create_requested.emit(path)

    def _on_many_files(self, paths: list) -> None:
        TOASTS.info(
            f"Chỉ nhận một video ở đây — {len(paths)} tệp bạn vừa thả sẽ chỉ "
            "lấy tệp đầu tiên. Dùng Xử lý hàng loạt cho nhiều video.",
            action_label="Mở Xử lý hàng loạt",
            on_action=self.batch_requested.emit)

    # -- Vòng đời ------------------------------------------------------
    def on_breakpoint(self, name: str) -> None:
        """Ở cửa sổ hẹp thì xếp ô tải lên và cột bên phải thành một cột dọc."""
        self.dropzone.setMinimumHeight(150 if name == "sm" else 180)
        self._layout_quick_cards(columns=2 if name in ("sm", "md") else 4)

    def cleanup(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.wait(2000)


def _large_file_limit() -> int:
    from autodub_gui.ui.dropzone import LARGE_FILE_BYTES

    return LARGE_FILE_BYTES
