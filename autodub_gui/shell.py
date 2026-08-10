"""Vỏ ứng dụng: thanh bên, thanh tiêu đề và cửa sổ thông báo.

Tách khỏi `app.py` để mỗi tệp giữ được kích thước dễ đọc. Ở đây chỉ có phần
hiển thị; việc điều hướng giữa các trang do `MainWindow` quyết định.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.formatting import format_relative
from autodub_gui.run_state import (
    LEVEL_ERROR, LEVEL_SUCCESS, LEVEL_WARNING, REGISTRY,
)
from autodub_gui.ui.avatar import InitialAvatar
from autodub_gui.ui.buttons import GhostButton, IconButton
from autodub_gui.ui.cards import SystemStatusCard
from autodub_gui.ui.effects import soft_shadow
from autodub_gui.ui.labels import ElidedLabel
from autodub_gui.ui.style import clear_background, scoped_style

BRAND_NAME = "VoxDub Studio"

_LOGO_PX = 32
_NAV_ICON_PX = 18
_POPUP_W = 340
_POPUP_MAX_H = 420
# Khoảng đệm trong suốt quanh cửa sổ thông báo để bóng đổ vẽ TRONG cửa sổ.
# Nếu bóng tràn ra ngoài, Windows từ chối vẽ (UpdateLayeredWindowIndirect failed).
_POPUP_SHADOW_PAD = tokens.SHADOW_BLUR + tokens.SHADOW_Y
_BADGE_H = 14
_DIVIDER_MARGIN = 16

# Màu chấm đứng đầu mỗi dòng trong cửa sổ thông báo
_LEVEL_COLOR = {
    LEVEL_SUCCESS: tokens.SUCCESS,
    LEVEL_WARNING: tokens.WARNING,
    LEVEL_ERROR: tokens.DANGER,
}


def display_name() -> str:
    """Tên hiển thị của người dùng, lấy từ tệp cấu hình hoặc tên đăng nhập máy."""
    name = os.environ.get("DISPLAY_NAME", "").strip()
    if name:
        return name
    try:
        return os.getlogin()
    except OSError:
        return "bạn"


def _divider() -> QFrame:
    """Đường kẻ ngang mảnh ngăn hai nhóm mục trong thanh bên."""
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {tokens.BORDER_SUBTLE}; border: none;")
    return line


def _section_label(text: str) -> QLabel:
    """Nhãn nhóm viết hoa nhỏ trong thanh bên (CÔNG CỤ, HỆ THỐNG)."""
    label = QLabel(text)
    label.setObjectName("sectionLabel")
    return label


class Sidebar(QFrame):
    """Thanh bên trái: biểu trưng, các nhóm mục, thẻ trạng thái và phiên bản."""

    page_requested = Signal(int)
    settings_requested = Signal()
    account_requested = Signal()

    def __init__(self, main_items: list[tuple[int, str, object]],
                 tool_items: list[tuple[int, str, object]],
                 second_items: list[tuple[int, str, object]],
                 version: str, parent: QWidget | None = None):
        super().__init__(parent)
        scoped_style(self, f"background: {tokens.BG_SIDEBAR}; "
                           f"border: none; "
                           f"border-right: 1px solid {tokens.BORDER_SUBTLE};")
        self._icon_only = False
        self._main_items = main_items
        self._tool_items = tool_items
        self._second_items = second_items

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_brand())
        root.addSpacing(tokens.SP_3)
        self.nav = self._build_list(main_items, "nav")
        self.nav_tools = self._build_list(tool_items, "nav2")
        self.nav2 = self._build_list(second_items, "nav2")
        root.addWidget(self.nav)
        root.addSpacing(tokens.SP_2)
        self._divider_widget = _divider()
        root.addWidget(self._divider_widget)
        self._tools_label = _section_label("CÔNG CỤ")
        root.addSpacing(tokens.SP_2)
        root.addWidget(self._tools_label)
        root.addWidget(self.nav_tools)
        self._system_label = _section_label("HỆ THỐNG")
        root.addSpacing(tokens.SP_2)
        root.addWidget(self._system_label)
        root.addWidget(self.nav2)
        root.addStretch()

        self.status_card = SystemStatusCard()
        self.status_card.clicked.connect(self.settings_requested.emit)
        card_wrap = QWidget()
        card_layout = QVBoxLayout(card_wrap)
        card_layout.setContentsMargins(tokens.SP_2, 0, tokens.SP_2, tokens.SP_2)
        card_layout.setSpacing(tokens.SP_2)
        card_layout.addWidget(self.status_card)
        self._user_card = self._build_user_card()
        card_layout.addWidget(self._user_card)
        root.addWidget(card_wrap)
        self._card_wrap = card_wrap

        self._version = QLabel(f"v{version}")
        self._version.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_BADGE}px; "
            f"background: transparent; padding: 6px 16px;")
        root.addWidget(self._version)

        self.nav.currentRowChanged.connect(self._on_main_row)
        self.nav_tools.currentRowChanged.connect(self._on_tool_row)
        self.nav2.currentRowChanged.connect(self._on_second_row)
        self.set_width_mode(tokens.SIDEBAR_W)

    # -- Dựng giao diện ------------------------------------------------
    def _build_brand(self) -> QWidget:
        brand = QWidget()
        clear_background(brand)
        row = QHBoxLayout(brand)
        row.setContentsMargins(_DIVIDER_MARGIN, tokens.SP_5,
                               _DIVIDER_MARGIN, tokens.SP_2)
        row.setSpacing(tokens.SP_2)
        self._logo = QLabel()
        self._logo.setPixmap(icons.app_logo(_LOGO_PX))
        clear_background(self._logo)
        self._brand_name = ElidedLabel(BRAND_NAME)
        self._brand_name.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_SECTION}px; "
            f"font-weight: 700; background: transparent;")
        row.addWidget(self._logo)
        row.addWidget(self._brand_name, 1)
        return brand

    def _build_list(self, items: list[tuple[int, str, object]],
                    object_name: str) -> QListWidget:
        widget = QListWidget()
        widget.setObjectName(object_name)
        widget.setIconSize(QSize(_NAV_ICON_PX, _NAV_ICON_PX))
        widget.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for _row, label, icon_fn in items:
            item = QListWidgetItem(f"  {label}")
            item.setIcon(icons.nav_icon(icon_fn))
            item.setToolTip(label)
            widget.addItem(item)
        height = tokens.NAV_ITEM_H * len(items) + tokens.SP_2 * len(items)
        widget.setMinimumHeight(height)
        widget.setMaximumHeight(height)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Fixed)
        return widget

    def _build_user_card(self) -> QWidget:
        """Thẻ người dùng dưới cùng: avatar + tên; bấm để đổi tên hiển thị."""
        card = QFrame()
        card.setObjectName("sidebarCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setToolTip("Mở Cài đặt để đổi tên hiển thị")
        row = QHBoxLayout(card)
        row.setContentsMargins(tokens.SP_3, tokens.SP_2,
                               tokens.SP_3, tokens.SP_2)
        row.setSpacing(tokens.SP_2)
        self._user_avatar = InitialAvatar(display_name(), 30)
        row.addWidget(self._user_avatar)
        col = QVBoxLayout()
        col.setSpacing(0)
        self._user_name = ElidedLabel(display_name())
        self._user_name.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 600; background: transparent;")
        caption = QLabel("Tài khoản")
        caption.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_BADGE}px; "
            f"background: transparent;")
        col.addWidget(self._user_name)
        col.addWidget(caption)
        row.addLayout(col, 1)
        card.mousePressEvent = (         # noqa: SLF001 — vùng bấm đơn giản
            lambda _e: self.account_requested.emit())
        return card

    def refresh_name(self) -> None:
        """Đọc lại tên hiển thị sau khi người dùng đổi trong Cài đặt."""
        name = display_name()
        self._user_name.setText(name)
        self._user_avatar.set_name(name)

    # -- Đồng bộ các danh sách -----------------------------------------
    def _clear_selection(self, *widgets: QListWidget) -> None:
        for widget in widgets:
            widget.blockSignals(True)
            widget.clearSelection()
            widget.setCurrentRow(-1)
            widget.blockSignals(False)

    def _on_main_row(self, index: int) -> None:
        if index < 0:
            return
        self._clear_selection(self.nav_tools, self.nav2)
        self.page_requested.emit(self._main_items[index][0])

    def _on_tool_row(self, index: int) -> None:
        if index < 0:
            return
        self._clear_selection(self.nav, self.nav2)
        self.page_requested.emit(self._tool_items[index][0])

    def _on_second_row(self, index: int) -> None:
        if index < 0:
            return
        self._clear_selection(self.nav, self.nav_tools)
        self.page_requested.emit(self._second_items[index][0])

    def select_row(self, row: int) -> None:
        """Tô sáng mục tương ứng với trang đang mở, không phát tín hiệu lại."""
        for widget, items in ((self.nav, self._main_items),
                              (self.nav_tools, self._tool_items),
                              (self.nav2, self._second_items)):
            widget.blockSignals(True)
            match = next((i for i, it in enumerate(items) if it[0] == row), -1)
            widget.setCurrentRow(match)
            if match < 0:
                widget.clearSelection()
            widget.blockSignals(False)

    # -- Thu gọn khi cửa sổ hẹp ----------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        super().resizeEvent(event)
        self._sync_footer()

    def _sync_footer(self) -> None:
        """Ẩn dần thẻ đáy khi cửa sổ quá thấp.

        Không đủ chỗ thì layout sẽ ép các thẻ này chồng lên danh sách và
        chữ bị cắt nham nhở — ẩn hẳn đi là cách xử lý tận gốc. Thẻ trạng
        thái (cao nhất) ẩn trước, thẻ tài khoản chỉ ẩn khi vẫn thiếu chỗ.
        """
        if self._icon_only:
            return
        # Chiều cao cần có khi mọi thứ đều hiện — tính lại từ trạng thái
        # "hiện đủ" để quyết định không bị dính vào trạng thái hiện tại.
        base = self.sizeHint().height()
        for widget in (self.status_card, self._user_card):
            if not widget.isVisibleTo(self):
                base += widget.sizeHint().height() + tokens.SP_2
        available = self.height()
        show_status = available >= base
        show_user = show_status or (
            available >= base - self.status_card.sizeHint().height()
            - tokens.SP_2)
        if show_status != self.status_card.isVisibleTo(self):
            self.status_card.setVisible(show_status)
        if show_user != self._user_card.isVisibleTo(self):
            self._user_card.setVisible(show_user)

    def set_width_mode(self, width: int) -> None:
        """Đổi giữa chế độ đầy đủ và chế độ chỉ hiện biểu tượng."""
        icon_only = width <= tokens.SIDEBAR_W_ICON
        self.setFixedWidth(width)
        if icon_only == self._icon_only:
            return
        self._icon_only = icon_only
        self._brand_name.setVisible(not icon_only)
        self._card_wrap.setVisible(not icon_only)
        self._version.setVisible(not icon_only)
        self._tools_label.setVisible(not icon_only)
        self._system_label.setVisible(not icon_only)
        for widget, items in ((self.nav, self._main_items),
                              (self.nav_tools, self._tool_items),
                              (self.nav2, self._second_items)):
            for i, (_row, label, _icon) in enumerate(items):
                item = widget.item(i)
                item.setText("" if icon_only else f"  {label}")
                item.setToolTip(label)
        self._sync_footer()


class NotificationPopup(QFrame):
    """Cửa sổ nhỏ liệt kê các hoạt động gần đây khi bấm vào chuông."""

    activity_opened = Signal(str)      # thư mục dự án của dòng được bấm

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Popup)
        # WA_TranslucentBackground + FramelessWindowHint cho phép border-radius
        # trong QSS cắt thực sự góc của cửa sổ popup thay vì chỉ vẽ đè lên
        # nền hệ điều hành màu xám/trắng vuông vức.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setFixedWidth(_POPUP_W + 2 * _POPUP_SHADOW_PAD)
        # Outer frame phải transparent hoàn toàn (không background của QFrame)
        self.setStyleSheet("NotificationPopup { background: transparent; border: none; }")

        # Bóng đổ phải nằm GỌN trong cửa sổ: đổ lên tấm panel bên trong và
        # chừa viền trong suốt xung quanh. Đổ bóng thẳng lên cửa sổ sẽ vẽ
        # tràn ra ngoài biên và Windows từ chối cập nhật
        # ("UpdateLayeredWindowIndirect failed").
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_POPUP_SHADOW_PAD, _POPUP_SHADOW_PAD,
                                 _POPUP_SHADOW_PAD, _POPUP_SHADOW_PAD)
        panel = QFrame()
        panel.setObjectName("notifPanel")
        self._panel = panel
        # Chọn theo objectName để nền/viền không lan sang QScrollArea con
        # (QScrollArea cũng là một QFrame).
        panel.setStyleSheet(
            f"QFrame#notifPanel {{ background: {tokens.BG_PANEL}; "
            f"border: 1px solid {tokens.BORDER_DEFAULT}; "
            f"border-radius: {tokens.RADIUS_LG}px; }}")
        soft_shadow(panel)
        outer.addWidget(panel)

        root = QVBoxLayout(panel)
        root.setContentsMargins(tokens.SP_3, tokens.SP_3,
                                tokens.SP_3, tokens.SP_3)
        root.setSpacing(tokens.SP_2)

        title = QLabel("Hoạt động gần đây")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 700; background: transparent; border: none;")
        root.addWidget(title)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }")
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body = QWidget()
        clear_background(self._body)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(tokens.SP_2)
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll)

        self._btn_read = GhostButton("Đánh dấu đã đọc")
        self._btn_read.clicked.connect(self._mark_read)
        root.addWidget(self._btn_read)

    def _clear(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def refresh(self) -> None:
        """Nạp lại danh sách từ sổ đăng ký."""
        self._clear()
        activities = REGISTRY.activities()
        if not activities:
            empty = QLabel("Chưa có hoạt động nào. Khi bạn chạy lồng tiếng, "
                           "kết quả sẽ hiện ở đây.")
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_LABEL}px; "
                f"background: transparent; border: none;")
            self._body_layout.addWidget(empty)
            self._btn_read.setEnabled(False)
        else:
            self._btn_read.setEnabled(REGISTRY.unread() > 0)
            for activity in activities:
                self._body_layout.addWidget(self._build_row(activity))
            self._body_layout.addStretch()
        # Chiều cao cuộn theo đúng nội dung, có trần _POPUP_MAX_H. Không nhờ
        # layout đo hộ được: các dòng vừa thêm còn ở trạng thái ẩn cho tới khi
        # popup thật sự hiện, và layout bỏ qua widget ẩn. Tự cộng chiều cao
        # từng dòng theo bề ngang thật (heightForWidth xử lý chữ xuống hàng).
        inner_w = _POPUP_W - 2 - 2 * tokens.SP_3      # trừ viền panel + lề
        content_h = self._measure_body(inner_w)
        if content_h > _POPUP_MAX_H:                   # sẽ có thanh cuộn dọc
            bar_w = self._scroll.verticalScrollBar().sizeHint().width()
            content_h = self._measure_body(inner_w - bar_w)
        self._scroll.setFixedHeight(max(tokens.SP_8,
                                        min(content_h, _POPUP_MAX_H)))

    def _measure_body(self, width: int) -> int:
        """Tổng chiều cao các dòng nếu xếp trong bề ngang `width`."""
        total = 0
        count = 0
        for i in range(self._body_layout.count()):
            widget = self._body_layout.itemAt(i).widget()
            if widget is None:
                continue
            if widget.layout() is not None and \
                    widget.layout().hasHeightForWidth():
                h = widget.layout().heightForWidth(width)
            elif widget.hasHeightForWidth():
                h = widget.heightForWidth(width)
            else:
                h = widget.sizeHint().height()
            total += max(0, h)
            count += 1
        return total + max(0, count - 1) * self._body_layout.spacing()

    def _build_row(self, activity) -> QWidget:
        row = QWidget()
        clear_background(row)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SP_2)
        dot = QLabel("●")
        dot.setStyleSheet(
            f"color: {_LEVEL_COLOR.get(activity.level, tokens.ACCENT_BLUE)}; "
            f"font-size: 9px; background: transparent; border: none;")
        text = QLabel(activity.text)
        text.setWordWrap(True)
        # Không cho chữ dài nới rộng dòng vượt quá bề ngang popup — thiếu
        # đoạn này chữ sẽ tràn viền / bị cắt thay vì xuống hàng. Phải giữ
        # cờ heightForWidth, nếu không chiều cao sau khi bọc chữ sẽ sai.
        policy = QSizePolicy(QSizePolicy.Policy.Ignored,
                             QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        text.setSizePolicy(policy)
        text.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            f"background: transparent; border: none;")
        when = QLabel(format_relative(activity.ts))
        when.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_BADGE}px; "
            f"background: transparent; border: none;")
        layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(text, 1)
        layout.addWidget(when, 0, Qt.AlignmentFlag.AlignTop)
        if activity.work_dir:
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setToolTip("Bấm để mở dự án này trong Trình chỉnh sửa")
            row.mousePressEvent = (          # noqa: SLF001 — gắn nhanh cho một dòng
                lambda _e, wd=activity.work_dir: self._open(wd))
        return row

    def _open(self, work_dir: str) -> None:
        self.hide()
        self.activity_opened.emit(work_dir)

    def _mark_read(self) -> None:
        REGISTRY.mark_all_read()
        self.refresh()

    def show_under(self, anchor: QWidget) -> None:
        """Hiện ngay dưới nút chuông, canh mép phải cho thẳng hàng."""
        self.refresh()
        # Xóa số liệu cũ ở CẢ HAI tầng layout rồi ép tính lại — thiếu bước
        # này popup giữ nguyên chiều cao của lần mở trước dù nội dung đã đổi.
        self._panel.layout().invalidate()
        self.layout().invalidate()
        self._panel.layout().activate()
        self.layout().activate()
        self.adjustSize()
        point = anchor.mapToGlobal(anchor.rect().bottomRight())
        # Trừ phần đệm bóng để mép PANEL (phần nhìn thấy) thẳng với chuông,
        # rồi kẹp vào vùng màn hình để Windows không từ chối vẽ popup.
        x = point.x() - self.width() + _POPUP_SHADOW_PAD
        y = point.y() + tokens.SP_1 - _POPUP_SHADOW_PAD
        screen = anchor.screen() or self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left(), min(x, area.right() - self.width() + 1))
            y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        self.move(x, y)
        self.show()


class NotificationButton(QWidget):
    """Nút chuông kèm huy hiệu số thông báo chưa đọc."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._button = IconButton(icons.bell(tokens.TEXT_SECONDARY),
                                  "Hoạt động gần đây")
        self._button.clicked.connect(self.clicked.emit)
        layout.addWidget(self._button)
        self._unread = 0
        REGISTRY.unread_changed.connect(self.set_unread)

    def anchor(self) -> QWidget:
        return self._button

    def set_unread(self, count: int) -> None:
        """Cập nhật số thông báo chưa đọc và vẽ lại huy hiệu."""
        if count == self._unread:
            return
        self._unread = count
        self._button.setToolTip(
            f"Hoạt động gần đây ({count} mục chưa đọc)" if count
            else "Hoạt động gần đây")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        super().paintEvent(event)
        if not self._unread:
            return
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QFont, QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = "9+" if self._unread > 9 else str(self._unread)
        font = QFont(self.font())
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        width = max(_BADGE_H,
                    painter.fontMetrics().horizontalAdvance(text) + 6)
        geo = self._button.geometry()
        badge = QRectF(geo.right() - width + 2, geo.top(), width, _BADGE_H)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens.DANGER))
        painter.drawRoundedRect(badge, _BADGE_H / 2, _BADGE_H / 2)
        painter.setPen(QColor(tokens.TEXT_ON_ACCENT))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class AppHeader(QFrame):
    """Thanh tiêu đề trang: tên trang, mô tả ngắn và các nút bên phải."""

    notifications_clicked = Signal()
    help_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(tokens.HEADER_H)
        self.setStyleSheet("QFrame { background: transparent; border: none; }")
        row = QHBoxLayout(self)
        row.setContentsMargins(28, tokens.SP_5, 28, 0)
        row.setSpacing(tokens.SP_3)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = ElidedLabel("")
        self.title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; "
            f"font-size: {tokens.FS_PAGE_TITLE}px; font-weight: 700; "
            f"background: transparent;")
        self.subtitle = ElidedLabel("")
        self.subtitle.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px; "
            f"background: transparent;")
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        row.addLayout(texts, 1)

        # Chỗ gắn các nút theo từng trang (Trang chủ có Nhập video, Tạo dự án)
        self._actions = QHBoxLayout()
        self._actions.setSpacing(tokens.SP_2)
        row.addLayout(self._actions)

        # Chỗ gắn widget hiện ở MỌI trang (huy hiệu Vox) — tách khỏi
        # ``_actions`` vì chỗ kia bị xóa sạch mỗi lần chuyển trang.
        self._persistent = QHBoxLayout()
        self._persistent.setSpacing(tokens.SP_2)
        row.addLayout(self._persistent)

        self.bell = NotificationButton()
        self.bell.clicked.connect(self.notifications_clicked.emit)
        row.addWidget(self.bell)

        help_button = IconButton(icons.help_circle(tokens.TEXT_SECONDARY),
                                 "Mở trang Trợ giúp")
        help_button.clicked.connect(self.help_clicked.emit)
        row.addWidget(help_button)

    def set_page(self, title: str, subtitle: str) -> None:
        """Đổi tên trang và dòng mô tả bên dưới."""
        self.title.setText(title)
        self.subtitle.setText(subtitle)

    def set_persistent(self, widget: QWidget) -> None:
        """Gắn một widget hiện ở mọi trang (gọi một lần lúc dựng cửa sổ)."""
        self._persistent.addWidget(widget)

    def set_actions(self, widgets: list[QWidget]) -> None:
        """Thay các nút riêng của trang (gọi mỗi lần chuyển trang)."""
        while self._actions.count():
            item = self._actions.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for widget in widgets:
            self._actions.addWidget(widget)
