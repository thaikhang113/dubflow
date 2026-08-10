"""Reusable widgets: step tracker, log panel, status banner.

State indicators are drawn (small squares/dots) rather than typed as text
glyphs, so rendering is identical on every system font.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor, QPainter, QTextCursor
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QSizePolicy, QVBoxLayout, QWidget,
)

from autodub.progress import ProgressEvent, STEPS
from autodub_gui import theme, tokens

STEP_LABELS = {
    "acquire": "Tải video",
    "extract": "Tách âm thanh",
    "separate": "Tách nhạc nền",
    "asr": "Nghe lời thoại gốc",
    "translate": "Dịch sang tiếng Việt",
    "tts": "Tạo giọng đọc",
    "merge_audio": "Ghép âm thanh",
    "merge_video": "Xuất video",
    "content": "Tiêu đề & mô tả",
}

_STATE_COLOR = {
    "idle": theme.TEXT_DIM,
    "start": theme.RUNNING,
    "progress": theme.RUNNING,
    "done": theme.SUCCESS,
    "skip": theme.TEXT_DIM,
    "error": theme.ERROR,
    "warn": theme.WARNING,
}
_STATE_TEXT = {
    "idle": "",
    "start": "đang chạy",
    "progress": "đang chạy",
    "done": "xong",
    "skip": "đã có sẵn",
    "error": "lỗi",
}


class StatusDot(QWidget):
    """A small painted circle whose colour reflects a step state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor(theme.TEXT_DIM)
        self._filled = False
        self.setFixedSize(QSize(14, 14))

    def set_state(self, state: str) -> None:
        self._color = QColor(_STATE_COLOR.get(state, theme.TEXT_DIM))
        self._filled = state in ("start", "progress", "done", "error")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(3, 3, -3, -3)
        if self._filled:
            p.setBrush(self._color)
            p.setPen(Qt.NoPen)
        else:
            p.setBrush(Qt.NoBrush)
            pen = p.pen()
            pen.setColor(self._color)
            pen.setWidth(1)
            p.setPen(pen)
        p.drawEllipse(rect)
        p.end()


class StepTracker(QWidget):
    """Grid of pipeline steps: dot | name | status text, plus a TTS bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(1, 1)

        self._rows: dict[str, tuple[StatusDot, QLabel, QLabel]] = {}
        for i, step in enumerate(s for s in STEPS if s != "done"):
            dot = StatusDot()
            name = QLabel(STEP_LABELS.get(step, step))
            name.setStyleSheet(f"color: {theme.TEXT_DIM};")
            status = QLabel("")
            status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
            status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(dot, i, 0)
            grid.addWidget(name, i, 1)
            grid.addWidget(status, i, 2)
            self._rows[step] = (dot, name, status)

        layout.addLayout(grid)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(16)   # tall enough to render the % text
        self._bar.setVisible(False)
        layout.addWidget(self._bar)
        # First-progress timestamps per step, for the ETA estimate.
        self._t0: dict[str, float] = {}

    @staticmethod
    def _fmt_eta(seconds: float) -> str:
        s = max(0, int(seconds))
        if s < 60:
            return f"{s} giây"
        m, s = divmod(s, 60)
        if m < 60:
            return f"{m} phút" if m >= 10 or not s else f"{m} phút {s} giây"
        h, m = divmod(m, 60)
        return f"{h} giờ {m} phút"

    def reset(self) -> None:
        for step, (dot, name, status) in self._rows.items():
            dot.set_state("idle")
            name.setStyleSheet(f"color: {theme.TEXT_DIM};")
            status.setText("")
            status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
            self._set_row_visible(step, True)
        self._bar.setVisible(False)
        self._bar.setValue(0)
        self._t0.clear()

    def _set_row_visible(self, step: str, visible: bool) -> None:
        for w in self._rows[step]:
            w.setVisible(visible)

    def show_only(self, steps) -> None:
        """Chỉ hiện các bước trong ``steps``, ẩn hẳn phần còn lại.

        Dùng cho pha Xuất video: lần chạy đó chỉ làm ghép video và viết mô tả,
        nên bày lại cả 7 bước đã xong ở trạng thái xám khiến người dùng tưởng
        phải làm lại từ đầu.
        """
        keep = set(steps)
        for step in self._rows:
            self._set_row_visible(step, step in keep)

    def apply_event(self, ev: ProgressEvent) -> None:
        if ev.step == "done":
            self._bar.setVisible(False)
            return
        row = self._rows.get(ev.step)
        if not row:
            return
        dot, name, status = row
        state = ev.status if ev.status in _STATE_COLOR else "start"
        dot.set_state(state)
        name.setStyleSheet(
            f"color: {theme.TEXT if state != 'idle' else theme.TEXT_DIM};")
        color = _STATE_COLOR[state]
        status.setStyleSheet(f"color: {color}; font-size: 12px;")

        if ev.status == "progress" and ev.total:
            # Remaining-time estimate from this step's own throughput.
            t0 = self._t0.setdefault(ev.step, time.monotonic())
            text = f"{ev.current}/{ev.total}"
            if ev.current >= 3:
                elapsed = time.monotonic() - t0
                remain = elapsed / ev.current * (ev.total - ev.current)
                text += f" ~{self._fmt_eta(remain)}"
            status.setText(text)
            if ev.step == "tts":
                self._bar.setVisible(True)
                self._bar.setMaximum(ev.total)
                self._bar.setValue(ev.current)
        elif ev.step == "tts" and ev.status == "done":
            self._bar.setVisible(False)
            status.setText("xong")
        elif ev.status == "error":
            status.setText("lỗi")
            status.setToolTip(ev.detail or "")
        else:
            status.setText(_STATE_TEXT.get(state, ""))


class LogPanel(QPlainTextEdit):
    """Khung Nhật ký chỉ đọc: tô màu theo mức, ghi đè tại chỗ dòng tiến trình.

    Có ba mức hiển thị ngoài các mức logging chuẩn:
    - ``logging.INFO`` (20) — màu TEXT_MUTED (mặc định)
    - ``logging.WARNING`` (30) — màu WARNING
    - ``logging.ERROR`` (40) — màu ERROR
    - ``log_text.SUCCESS`` (25) — màu SUCCESS (dùng cho dòng "đã xong")

    Dòng "tiến trình" (``is_progress=True``) ghi đè dòng trước nếu dòng trước
    cũng là tiến trình — video nghìn câu không làm ngập Nhật ký.
    """

    MAX_BLOCKS = 600

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(self.MAX_BLOCKS)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {tokens.LOG_BG}; "
            f"color: {theme.TEXT_MUTED}; "
            f"font-family: 'Segoe UI', sans-serif; font-size: 13px; "
            f"border: 1px solid {theme.BORDER}; padding: 4px 8px; }}")
        self._last_is_progress = False

    def _color_for(self, levelno: int) -> str:
        from autodub_gui.log_text import SUCCESS
        if levelno >= logging.ERROR:
            return theme.ERROR
        if levelno >= logging.WARNING:
            return theme.WARNING
        if levelno == SUCCESS:
            return theme.SUCCESS
        return theme.TEXT_MUTED

    def append_log(self, message: str, levelno: int,
                   is_progress: bool = False) -> None:
        """Thêm một dòng mới vào Nhật ký.

        ``is_progress=True``: ghi đè dòng cuối nếu nó cũng là dòng tiến trình,
        thay vì chèn thêm — tránh làm ngập panel khi số câu lớn.
        """
        color = self._color_for(levelno)
        escaped = (message.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))
        html = f'<span style="color:{color};">{escaped}</span>'

        if is_progress and self._last_is_progress:
            # Xoá dòng cuối, thay bằng dòng mới.
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            # removeSelectedText có thể để lại dòng trống — xoá nốt nếu cần.
            cursor.movePosition(QTextCursor.End)
            if cursor.block().text().strip():
                # vẫn còn chữ: thêm dòng mới trước khi viết
                self.appendHtml(html)
            else:
                cursor.insertHtml(html)
        else:
            self.appendHtml(html)

        self._last_is_progress = is_progress
        self.moveCursor(QTextCursor.End)

    def reset_log(self) -> None:
        """Xoá toàn bộ nhật ký và reset cờ tiến trình."""
        self.clear()
        self._last_is_progress = False


class RunStatsPanel(QFrame):
    """Dải số liệu của lần chạy: số câu thoại và Vox tạm tính.

    Số câu lấy từ sự kiện ``asr done`` (detail "N segments"); Vox tích lũy
    đọc từ ``USAGE`` mỗi giây trong lúc dịch — đúng con số máy chủ báo về
    sau từng lô, nên khớp với thẻ tổng kết ở bước Xuất video.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("runstats")
        self.setStyleSheet(
            f"QFrame#runstats {{ background: {theme.BG_PANEL}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 3px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(18)
        self._sentences = QLabel("")
        self._vox = QLabel("")
        for label in (self._sentences, self._vox):
            label.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px;")
            row.addWidget(label)
        row.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)

    def reset(self) -> None:
        self._timer.stop()
        self._sentences.setText("")
        self._vox.setText("")

    def apply_event(self, ev: ProgressEvent) -> None:
        if ev.step == "asr" and ev.status in ("done", "skip"):
            # detail có dạng "123 segments" hoặc "123 segments (cached)"
            head = str(ev.detail or "").split(" ", 1)[0]
            if head.isdigit():
                self._sentences.setText(f"Số câu thoại: {int(head):,}")
        elif ev.step == "translate" and ev.status in ("start", "progress"):
            if not self._timer.isActive():
                self._poll()
                self._timer.start()
        elif ev.step == "done" or ev.status == "error":
            self._timer.stop()
            self._poll()

    def _poll(self) -> None:
        from autodub.text.translate_common import USAGE

        vox = USAGE.snapshot()["vox"]
        if vox:
            self._vox.setText(f"Vox tạm tính: {vox:,}")

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt API
        self._timer.stop()
        super().hideEvent(event)


class Banner(QFrame):
    """Inline notice panel with a coloured left edge and action buttons."""

    def __init__(self, kind: str, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        color = {"success": theme.SUCCESS, "warning": theme.WARNING,
                 "error": theme.ERROR}.get(kind, theme.ACCENT)
        self.setStyleSheet(
            f"QFrame#banner {{ background: {theme.BG_PANEL}; "
            f"border: 1px solid {theme.BORDER}; border-left: 3px solid {color}; "
            f"border-radius: 3px; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        self._title = QLabel(title)
        self._title.setStyleSheet(f"color: {color}; font-weight: 600;")
        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._body.setStyleSheet(f"color: {theme.TEXT};")

        self._buttons = QHBoxLayout()
        self._buttons.setSpacing(6)
        self._buttons.addStretch()

        outer.addWidget(self._title)
        outer.addWidget(self._body)
        outer.addLayout(self._buttons)
        self.setVisible(False)

    def set_text(self, text: str) -> None:
        self._body.setText(text)

    def add_button(self, button) -> None:
        # insert before the stretch
        self._buttons.insertWidget(self._buttons.count() - 1, button)
