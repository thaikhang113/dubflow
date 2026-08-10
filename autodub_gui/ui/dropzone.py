"""Vùng kéo thả video, đủ năm trạng thái theo đặc tả.

Nghỉ, đang kéo qua, đang chuẩn bị, đã sẵn sàng và lỗi.

Việc kiểm tra tệp (có đọc được không, có luồng hình ảnh không) do trang gọi
thực hiện ở luồng nền; vùng này chỉ lo hiển thị trạng thái.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QSizePolicy, QStackedLayout,
    QVBoxLayout, QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.ui.buttons import GhostButton, PrimaryButton
from autodub_gui.ui.labels import ElidedLabel
from autodub_gui.ui.progress import ThinProgressBar
from autodub_gui.ui.style import clear_background

VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".wmv")
VIDEO_FILTER = ("Video (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.flv *.wmv);;"
                "Tất cả tệp (*.*)")
SUPPORTED_TEXT = "Hỗ trợ: MP4, MOV, MKV, AVI, WebM — Tối đa 10GB"
LARGE_FILE_BYTES = 4 * 1024 ** 3      # trên mức này chỉ cảnh báo mềm, không chặn

_DASH_INSET = 10
_DASH_PATTERN = (6, 4)
_ICON_PX = 40
_INSET = _DASH_INSET + 6   # chừa chỗ cho viền nét đứt vẽ ở paintEvent
# Chiều cao tối thiểu phải đủ chứa nội dung cộng hai lề, nếu không chữ dưới
# cùng sẽ bị đẩy đè lên viền nét đứt.
_MIN_H = 212
_COMPACT_H = 152
_DRAG_TINT_ALPHA = 26      # khoảng 10% — nền xanh mờ khi đang kéo tệp qua


def is_video_file(path: str) -> bool:
    """Đuôi tệp có nằm trong danh sách định dạng video được hỗ trợ không."""
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


class DragDropZone(QWidget):
    """Vùng nhận video kéo thả hoặc chọn từ máy."""

    file_selected = Signal(str)       # đường dẫn tệp hợp lệ
    files_rejected = Signal(list)     # người dùng thả nhiều tệp một lúc
    retry_requested = Signal()

    STATES = ("idle", "dragover", "busy", "success", "error")

    def __init__(self, parent: QWidget | None = None, *, compact: bool = False):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._state = "idle"
        self._compact = compact
        self.setMinimumHeight(_COMPACT_H if compact else _MIN_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding if not compact
                           else QSizePolicy.Policy.Fixed)
        self._build()
        self._apply_state()

    # -- Dựng giao diện ------------------------------------------------
    def _build(self) -> None:
        self._stack = QStackedLayout(self)
        # QStackedLayout không áp lề của chính nó lên các trang con, nên lề
        # phải đặt ở từng trang; đặt ở đây thì nội dung vẫn tràn ra sát mép.
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._page_idle = self._build_idle()
        self._page_busy = self._build_busy()
        self._page_done = self._build_done()
        self._page_error = self._build_error()
        for page in (self._page_idle, self._page_busy,
                     self._page_done, self._page_error):
            self._stack.addWidget(page)

    def _centered(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        clear_background(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(_INSET, _INSET, _INSET, _INSET)
        layout.setSpacing(tokens.SP_2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return page, layout

    def _icon(self, icon, size: int = _ICON_PX) -> QLabel:
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(icon.pixmap(size, size))
        clear_background(label)
        return label

    def _text(self, text: str, *, size: int, color: str,
              weight: int = 500) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: {color}; font-size: {size}px; font-weight: {weight}; "
            f"background: transparent;")
        return label

    def _build_idle(self) -> QWidget:
        page, layout = self._centered()
        self._idle_icon = self._icon(icons.upload_cloud(),
                                     _ICON_PX if not self._compact else 26)
        layout.addWidget(self._idle_icon)
        self._idle_title = self._text("Kéo & thả video vào đây",
                                      size=tokens.FS_CARD_TITLE,
                                      color=tokens.TEXT_PRIMARY, weight=600)
        layout.addWidget(self._idle_title)
        if not self._compact:
            layout.addWidget(self._text("hoặc", size=tokens.FS_LABEL,
                                        color=tokens.TEXT_MUTED))
        row = QHBoxLayout()
        row.addStretch()
        self._btn_browse = PrimaryButton("Chọn file từ máy")
        self._btn_browse.clicked.connect(self.browse)
        row.addWidget(self._btn_browse)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(self._text(SUPPORTED_TEXT, size=tokens.FS_META,
                                    color=tokens.TEXT_MUTED, weight=400))
        return page

    def _build_busy(self) -> QWidget:
        page, layout = self._centered()
        self._busy_label = self._text("Đang chuẩn bị video…",
                                      size=tokens.FS_BODY,
                                      color=tokens.TEXT_PRIMARY, weight=600)
        layout.addWidget(self._busy_label)
        self._busy_bar = ThinProgressBar()
        self._busy_bar.setMinimumWidth(220)
        layout.addWidget(self._busy_bar)
        return page

    def _build_done(self) -> QWidget:
        page, layout = self._centered()
        layout.addWidget(self._icon(icons.check(tokens.SUCCESS), 32))
        layout.addWidget(self._text("Video đã sẵn sàng", size=tokens.FS_BODY,
                                    color=tokens.SUCCESS, weight=600))
        self._done_name = ElidedLabel("")
        self._done_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._done_name.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_LABEL}px; "
            f"background: transparent;")
        layout.addWidget(self._done_name)
        row = QHBoxLayout()
        row.addStretch()
        btn = GhostButton("Đổi video")
        btn.clicked.connect(self.browse)
        row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _build_error(self) -> QWidget:
        page, layout = self._centered()
        layout.addWidget(self._icon(icons.error(tokens.DANGER), 32))
        self._error_label = self._text("", size=tokens.FS_LABEL,
                                       color=tokens.DANGER, weight=500)
        layout.addWidget(self._error_label)
        row = QHBoxLayout()
        row.addStretch()
        btn = GhostButton("Thử lại")
        btn.clicked.connect(self._on_retry)
        row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    # -- Trạng thái ----------------------------------------------------
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        """Chuyển sang một trong năm trạng thái đã khai báo."""
        if state not in self.STATES:
            return
        self._state = state
        self._apply_state()

    def _apply_state(self) -> None:
        pages = {
            "idle": self._page_idle, "dragover": self._page_idle,
            "busy": self._page_busy, "success": self._page_done,
            "error": self._page_error,
        }
        self._stack.setCurrentWidget(pages[self._state])
        if self._state == "dragover":
            self._idle_title.setText("Thả video để tải lên")
        else:
            self._idle_title.setText("Kéo & thả video vào đây")
        self.update()

    def set_busy(self, percent: int, message: str = "") -> None:
        """Hiện tiến trình khi đang sao chép hoặc kiểm tra tệp."""
        self.set_state("busy")
        self._busy_bar.setValue(max(0, min(100, percent)))
        self._busy_label.setText(message or f"Đang chuẩn bị video… {percent}%")

    def set_success(self, path: str) -> None:
        """Tệp đã hợp lệ và sẵn sàng dùng."""
        self._done_name.setText(os.path.basename(path))
        self.set_state("success")

    def set_error(self, message: str) -> None:
        """Hiện lý do tệp không dùng được, kèm nút thử lại."""
        self._error_label.setText(message)
        self.set_state("error")

    def reset(self) -> None:
        """Quay về trạng thái nghỉ ban đầu."""
        self.set_state("idle")

    def _on_retry(self) -> None:
        self.reset()
        self.retry_requested.emit()

    # -- Tương tác -----------------------------------------------------
    def browse(self) -> None:
        """Mở hộp thoại chọn tệp video từ máy."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn video", os.path.expanduser("~"), VIDEO_FILTER)
        if path:
            self.file_selected.emit(path)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.set_state("dragover")

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        if self._state == "dragover":
            self.set_state("idle")
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        paths = [p for p in paths if p and os.path.isfile(p)]
        self.set_state("idle")
        if not paths:
            self.set_error("Không nhận được tệp nào. Hãy thử kéo lại một tệp "
                           "video từ máy của bạn.")
            return
        if len(paths) > 1:
            self.files_rejected.emit(paths)
        self.file_selected.emit(paths[0])

    def mousePressEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        if (event.button() == Qt.MouseButton.LeftButton
                and self._state in ("idle", "dragover")):
            self.browse()
        super().mousePressEvent(event)

    # -- Vẽ nền --------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -2, -2)
        outer = QPainterPath()
        outer.addRoundedRect(rect, tokens.RADIUS_LG, tokens.RADIUS_LG)

        active = self._state == "dragover"
        if active:
            tint = QColor(tokens.ACCENT_BLUE)
            tint.setAlpha(_DRAG_TINT_ALPHA)
            painter.fillPath(outer, tint)
            painter.setPen(QPen(QColor(tokens.BORDER_ACTIVE), 2))
        else:
            painter.fillPath(outer, QColor(tokens.BG_PANEL))
            painter.setPen(QPen(QColor(tokens.BORDER_UPLOAD), 1))
        painter.drawPath(outer)

        if not active:
            dashed = QPen(QColor(tokens.BORDER_DEFAULT), 1.5)
            dashed.setDashPattern(list(_DASH_PATTERN))
            painter.setPen(dashed)
            inner = QPainterPath()
            inner.addRoundedRect(
                rect.adjusted(_DASH_INSET, _DASH_INSET,
                              -_DASH_INSET, -_DASH_INSET),
                tokens.RADIUS_MD, tokens.RADIUS_MD)
            painter.drawPath(inner)
        painter.end()
