"""Các loại thẻ dùng ở Trang chủ và trang Dự án của tôi."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.formatting import format_duration
from autodub_gui.ui.badges import STATUS_KIND, StatusBadge
from autodub_gui.ui.buttons import GhostButton, IconButton
from autodub_gui.ui.labels import ElidedLabel
from autodub_gui.ui.progress import ThinProgressBar
from autodub_gui.ui.style import clear_background

THUMB_W, THUMB_H = 96, 54          # ảnh nhỏ trong thẻ "đang xử lý"
CARD_THUMB_RATIO = 9 / 16
_DUR_BADGE_PAD = 6
_DUR_BADGE_H = 18
_DUR_BADGE_ALPHA = 184
_PLAY_ALPHA = 150
_ACTION_ICON = 28
_INFO_BLOCK_H = 78                 # phần chữ bên dưới ảnh của thẻ dự án


class Card(QFrame):
    """Khung thẻ cơ bản: nền tối, viền mờ, bo góc."""

    def __init__(self, parent: QWidget | None = None, *,
                 padding: int = tokens.SP_4, spacing: int = tokens.SP_3):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)

    def add_header(self, title: str, action: QWidget | None = None) -> QHBoxLayout:
        """Thêm hàng tiêu đề, kèm một widget hành động ở bên phải nếu có."""
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        label = QLabel(title)
        label.setObjectName("cardTitle")
        row.addWidget(label)
        row.addStretch()
        if action is not None:
            row.addWidget(action)
        self.body.addLayout(row)
        return row


class ThumbnailLabel(QLabel):
    """Ô ảnh đại diện 16:9, bo góc trên, có huy hiệu thời lượng ở góc dưới phải."""

    def __init__(self, parent: QWidget | None = None, *,
                 round_top_only: bool = True):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._duration = 0.0
        self._round_top_only = round_top_only
        self._show_play = False
        self.setMinimumHeight(int(tokens.CARD_MIN_W * CARD_THUMB_RATIO))
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        clear_background(self)

    def set_thumbnail(self, pixmap: QPixmap | None) -> None:
        """Đặt ảnh; truyền None để quay về ô giữ chỗ."""
        self._pixmap = pixmap
        self.update()

    def set_duration(self, seconds: float) -> None:
        """Thời lượng video hiện trong huy hiệu góc dưới phải."""
        self._duration = seconds or 0.0
        self.update()

    def set_play_overlay(self, shown: bool) -> None:
        """Hiện lớp phủ mờ kèm nút phát khi con trỏ đi qua thẻ."""
        if shown != self._show_play:
            self._show_play = shown
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        radius = tokens.RADIUS_LG - 2
        clip = QPainterPath()
        rect = self.rect()
        if self._round_top_only:
            clip.addRoundedRect(rect.adjusted(0, 0, 0, radius), radius, radius)
            clip.addRect(QRect(rect.left(), rect.bottom() - radius,
                               rect.width(), radius + 1))
            clip = clip.simplified()
        else:
            clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(tokens.BG_INPUT))

        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width() - scaled.width()) // 2,
                               (self.height() - scaled.height()) // 2, scaled)
        else:
            pixmap = icons.waveform(tokens.TEXT_DISABLED).pixmap(28, 28)
            painter.drawPixmap((self.width() - 28) // 2,
                               (self.height() - 28) // 2, pixmap)

        if self._show_play:
            overlay = QColor(0, 0, 0, _PLAY_ALPHA)
            painter.fillRect(rect, overlay)
            play = icons.play(tokens.TEXT_ON_ACCENT).pixmap(30, 30)
            painter.drawPixmap((self.width() - 30) // 2,
                               (self.height() - 30) // 2, play)

        if self._duration > 0:
            text = format_duration(self._duration)
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(text) + _DUR_BADGE_PAD * 2
            badge = QRect(self.width() - width - 8,
                          self.height() - _DUR_BADGE_H - 8,
                          width, _DUR_BADGE_H)
            path = QPainterPath()
            path.addRoundedRect(badge, 5, 5)
            painter.fillPath(path, QColor(0, 0, 0, _DUR_BADGE_ALPHA))
            painter.setPen(QColor(tokens.TEXT_ON_ACCENT))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class StatCard(QWidget):
    """Ô số liệu: biểu tượng nhỏ, con số và nhãn mô tả."""

    def __init__(self, label: str, icon_fn, color: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SP_3, tokens.SP_2,
                                tokens.SP_3, tokens.SP_2)
        root.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(tokens.SP_2)
        icon = QLabel()
        icon.setPixmap(icon_fn(color).pixmap(14, 14))
        clear_background(icon)
        self.value = QLabel("—")
        self.value.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 15px; "
            f"font-weight: 700; background: transparent;")
        top.addWidget(icon)
        top.addWidget(self.value)
        top.addStretch()
        root.addLayout(top)
        caption = QLabel(label)
        caption.setWordWrap(True)
        caption.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_BADGE}px; "
            f"background: transparent;")
        root.addWidget(caption)

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class StatGrid(Card):
    """Lưới hai hàng hai cột chứa các ô số liệu."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent, padding=tokens.SP_3, spacing=tokens.SP_2)
        self.add_header(title)
        grid = QGridLayout()
        grid.setSpacing(tokens.SP_2)
        self.cards: dict[str, StatCard] = {
            "completed": StatCard("Dự án hoàn thành", icons.check, tokens.SUCCESS),
            "time": StatCard("Thời gian đã xử lý", icons.reload, tokens.ACCENT_BLUE),
            "size": StatCard("Dung lượng đã dùng", icons.layers, tokens.ACCENT_PURPLE),
            "rate": StatCard("Tỷ lệ thành công", icons.waveform, tokens.WARNING),
        }
        for i, card in enumerate(self.cards.values()):
            grid.addWidget(card, i // 2, i % 2)
        self.body.addLayout(grid)

    def set_values(self, values: dict[str, str]) -> None:
        """Điền số liệu đã tính xong."""
        for key, text in values.items():
            if key in self.cards:
                self.cards[key].set_value(text)

    def set_loading(self) -> None:
        """Hiện chỗ giữ tạm trong lúc luồng nền đang đếm."""
        for card in self.cards.values():
            card.set_value("…")


class ProcessingCard(Card):
    """Thẻ "Dự án đang xử lý", gắn với sổ đăng ký tiến trình."""

    stop_requested = Signal()
    create_requested = Signal()
    details_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, padding=tokens.SP_3, spacing=tokens.SP_2)
        self.add_header("Dự án đang xử lý")

        # Hai khối này nằm TRONG thẻ nên phải trong suốt: bảng kiểu chung đặt
        # nền cho mọi QWidget, giữ nguyên thì chúng vẽ ra một hình chữ nhật
        # tối đè lên nền thẻ, nhìn như một hộp rời rạc.
        self._busy = QWidget()
        clear_background(self._busy)
        busy = QVBoxLayout(self._busy)
        busy.setContentsMargins(0, 0, 0, 0)
        busy.setSpacing(tokens.SP_2)

        row = QHBoxLayout()
        row.setSpacing(tokens.SP_3)
        self._thumb = ThumbnailLabel(round_top_only=False)
        self._thumb.setFixedSize(THUMB_W, THUMB_H)   # chỉ là ảnh, không chứa chữ
        row.addWidget(self._thumb)
        info = QVBoxLayout()
        info.setSpacing(3)
        self._title = ElidedLabel("")
        self._title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_BODY}px; "
            f"font-weight: 600; background: transparent;")
        step_row = QHBoxLayout()
        step_row.setSpacing(tokens.SP_2)
        self._step = ElidedLabel("")
        self._step.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self._percent = QLabel("0%")
        self._percent.setStyleSheet(
            f"color: {tokens.PRIMARY}; font-size: {tokens.FS_PAGE_TITLE}px; "
            f"font-weight: 700; background: transparent;")
        step_row.addWidget(self._step, 1)
        step_row.addWidget(self._percent)
        info.addWidget(self._title)
        info.addLayout(step_row)
        row.addLayout(info, 1)
        busy.addLayout(row)

        self._bar = ThinProgressBar(color=tokens.PROCESSING)
        busy.addWidget(self._bar)

        foot = QHBoxLayout()
        foot.setSpacing(tokens.SP_2)
        self._eta = QLabel("")
        self._eta.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        foot.addWidget(self._eta, 1)
        self._btn_details = GhostButton("Xem chi tiết")
        self._btn_details.clicked.connect(self.details_requested.emit)
        foot.addWidget(self._btn_details)
        self._btn_stop = GhostButton("Dừng")
        self._btn_stop.clicked.connect(self.stop_requested.emit)
        foot.addWidget(self._btn_stop)
        busy.addLayout(foot)
        self.body.addWidget(self._busy)

        self._idle = QWidget()
        clear_background(self._idle)
        idle = QVBoxLayout(self._idle)
        # Lề đều bốn phía để dòng chữ không dính sát mép trên hay mép trái
        # của thẻ.
        idle.setContentsMargins(0, tokens.SP_3, 0, tokens.SP_2)
        idle.setSpacing(tokens.SP_3)
        empty = QLabel("Chưa có dự án nào đang chạy")
        empty.setWordWrap(True)
        empty.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_LABEL}px; "
            f"background: transparent;")
        idle.addWidget(empty)
        btn_row = QHBoxLayout()
        btn_new = GhostButton("Tạo dự án mới")
        btn_new.clicked.connect(self.create_requested.emit)
        btn_row.addWidget(btn_new)
        btn_row.addStretch()
        idle.addLayout(btn_row)
        self.body.addWidget(self._idle)
        self.show_idle()

    def show_idle(self) -> None:
        """Không có việc nào đang chạy."""
        self._busy.setVisible(False)
        self._idle.setVisible(True)

    def show_job(self, title: str, step_label: str, percent: int,
                 eta_text: str, thumbnail: QPixmap | None = None) -> None:
        """Hiện thông tin công việc đang chạy."""
        self._idle.setVisible(False)
        self._busy.setVisible(True)
        self._title.setText(title)
        self._step.setText(step_label)
        self._percent.setText(f"{percent}%")
        self._bar.setValue(max(0, min(100, percent)))
        self._eta.setText(f"Thời gian còn lại: {eta_text}" if eta_text else "")
        if thumbnail is not None:
            self._thumb.set_thumbnail(thumbnail)


class ProjectCard(QFrame):
    """Thẻ một dự án: ảnh 16:9, tên, ngày, huy hiệu và hàng nút khi rê chuột."""

    open_video = Signal(str)
    open_folder = Signal(str)
    edit_project = Signal(str)
    delete_project = Signal(str)
    clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(tokens.CARD_MIN_W)
        self._key = ""
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.thumb = ThumbnailLabel()
        root.addWidget(self.thumb)

        info = QWidget()
        clear_background(info)
        layout = QVBoxLayout(info)
        layout.setContentsMargins(tokens.SP_3, 10, tokens.SP_3, 10)
        layout.setSpacing(tokens.SP_2)
        self.title = ElidedLabel("")
        self.title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_BODY}px; "
            f"font-weight: 600; background: transparent;")
        layout.addWidget(self.title)

        meta = QHBoxLayout()
        meta.setSpacing(tokens.SP_2)
        self.date = QLabel("")
        self.date.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.badge = StatusBadge()
        meta.addWidget(self.date, 1)
        meta.addWidget(self.badge)
        layout.addLayout(meta)

        self.actions = QWidget()
        clear_background(self.actions)
        act = QHBoxLayout(self.actions)
        act.setContentsMargins(0, 0, 0, 0)
        act.setSpacing(tokens.SP_1)
        specs = (
            (icons.play(tokens.SUCCESS), "Mở video kết quả", self.open_video),
            (icons.folder(tokens.TEXT_SECONDARY), "Mở thư mục dự án", self.open_folder),
            (icons.edit(tokens.ACCENT_BLUE), "Chỉnh sửa dự án", self.edit_project),
            (icons.trash(tokens.DANGER), "Xóa dự án", self.delete_project),
        )
        for icon, tip, signal in specs:
            btn = IconButton(icon, tip, size=_ACTION_ICON)
            btn.clicked.connect(
                lambda _c=False, s=signal: s.emit(self._key))
            act.addWidget(btn)
        act.addStretch()
        self.actions.setVisible(False)
        layout.addWidget(self.actions)
        root.addWidget(info)

    def set_project(self, key: str, title: str, date_label: str,
                    status: str, status_label: str, duration_s: float,
                    thumbnail: QPixmap | None = None) -> None:
        """Đổ dữ liệu một dự án vào thẻ."""
        self._key = key
        self.title.setText(title)
        self.date.setText(date_label)
        self.badge.set_state(status_label, STATUS_KIND.get(status, "neutral"))
        self.thumb.set_duration(duration_s)
        self.thumb.set_thumbnail(thumbnail)
        self.setToolTip(title)

    def key(self) -> str:
        return self._key

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        """Gắn ảnh đại diện khi luồng nền tạo xong."""
        self.thumb.set_thumbnail(pixmap)

    def enterEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        self.actions.setVisible(True)
        self.thumb.set_play_overlay(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        self.actions.setVisible(False)
        self.thumb.set_play_overlay(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802 — theo quy ước của Qt
        width = max(self.width(), tokens.CARD_MIN_W)
        return QSize(width, int(width * CARD_THUMB_RATIO) + _INFO_BLOCK_H)


class QuickStartCard(QFrame):
    """Ô "Bắt đầu nhanh" ở Trang chủ: biểu tượng tròn, tiêu đề và mô tả ngắn."""

    clicked = Signal()

    def __init__(self, title: str, description: str, icon_fn, color: str,
                 bg_color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SP_4, tokens.SP_4,
                                tokens.SP_4, tokens.SP_4)
        root.setSpacing(tokens.SP_2)

        icon = QLabel()
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(icon_fn(color).pixmap(18, 18))
        icon.setStyleSheet(
            f"background: {bg_color}; border-radius: 18px;")
        root.addWidget(icon)

        label = QLabel(title)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_BODY}px; "
            f"font-weight: 600; background: transparent;")
        root.addWidget(label)

        caption = QLabel(description)
        caption.setWordWrap(True)
        caption.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        root.addWidget(caption)
        root.addStretch()

    def mousePressEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class SystemStatusCard(QFrame):
    """Thẻ ở đáy thanh bên: tình trạng giọng đọc, dịch và FFmpeg."""

    recheck_requested = Signal()
    clicked = Signal()

    ROWS = ("voice", "translate", "ffmpeg")
    LABELS = {"voice": "Giọng đọc", "translate": "Dịch", "ffmpeg": "FFmpeg"}

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sidebarCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SP_3, 10, tokens.SP_3, 10)
        root.setSpacing(tokens.SP_2)
        title = QLabel("Trạng thái hệ thống")
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 600; background: transparent;")
        root.addWidget(title)

        self._values: dict[str, ElidedLabel] = {}
        self._dots: dict[str, QLabel] = {}
        for key in self.ROWS:
            row = QHBoxLayout()
            row.setSpacing(tokens.SP_2)
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color: {tokens.TEXT_DISABLED}; font-size: 9px; "
                f"background: transparent;")
            name = QLabel(self.LABELS[key])
            # Nhãn không được co lại, nếu không chữ sẽ bị cắt cụt.
            name.setSizePolicy(QSizePolicy.Policy.Fixed,
                               QSizePolicy.Policy.Preferred)
            name.setStyleSheet(
                f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_BADGE}px; "
                f"background: transparent;")
            value = ElidedLabel("đang kiểm tra")
            value.setAlignment(Qt.AlignmentFlag.AlignRight |
                               Qt.AlignmentFlag.AlignVCenter)
            value.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; "
                f"font-size: {tokens.FS_BADGE}px; background: transparent;")
            row.addWidget(dot)
            row.addWidget(name)
            row.addWidget(value, 1)
            root.addLayout(row)
            self._values[key] = value
            self._dots[key] = dot

        self._btn = GhostButton("Kiểm tra lại")
        self._btn.clicked.connect(self.recheck_requested.emit)
        root.addWidget(self._btn)

    def set_row(self, key: str, text: str, ok: bool | None) -> None:
        """Cập nhật một dòng: ok True là xanh, False là đỏ, None là vàng."""
        if key not in self._values:
            return
        color = (tokens.SUCCESS if ok else
                 tokens.WARNING if ok is None else tokens.DANGER)
        self._values[key].setText(text)
        self._dots[key].setStyleSheet(
            f"color: {color}; font-size: 9px; background: transparent;")

    def set_checking(self) -> None:
        """Khóa nút trong lúc đang đọc lại cấu hình."""
        self._btn.set_loading(True, "Đang kiểm tra")

    def set_checked(self) -> None:
        """Mở khóa nút khi đã kiểm tra xong."""
        self._btn.set_loading(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
