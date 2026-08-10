"""Ô chọn giọng đọc, dùng chung cho Cài đặt, Tạo dự án và Trình chỉnh sửa.

Thay cho một danh sách thả xuống chữ trần, ô này là một nút lớn hiện avatar
và tên giọng đang chọn; bấm vào sẽ mở một bảng chọn: ô tìm kiếm ở trên, bên
dưới là từng giọng một dòng (avatar, tên, mô tả ngắn). Cùng một cách hiển
thị với thư viện giọng trong Cài đặt, nên chọn giọng ở đâu cũng quen tay.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.ui.avatar import InitialAvatar
from autodub_gui.ui.buttons import GhostButton
from autodub_gui.ui.style import clear_background

_ROW_AVATAR = 30
_TRIGGER_AVATAR = 34
_POPUP_MAX_ROWS = 6          # cao hơn thì cuộn
_ROW_H = 52
_POPUP_MIN_W = 320


def _tag_text(voice) -> str:
    """Dòng mô tả ngắn dưới tên: Nữ · Miền Bắc · Kể chuyện."""
    from autodub.speech.tts.voices import COUNTRIES, GENDERS, STYLES

    gender = {k: t for t, k in GENDERS}.get(voice.gender, "")
    country = ({k: t for t, k in COUNTRIES}.get(voice.country, "")
               if voice.country != "vn" else "")
    style = {k: t for t, k in STYLES}.get(voice.style, "")
    extra = ("CapCut" if voice.is_capcut
             else "Giọng bạn thêm" if voice.custom else "")
    return " · ".join(p for p in (gender, country, style, extra) if p)


class _VoiceRow(QFrame):
    """Một dòng trong bảng chọn: avatar + tên + mô tả, bấm là chọn."""

    picked = Signal(str)

    def __init__(self, voice, selected: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self._name = voice.name
        self.setFixedHeight(_ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._base = tokens.BG_SELECTED_SOFT if selected else "transparent"
        self._hover = tokens.BG_SELECTED if selected else tokens.BG_PANEL_HOVER
        self._paint(self._base)

        row = QHBoxLayout(self)
        row.setContentsMargins(tokens.SP_2, 0, tokens.SP_2, 0)
        row.setSpacing(tokens.SP_2)
        row.addWidget(InitialAvatar(voice.name, _ROW_AVATAR))
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(voice.name)
        name.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_BODY}px; "
            f"font-weight: 600; background: transparent;")
        col.addWidget(name)
        tags = _tag_text(voice)
        if tags:
            meta = QLabel(tags)
            meta.setStyleSheet(
                f"color: {tokens.TEXT_MUTED}; "
                f"font-size: {tokens.FS_META}px; background: transparent;")
            col.addWidget(meta)
        row.addLayout(col, 1)
        if selected:
            check = QLabel()
            check.setPixmap(icons.check(tokens.PRIMARY).pixmap(16, 16))
            clear_background(check)
            row.addWidget(check)

    def _paint(self, color: str) -> None:
        self.setStyleSheet(
            f"QFrame {{ background: {color}; border: none; "
            f"border-radius: {tokens.RADIUS_MD}px; }}")

    def enterEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        self._paint(self._hover)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        self._paint(self._base)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        self.picked.emit(self._name)


class _VoicePopup(QFrame):
    """Bảng thả xuống: ô tìm kiếm + danh sách giọng cuộn được."""

    picked = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setStyleSheet(
            f"QFrame {{ background: {tokens.BG_PANEL}; "
            f"border: 1px solid {tokens.BORDER_DEFAULT}; "
            f"border-radius: {tokens.RADIUS_LG}px; }}")
        self._voices: list = []
        self._current = ""
        self._selected_row: _VoiceRow | None = None
        self._src_tab = 0                # 0 = offline, 1 = capcut

        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SP_2, tokens.SP_2,
                                tokens.SP_2, tokens.SP_2)
        root.setSpacing(tokens.SP_2)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Tìm giọng theo tên")
        self._search.setClearButtonEnabled(True)
        self._search.addAction(icons.search(tokens.TEXT_MUTED),
                               QLineEdit.ActionPosition.LeadingPosition)
        self._search.textChanged.connect(lambda _t: self._rebuild())
        root.addWidget(self._search)

        # Tab nguồn — chỉ hiện khi catalog có giọng CapCut.
        from autodub_gui.ui.pill_tabs import PillTabBar

        self._src_tabs = PillTabBar()
        self._src_tabs.add_tab("Giọng offline")
        self._src_tabs.add_tab("CapCut")
        self._src_tabs.changed.connect(self._on_src_tab)
        self._src_tabs.setVisible(False)
        root.addWidget(self._src_tabs)

        # CapCut đọc qua máy chủ — nói trước ở đây, đừng để người dùng chọn
        # xong rồi mới gặp lỗi mạng giữa lúc lồng tiếng.
        self._online_hint = QLabel("Giọng CapCut cần kết nối mạng.")
        self._online_hint.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent; padding: 0 4px;")
        self._online_hint.setVisible(False)
        root.addWidget(self._online_hint)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        clear_background(holder)
        self._list = QVBoxLayout(holder)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(2)
        self._scroll.setWidget(holder)
        root.addWidget(self._scroll)

        self._empty = QLabel("Không có giọng nào khớp.")
        self._empty.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_LABEL}px; "
            f"background: transparent; padding: 6px;")
        self._empty.setVisible(False)
        root.addWidget(self._empty)

    def open_for(self, anchor: QWidget, voices: list, current: str) -> None:
        """Hiện ngay dưới nút, rộng bằng nút (tối thiểu _POPUP_MIN_W)."""
        from autodub.speech.tts.voices import source_group

        self._voices = voices
        self._current = current
        self._search.clear()
        # Tab nguồn chỉ có nghĩa khi thật sự có giọng CapCut; mở bảng thì
        # nhảy sẵn vào tab chứa giọng đang chọn.
        has_capcut = any(source_group(v) == "capcut" for v in voices)
        self._src_tabs.setVisible(has_capcut)
        picked = next((v for v in voices if v.name == current), None)
        self._src_tab = (1 if has_capcut and picked is not None
                         and source_group(picked) == "capcut" else 0)
        self._src_tabs.set_current_index(self._src_tab)   # signal bị chặn vì
        self._rebuild()                                   # index không đổi
        width = max(anchor.width(), _POPUP_MIN_W)
        rows = min(self._visible_count(), _POPUP_MAX_ROWS) or 1
        self._scroll.setFixedHeight(rows * (_ROW_H + 2) + tokens.SP_1)
        self.setFixedWidth(width)
        self.adjustSize()
        point = anchor.mapToGlobal(anchor.rect().bottomLeft())
        self.move(point.x(), point.y() + tokens.SP_1)
        self.show()
        self._search.setFocus()
        # Cuộn tới giọng đang chọn, để nó luôn trong tầm mắt khi mở bảng.
        if self._selected_row is not None:
            self._scroll.ensureWidgetVisible(self._selected_row, 0, 0)

    def _visible_count(self) -> int:
        """Số giọng thuộc tab nguồn đang mở (chưa tính ô tìm kiếm)."""
        return len(self._tab_voices())

    def _tab_voices(self) -> list:
        """Giọng thuộc tab nguồn đang chọn; tab ẩn thì trả cả danh sách."""
        if not self._src_tabs.isVisible():
            return self._voices
        from autodub.speech.tts.voices import source_group

        want = "capcut" if self._src_tab == 1 else "offline"
        return [v for v in self._voices if source_group(v) == want]

    def _on_src_tab(self, index: int) -> None:
        if index == self._src_tab:
            return
        self._src_tab = index
        self._rebuild()

    def _rebuild(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._selected_row = None
        self._online_hint.setVisible(self._src_tabs.isVisible()
                                     and self._src_tab == 1)
        query = self._search.text().strip()
        matched = [v for v in self._tab_voices() if v.matches(query=query)]
        self._empty.setVisible(not matched)
        for voice in matched:
            selected = voice.name == self._current
            row = _VoiceRow(voice, selected)
            row.picked.connect(self._on_pick)
            self._list.addWidget(row)
            if selected:
                self._selected_row = row
        self._list.addStretch()

    def _on_pick(self, name: str) -> None:
        self.hide()
        self.picked.emit(name)


class _TriggerButton(QPushButton):
    """Nút lớn hiện giọng đang chọn: avatar + tên + mô tả + mũi tên."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            f"QPushButton {{ background: {tokens.BG_INPUT}; "
            f"border: 1px solid {tokens.BORDER_SUBTLE}; "
            f"border-radius: {tokens.RADIUS_MD}px; padding: 6px 10px; "
            f"text-align: left; }} "
            f"QPushButton:hover {{ border-color: {tokens.BORDER_DEFAULT}; }} "
            f"QPushButton:focus {{ border-color: {tokens.BORDER_ACTIVE}; }} "
            f"QPushButton:disabled {{ background: {tokens.BG_INPUT_DISABLED}; }}")

        row = QHBoxLayout(self)
        row.setContentsMargins(tokens.SP_1, tokens.SP_1,
                               tokens.SP_2, tokens.SP_1)
        row.setSpacing(tokens.SP_2)
        self._avatar = InitialAvatar("", _TRIGGER_AVATAR)
        row.addWidget(self._avatar)
        col = QVBoxLayout()
        col.setSpacing(0)
        self._name = QLabel("")
        self._name.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_BODY}px; "
            f"font-weight: 600; background: transparent;")
        self._meta = QLabel("")
        self._meta.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        col.addWidget(self._name)
        col.addWidget(self._meta)
        row.addLayout(col, 1)
        chevron = QLabel()
        chevron.setPixmap(
            icons.chevron_down(tokens.TEXT_SECONDARY).pixmap(14, 14))
        clear_background(chevron)
        row.addWidget(chevron)
        # Các nhãn con không được nuốt cú bấm chuột của nút.
        for child in (self._avatar, self._name, self._meta, chevron):
            child.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def show_voice(self, voice) -> None:
        self._avatar.set_name(voice.name if voice else "")
        self._name.setText(voice.name if voice else "Chọn giọng đọc")
        self._meta.setText(_tag_text(voice) if voice else "")


class VoicePicker(QWidget):
    """Nút chọn giọng mở bảng tìm kiếm + nút nghe thử.

    Hợp đồng với các trang: tín hiệu `changed`, `preview_requested(str)`;
    phương thức `voice()`, `set_voice()`, `reload()`, `set_preview_enabled()`.
    """

    changed = Signal()
    preview_requested = Signal(str)      # tên giọng

    def __init__(self, label: str = "Giọng đọc", show_preview: bool = True,
                 parent: QWidget | None = None):
        super().__init__(parent)
        from autodub.speech.tts import voices as catalog

        self._catalog = catalog
        self._voices: list = []
        self._current = ""

        clear_background(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(tokens.SP_1)

        if label:
            caption = QLabel(label)
            caption.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; "
                f"font-size: {tokens.FS_LABEL}px; font-weight: 500; "
                f"background: transparent;")
            root.addWidget(caption)

        self._trigger = _TriggerButton()
        self._trigger.setToolTip(
            "Bấm để mở danh sách giọng. Mỗi giọng là một người đọc riêng.")
        self._trigger.clicked.connect(self._open_popup)
        root.addWidget(self._trigger)

        self._popup = _VoicePopup(self)
        self._popup.picked.connect(self._on_pick)

        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        if show_preview:
            self.btn_preview = GhostButton("Nghe thử giọng này")
            # Không nhận focus qua chuột để bị disable không gây cuộn danh sách.
            self.btn_preview.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self.btn_preview.clicked.connect(
                lambda: self.preview_requested.emit(self.voice()))
            row.addWidget(self.btn_preview)
        else:
            self.btn_preview = None
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        row.addWidget(self.count_label, 1)
        root.addLayout(row)

        self.reload()

    # -- Dữ liệu -------------------------------------------------------
    def reload(self, settings=None) -> None:
        """Đọc lại danh mục giọng (gọi sau khi vừa học thêm một giọng mới)."""
        from autodub.config import Settings

        try:
            self._voices = self._catalog.catalog(settings or Settings.load())
        except Exception:  # noqa: BLE001 — thiếu tệp thì để catalog rỗng
            self._voices = []
        if not self._current or all(
                v.name != self._current for v in self._voices):
            self._current = self._voices[0].name if self._voices else ""
        self._sync()

    def _voice_of(self, name: str):
        return next((v for v in self._voices if v.name == name), None)

    def _sync(self) -> None:
        self._trigger.show_voice(self._voice_of(self._current))
        self.count_label.setText(f"{len(self._voices)} giọng")

    def _open_popup(self) -> None:
        self._popup.open_for(self._trigger, self._voices, self._current)

    def _on_pick(self, name: str) -> None:
        if name == self._current:
            return
        self._current = name
        self._sync()
        self.changed.emit()

    # -- Giá trị -------------------------------------------------------
    def voice(self) -> str:
        return self._current

    def set_voice(self, name: str) -> None:
        """Chọn một giọng theo tên; tên lạ thì giữ nguyên lựa chọn hiện tại."""
        name = (name or "").strip()
        if not name or self._voice_of(name) is None:
            return
        self._current = name
        self._sync()

    def set_preview_enabled(self, enabled: bool) -> None:
        if self.btn_preview is not None:
            self.btn_preview.setEnabled(enabled)
