"""Khung chung cho các trang Công cụ dựng từ bảng khai báo cấu hình.

Trang Cài đặt gom sáu thẻ vào một chỗ. Các trang Công cụ ở đây tách riêng
từng phần thường dùng ra thành trang độc lập, nhưng vẫn đọc cùng một bảng
khai báo trong `settings_fields.py` và ghi xuống cùng một tệp cấu hình. Nhờ
vậy sửa ở đâu cũng ra cùng một kết quả, không có hai nguồn sự thật.

Lưu ở trang Công cụ chỉ ghi những khóa thuộc trang đó, nên không đè lên
những gì người dùng đang sửa dở ở trang Cài đặt.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from autodub_gui import tokens
from autodub_gui.env_store import (
    bool_to_env, env_bool, env_to_multiline, multiline_to_env, read_env,
    write_env,
)
from autodub_gui.pages import BasePage
from autodub_gui.pages import settings_fields as spec
from autodub_gui.ui.buttons import GhostButton, PrimaryButton
from autodub_gui.ui.collapsible import CollapsibleSection
from autodub_gui.ui.inputs import (
    LabeledCombo, LabeledLineEdit, LabeledSlider, LabeledWidget,
)
from autodub_gui.ui.modal import ConfirmDialog
from autodub_gui.ui.style import clear_background
from autodub_gui.ui.toast import TOASTS

_PAGE_MARGIN = 24
_MULTILINE_H = 76


def _to_float(raw: str, fallback: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        try:
            return float(fallback)
        except (TypeError, ValueError):
            return 0.0


class ToolPage(BasePage):
    """Một trang công cụ: tiêu đề, các nhóm ô nhập, chân trang Hủy và Lưu."""

    saved = Signal()

    #: Thẻ trong `settings_fields` mà trang này lấy các mục ra dựng.
    TAB: str = ""
    #: Tiêu đề và câu dẫn hiện ở đầu trang.
    TITLE: str = ""
    SUBTITLE: str = ""
    #: Những nhóm mở sẵn khi vào trang; còn lại gập cho gọn.
    EXPANDED: set[str] = set()
    SAVE_LABEL: str = "Lưu thay đổi"
    SAVED_TOAST: str = "Đã lưu thay đổi."

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._widgets: dict[str, QWidget] = {}
        self._sections: dict[str, CollapsibleSection] = {}
        self._snapshot: dict[str, str] = {}
        self._dirty = False
        self._build()
        self.reload()

    # -- Dựng giao diện ------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(_PAGE_MARGIN, tokens.SP_4,
                                _PAGE_MARGIN, tokens.SP_4)
        root.setSpacing(tokens.SP_3)

        if self.TITLE:
            title = QLabel(self.TITLE)
            title.setObjectName("pageTitle")
            root.addWidget(title)
        if self.SUBTITLE:
            hint = QLabel(self.SUBTITLE)
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            root.addWidget(hint)

        root.addWidget(self._build_body(), 1)
        root.addLayout(self._build_footer())

    def _build_body(self) -> QWidget:
        """Vùng cuộn chứa các nhóm mục. Trang con có thể thay hẳn phần này."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        clear_background(scroll)
        clear_background(scroll.viewport())

        holder = QWidget()
        clear_background(holder)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, tokens.SP_2, tokens.SP_3, tokens.SP_4)
        layout.setSpacing(tokens.SP_4)
        for group in spec.groups_of(self.TAB):
            layout.addWidget(self._build_group(group))
        for extra in self.extra_panels():
            layout.addWidget(extra)
        layout.addStretch()
        scroll.setWidget(holder)
        return scroll

    def extra_panels(self) -> list[QWidget]:
        """Phần không phải ô nhập đơn giản; trang con ghi đè nếu cần."""
        return []

    def _build_group(self, group: str) -> QWidget:
        section = CollapsibleSection(group, expanded=group in self.EXPANDED)
        self._sections[group] = section
        for item in spec.fields_of(self.TAB):
            if item.group != group:
                continue
            widget = self._build_field(item)
            self._widgets[item.key] = widget
            section.add_widget(widget)
        return section

    # -- Dựng từng loại ô nhập -----------------------------------------
    def _build_field(self, item: spec.Field) -> QWidget:
        builders = {
            spec.COMBO: self._build_combo,
            spec.FONT: self._build_font,
            spec.CHECK: self._build_check,
            spec.SLIDER: self._build_slider,
            spec.NUMBER: self._build_number,
            spec.MULTILINE: self._build_multiline,
            spec.FOLDER: self._build_folder,
            spec.FILE: self._build_file,
            spec.COLOR: self._build_color,
        }
        return builders.get(item.kind, self._build_text)(item)

    def _build_combo(self, item: spec.Field) -> QWidget:
        widget = LabeledCombo(item.label, item.options, item.hint)
        widget.changed.connect(self._mark_dirty)
        return widget

    def _build_font(self, item: spec.Field) -> QWidget:
        from autodub_gui.fonts import font_choices

        widget = LabeledCombo(item.label, font_choices(), item.hint)
        widget.changed.connect(self._mark_dirty)
        return widget

    def _build_check(self, item: spec.Field) -> QWidget:
        box = QCheckBox(item.label)
        box.setToolTip(item.hint)
        box.toggled.connect(self._mark_dirty)
        return box

    def _build_slider(self, item: spec.Field) -> QWidget:
        widget = LabeledSlider(item.label, item.minimum, item.maximum,
                               item.step, item.hint, item.suffix,
                               decimals=item.decimals)
        widget.changed.connect(self._mark_dirty)
        return widget

    def _build_number(self, item: spec.Field) -> QWidget:
        spin = QDoubleSpinBox()
        spin.setRange(item.minimum, item.maximum)
        spin.setSingleStep(item.step)
        spin.setDecimals(item.decimals)
        spin.setSuffix(item.suffix)
        spin.valueChanged.connect(self._mark_dirty)
        return LabeledWidget(item.label, spin, item.hint)

    def _build_text(self, item: spec.Field) -> QWidget:
        widget = LabeledLineEdit(item.label, item.placeholder, item.hint)
        widget.changed.connect(self._mark_dirty)
        return widget

    def _build_multiline(self, item: spec.Field) -> QWidget:
        from PySide6.QtWidgets import QPlainTextEdit

        edit = QPlainTextEdit()
        edit.setPlaceholderText(item.placeholder)
        edit.setFixedHeight(_MULTILINE_H)
        edit.textChanged.connect(self._mark_dirty)
        return LabeledWidget(item.label, edit, item.hint)

    def _build_folder(self, item: spec.Field) -> QWidget:
        from autodub_gui.ui.inputs import FilePicker

        widget = FilePicker(item.label, item.placeholder, item.hint,
                            directory=True)
        widget.changed.connect(lambda _t: self._mark_dirty())
        return widget

    def _build_file(self, item: spec.Field) -> QWidget:
        from autodub_gui.ui.inputs import FilePicker

        widget = FilePicker(item.label, item.placeholder, item.hint,
                            name_filter="Âm thanh (*.wav *.mp3 *.m4a *.flac)")
        widget.changed.connect(lambda _t: self._mark_dirty())
        return widget

    def _build_color(self, item: spec.Field) -> QWidget:
        button = GhostButton(item.default)
        button.setToolTip(item.hint)
        button.clicked.connect(lambda: self._pick_color(button))
        paint_color(button, item.default)
        return LabeledWidget(item.label, button, item.hint)

    def _pick_color(self, button) -> None:
        from PySide6.QtGui import QColor

        current = QColor(button.text().strip()
                         or tokens.SUBTITLE_TEXT_DEFAULT)
        chosen = QColorDialog.getColor(current, self, "Chọn màu")
        if chosen.isValid():
            paint_color(button, chosen.name().upper())
            self._mark_dirty()

    # -- Chân trang ------------------------------------------------------
    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        for widget in self.footer_extras():
            row.addWidget(widget)
        row.addStretch()
        self.btn_cancel = GhostButton("Hủy")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_changes)
        self.btn_save = PrimaryButton(self.SAVE_LABEL)
        self.btn_save.clicked.connect(self.save)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_save)
        return row

    def footer_extras(self) -> list[QWidget]:
        """Nút phụ ở góc trái chân trang; trang con ghi đè nếu cần."""
        return []

    # -- Đọc và ghi giá trị của một ô ------------------------------------
    def _widget_of(self, key: str) -> QWidget | None:
        widget = self._widgets.get(key)
        return getattr(widget, "field", widget) if widget is not None else None

    def _get_value(self, item: spec.Field) -> str:
        widget = self._widget_of(item.key)
        if widget is None:
            return item.default
        if item.kind in (spec.COMBO, spec.FONT):
            return widget.current_key()
        if item.kind == spec.CHECK:
            return bool_to_env(widget.isChecked())
        if item.kind == spec.SLIDER:
            return f"{widget.value():.{item.decimals}f}"
        if item.kind == spec.NUMBER:
            return f"{widget.widget.value():.{item.decimals}f}"
        if item.kind == spec.MULTILINE:
            return multiline_to_env(widget.widget.toPlainText())
        if item.kind == spec.COLOR:
            return widget.widget.text().strip()
        return widget.text()

    def _set_value(self, item: spec.Field, raw: str) -> None:
        widget = self._widget_of(item.key)
        if widget is None:
            return
        if item.kind in (spec.COMBO, spec.FONT):
            widget.set_key(raw or item.default)
        elif item.kind == spec.CHECK:
            widget.setChecked(env_bool(raw, env_bool(item.default)))
        elif item.kind == spec.SLIDER:
            widget.set_value(_to_float(raw, item.default))
        elif item.kind == spec.NUMBER:
            widget.widget.setValue(_to_float(raw, item.default))
        elif item.kind == spec.MULTILINE:
            widget.widget.setPlainText(env_to_multiline(raw))
        elif item.kind == spec.COLOR:
            paint_color(widget.widget, raw or item.default)
        else:
            widget.set_text(raw)

    # -- Nạp, gom, lưu ---------------------------------------------------
    def fields(self) -> list[spec.Field]:
        return spec.fields_of(self.TAB)

    def reload(self) -> None:
        """Đọc lại giá trị của trang này từ tệp cấu hình."""
        env = read_env()
        for item in self.fields():
            self._set_value(item, env.get(item.key, item.default))
        self.load_extra(env)
        self._snapshot = self._collect()
        self._set_dirty(False)

    def load_extra(self, env: dict[str, str]) -> None:
        """Nạp phần ngoài bảng khai báo; trang con ghi đè nếu cần."""

    def collect_extra(self) -> dict[str, str]:
        """Giá trị ngoài bảng khai báo; trang con ghi đè nếu cần."""
        return {}

    def _collect(self) -> dict[str, str]:
        values = {item.key: self._get_value(item) for item in self.fields()}
        values.update(self.collect_extra())
        return values

    def current_values(self) -> dict[str, str]:
        """Giá trị đang hiển thị, cho các nút kiểm tra kết nối."""
        return self._collect()

    def save(self) -> None:
        values = self._collect()
        try:
            write_env(values)
        except OSError as e:
            ConfirmDialog.show_error(
                self, "Không lưu được thay đổi",
                "Ứng dụng không ghi được vào tệp cấu hình. Có thể tệp đang bị "
                "một chương trình khác mở, hoặc thư mục không cho ghi. Hãy "
                "đóng chương trình đó rồi bấm Lưu lại.", detail=str(e))
            return
        self.after_save(values)
        self._snapshot = self._collect()
        self._set_dirty(False)
        TOASTS.success(self.SAVED_TOAST)
        self.saved.emit()

    def after_save(self, values: dict[str, str]) -> None:
        """Việc cần làm ngay sau khi ghi; trang con ghi đè nếu cần."""

    def _cancel_changes(self) -> None:
        if not self._dirty:
            return
        confirmed, _ = ConfirmDialog.ask(
            self, "Bỏ thay đổi",
            "Mọi thay đổi bạn vừa chỉnh sẽ quay về giá trị đã lưu lần trước. "
            "Bạn có chắc không?",
            kind="warning", confirm_label="Bỏ thay đổi",
            cancel_label="Giữ lại")
        if not confirmed:
            return
        for item in self.fields():
            self._set_value(item, self._snapshot.get(item.key, item.default))
        self.load_extra(self._snapshot)
        self._set_dirty(False)
        TOASTS.info("Đã quay về giá trị đã lưu lần trước.")

    # -- Theo dõi thay đổi -----------------------------------------------
    def _mark_dirty(self, *_args) -> None:
        self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self.btn_cancel.setEnabled(dirty)
        self.btn_save.setText(self.SAVE_LABEL + (" •" if dirty else ""))

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    # -- Vòng đời --------------------------------------------------------
    def on_shown(self) -> None:
        """Trang Cài đặt có thể đã ghi đè giá trị — đọc lại nếu chưa sửa gì."""
        if not self._dirty:
            self.reload()


def paint_color(button, hex_color: str) -> None:
    """Tô nền nút theo màu đang chọn, chữ đen hay trắng tùy độ sáng."""
    from PySide6.QtGui import QColor

    button.setText(hex_color)
    color = QColor(hex_color)
    luminance = (0.299 * color.red() + 0.587 * color.green()
                 + 0.114 * color.blue())
    text_color = tokens.BG_APP if luminance > 140 else tokens.TEXT_ON_ACCENT
    button.setStyleSheet(
        f"QPushButton#ghost {{ background: {hex_color}; "
        f"color: {text_color}; font-weight: 600; }}")
