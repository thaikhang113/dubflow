"""Mục có thể gập lại để giấu bớt tùy chọn nâng cao."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from autodub_gui import icons, tokens
from autodub_gui.ui.buttons import IconButton
from autodub_gui.ui.style import clear_background

_TOGGLE_SIZE = 26


class CollapsibleSection(QWidget):
    """Tiêu đề bấm được, bên dưới là phần nội dung có thể ẩn hiện."""

    toggled = Signal(bool)

    def __init__(self, title: str, expanded: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._expanded = expanded
        # Nhóm này luôn nằm trong một thẻ hoặc một trang đã có nền — để trong
        # suốt thì nó ăn theo nền đó thay vì tự vẽ ra một khối tối.
        clear_background(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(tokens.SP_2)

        header = QWidget()
        clear_background(header)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SP_2)
        self._toggle = IconButton(self._arrow(), "Mở rộng hoặc thu gọn mục này",
                                  size=_TOGGLE_SIZE)
        self._toggle.clicked.connect(self.toggle)
        self._title = QLabel(title)
        self._title.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 600; background: transparent;")
        row.addWidget(self._toggle)
        row.addWidget(self._title, 1)
        header.mousePressEvent = lambda _e: self.toggle()   # noqa: SLF001
        root.addWidget(header)

        # Phải gắn cha NGAY từ lúc tạo: một widget chưa có cha mà bị cho hiện
        # sẽ được Windows dựng thành cửa sổ riêng và nháy lên một khoảnh khắc
        # trước khi được đưa vào bố cục. Vì lý do đó, việc ẩn/hiện cũng chỉ
        # được làm SAU khi widget đã nằm trong bố cục bên dưới.
        self._content = QWidget(self)
        clear_background(self._content)
        self._layout = QVBoxLayout(self._content)
        # Thụt vào đúng bằng bề ngang nút mũi tên cộng khoảng cách, để nội dung
        # thẳng hàng với chữ tiêu đề chứ không lệch một quãng lửng lơ.
        self._layout.setContentsMargins(_TOGGLE_SIZE + tokens.SP_2, 0,
                                        0, tokens.SP_2)
        self._layout.setSpacing(tokens.SP_3)
        root.addWidget(self._content)
        self._content.setVisible(expanded)

    def _arrow(self):
        return (icons.chevron_down(tokens.TEXT_SECONDARY) if self._expanded
                else icons.chevron_right(tokens.TEXT_SECONDARY))

    def toggle(self) -> None:
        """Đổi giữa mở rộng và thu gọn."""
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._toggle.setIcon(self._arrow())
        self.toggled.emit(expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_content_indent(self, indent: int) -> None:
        """Đổi khoảng thụt trái của phần nội dung.

        Mặc định nội dung thụt vào thẳng hàng với chữ tiêu đề; trong cột hẹp
        (như thẻ Quản lý giọng) đặt 0 để nút chiếm trọn bề ngang, không lệch.
        """
        margins = self._layout.contentsMargins()
        self._layout.setContentsMargins(indent, margins.top(),
                                        margins.right(), margins.bottom())

    def set_title(self, title: str) -> None:
        """Đổi dòng tiêu đề của mục."""
        self._title.setText(title)

    def add_widget(self, widget: QWidget) -> None:
        """Thêm một widget vào phần nội dung."""
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        """Thêm một bố cục vào phần nội dung."""
        self._layout.addLayout(layout)
