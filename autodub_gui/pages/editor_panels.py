"""Các bảng bên phải của Trình chỉnh sửa.

Bảng danh sách phụ đề là phần được dùng nhiều nhất nên được tối ưu riêng:
khi dự án có nhiều câu, chỉ những câu đang nhìn thấy mới được dựng widget.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)

from autodub_gui import dub_constants as consts
from autodub_gui import icons, tokens
from autodub_gui.formatting import (
    format_duration, format_hours, format_size, format_timecode,
)
from autodub_gui.ui.buttons import GhostButton, IconButton, PrimaryButton
from autodub_gui.ui.collapsible import CollapsibleSection
from autodub_gui.ui.inputs import LabeledCombo, LabeledSlider, SearchBox
from autodub_gui.ui.labels import ElidedLabel
from autodub_gui.ui.progress import ThinProgressBar
from autodub_gui.ui.style import clear_background

EDIT_DEBOUNCE_MS = 800
_ROW_ICON = 24
_TEXT_MIN_H = 46
_ROW_PADDING = 8


class _GrowingTextEdit(QPlainTextEdit):
    """Ô nhập tự cao lên theo nội dung — chữ dài mấy cũng không bị cắt.

    QPlainTextEdit mặc định giữ chiều cao cố định và cuộn bên trong; trong
    danh sách câu thoại điều đó đồng nghĩa với chữ bị cắt (thanh cuộn đã tắt).
    Ô này đo số dòng thật sau khi xuống dòng và nới chiều cao theo.
    """

    height_changed = Signal()

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda _s: self._fit())
        self._fit()

    def _fit(self) -> None:
        # documentSize() của QPlainTextDocumentLayout trả chiều cao theo SỐ
        # DÒNG (đã tính cả xuống dòng tự động), không phải điểm ảnh.
        lines = max(1, int(self.document().size().height()))
        height = int(lines * self.fontMetrics().lineSpacing()
                     + 2 * self.document().documentMargin()
                     + 2 * self.frameWidth() + 2)
        height = max(_TEXT_MIN_H, height)
        if height != self.minimumHeight():
            self.setMinimumHeight(height)
            self.setMaximumHeight(height)
            self.height_changed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        super().resizeEvent(event)
        # Đổi bề rộng làm chữ xuống dòng khác đi — đo lại chiều cao.
        self._fit()


class SegmentRow(QWidget):
    """Một câu thoại: mốc thời gian, lời đọc, phụ đề riêng và hàng nút.

    Ô phụ đề riêng chỉ hiện khi người dùng bật chế độ tách phụ đề, hoặc khi
    câu này vốn đã có phụ đề khác lời đọc. Để trống ô đó nghĩa là phụ đề dùng
    y hệt lời đọc — đúng như phần lớn trường hợp.
    """

    text_edited = Signal(int, str)
    subtitle_edited = Signal(int, str)
    play_requested = Signal(int)
    resynth_requested = Signal(int)
    split_requested = Signal(int)
    merge_requested = Signal(int)
    delete_requested = Signal(int)
    height_changed = Signal(int)         # id câu — dòng cần được đo lại
    voice_changed = Signal(int, str)     # (id, tên giọng) — "" = dùng giọng chung

    def __init__(self, segment: dict, text_field: str,
                 show_subtitle: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        from autodub.text.srt import SUBTITLE_FIELD, has_subtitle_override

        self._id = int(segment.get("id", 0))
        self._text_field = text_field
        self._voice_override: str = str(segment.get("voice", "")).strip()
        root = QVBoxLayout(self)
        root.setContentsMargins(_ROW_PADDING, _ROW_PADDING,
                                _ROW_PADDING, _ROW_PADDING)
        root.setSpacing(tokens.SP_1)

        head = QHBoxLayout()
        head.setSpacing(tokens.SP_2)
        self.time_label = QLabel(self._time_text(segment))
        self.time_label.setStyleSheet(
            f"color: {tokens.PRIMARY}; font-size: {tokens.FS_META}px; "
            f"font-family: {tokens.FONT_MONO}; background: transparent;")
        head.addWidget(self.time_label)
        head.addStretch()
        # Chip giọng riêng — chỉ hiện khi câu này có giọng khác giọng chung.
        from PySide6.QtWidgets import QPushButton
        self._voice_chip = QPushButton(self._voice_override or "")
        self._voice_chip.setToolTip("Giọng riêng của câu này — bấm để bỏ")
        self._voice_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._voice_chip.setStyleSheet(
            f"QPushButton {{ background: {tokens.BG_SELECTED_SOFT}; "
            f"color: {tokens.ACCENT_PURPLE}; font-size: {tokens.FS_BADGE}px; "
            f"font-weight: 600; border: 1px solid {tokens.ACCENT_PURPLE}; "
            f"border-radius: 8px; padding: 0 6px; }} "
            f"QPushButton:hover {{ background: {tokens.BG_SELECTED}; }}")
        self._voice_chip.setFixedHeight(18)
        self._voice_chip.setVisible(bool(self._voice_override))
        self._voice_chip.clicked.connect(lambda: self._emit_voice(""))
        head.addWidget(self._voice_chip)
        self.index_label = QLabel(f"Câu {self._id}")
        self.index_label.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_BADGE}px; "
            f"background: transparent;")
        head.addWidget(self.index_label)
        root.addLayout(head)

        self.editor = self._text_box(str(segment.get(text_field, "")),
                                     tokens.TEXT_PRIMARY)
        self.editor.textChanged.connect(
            lambda: self.text_edited.emit(self._id,
                                          self.editor.toPlainText()))
        root.addWidget(self.editor)

        self.sub_caption = QLabel("Phụ đề riêng")
        self.sub_caption.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_BADGE}px; "
            f"background: transparent;")
        self.sub_editor = self._text_box(
            str(segment.get(SUBTITLE_FIELD, "") or ""), tokens.TEXT_SECONDARY)
        self.sub_editor.setPlaceholderText("Để trống là dùng y hệt lời đọc")
        self.sub_editor.textChanged.connect(
            lambda: self.subtitle_edited.emit(self._id,
                                              self.sub_editor.toPlainText()))
        root.addWidget(self.sub_caption)
        root.addWidget(self.sub_editor)
        self.set_subtitle_visible(
            show_subtitle or has_subtitle_override(segment, text_field))

        root.addLayout(self._build_actions())
        # Ô chữ cao lên (gõ thêm dòng) thì báo cho danh sách nới dòng theo.
        self.editor.height_changed.connect(
            lambda: self.height_changed.emit(self._id))
        self.sub_editor.height_changed.connect(
            lambda: self.height_changed.emit(self._id))

    @staticmethod
    def _text_box(text: str, color: str) -> "_GrowingTextEdit":
        box = _GrowingTextEdit(text)
        box.setStyleSheet(
            f"QPlainTextEdit {{ background: transparent; border: none; "
            f"color: {color}; font-size: {tokens.FS_BODY}px; padding: 0; }}")
        return box

    def set_subtitle_visible(self, visible: bool) -> None:
        self.sub_caption.setVisible(visible)
        self.sub_editor.setVisible(visible)

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_1)
        specs = (
            (icons.play(tokens.SUCCESS), "Nghe câu này", self.play_requested),
            (icons.reload(tokens.ACCENT_BLUE), "Đọc lại câu này",
             self.resynth_requested),
            (icons.scissors(tokens.TEXT_SECONDARY), "Tách câu này làm đôi",
             self.split_requested),
            (icons.merge(tokens.TEXT_SECONDARY), "Gộp với câu bên dưới",
             self.merge_requested),
            (icons.trash(tokens.DANGER), "Xóa câu này", self.delete_requested),
        )
        for icon, tip, signal in specs:
            button = IconButton(icon, tip, size=_ROW_ICON)
            button.clicked.connect(lambda _c=False, s=signal: s.emit(self._id))
            row.addWidget(button)
        # Nút gán giọng riêng — mở popup giọng để người dùng chọn.
        self._btn_voice = IconButton(
            icons.mic(tokens.TEXT_SECONDARY),
            "Gán giọng riêng cho câu này", size=_ROW_ICON)
        self._btn_voice.clicked.connect(self._open_voice_popup)
        row.addWidget(self._btn_voice)
        row.addStretch()
        return row

    def _open_voice_popup(self) -> None:
        """Mở popup chọn giọng cho riêng câu này."""
        from autodub.speech.tts import voices as catalog
        from autodub.config import Settings
        from autodub_gui.voice_picker import _VoicePopup

        try:
            voices = catalog.catalog(Settings.load())
        except Exception:  # noqa: BLE001
            voices = []
        popup = _VoicePopup(self)
        popup.picked.connect(self._emit_voice)
        popup.open_for(self._btn_voice, voices, self._voice_override)

    def _emit_voice(self, name: str) -> None:
        """Phát tín hiệu thay đổi giọng và cập nhật chip hiển thị."""
        name = (name or "").strip()
        self._voice_override = name
        self._voice_chip.setText(name)
        self._voice_chip.setVisible(bool(name))
        self.voice_changed.emit(self._id, name)

    @staticmethod
    def _time_text(segment: dict) -> str:
        return (f"{format_timecode(segment.get('start', 0))}  →  "
                f"{format_timecode(segment.get('end', 0))}")

    def segment_id(self) -> int:
        return self._id

    def set_text(self, text: str) -> None:
        if text != self.editor.toPlainText():
            self.editor.blockSignals(True)
            self.editor.setPlainText(text)
            self.editor.blockSignals(False)

    def set_times(self, segment: dict) -> None:
        self.time_label.setText(self._time_text(segment))

    def set_active(self, active: bool) -> None:
        """Tô sáng câu đang được đọc."""
        self.setStyleSheet(
            f"background: {tokens.BG_SELECTED_SOFT}; border-radius: 8px;"
            if active else "background: transparent;")


class SubtitleListPanel(QWidget):
    """Danh sách câu thoại có tìm kiếm và các nút thao tác từng câu."""

    text_edited = Signal(int, str)
    subtitle_edited = Signal(int, str)
    segment_selected = Signal(int)
    play_requested = Signal(int)
    resynth_requested = Signal(int)
    split_requested = Signal(int)
    merge_requested = Signal(int)
    delete_requested = Signal(int)
    voice_changed = Signal(int, str)     # (seg_id, tên giọng) — "" = giọng chung
    add_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._segments: list[dict] = []
        self._filtered: list[dict] = []
        self._rows: dict[int, SegmentRow] = {}
        self._items: dict[int, QListWidgetItem] = {}
        self._text_field = "text_vi"
        self._active = -1
        self._split_mode = False
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(tokens.SP_2)

        head = QHBoxLayout()
        head.setSpacing(tokens.SP_2)
        title = QLabel("Lời thoại và phụ đề")
        title.setObjectName("cardTitle")
        head.addWidget(title)
        head.addStretch()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        head.addWidget(self.count_label)
        root.addLayout(head)

        self.search = SearchBox("Tìm trong lời thoại")
        self.search.search_changed.connect(self._apply_filter)
        root.addWidget(self.search)

        self.chk_split = QCheckBox("Phụ đề viết riêng, khác lời đọc")
        self.chk_split.setToolTip(
            "Bật khi bạn muốn chữ trên màn hình khác với chữ được đọc lên. "
            "Sửa phụ đề riêng chỉ cần ghi lại phụ đề vào video, không phải "
            "đọc lại giọng.")
        self.chk_split.toggled.connect(self._on_split_toggled)
        root.addWidget(self.chk_split)

        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setUniformItemSizes(False)
        self.list.currentRowChanged.connect(self._on_row_changed)
        root.addWidget(self.list, 1)

        add_button = GhostButton("Thêm câu mới")
        add_button.clicked.connect(self.add_requested.emit)
        root.addWidget(add_button)

    # -- Dữ liệu -------------------------------------------------------
    def set_segments(self, segments: list[dict],
                     text_field: str = "text_vi") -> None:
        """Dựng lại toàn bộ danh sách."""
        self._segments = segments
        self._text_field = text_field
        self._apply_filter(self.search.text())

    def _apply_filter(self, query: str = "") -> None:
        text = (query or "").strip().lower()
        self._filtered = [s for s in self._segments
                          if not text
                          or text in str(s.get(self._text_field, "")).lower()]
        self._rebuild()

    def _on_split_toggled(self, checked: bool) -> None:
        self._split_mode = checked
        for row in self._rows.values():
            row.set_subtitle_visible(checked)
        # Chiều cao dòng đổi khi ô phụ đề hiện ra — dựng lại để không bị cắt.
        self._rebuild()

    def _rebuild(self) -> None:
        self.list.clear()
        self._rows.clear()
        self._items.clear()
        for segment in self._filtered:
            row = SegmentRow(segment, self._text_field, self._split_mode)
            row.text_edited.connect(self.text_edited.emit)
            row.subtitle_edited.connect(self.subtitle_edited.emit)
            row.play_requested.connect(self.play_requested.emit)
            row.resynth_requested.connect(self.resynth_requested.emit)
            row.split_requested.connect(self.split_requested.emit)
            row.merge_requested.connect(self.merge_requested.emit)
            row.delete_requested.connect(self.delete_requested.emit)
            row.voice_changed.connect(self.voice_changed.emit)
            row.height_changed.connect(self._on_row_height_changed)
            item = QListWidgetItem(self.list)
            item.setSizeHint(QSize(0, row.sizeHint().height()))
            item.setData(Qt.ItemDataRole.UserRole, row.segment_id())
            self.list.setItemWidget(item, row)
            self._rows[row.segment_id()] = row
            self._items[row.segment_id()] = item
        total = len(self._segments)
        shown = len(self._filtered)
        self.count_label.setText(
            f"{total} câu" if shown == total
            else f"{shown} trên {total} câu")

    def _on_row_height_changed(self, seg_id: int) -> None:
        """Nới dòng danh sách theo chiều cao mới của ô chữ — không cắt chữ."""
        row = self._rows.get(seg_id)
        item = self._items.get(seg_id)
        if row is None or item is None:
            return
        height = row.sizeHint().height()
        if item.sizeHint().height() != height:
            item.setSizeHint(QSize(0, height))

    def _on_row_changed(self, index: int) -> None:
        item = self.list.item(index)
        if item is not None:
            self.segment_selected.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def highlight(self, seg_id: int) -> None:
        """Tô sáng câu đang được đọc và cuộn tới nếu nó nằm ngoài tầm nhìn."""
        if seg_id == self._active:
            return
        previous = self._rows.get(self._active)
        if previous is not None:
            previous.set_active(False)
        self._active = seg_id
        row = self._rows.get(seg_id)
        if row is None:
            return
        row.set_active(True)
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == seg_id:
                if not self._is_visible(index):
                    self.list.scrollToItem(
                        item, QAbstractItemView.ScrollHint.PositionAtCenter)
                break

    def _is_visible(self, index: int) -> bool:
        """Dòng này có đang nằm trong vùng nhìn thấy không, tránh cuộn giật."""
        item = self.list.item(index)
        rect = self.list.visualItemRect(item)
        return self.list.viewport().rect().intersects(rect)

    def refresh_times(self, segments: list[dict]) -> None:
        """Cập nhật mốc thời gian sau khi người dùng kéo trên dải thời gian."""
        for segment in segments:
            row = self._rows.get(int(segment.get("id", 0)))
            if row is not None:
                row.set_times(segment)

    def selected_id(self) -> int:
        item = self.list.currentItem()
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else -1

    def focus_search(self) -> None:
        self.search.focus()


class OverviewPanel(QScrollArea):
    """Thông tin chung của dự án và các nút mở nhanh."""

    open_folder = Signal()
    open_subtitle = Signal()
    open_youtube = Signal()
    open_other = Signal()
    issue_clicked = Signal(int)          # id câu trong báo cáo chất lượng
    context_saved = Signal(dict)         # ngữ cảnh dịch người dùng vừa sửa

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        holder = QWidget()
        clear_background(holder)
        self._layout = QVBoxLayout(holder)
        self._layout.setContentsMargins(0, 0, tokens.SP_2, 0)
        self._layout.setSpacing(tokens.SP_3)

        self._rows: dict[str, ElidedLabel] = {}
        info = CollapsibleSection("Thông tin dự án", expanded=True)
        for key, label in (("title", "Tên dự án"), ("path", "Thư mục"),
                           ("language", "Ngôn ngữ gốc"), ("voice", "Giọng đọc"),
                           ("segments", "Số câu thoại"),
                           ("duration", "Thời lượng"),
                           ("processing", "Thời gian đã xử lý"),
                           ("size", "Dung lượng")):
            info.add_layout(self._info_row(key, label))
        self._layout.addWidget(info)

        self.quality = CollapsibleSection("Chất lượng bản lồng tiếng",
                                          expanded=True)
        self.quality_label = QLabel("Chưa có số liệu.")
        self.quality_label.setWordWrap(True)
        self.quality_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.quality.add_widget(self.quality_label)
        # Danh sách câu cần xem lại — bấm một dòng là nhảy tới đúng câu đó
        # trong mục Phụ đề, khỏi phải dò tìm bằng mắt.
        self.issue_list = QListWidget()
        self.issue_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.issue_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.issue_list.setStyleSheet(
            f"QListWidget {{ background: {tokens.BG_INPUT}; border: 1px solid "
            f"{tokens.BORDER_SUBTLE}; border-radius: 8px; }}"
            f"QListWidget::item {{ padding: 6px 8px; }}")
        self.issue_list.itemClicked.connect(self._on_issue_clicked)
        self.issue_list.setVisible(False)
        self.quality.add_widget(self.issue_list)
        self.usage_label = QLabel("")
        self.usage_label.setWordWrap(True)
        self.usage_label.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_BADGE}px; "
            f"background: transparent;")
        self.usage_label.setVisible(False)
        self.quality.add_widget(self.usage_label)
        self._layout.addWidget(self.quality)

        actions = CollapsibleSection("Mở nhanh", expanded=True)
        for text, signal in (("Mở thư mục dự án", self.open_folder),
                             ("Mở tệp phụ đề", self.open_subtitle),
                             ("Mở thư mục tiêu đề và mô tả", self.open_youtube),
                             ("Mở thư mục dự án khác…", self.open_other)):
            row = QHBoxLayout()
            button = GhostButton(text)
            button.clicked.connect(signal.emit)
            row.addWidget(button)
            row.addStretch()
            actions.add_layout(row)
        self._layout.addWidget(actions)
        self._layout.addWidget(self._build_context_section())
        self._layout.addStretch()
        self.setWidget(holder)

    def _build_context_section(self) -> CollapsibleSection:
        """Mục xem/sửa ngữ cảnh dịch riêng của video này.

        Đây là chính ``data/video_context.json`` — thứ lượt phân tích tự động
        đã đoán ra. Người dùng sửa ở đây rồi dịch lại/xuất lại thì bản dịch
        dùng đúng thuật ngữ và xưng hô họ muốn, không phải đoán nữa.
        """
        section = CollapsibleSection("Ngữ cảnh dịch của video này",
                                     expanded=False)
        note = QLabel(
            "App tự phân tích video để đoán chủ đề, xưng hô và thuật ngữ. "
            "Bạn có thể sửa lại cho đúng ý — bản dịch lại (nếu có) sẽ dùng "
            "các thông tin này.")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        section.add_widget(note)

        self._ctx_fields: dict[str, QPlainTextEdit] = {}
        for key, label, placeholder, height in (
                ("summary", "Video nói về gì",
                 "Ví dụ: Video review điện thoại, người nói là chủ kênh…", 64),
                ("domain", "Chủ đề",
                 "Ví dụ: review công nghệ", 40),
                ("pronouns", "Cách xưng hô",
                 "Ví dụ: mình – các bạn", 40),
                ("glossary", "Thuật ngữ cố định (mỗi dòng: gốc = dịch)",
                 "Ví dụ:\n小米 = Xiaomi\n老板 = ông chủ", 88),
                ("style_notes", "Ghi chú văn phong",
                 "Ví dụ: giọng vui vẻ, thân mật", 40)):
            caption = QLabel(label)
            caption.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; "
                f"font-size: {tokens.FS_META}px; background: transparent;")
            box = QPlainTextEdit()
            box.setPlaceholderText(placeholder)
            box.setFixedHeight(height)
            box.setStyleSheet(
                f"QPlainTextEdit {{ background: {tokens.BG_INPUT}; "
                f"border: 1px solid {tokens.BORDER_SUBTLE}; "
                f"border-radius: 6px; color: {tokens.TEXT_PRIMARY}; "
                f"font-size: {tokens.FS_META}px; padding: 4px; }}")
            self._ctx_fields[key] = box
            section.add_widget(caption)
            section.add_widget(box)

        row = QHBoxLayout()
        save = GhostButton("Lưu ngữ cảnh")
        save.setToolTip("Lưu vào dự án này. Lần dịch lại kế tiếp sẽ dùng "
                        "đúng các thông tin trên.")
        save.clicked.connect(self._emit_context)
        row.addWidget(save)
        row.addStretch()
        section.add_layout(row)
        return section

    def set_context(self, context: dict) -> None:
        """Đổ ``video_context.json`` vào các ô sửa (glossary: list → text)."""
        for key, box in self._ctx_fields.items():
            value = (context or {}).get(key, "")
            if key == "glossary" and isinstance(value, list):
                value = "\n".join(str(x).strip() for x in value
                                  if str(x).strip())
            box.blockSignals(True)
            box.setPlainText(str(value or ""))
            box.blockSignals(False)

    def _emit_context(self) -> None:
        data: dict = {}
        for key, box in self._ctx_fields.items():
            text = box.toPlainText().strip()
            if key == "glossary":
                data[key] = [line.strip() for line in text.splitlines()
                             if line.strip()]
            else:
                data[key] = text
        self.context_saved.emit(data)

    def _info_row(self, key: str, label: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        name = QLabel(label)
        name.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        name.setMinimumWidth(130)
        value = ElidedLabel("—")
        value.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        row.addWidget(name)
        row.addWidget(value, 1)
        self._rows[key] = value
        return row

    def set_project(self, project, segments: int, quality: dict) -> None:
        """Đổ thông tin của một dự án vào bảng."""
        values = {
            "title": project.title,
            "path": project.work_dir,
            "language": project.source_lang or "không rõ",
            "voice": project.voice or "không rõ",
            "segments": str(segments),
            "duration": format_duration(project.duration_s),
            "processing": format_hours(project.processing_s),
            "size": format_size(project.size_bytes),
        }
        for key, text in values.items():
            self._rows[key].setText(text)
        self.quality_label.setText(_quality_text(quality))
        self._fill_issues(quality)

    def _fill_issues(self, quality: dict) -> None:
        """Đổ danh sách câu cần xem lại từ quality_report.json."""
        self.issue_list.clear()
        issues = [s for s in (quality or {}).get("per_segment") or []
                  if isinstance(s, dict) and s.get("id") is not None]
        self.issue_list.setVisible(bool(issues))
        for seg in issues:
            item = QListWidgetItem(_issue_text(seg))
            item.setData(Qt.ItemDataRole.UserRole, int(seg["id"]))
            item.setToolTip("Bấm để nhảy tới câu này trong mục Phụ đề")
            self.issue_list.addItem(item)
        # Cao vừa đủ nội dung (tối đa ~8 dòng) — bảng Tổng quan tự cuộn.
        if issues:
            row_h = self.issue_list.sizeHintForRow(0)
            self.issue_list.setFixedHeight(
                min(len(issues), 8) * max(row_h, 24) + 12)
        usage = (quality or {}).get("translate_usage") or {}
        total = int(usage.get("total_tokens", 0) or 0)
        if total:
            self.usage_label.setText(
                f"Lượt dịch dùng {usage.get('requests', 0)} lần gọi, "
                f"{total:,} token ({usage.get('prompt_tokens', 0):,} gửi đi, "
                f"{usage.get('completion_tokens', 0):,} nhận về).".replace(
                    ",", "."))
        self.usage_label.setVisible(bool(total))

    def _on_issue_clicked(self, item: QListWidgetItem) -> None:
        self.issue_clicked.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def set_voice(self, name: str) -> None:
        """Cập nhật riêng dòng giọng đọc sau khi đã phân giải được tên thật."""
        if name:
            self._rows["voice"].setText(name)


def _quality_text(quality: dict) -> str:
    """Diễn giải bản đánh giá chất lượng bằng lời thường."""
    summary = (quality or {}).get("summary") or {}
    if not summary:
        return "Chưa có số liệu chất lượng cho dự án này."
    total = summary.get("segments_total", "—")
    ok = summary.get("segments_ok", "—")
    overlapped = summary.get("segments_overlapped", 0)
    lines = [f"{ok} trên {total} câu khớp thời lượng."]
    if overlapped:
        lines.append(
            f"Còn {overlapped} câu bị chồng sang câu sau. Hãy giảm Tốc độ "
            "video hoặc tăng Tốc độ giọng đọc rồi xuất lại.")
    else:
        lines.append("Không còn câu nào bị chồng tiếng.")
    extras = []
    if summary.get("segments_shifted"):
        extras.append(f"{summary['segments_shifted']} câu được lùi nhẹ "
                      "vào khoảng lặng")
    if summary.get("segments_compressed"):
        extras.append(f"{summary['segments_compressed']} câu đọc nhanh hơn "
                      "một chút cho vừa chỗ")
    if summary.get("segments_over_budget"):
        extras.append(f"{summary['segments_over_budget']} câu có bản dịch "
                      "dài hơn thời lượng cho phép")
    if extras:
        lines.append(", ".join(extras).capitalize() + ".")
    hint = (quality or {}).get("hint")
    if hint:
        lines.append(str(hint))
    return " ".join(lines)


def _issue_text(seg: dict) -> str:
    """Một dòng mô tả vấn đề của một câu, ngắn gọn cho danh sách."""
    tags = []
    if seg.get("overlap_prev_s"):
        tags.append(f"chồng {seg['overlap_prev_s']:.1f}s")
    if seg.get("shift_s"):
        tags.append(f"lùi {seg['shift_s']:.1f}s")
    if seg.get("atempo"):
        tags.append(f"nén {seg['atempo']:.2f}x")
    if seg.get("over_budget_chars"):
        tags.append(f"dài quá {seg['over_budget_chars']} ký tự")
    text = str(seg.get("text", "") or "")
    if len(text) > 60:
        text = text[:57] + "…"
    head = f"Câu {seg.get('id')}"
    if tags:
        head += " — " + ", ".join(tags)
    return f"{head}\n{text}" if text else head


class AudioPanel(CollapsibleSection):
    """Tinh chỉnh âm thanh, lưu riêng cho từng dự án."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Âm thanh của dự án này", expanded=True, parent=parent)
        self.postprocess = QCheckBox("Làm đều độ lớn giọng đọc")
        self.postprocess.setToolTip(
            "Cân bằng để câu nào cũng nghe rõ như nhau.")
        self.loudness = LabeledSlider(
            "Độ lớn giọng đọc", -24.0, -10.0, 0.5,
            "Càng gần 0 thì giọng càng to.", " dB", decimals=1)
        self.duck = LabeledSlider(
            "Giảm nhạc nền khi có lời", -24.0, 0.0, 0.5,
            "Nhạc nền tự nhỏ đi bấy nhiêu mỗi khi có lời thoại.",
            " dB", decimals=1)
        self.soft_timing = QCheckBox("Tự căn lại thời điểm từng câu")
        self.drift = LabeledSlider(
            "Cho phép lệch tối đa", 0.0, 5.0, 0.1,
            "Mỗi câu được dịch đi nhiều nhất bấy nhiêu giây.",
            " giây", decimals=1)
        for widget in (self.postprocess, self.loudness, self.duck,
                       self.soft_timing, self.drift):
            self.add_widget(widget)
        for widget in (self.loudness, self.duck, self.drift):
            widget.changed.connect(lambda _v: self.changed.emit())
        for box in (self.postprocess, self.soft_timing):
            box.toggled.connect(lambda _c: self.changed.emit())

    def load(self, opts: dict, settings) -> None:
        """Nạp từ tùy chọn của dự án, thiếu thì lấy theo cài đặt chung."""
        self.postprocess.setChecked(
            bool(opts.get("voice_postprocess", settings.voice_postprocess)))
        self.loudness.set_value(
            float(opts.get("voice_target_lufs", settings.voice_target_lufs)))
        self.duck.set_value(
            float(opts.get("bg_duck_voice_db", settings.bg_duck_voice_db)))
        self.soft_timing.setChecked(
            bool(opts.get("soft_timing_fit", settings.soft_timing_fit)))
        self.drift.set_value(
            float(opts.get("timing_max_drift_s", settings.timing_max_drift_s)))

    def values(self) -> dict:
        return {
            "voice_postprocess": self.postprocess.isChecked(),
            "voice_target_lufs": self.loudness.value(),
            "bg_duck_voice_db": self.duck.value(),
            "soft_timing_fit": self.soft_timing.isChecked(),
            "timing_max_drift_s": self.drift.value(),
        }


class VoicePanel(CollapsibleSection):
    """Chọn giọng theo tên và đọc lại những câu đã sửa."""

    preview_requested = Signal(str)      # tên giọng
    resynth_all_requested = Signal()
    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Giọng đọc", expanded=True, parent=parent)
        from autodub_gui.voice_picker import VoicePicker

        self.picker = VoicePicker("Giọng đọc của video này")
        self.picker.setToolTip(
            "Đây là giọng video này đang dùng. Đổi giọng ở đây rồi bấm "
            "«Lưu tất cả và đọc lại» để đọc lại toàn bộ bằng giọng mới — "
            "cài đặt chung không bị ảnh hưởng.")
        self.picker.changed.connect(self._on_voice_changed)
        self.picker.preview_requested.connect(self.preview_requested.emit)
        self.add_widget(self.picker)

        self.voice_hint = QLabel("")
        self.voice_hint.setWordWrap(True)
        self.voice_hint.setStyleSheet(
            f"color: {tokens.WARNING}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.voice_hint.setVisible(False)
        self.add_widget(self.voice_hint)

        self.speed = LabeledSlider(
            "Tốc độ đọc", 0.5, 2.0, 0.05,
            "1.00 là tốc độ tự nhiên.", "x")
        self.speed.set_value(1.0)
        self.speed.changed.connect(lambda _v: self.changed.emit())
        self.add_widget(self.speed)

        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        self.btn_resynth = PrimaryButton("Lưu tất cả và đọc lại")
        self.btn_resynth.setToolTip(
            "Lưu mọi câu bạn đã sửa rồi tạo lại giọng đọc cho những câu đó.")
        self.btn_resynth.clicked.connect(self.resynth_all_requested.emit)
        row.addWidget(self.btn_resynth)
        row.addStretch()
        self.add_layout(row)

        self.progress = ThinProgressBar()
        self.progress.setVisible(False)
        self.add_widget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.add_widget(self.status)
        self._project_voice = ""

    def set_project_voice(self, name: str) -> None:
        """Ghi nhớ giọng video này đang dùng thật, để so khi người dùng đổi."""
        self._project_voice = name
        self.picker.set_voice(name)
        self._refresh_hint()

    def _on_voice_changed(self) -> None:
        self._refresh_hint()
        self.changed.emit()

    def _refresh_hint(self) -> None:
        """Đổi giọng mà chưa đọc lại thì video vẫn là giọng cũ — phải nói rõ."""
        changed = (self._project_voice
                   and self.picker.voice() != self._project_voice)
        if changed:
            self.voice_hint.setText(
                f"Video đang dùng giọng {self._project_voice}. Bấm «Lưu tất "
                f"cả và đọc lại» để chuyển hẳn sang giọng "
                f"{self.picker.voice()}.")
        self.voice_hint.setVisible(bool(changed))

    def mark_voice_applied(self) -> None:
        """Gọi sau khi đọc lại xong: giọng đang chọn đã thành giọng của video."""
        self._project_voice = self.picker.voice()
        self._refresh_hint()

    def has_pending_voice_change(self) -> bool:
        """Người dùng đã đổi giọng nhưng chưa đọc lại toàn bộ."""
        return bool(self._project_voice
                    and self.picker.voice() != self._project_voice)

    def project_voice(self) -> str:
        """Giọng đang nằm thật trong âm thanh của video."""
        return self._project_voice or self.picker.voice()

    def set_progress(self, done: int, total: int) -> None:
        self.progress.setVisible(total > 0)
        self.progress.setValue(int(done / total * 100) if total else 0)
        self.status.setText(f"Đang đọc lại câu {done} trên {total}"
                            if total else "")

    def finish_progress(self, message: str) -> None:
        self.progress.setVisible(False)
        self.status.setText(message)

    def values(self) -> dict:
        # KHÔNG trả về "voice": khóa đó trong render_opts luôn là giọng đã
        # nằm thật trong âm thanh, chỉ được cập nhật sau khi đọc lại thành
        # công (xem editor_export._on_resynth_done).
        return {"voice_speed": self.speed.value()}


class BackgroundPanel(CollapsibleSection):
    """Xử lý nhạc nền của dự án."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Nhạc nền", expanded=True, parent=parent)
        self.mode = LabeledCombo("Cách xử lý", consts.BG_MODES,
                                 "Cách xử lý âm thanh gốc của video")
        self.mode.changed.connect(self.changed.emit)
        self.duck = LabeledSlider(
            "Mức giảm tiếng gốc", -40.0, 0.0, 1.0,
            "Càng âm thì tiếng gốc càng nhỏ.", " dB", decimals=0)
        self.duck.set_value(-12.0)
        self.duck.changed.connect(lambda _v: self.changed.emit())
        self.add_widget(self.mode)
        self.add_widget(self.duck)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.add_widget(self.status)

    def set_separated(self, available: bool) -> None:
        """Cho biết dự án đã có bản nhạc nền tách sẵn hay chưa."""
        self.status.setText(
            "Dự án này đã có bản nhạc nền tách sẵn, xuất lại sẽ rất nhanh."
            if available else
            "Dự án này chưa tách nhạc nền. Chọn Tách giọng gốc sẽ mất thêm "
            "thời gian ở lần xuất tới.")

    def values(self) -> dict:
        return {"bg_mode": self.mode.current_key(),
                "bg_duck_db": self.duck.value()}


class ExportPanel(CollapsibleSection):
    """Chọn kiểu phụ đề rồi xuất video, hoặc chỉ ghi lại phụ đề."""

    export_requested = Signal()
    subtitles_requested = Signal()
    style_requested = Signal()
    preview_requested = Signal()
    export_srt_requested = Signal()
    export_ass_requested = Signal()
    export_audio_mp3_requested = Signal()
    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Xuất video", expanded=True, parent=parent)
        from autodub.media.subtitle import PRESET_CHOICES

        self.subtitle = LabeledCombo("Kiểu phụ đề", consts.SUBTITLE_MODES,
                                     "Cách hiện phụ đề trên video kết quả")
        self.subtitle.changed.connect(self.changed.emit)
        self.add_widget(self.subtitle)

        self.preset = LabeledCombo(
            "Bộ kiểu chữ", PRESET_CHOICES,
            "Đổi bộ kiểu rồi bấm Ghi lại phụ đề là thấy ngay trên video.")
        self.preset.changed.connect(self.changed.emit)
        self.add_widget(self.preset)

        row = QHBoxLayout()
        style = GhostButton("Kiểu chữ và vùng che…")
        style.clicked.connect(self.style_requested.emit)
        row.addWidget(style)
        row.addStretch()
        self.add_layout(row)

        self.source_info = QLabel("")
        self.source_info.setWordWrap(True)
        self.source_info.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.add_widget(self.source_info)

        self.btn_preview = GhostButton("Xem thử câu đang chọn")
        self.btn_preview.setToolTip(
            "Dựng nhanh vài giây quanh câu đang chọn (giọng + nhạc nền + "
            "phụ đề như bản xuất) để kiểm tra trước khi xuất cả video.")
        self.btn_preview.clicked.connect(self.preview_requested.emit)
        self.btn_subtitles = GhostButton("Ghi lại phụ đề vào video")
        self.btn_subtitles.setToolTip(
            "Chỉ vẽ lại chữ lên video, giữ nguyên giọng đọc đã có. Nhanh hơn "
            "nhiều so với xuất lại cả video, dùng khi bạn chỉ sửa chữ hoặc "
            "đổi kiểu chữ.")
        self.btn_subtitles.clicked.connect(self.subtitles_requested.emit)
        self.btn_export = PrimaryButton("Xuất video")
        self.btn_export.setToolTip(
            "Ghép lại cả âm thanh lẫn hình. Dùng khi bạn vừa đọc lại giọng "
            "hoặc đổi nhạc nền.")
        self.btn_export.clicked.connect(self.export_requested.emit)
        # Hai nút xếp DỌC: bảng bên phải có thể hẹp tới 280 điểm, đặt cạnh
        # nhau là nhãn dài («Ghi lại phụ đề vào video») bị ép cắt chữ.
        for button in (self.btn_preview, self.btn_export, self.btn_subtitles):
            row = QHBoxLayout()
            row.setSpacing(tokens.SP_2)
            row.addWidget(button)
            row.addStretch()
            self.add_layout(row)

        self.progress = ThinProgressBar()
        self.progress.setVisible(False)
        self.add_widget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.add_widget(self.status)

        # --- Xuất riêng phụ đề / âm thanh -----------------------------------
        sep = QLabel("Xuất riêng")
        sep.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"font-weight: 600; background: transparent; "
            f"border-top: 1px solid {tokens.BORDER_SUBTLE}; "
            f"padding-top: {tokens.SP_2}px; margin-top: {tokens.SP_2}px;")
        self.add_widget(sep)

        self.btn_export_srt = GhostButton("Tải xuống .SRT")
        self.btn_export_srt.setToolTip(
            "Xuất tệp phụ đề .srt ra máy (dùng được với CapCut, "
            "Premiere, DaVinci Resolve…).")
        self.btn_export_srt.clicked.connect(self.export_srt_requested.emit)

        self.btn_export_ass = GhostButton("Tải xuống .ASS")
        self.btn_export_ass.setToolTip(
            "Xuất tệp phụ đề .ass kiểu karaoke/cụm chữ.")
        self.btn_export_ass.clicked.connect(self.export_ass_requested.emit)

        self.btn_export_mp3 = GhostButton("Tải xuống MP3 lồng tiếng")
        self.btn_export_mp3.setToolTip(
            "Xuất riêng bản âm thanh đã lồng tiếng thành tệp MP3.")
        self.btn_export_mp3.clicked.connect(self.export_audio_mp3_requested.emit)

        for button in (self.btn_export_srt, self.btn_export_ass,
                       self.btn_export_mp3):
            row2 = QHBoxLayout()
            row2.setSpacing(tokens.SP_2)
            row2.addWidget(button)
            row2.addStretch()
            self.add_layout(row2)

        # --- Lịch sử bản xuất -----------------------------------------------
        self._hist_section = CollapsibleSection(
            "Lịch sử bản xuất", expanded=False, parent=self)
        self._hist_list = QListWidget()
        self._hist_list.setFixedHeight(120)
        self._hist_list.setStyleSheet(
            f"QListWidget {{ background: {tokens.BG_INPUT}; "
            f"border: 1px solid {tokens.BORDER_SUBTLE}; border-radius: 6px; "
            f"font-size: {tokens.FS_META}px; }} "
            f"QListWidget::item:hover {{ background: {tokens.BG_PANEL_HOVER}; }}")
        self._hist_list.itemDoubleClicked.connect(self._open_history_item)
        self._hist_section.add_widget(self._hist_list)
        self.add_widget(self._hist_section)

    def refresh_history(self, work_dir: str) -> None:
        """Nạp lại danh sách bản xuất đã lưu trong export_history."""
        from autodub.editor import list_export_history

        self._hist_list.clear()
        entries = list_export_history(work_dir)
        if not entries:
            item = QListWidgetItem("(chưa có bản nào)")
            from PySide6.QtCore import Qt
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._hist_list.addItem(item)
            return
        import time

        for e in entries:
            ts = time.strftime("%d/%m/%Y %H:%M", time.localtime(e["mtime"]))
            size_mb = e["size_bytes"] / 1024 / 1024
            label = f"{ts}  ({size_mb:.1f} MB)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, e["path"])
            item.setToolTip(e["path"])
            self._hist_list.addItem(item)

    def _open_history_item(self, item: QListWidgetItem) -> None:
        from autodub_gui.system_open import open_file
        from PySide6.QtCore import Qt

        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            open_file(path)

    def set_source_info(self, width: int, height: int, fps: float) -> None:
        """Hiện thông số video gốc; bản này giữ nguyên chứ chưa đổi được."""
        if width and height:
            self.source_info.setText(
                f"Video kết quả giữ nguyên thông số của video gốc: "
                f"{width} nhân {height} điểm ảnh, {fps:.0f} hình mỗi giây.")
        else:
            self.source_info.setText(
                "Video kết quả giữ nguyên độ phân giải và số hình mỗi giây "
                "của video gốc.")

    def set_running(self, running: bool, subtitles_only: bool = False) -> None:
        if subtitles_only:
            self.btn_subtitles.set_loading(running, "Đang ghi phụ đề")
            self.btn_export.setEnabled(not running)
        else:
            self.btn_export.set_loading(running, "Đang xuất video")
            self.btn_subtitles.setEnabled(not running)
        self.btn_preview.setEnabled(not running)
        self.progress.setVisible(running)
        if running:
            self.progress.set_indeterminate(True)

    def set_previewing(self, running: bool) -> None:
        """Khóa các nút trong lúc dựng đoạn xem thử (vài giây)."""
        self.btn_preview.set_loading(running, "Đang dựng đoạn thử")
        self.btn_export.setEnabled(not running)
        self.btn_subtitles.setEnabled(not running)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def values(self) -> dict:
        return {"subtitle_mode": self.subtitle.current_key(),
                "subtitle_preset": self.preset.current_key()}


class DirtyBanner(QWidget):
    """Nhắc việc còn phải làm sau khi sửa: đọc lại giọng, hay ghi lại phụ đề.

    Hai loại thay đổi có hai việc phải làm khác hẳn nhau, nên băng nhắc phải
    nói rõ từng loại — không thì người dùng bấm Xuất video mà chữ trên phim
    vẫn là chữ cũ, hoặc ngược lại, xuất lại cả video chỉ vì sửa một dấu phẩy.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SP_3, tokens.SP_2,
                                  tokens.SP_3, tokens.SP_2)
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            f"color: {tokens.WARNING}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        layout.addWidget(self.label)
        self.setStyleSheet(
            f"background: {tokens.WARNING_BG}; "
            f"border: 1px solid {tokens.WARNING}; border-radius: 8px;")
        self.setVisible(False)

    def set_count(self, voice_count: int, subtitle_count: int = 0) -> None:
        """Hiện số câu đã sửa và việc cần làm tiếp theo."""
        self.setVisible(bool(voice_count or subtitle_count))
        parts: list[str] = []
        if voice_count:
            parts.append(
                f"Đã sửa lời đọc của {voice_count} câu — bấm «Lưu tất cả và "
                "đọc lại» ở mục Giọng đọc, rồi bấm «Xuất video».")
        if subtitle_count:
            parts.append(
                f"Đã sửa phụ đề của {subtitle_count} câu — bấm «Ghi lại phụ "
                "đề vào video» ở mục Xuất video là xong, không cần đọc lại "
                "giọng.")
        self.label.setText(" ".join(parts))


class QCPanel(QWidget):
    """Bảng kiểm tra chất lượng trước khi xuất - gộp vấn đề từ quality_report
    và kiểm tra phía client (dịch trống, đọc quá nhanh, chưa đọc lại sau sửa).

    Mỗi dòng bấm được → nhảy tới câu trong danh sách phụ đề.
    """

    issue_clicked = Signal(int)

    # Ngưỡng tốc độ đọc quá nhanh (ký tự/giây) - vượt ngưỡng này thì cảnh báo
    _FAST_CPS = 18.0

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SP_4, tokens.SP_4,
                                  tokens.SP_4, tokens.SP_4)
        layout.setSpacing(tokens.SP_3)

        header = QLabel("Kiểm tra lỗi trước khi xuất")
        header.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_CARD_TITLE}px; "
            f"font-weight: 600; background: transparent;")
        layout.addWidget(header)

        hint = QLabel(
            "Danh sách các vấn đề cần xem lại. Bấm vào từng dòng để nhảy tới "
            "câu đó trong mục Phụ đề.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        layout.addWidget(hint)

        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setSpacing(2)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {tokens.BG_PANEL}; "
            f"border: 1px solid {tokens.BORDER_DEFAULT}; border-radius: 8px; "
            f"padding: {tokens.SP_2}px; }} "
            f"QListWidget::item {{ padding: {tokens.SP_2}px; "
            f"border-radius: 6px; }} "
            f"QListWidget::item:hover {{ background: {tokens.BG_PANEL_HOVER}; }} "
            f"QListWidget::item:selected {{ background: {tokens.BG_SELECTED}; "
            f"color: {tokens.TEXT_PRIMARY}; }}")
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list, 1)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        layout.addWidget(self.summary)

    def refresh(self, segments: list[dict], quality: dict,
                dirty_ids: set[int], text_field: str = "text_vi") -> None:
        """Quét toàn bộ segments + quality_report + dirty_ids để tìm vấn đề."""
        self.list.clear()
        issues: list[tuple[int, str, str]] = []  # (seg_id, category, text)

        # 1. Vấn đề từ quality_report.json (overlap, shift, atempo, over_budget)
        per_seg = {s.get("id"): s for s in (quality or {}).get("per_segment") or []
                   if isinstance(s, dict) and s.get("id") is not None}
        for seg_id, qdata in per_seg.items():
            desc = _issue_text(qdata)
            issues.append((seg_id, "timing", desc))

        # 2. Kiểm tra client-side
        for seg in segments:
            seg_id = seg.get("id")
            if seg_id is None:
                continue
            text = str(seg.get(text_field, "")).strip()
            dur = float(seg.get("duration") or 0)
            if dur <= 0:
                dur = float(seg.get("end", 0)) - float(seg.get("start", 0))

            # Dịch trống
            if not text:
                issues.append((seg_id, "empty",
                              f"Câu {seg_id}\nBản dịch trống"))
                continue

            # Đọc quá nhanh
            if dur > 0.1:
                cps = len(text) / dur
                if cps > self._FAST_CPS:
                    issues.append((seg_id, "fast",
                                  f"Câu {seg_id} — đọc nhanh {cps:.1f} ký tự/giây\n{text[:60]}{'…' if len(text) > 60 else ''}"))

            # Chưa đọc lại sau sửa
            if seg_id in dirty_ids:
                issues.append((seg_id, "dirty",
                              f"Câu {seg_id} — đã sửa lời đọc, chưa tổng hợp lại\n{text[:60]}{'…' if len(text) > 60 else ''}"))

        # Sắp xếp: timing trước, empty/fast/dirty sau, cùng loại thì theo seg_id
        _ORDER = {"timing": 0, "empty": 1, "fast": 2, "dirty": 3}
        issues.sort(key=lambda x: (_ORDER.get(x[1], 9), x[0]))

        # Đổ vào list
        for seg_id, cat, desc in issues:
            item = QListWidgetItem(desc)
            item.setData(Qt.ItemDataRole.UserRole, seg_id)
            # Màu sắc theo loại
            if cat == "timing":
                item.setForeground(QColor(tokens.DANGER))
            elif cat == "empty":
                item.setForeground(QColor(tokens.WARNING))
            elif cat == "fast":
                item.setForeground(QColor(tokens.WARNING))
            else:  # dirty
                item.setForeground(QColor(tokens.TEXT_MUTED))
            self.list.addItem(item)

        # Tổng kết
        if not issues:
            self.summary.setText(
                "Không phát hiện vấn đề. Video sẵn sàng xuất.")
            self.summary.setStyleSheet(
                f"color: {tokens.SUCCESS}; font-size: {tokens.FS_META}px; "
                f"font-weight: 600; background: transparent;")
        else:
            counts = {}
            for _sid, cat, _desc in issues:
                counts[cat] = counts.get(cat, 0) + 1
            parts = []
            if counts.get("timing"):
                parts.append(f"{counts['timing']} câu lỗi timing")
            if counts.get("empty"):
                parts.append(f"{counts['empty']} câu dịch trống")
            if counts.get("fast"):
                parts.append(f"{counts['fast']} câu đọc quá nhanh")
            if counts.get("dirty"):
                parts.append(f"{counts['dirty']} câu chưa đọc lại")
            self.summary.setText(
                f"Phát hiện {len(issues)} vấn đề: {', '.join(parts)}.")
            self.summary.setStyleSheet(
                f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
                f"background: transparent;")

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        seg_id = item.data(Qt.ItemDataRole.UserRole)
        if seg_id is not None:
            self.issue_clicked.emit(int(seg_id))


def debounce_timer(parent: QWidget, callback) -> QTimer:
    """Bộ đếm giờ chờ người dùng gõ xong rồi mới lưu."""
    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.setInterval(EDIT_DEBOUNCE_MS)
    timer.timeout.connect(callback)
    return timer
