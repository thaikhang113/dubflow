"""Hàng chuyển trang cho danh sách dài."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from autodub_gui import icons, tokens
from autodub_gui.ui.buttons import IconButton

_BUTTON = 32
_ELLIPSIS = -1
_MAX_PLAIN_PAGES = 7      # ít hơn mức này thì hiện hết, không cần dấu ba chấm
_NEIGHBOURS = 1           # số trang hiện hai bên trang đang xem


def page_numbers(current: int, total: int) -> list[int]:
    """Dãy số trang cần hiện, dùng -1 để đánh dấu chỗ rút gọn.

    Tách riêng khỏi phần vẽ để kiểm thử được bằng pytest.
    """
    if total <= _MAX_PLAIN_PAGES:
        return list(range(1, total + 1))
    pages = [1]
    if current > 2 + _NEIGHBOURS:
        pages.append(_ELLIPSIS)
    start = max(2, current - _NEIGHBOURS)
    end = min(total - 1, current + _NEIGHBOURS)
    pages.extend(range(start, end + 1))
    if current < total - 1 - _NEIGHBOURS:
        pages.append(_ELLIPSIS)
    pages.append(total)
    return pages


class Pagination(QWidget):
    """Nút lùi, các số trang và nút tiến."""

    page_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._current = 1
        self._total = 1
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(tokens.SP_1)
        self._rebuild()

    def set_range(self, current: int, total: int) -> None:
        """Đặt trang hiện tại và tổng số trang rồi vẽ lại."""
        self._total = max(1, total)
        self._current = max(1, min(current, self._total))
        self._rebuild()

    def current_page(self) -> int:
        return self._current

    def go_to(self, page: int) -> None:
        """Chuyển trang và báo cho trang cha biết."""
        if 1 <= page <= self._total and page != self._current:
            self._current = page
            self._rebuild()
            self.page_changed.emit(page)

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild(self) -> None:
        self._clear()
        self._layout.addStretch()
        prev = IconButton(icons.chevron_left(tokens.TEXT_SECONDARY),
                          "Trang trước", size=_BUTTON)
        prev.setEnabled(self._current > 1)
        prev.clicked.connect(lambda: self.go_to(self._current - 1))
        self._layout.addWidget(prev)

        for page in page_numbers(self._current, self._total):
            self._layout.addWidget(self._page_widget(page))

        nxt = IconButton(icons.chevron_right(tokens.TEXT_SECONDARY),
                         "Trang sau", size=_BUTTON)
        nxt.setEnabled(self._current < self._total)
        nxt.clicked.connect(lambda: self.go_to(self._current + 1))
        self._layout.addWidget(nxt)
        self._layout.addStretch()

    def _page_widget(self, page: int) -> QWidget:
        if page == _ELLIPSIS:
            label = QLabel("…")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedSize(_BUTTON, _BUTTON)
            label.setStyleSheet(
                f"color: {tokens.TEXT_MUTED}; background: transparent;")
            return label
        button = QPushButton(str(page))
        button.setFixedSize(_BUTTON, _BUTTON)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(f"Sang trang {page}")
        active = page == self._current
        button.setStyleSheet(
            f"QPushButton {{ border: none; border-radius: 8px; padding: 0; "
            f"min-height: 0; font-weight: {'700' if active else '500'}; "
            f"background: {tokens.PRIMARY if active else 'transparent'}; "
            f"color: {tokens.TEXT_ON_ACCENT if active else tokens.TEXT_SECONDARY}; }}"
            f"QPushButton:hover {{ background: "
            f"{tokens.PRIMARY if active else tokens.BG_PANEL_HOVER}; "
            f"color: {tokens.TEXT_ON_ACCENT if active else tokens.TEXT_PRIMARY}; }}")
        button.clicked.connect(lambda _c=False, p=page: self.go_to(p))
        return button
