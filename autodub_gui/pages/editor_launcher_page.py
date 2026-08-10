"""Trang launcher khi click "Trình chỉnh sửa" nhưng chưa có project mở.

Hiển thị:
- Banner project đang mở (nếu có) với nút "Tiếp tục"
- Danh sách 8 project gần đây
- Nút "Mở thư mục..." fallback
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QScrollArea,
                                QVBoxLayout, QWidget)

from autodub_gui import tokens
from autodub_gui.pages import BasePage
from autodub_gui.ui.buttons import GhostButton, PrimaryButton
from autodub_gui.ui.cards import Card
from autodub_gui.ui.style import clear_background
from autodub_gui.ui.empty import EmptyState, LoadingState


class EditorLauncherPage(BasePage):
    """Trang trung gian: hiện khi ROW_EDITOR được chọn nhưng chưa có project."""

    open_requested = Signal(str)   # work_dir để mở editor

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._current_project_dir: str | None = None
        self._worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SP_6, tokens.SP_5,
                                tokens.SP_6, tokens.SP_6)
        root.setSpacing(tokens.SP_4)

        title = QLabel("Trình chỉnh sửa")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        hint = QLabel("Chọn một dự án để chỉnh sửa lời thoại, giọng đọc và phụ đề.")
        hint.setObjectName("hint")
        root.addWidget(hint)

        # Banner project đang mở
        self._current_banner = self._build_current_banner()
        root.addWidget(self._current_banner)

        # Danh sách gần đây
        recent_label = QLabel("Dự án gần đây")
        recent_label.setObjectName("sectionTitle")
        root.addWidget(recent_label)

        # Vùng cuộn để hiện các project card
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        clear_background(scroll)
        clear_background(scroll.viewport())

        self._list_body = QWidget()
        clear_background(self._list_body)
        self._list_layout = QVBoxLayout(self._list_body)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(tokens.SP_2)

        self._loading = LoadingState("Đang quét dự án...")
        self._list_layout.addWidget(self._loading)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_body)
        root.addWidget(scroll, 1)

        # Nút mở thư mục tùy chọn
        btn_open = GhostButton("Mở thư mục dự án...")
        btn_open.clicked.connect(self._browse_folder)
        btn_wrap = QWidget()
        clear_background(btn_wrap)
        btn_row = QHBoxLayout(btn_wrap)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addWidget(btn_open)
        btn_row.addStretch()
        root.addWidget(btn_wrap)

    # -- Banner project đang mở -------------------------------------------
    def _build_current_banner(self) -> QWidget:
        banner = Card(parent=self, padding=tokens.SP_4, spacing=0)
        banner.setVisible(False)
        layout = QHBoxLayout()
        layout.setSpacing(tokens.SP_3)
        banner.body.addLayout(layout)

        icon = QLabel("—")
        icon.setFixedSize(QSize(36, 36))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {tokens.PRIMARY};"
            f"background: {tokens.BG_SELECTED}; border-radius: 8px;")
        layout.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(2)
        self._banner_title = QLabel("—")
        self._banner_title.setObjectName("cardTitle")
        self._banner_sub = QLabel("Đang mở")
        self._banner_sub.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_LABEL}px;")
        col.addWidget(self._banner_title)
        col.addWidget(self._banner_sub)
        layout.addLayout(col, 1)

        btn_resume = PrimaryButton("Tiếp tục chỉnh sửa")
        btn_resume.clicked.connect(self._resume_current)
        layout.addWidget(btn_resume)

        self._banner_widget = banner
        return banner

    # -- Logic -----------------------------------------------------------
    def set_current_project(self, work_dir: str | None,
                            title: str = "") -> None:
        """Gọi từ app.py khi editor mở/đóng project để cập nhật banner."""
        self._current_project_dir = work_dir
        if work_dir:
            self._banner_title.setText(title or work_dir)
            self._banner_sub.setText("Đang mở — nhấn để tiếp tục chỉnh sửa")
            self._banner_widget.setVisible(True)
        else:
            self._banner_widget.setVisible(False)

    def _resume_current(self) -> None:
        if self._current_project_dir:
            self.open_requested.emit(self._current_project_dir)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục dự án", "",
            QFileDialog.Option.ShowDirsOnly)
        if folder:
            self.open_requested.emit(folder)

    def on_shown(self) -> None:
        """Quét danh sách project gần đây mỗi khi trang được mở."""
        self._start_scan()

    def _start_scan(self) -> None:
        import os

        from autodub_gui.workers import ProjectScanWorker

        settings = self._settings_provider()
        output_dir = getattr(settings, "output_dir", "") or "output"
        if not os.path.isabs(output_dir):
            from autodub.utils import app_root
            output_dir = os.path.join(app_root(), output_dir)

        if self._worker is not None:
            return

        # Reset UI về trạng thái loading
        self._clear_list()
        self._loading.setVisible(True)

        worker = ProjectScanWorker(output_dir, parent=self)
        worker.ready.connect(self._on_projects_ready)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(self._on_scan_finished)
        self._worker = worker
        worker.start()

    def _on_scan_finished(self) -> None:
        """Buông tham chiếu trước khi đối tượng C++ bị hủy.

        Giữ lại con trỏ đã deleteLater rồi gọi isRunning() lên nó sẽ ném
        RuntimeError của shiboken, nên phải xóa tham chiếu ngay tại đây.
        """
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

    def _clear_list(self) -> None:
        # Xóa hết widget (trừ loading và stretch cuối)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w and w is not self._loading:
                w.deleteLater()

    def _on_projects_ready(self, projects: list) -> None:
        self._loading.setVisible(False)
        recent = projects[:8]
        if not recent:
            empty = EmptyState(
                "Chưa có dự án nào",
                "Tạo dự án mới để bắt đầu, hoặc mở thư mục dự án có sẵn.",
                parent=self)
            self._list_layout.insertWidget(0, empty)
            return
        for project in recent:
            card = _ProjectRow(project)
            card.open_requested.connect(self.open_requested.emit)
            self._list_layout.insertWidget(
                self._list_layout.count() - 1, card)

    def _on_scan_failed(self, msg: str) -> None:
        # Reset con trỏ để lần mở trang tiếp theo có thể quét lại.
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self._loading.setVisible(False)
        from autodub_gui.ui.empty import ErrorState
        err = ErrorState("Không quét được danh sách dự án", msg)
        self._list_layout.insertWidget(0, err)

    def cleanup(self) -> None:
        """Chờ luồng quét dừng hẳn trước khi trang bị hủy."""
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.wait(3000)


# ---- Widget một dòng project ------------------------------------------
class _ProjectRow(QWidget):
    """Một dòng trong danh sách dự án gần đây."""

    open_requested = Signal(str)    # work_dir

    def __init__(self, project, parent: QWidget | None = None):
        super().__init__(parent)
        self._work_dir = project.work_dir
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        frame = Card(parent=self, padding=tokens.SP_3, spacing=0)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        row = QHBoxLayout()
        row.setSpacing(tokens.SP_3)
        frame.body.addLayout(row)

        # Trạng thái màu
        from autodub_gui.projects import (STATUS_COMPLETED, STATUS_FAILED,
                                           STATUS_PROCESSING)
        from autodub_gui import tokens as t
        color = {
            STATUS_COMPLETED: t.SUCCESS,
            STATUS_FAILED: t.DANGER,
            STATUS_PROCESSING: t.PRIMARY,
        }.get(project.status, t.TEXT_MUTED)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 10px; background: transparent;")
        row.addWidget(dot)

        col = QVBoxLayout()
        col.setSpacing(1)
        title = QLabel(project.title or project.work_dir)
        title.setObjectName("cardTitle")
        sub_parts = [project.status_label]
        if project.date_label:
            sub_parts.append(project.date_label)
        sub = QLabel("  ·  ".join(sub_parts))
        sub.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_LABEL}px;")
        col.addWidget(title)
        col.addWidget(sub)
        row.addLayout(col, 1)

        btn = GhostButton("Mở")
        btn.setFixedWidth(60)
        btn.clicked.connect(lambda: self.open_requested.emit(self._work_dir))
        row.addWidget(btn)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.open_requested.emit(self._work_dir)
