"""Lưới thẻ dự án, tự đổi số cột theo bề rộng cửa sổ."""
from __future__ import annotations

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget

from autodub_gui import tokens
from autodub_gui.ui.cards import ProjectCard

# Bề rộng cửa sổ tối thiểu để hiện đủ số cột tương ứng
_COLUMN_RULES = ((1440, 4), (1024, 3), (0, 2))
_MAX_THUMB_JOBS = 4


class ProjectGrid(QWidget):
    """Lưới thẻ dự án. Ảnh đại diện được tạo dần ở luồng nền."""

    open_video = Signal(str)
    open_folder = Signal(str)
    edit_project = Signal(str)
    delete_project = Signal(str)
    card_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, max_items: int = 0,
                 columns: int = 0):
        super().__init__(parent)
        self._max_items = max_items
        self._fixed_columns = columns
        self._cards: dict[str, ProjectCard] = {}
        self._order: list[str] = []
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(_MAX_THUMB_JOBS)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(tokens.SP_4)
        self._columns = 0

    # -- Đổ dữ liệu ----------------------------------------------------
    def set_projects(self, projects: list) -> None:
        """Dựng lại toàn bộ lưới từ danh sách dự án."""
        self.clear()
        shown = projects[:self._max_items] if self._max_items else projects
        for project in shown:
            card = ProjectCard(self)
            card.set_project(project.key, project.title, project.date_label,
                             project.status, project.status_label,
                             project.duration_s)
            card.open_video.connect(self.open_video.emit)
            card.open_folder.connect(self.open_folder.emit)
            card.edit_project.connect(self.edit_project.emit)
            card.delete_project.connect(self.delete_project.emit)
            card.clicked.connect(self.card_clicked.emit)
            self._cards[project.key] = card
            self._order.append(project.key)
            self._load_thumbnail(project, card)
        self._relayout(force=True)

    def _load_thumbnail(self, project, card: ProjectCard) -> None:
        """Dùng ảnh đã có ngay, còn không thì nhờ luồng nền tạo."""
        import os

        from autodub_gui.workers import ThumbnailWorker

        if project.thumb_path and os.path.isfile(project.thumb_path):
            card.set_thumbnail(QPixmap(project.thumb_path))
            return
        worker = ThumbnailWorker(project)
        worker.signals.ready.connect(self._on_thumbnail)
        self._pool.start(worker)

    def _on_thumbnail(self, key: str, path: str) -> None:
        card = self._cards.get(key)
        if card is not None:
            card.set_thumbnail(QPixmap(path))

    def clear(self) -> None:
        """Bỏ mọi thẻ đang có."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards.clear()
        self._order.clear()

    def remove(self, key: str) -> None:
        """Bỏ một thẻ khỏi lưới, dùng khi người dùng ẩn hoặc xóa dự án."""
        card = self._cards.pop(key, None)
        if card is None:
            return
        if key in self._order:
            self._order.remove(key)
        card.setParent(None)
        card.deleteLater()
        self._relayout(force=True)

    def count(self) -> int:
        return len(self._cards)

    # -- Bố trí --------------------------------------------------------
    def _column_count(self) -> int:
        if self._fixed_columns:
            return self._fixed_columns
        width = self.width() or tokens.CARD_MIN_W
        for threshold, columns in _COLUMN_RULES:
            if width >= threshold:
                return columns
        return 2

    def _relayout(self, force: bool = False) -> None:
        columns = self._column_count()
        if columns == self._columns and not force:
            return
        self._columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, key in enumerate(self._order):
            card = self._cards[key]
            self._grid.addWidget(card, index // columns, index % columns)
        for column in range(max(columns, self._grid.columnCount())):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        super().resizeEvent(event)
        self._relayout()
