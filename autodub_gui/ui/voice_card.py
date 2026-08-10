"""Thẻ giọng đọc trong thư viện giọng: avatar, tên, nhãn lọc và nút nghe thử.

Thanh sóng âm bên dưới chỉ là trang trí — cao độ các cột sinh từ tên giọng
bằng hàm băm ổn định, nên mỗi giọng có một "vân sóng" riêng không đổi.
"""
from __future__ import annotations

import zlib

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from autodub_gui import tokens
from autodub_gui.ui.avatar import InitialAvatar
from autodub_gui.ui.badges import StatusBadge
from autodub_gui.ui.buttons import GhostButton

_BAR_COUNT = 24
_BAR_HEIGHT = 26


class WaveformBar(QWidget):
    """Dãy cột dọc mô phỏng dạng sóng, sinh ổn định từ một chuỗi hạt giống."""

    def __init__(self, seed: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._heights = self._make_heights(seed)
        self.setFixedHeight(_BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    @staticmethod
    def _make_heights(seed: str) -> list[float]:
        """Cao độ 0.25..1.0 cho từng cột, băm từ seed nên không đổi."""
        heights: list[float] = []
        for i in range(_BAR_COUNT):
            h = zlib.crc32(f"{seed}:{i}".encode("utf-8")) % 100
            heights.append(0.25 + (h / 100) * 0.75)
        return heights

    def sizeHint(self) -> QSize:  # noqa: N802 — theo quy ước của Qt
        return QSize(120, _BAR_HEIGHT)

    def paintEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        step = w / _BAR_COUNT
        pen = QPen(QColor(tokens.WAVEFORM), max(1.6, step * 0.45),
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        cy = h / 2
        for i, ratio in enumerate(self._heights):
            x = step * (i + 0.5)
            half = (h - 4) * ratio / 2
            painter.drawLine(QPointF(x, cy - half), QPointF(x, cy + half))
        painter.end()


class VoiceCard(QFrame):
    """Một giọng đọc trong lưới: bấm vào thẻ để chọn, nút riêng để nghe thử."""

    selected = Signal(str)              # tên giọng vừa được chọn
    preview_requested = Signal(str)     # tên giọng cần nghe thử

    def __init__(self, voice, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("voiceCard")
        self.voice = voice
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()

    def _build(self) -> None:
        from autodub.speech.tts.voices import (
            COUNTRIES, GENDERS, STYLES,
        )
        gender_label = dict((k, v) for v, k in GENDERS)
        country_label = dict((k, v) for v, k in COUNTRIES)
        style_label = dict((k, v) for v, k in STYLES)

        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SP_4, tokens.SP_4,
                                tokens.SP_4, tokens.SP_3)
        root.setSpacing(tokens.SP_2)

        # Hàng đầu: avatar + tên + huy hiệu giới tính
        top = QHBoxLayout()
        top.setSpacing(tokens.SP_3)
        top.addWidget(InitialAvatar(self.voice.name, 44))

        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        name = QLabel(self.voice.name)
        name.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_CARD_TITLE}px; "
            f"font-weight: 600; background: transparent;")
        name_col.addWidget(name)
        sub_parts = [country_label.get(self.voice.country, ""),
                     style_label.get(self.voice.style, "")]
        sub = QLabel(" · ".join(p for p in sub_parts if p))
        sub.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_LABEL}px; "
            f"background: transparent;")
        name_col.addWidget(sub)
        top.addLayout(name_col, 1)

        gender_text = gender_label.get(self.voice.gender, "")
        if gender_text:
            badge = StatusBadge(
                gender_text,
                "accent" if self.voice.gender == "female" else "processing")
            top.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(top)

        # Thanh sóng trang trí
        root.addWidget(WaveformBar(self.voice.name))

        # Hàng cuối: nhãn nguồn + nút nghe thử
        bottom = QHBoxLayout()
        bottom.setSpacing(tokens.SP_2)
        if self.voice.custom:
            origin = QLabel("Giọng bạn thêm")
            origin.setStyleSheet(
                f"color: {tokens.ACCENT_PURPLE}; "
                f"font-size: {tokens.FS_META}px; background: transparent;")
            bottom.addWidget(origin)
        bottom.addStretch()
        self.btn_preview = GhostButton("Nghe thử")
        # Chỉ nhận focus qua phím Tab: nút này bị khóa tạm trong lúc phát,
        # nếu nó đang giữ focus do cú bấm chuột thì Qt sẽ chuyển focus đi
        # nơi khác và lưới giọng tự cuộn theo — rất khó chịu.
        self.btn_preview.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_preview.clicked.connect(
            lambda: self.preview_requested.emit(self.voice.name))
        bottom.addWidget(self.btn_preview)
        root.addLayout(bottom)

    # -- Trạng thái chọn -------------------------------------------------
    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        """Đổi diện mạo qua dynamic property (QSS [selected="true"])."""
        if selected == self._selected:
            return
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_preview_enabled(self, enabled: bool) -> None:
        self.btn_preview.setEnabled(enabled)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — quy ước Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.voice.name)
        super().mouseReleaseEvent(event)
