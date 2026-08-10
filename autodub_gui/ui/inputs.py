"""Ô nhập liệu có nhãn, chú giải và chỗ hiển thị lỗi.

Mọi ô đều có nhãn rõ ràng; ô nào khó hiểu đều kèm chú giải viết bằng lời
thường, không dùng thuật ngữ kỹ thuật.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QSizePolicy, QSlider, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.ui.buttons import GhostButton

_SEARCH_DEBOUNCE_MS = 250
_SLIDER_SCALE = 100
_LABEL_SPACING = 6
#: Chiều cao một dòng trong bảng thả xuống — khớp `min-height` của
#: `QComboBox QAbstractItemView::item` trong theme.py.
_COMBO_ROW_H = 30


def polish_combo(combo: QComboBox) -> None:
    """Làm mượt bảng thả xuống của một QComboBox bất kỳ.

    Những việc phải làm bằng mã, QSS chung không tự lo được:
    1. Gắn QStyledItemDelegate — không có nó thì các luật `::item` trong
       bảng kiểu chung (dòng cao, bo góc, trạng thái rê chuột) bị Qt bỏ qua.
    2. Đặt bảng kiểu THẲNG lên widget view — bảng thả xuống là một cửa sổ
       tách rời, luật `QComboBox QAbstractItemView` trong QSS chung có lúc
       không với tới nó (nhất là sau khi nạp lại danh sách), khiến popup rơi
       về màu xám mặc định của HĐH: không viền, không hover. Đặt trực tiếp
       thì kiểu luôn còn đó.
    3. Tô nền ĐẶC cho cửa sổ chứa popup — trước đây dùng chiêu trong suốt
       (WA_TranslucentBackground) để lộ góc bo, nhưng trên một số máy
       Windows không composite được popup trong suốt khiến toàn bộ nền
       biến mất, chữ nổi lơ lửng trên trang. Nền đặc cùng màu panel thì
       luôn hiển thị đúng; góc bo hơi vuông ở mép ngoài là đánh đổi
       chấp nhận được.
    4. Nới bảng thả xuống cho vừa mục dài nhất, để mục dài không bị cắt.
    """
    combo.setItemDelegate(QStyledItemDelegate(combo))
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    view = combo.view()
    view.setMouseTracking(True)      # cần cho trạng thái :hover của ::item
    view.setStyleSheet(f"""
        QAbstractItemView {{
            background: {tokens.BG_PANEL};
            border: 1px solid {tokens.BORDER_DEFAULT};
            border-radius: 10px;
            outline: none;
            padding: 5px;
            color: {tokens.TEXT_PRIMARY};
            selection-background-color: {tokens.BG_SELECTED};
            selection-color: {tokens.TEXT_PRIMARY};
        }}
        QAbstractItemView::item {{
            min-height: 30px;
            padding: 4px 10px;
            border: none;
            border-radius: 6px;
            color: {tokens.TEXT_PRIMARY};
            background: transparent;
        }}
        QAbstractItemView::item:hover {{
            background: {tokens.BG_PANEL_HOVER};
        }}
        QAbstractItemView::item:selected {{
            background: {tokens.BG_SELECTED};
            color: {tokens.TEXT_PRIMARY};
        }}
    """)
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    container = view.window()
    if container is not None and container is not combo.window():
        container.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, False)
        container.setStyleSheet(
            f"background: {tokens.BG_PANEL}; "
            f"border: 1px solid {tokens.BORDER_DEFAULT};")
    metrics = combo.fontMetrics()
    widest = max((metrics.horizontalAdvance(combo.itemText(i))
                  for i in range(combo.count())), default=0)
    view.setMinimumWidth(widest + tokens.SP_8)

    # 5. Ép mọi dòng cùng MỘT chiều cao thật.
    #    `min-height` trong QSS chỉ nới ô vẽ chứ không đổi bước nhảy giữa hai
    #    dòng: Qt vẫn xếp dòng theo chiều cao của font, nên các dòng chồng
    #    lên nhau trong khi popup lại được cấp chiều cao theo min-height —
    #    kết quả là chữ dồn lên nửa trên, nửa dưới bỏ trống một mảng lớn.
    #    Đặt uniformItemSizes + gán thẳng chiều cao cho từng dòng thì hai
    #    con số này khớp nhau, popup ôm sát nội dung.
    if hasattr(view, "setUniformItemSizes"):
        view.setUniformItemSizes(True)
    model = combo.model()
    if model is not None:
        size = model.index(0, 0).data(Qt.ItemDataRole.SizeHintRole)
        row_h = max(_COMBO_ROW_H, size.height() if size is not None else 0)
        for i in range(combo.count()):
            combo.setItemData(i, QSize(0, row_h), Qt.ItemDataRole.SizeHintRole)


class _Field(QWidget):
    """Khung dựng chung: nhãn ở trên, ô nhập ở dưới, dòng lỗi ẩn sẵn."""

    def __init__(self, label: str, hint: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(_LABEL_SPACING)
        if label:
            self._label = QLabel(label)
            self._label.setWordWrap(True)
            self._label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; "
                f"font-size: {tokens.FS_LABEL}px; font-weight: 500; "
                f"background: transparent;")
            self._root.addWidget(self._label)
        if hint:
            self.setToolTip(hint)
        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        self._error.setStyleSheet(
            f"color: {tokens.DANGER}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")

    def _finish(self) -> None:
        self._root.addWidget(self._error)

    def set_error(self, message: str) -> None:
        """Hiện hoặc ẩn dòng báo lỗi ngay dưới ô nhập."""
        self._error.setText(message)
        self._error.setVisible(bool(message))


class LabeledCombo(_Field):
    """Nhãn kèm danh sách chọn.

    Ô đang đóng được phép co lại theo bề ngang của khung chứa (mục dài sẽ
    được rút gọn), còn bảng thả xuống luôn được nới đủ rộng cho mục dài nhất
    — nhờ vậy cột biểu mẫu hẹp không bao giờ bị nội dung chống tràn ra ngoài.
    """

    changed = Signal()
    _MIN_CHARS = 12      # bề ngang tối thiểu của ô đang đóng, tính theo chữ

    def __init__(self, label: str, options: list[tuple[str, str]] | None = None,
                 hint: str = "", parent: QWidget | None = None):
        super().__init__(label, hint, parent)
        self.combo = QComboBox()
        self.combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(self._MIN_CHARS)
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Fixed)
        if hint:
            self.combo.setToolTip(hint)
        for text, key in (options or []):
            self.combo.addItem(text, key)
        self.combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
        polish_combo(self.combo)
        self._root.addWidget(self.combo)
        self._finish()

    def set_options(self, options: list[tuple[str, str]]) -> None:
        """Nạp lại danh sách, giữ nguyên lựa chọn cũ nếu vẫn còn."""
        previous = self.current_key()
        self.combo.blockSignals(True)
        self.combo.clear()
        for text, key in options:
            self.combo.addItem(text, key)
        self.combo.blockSignals(False)
        if previous:
            self.set_key(previous)
        polish_combo(self.combo)

    def current_key(self) -> str:
        data = self.combo.currentData()
        return data if data is not None else self.combo.currentText()

    def set_key(self, key: str) -> None:
        index = self.combo.findData(key)
        if index < 0:
            index = self.combo.findText(key)
        if index >= 0:
            self.combo.setCurrentIndex(index)


class LabeledLineEdit(_Field):
    """Nhãn kèm ô nhập một dòng."""

    changed = Signal(str)

    def __init__(self, label: str, placeholder: str = "", hint: str = "",
                 parent: QWidget | None = None, *, password: bool = False):
        super().__init__(label, hint, parent)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        if hint:
            self.edit.setToolTip(hint)
        if password:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.textChanged.connect(self.changed.emit)
        self._root.addWidget(self.edit)
        self._finish()

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, value: str) -> None:
        self.edit.setText(value or "")


class LabeledSlider(_Field):
    """Nhãn kèm thanh trượt số thực và ô số, hai bên đồng bộ với nhau."""

    changed = Signal(float)

    def __init__(self, label: str, minimum: float, maximum: float,
                 step: float = 0.05, hint: str = "", suffix: str = "",
                 parent: QWidget | None = None, *, decimals: int = 2):
        super().__init__(label, hint, parent)
        self._min, self._max = minimum, maximum
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_3)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(minimum * _SLIDER_SCALE),
                             int(maximum * _SLIDER_SCALE))
        self.slider.setSingleStep(max(1, int(step * _SLIDER_SCALE)))
        self.slider.setPageStep(max(1, int(step * _SLIDER_SCALE * 2)))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setSuffix(suffix)
        self.spin.setSizePolicy(QSizePolicy.Policy.Minimum,
                                QSizePolicy.Policy.Fixed)
        if hint:
            self.slider.setToolTip(hint)
            self.spin.setToolTip(hint)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)
        self._root.addLayout(row)
        self._finish()
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, raw: int) -> None:
        value = raw / _SLIDER_SCALE
        if abs(value - self.spin.value()) > 1e-9:
            self.spin.blockSignals(True)
            self.spin.setValue(value)
            self.spin.blockSignals(False)
        self.changed.emit(value)

    def _from_spin(self, value: float) -> None:
        raw = int(round(value * _SLIDER_SCALE))
        if raw != self.slider.value():
            self.slider.blockSignals(True)
            self.slider.setValue(raw)
            self.slider.blockSignals(False)
        self.changed.emit(value)

    def value(self) -> float:
        return self.spin.value()

    def set_value(self, value: float) -> None:
        self.spin.setValue(max(self._min, min(self._max, value)))


class SearchBox(QWidget):
    """Ô tìm kiếm có biểu tượng kính lúp, chờ 250ms sau lần gõ cuối mới lọc."""

    search_changed = Signal(str)

    def __init__(self, placeholder: str = "Tìm theo tên video",
                 parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        self.edit.addAction(icons.search(tokens.TEXT_MUTED),
                            QLineEdit.ActionPosition.LeadingPosition)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Fixed)
        row.addWidget(self.edit)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._timer.timeout.connect(
            lambda: self.search_changed.emit(self.text()))
        self.edit.textChanged.connect(lambda _t: self._timer.start())

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, value: str) -> None:
        self.edit.setText(value or "")

    def focus(self) -> None:
        """Đưa con trỏ vào ô tìm kiếm và bôi đen chữ đang có."""
        self.edit.setFocus()
        self.edit.selectAll()


class FilePicker(_Field):
    """Nhãn kèm đường dẫn và nút chọn. Đường dẫn dài được giữ trong chú giải."""

    changed = Signal(str)

    def __init__(self, label: str, placeholder: str = "",
                 hint: str = "", parent: QWidget | None = None, *,
                 directory: bool = False,
                 name_filter: str = "Tất cả tệp (*.*)"):
        super().__init__(label, hint, parent)
        self._directory = directory
        self._filter = name_filter
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(self._on_text)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Fixed)
        self.button = GhostButton("Chọn…")
        self.button.clicked.connect(self._browse)
        row.addWidget(self.edit, 1)
        row.addWidget(self.button)
        self._root.addLayout(row)
        self._finish()

    def _on_text(self, value: str) -> None:
        self.edit.setToolTip(value)
        self.changed.emit(value)

    def _browse(self) -> None:
        start = self.edit.text().strip() or os.path.expanduser("~")
        if self._directory:
            chosen = QFileDialog.getExistingDirectory(
                self, "Chọn thư mục", start)
        else:
            chosen, _ = QFileDialog.getOpenFileName(
                self, "Chọn tệp", start, self._filter)
        if chosen:
            self.edit.setText(chosen)

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, value: str) -> None:
        self.edit.setText(value or "")


class LabeledWidget(_Field):
    """Bọc một widget bất kỳ vào khung nhãn chuẩn."""

    def __init__(self, label: str, widget: QWidget, hint: str = "",
                 parent: QWidget | None = None):
        super().__init__(label, hint, parent)
        self.widget = widget
        if hint:
            widget.setToolTip(hint)
        self._root.addWidget(widget)
        self._finish()

