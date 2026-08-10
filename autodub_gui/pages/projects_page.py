"""Trang Dự án của tôi: tìm kiếm, lọc, sắp xếp và phân trang."""
from __future__ import annotations

import shutil

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from autodub_gui import icons, projects as projects_mod, tokens
from autodub_gui.pages import BasePage
from autodub_gui.run_state import REGISTRY
from autodub_gui.system_open import open_file, open_folder
from autodub_gui.ui.buttons import IconButton
from autodub_gui.ui.empty import EmptyState, ErrorState, LoadingState
from autodub_gui.ui.grid import ProjectGrid
from autodub_gui.ui.inputs import LabeledCombo, SearchBox
from autodub_gui.ui.modal import ConfirmDialog
from autodub_gui.ui.pagination import Pagination
from autodub_gui.ui.toast import TOASTS
from autodub_gui.ui.style import clear_background

PAGE_SIZE = 12
_PAGE_MARGIN = 28

_STATUS_FILTERS = [
    ("Tất cả trạng thái", ""),
    ("Hoàn thành", projects_mod.STATUS_COMPLETED),
    ("Đang xử lý", projects_mod.STATUS_PROCESSING),
    ("Chờ dịch", projects_mod.STATUS_PENDING),
    ("Chờ xuất video", projects_mod.STATUS_LOCKED),
    ("Lỗi", projects_mod.STATUS_FAILED),
]

_SORT_OPTIONS = [
    ("Mới nhất", "newest"),
    ("Cũ nhất", "oldest"),
    ("Tên A đến Z", "name"),
    ("Thời lượng dài nhất", "duration"),
]


class ProjectsPage(BasePage):
    """Toàn bộ dự án đã và đang xử lý."""

    edit_requested = Signal(str)
    create_requested = Signal()
    settings_requested = Signal()

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._scan_worker = None
        self._all: list = []
        self._filtered: list = []
        self._hidden: set[str] = set()
        self._page = 1
        self._build()

    # -- Dựng giao diện ------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(_PAGE_MARGIN, tokens.SP_2,
                                _PAGE_MARGIN, tokens.SP_5)
        root.setSpacing(tokens.SP_4)
        root.addLayout(self._build_toolbar())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_grid_page())
        self.loading = LoadingState("Đang đọc danh sách dự án")
        self.empty = EmptyState(
            "Chưa có dự án nào",
            "Lồng tiếng video đầu tiên của bạn — chỉ mất vài phút để bắt đầu.",
            "Tạo dự án mới")
        self.empty.action_clicked.connect(self.create_requested.emit)
        self.error = ErrorState(
            "Không mở được thư mục lưu video",
            action_label="Mở Cài đặt")
        self.error.retry_clicked.connect(self.reload)
        self.error.action_clicked.connect(self.settings_requested.emit)
        for widget in (self.loading, self.empty, self.error):
            self.stack.addWidget(widget)
        root.addWidget(self.stack, 1)

        self.pagination = Pagination()
        self.pagination.page_changed.connect(self._go_to_page)
        root.addWidget(self.pagination)

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_3)
        self.search = SearchBox("Tìm theo tên video")
        self.search.search_changed.connect(lambda _t: self._apply_filters())
        row.addWidget(self.search, 1)

        self.filter_status = LabeledCombo("", _STATUS_FILTERS,
                                          "Chỉ hiện dự án ở trạng thái đã chọn")
        self.filter_status.changed.connect(self._apply_filters)
        row.addWidget(self.filter_status)

        self.sort_by = LabeledCombo("", _SORT_OPTIONS,
                                    "Thứ tự sắp xếp danh sách")
        self.sort_by.changed.connect(self._apply_filters)
        row.addWidget(self.sort_by)

        reload_button = IconButton(icons.reload(tokens.TEXT_SECONDARY),
                                   "Quét lại thư mục lưu video")
        reload_button.clicked.connect(self.reload)
        row.addWidget(reload_button)
        return row

    def _build_grid_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        clear_background(holder)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SP_3)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        layout.addWidget(self.count_label)

        self.grid = ProjectGrid()
        self.grid.card_clicked.connect(self.edit_requested.emit)
        self.grid.edit_project.connect(self.edit_requested.emit)
        self.grid.open_video.connect(self._open_video)
        self.grid.open_folder.connect(self._open_folder)
        self.grid.delete_project.connect(self._delete)
        layout.addWidget(self.grid)
        layout.addStretch()
        scroll.setWidget(holder)
        return scroll

    # -- Dữ liệu -------------------------------------------------------
    def on_shown(self) -> None:
        if not self._all:
            self.reload()

    def reload(self) -> None:
        """Quét lại toàn bộ thư mục kết quả."""
        from autodub_gui.workers import ProjectScanWorker

        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        try:
            output_dir = self._settings_provider().output_dir
        except Exception as e:  # noqa: BLE001 — tệp cấu hình hỏng
            self._show_error(str(e))
            return
        self.stack.setCurrentWidget(self.loading)
        job = REGISTRY.current()
        worker = ProjectScanWorker(output_dir, job.work_dir if job else "", self)
        worker.ready.connect(self._on_scanned)
        worker.failed.connect(self._show_error)
        self._scan_worker = worker
        worker.start()

    def _on_scanned(self, found: list) -> None:
        self._all = found
        self._page = 1
        self._apply_filters()

    def _show_error(self, message: str) -> None:
        self.error.set_message(
            "Không mở được thư mục lưu video",
            "Thư mục đã đặt trong Cài đặt hiện không tồn tại hoặc không có "
            f"quyền đọc. Hãy chọn một thư mục khác rồi thử lại. ({message})")
        self.stack.setCurrentWidget(self.error)

    def _apply_filters(self) -> None:
        visible = [p for p in self._all if p.key not in self._hidden]
        self._filtered = projects_mod.filter_projects(
            visible, self.search.text(), self.filter_status.current_key(),
            self.sort_by.current_key())
        total_pages = max(1, (len(self._filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
        self._page = min(self._page, total_pages)
        self.pagination.set_range(self._page, total_pages)
        self._render_page()

    def _render_page(self) -> None:
        if not self._filtered:
            self._render_empty()
            return
        start = (self._page - 1) * PAGE_SIZE
        page_items = self._filtered[start:start + PAGE_SIZE]
        self.grid.set_projects(page_items)
        self.count_label.setText(
            f"{len(self._filtered)} dự án — đang xem "
            f"{start + 1} đến {start + len(page_items)}")
        self.stack.setCurrentIndex(0)
        self.pagination.setVisible(len(self._filtered) > PAGE_SIZE)

    def _render_empty(self) -> None:
        """Không có kết quả: nói rõ vì đang lọc hay vì chưa có dự án nào."""
        filtering = bool(self.search.text() or self.filter_status.current_key())
        if filtering:
            self.empty.setVisible(True)
            self.count_label.setText("")
            self.grid.clear()
            self.stack.setCurrentIndex(0)
            self.count_label.setText(
                "Không có dự án nào khớp với bộ lọc hiện tại.")
        else:
            self.stack.setCurrentWidget(self.empty)
        self.pagination.setVisible(False)

    def _go_to_page(self, page: int) -> None:
        self._page = page
        self._render_page()

    def _project(self, key: str):
        return next((p for p in self._all if p.key == key), None)

    # -- Thao tác ------------------------------------------------------
    def _open_video(self, key: str) -> None:
        project = self._project(key)
        if project is None:
            return
        target = project.output_path or project.video_path
        if not target:
            TOASTS.warn("Dự án này chưa có video kết quả. Hãy mở Trình chỉnh "
                        "sửa rồi bấm Xuất video.")
            return
        ok, message = open_file(target)
        if not ok:
            TOASTS.warn(message)

    def _open_folder(self, key: str) -> None:
        project = self._project(key)
        if project is None:
            return
        ok, message = open_folder(project.work_dir)
        if not ok:
            TOASTS.warn(message)

    def _delete(self, key: str) -> None:
        """Hỏi kỹ trước khi xóa. Mặc định chỉ ẩn khỏi danh sách cho an toàn."""
        project = self._project(key)
        if project is None:
            return
        confirmed, hide_only = ConfirmDialog.ask(
            self, "Xóa dự án",
            f"Bạn muốn bỏ dự án «{project.title}» khỏi danh sách?\n\n"
            "Nếu bỏ dấu tích bên dưới, toàn bộ thư mục dự án sẽ bị xóa khỏi "
            "máy và không thể lấy lại.",
            kind="danger", confirm_label="Xóa", cancel_label="Giữ lại",
            checkbox_label="Chỉ ẩn khỏi danh sách, giữ tệp trên máy",
            checkbox_checked=True)
        if not confirmed:
            return
        if hide_only:
            self._hidden.add(key)
            self._apply_filters()
            TOASTS.info("Đã ẩn khỏi danh sách. Tệp trên máy vẫn còn nguyên.")
            return
        try:
            shutil.rmtree(project.work_dir)
        except OSError as e:
            TOASTS.error(
                "Không xóa được thư mục dự án. Có thể một tệp trong đó đang "
                "được chương trình khác mở — hãy đóng lại rồi thử lần nữa.",
                detail=str(e))
            return
        self._all = [p for p in self._all if p.key != key]
        self._apply_filters()
        TOASTS.success(f"Đã xóa dự án «{project.title}» khỏi máy.")

    # -- Vòng đời ------------------------------------------------------
    def on_breakpoint(self, name: str) -> None:
        self.grid.setProperty("breakpoint", name)

    def focus_search(self) -> None:
        """Đưa con trỏ vào ô tìm kiếm, dùng cho phím tắt."""
        self.search.focus()

    def cleanup(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.wait(2000)
