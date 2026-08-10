"""Thẻ "Giọng đọc" trong Cài đặt và trang Giọng đọc AI.

Cột trái là bảng danh sách: ô tìm kiếm và ô sắp xếp, hàng bộ lọc (quốc gia ·
giới tính · phong cách) kèm nút xóa lọc, thanh tab (Tất cả / Yêu thích / Gần
đây) có số đếm, hàng tiêu đề cột, các hàng giọng và thanh chuyển trang.

Cột phải là chi tiết giọng đang chọn: avatar và nút yêu thích, khung sóng âm
kèm nút nghe thử, ô phong cách đọc, nút áp dụng, dải giọng dùng gần đây và
khối quản lý giọng.

Hợp đồng với trang Cài đặt giữ nguyên: `load(env)`, `values()`, `cleanup()`
và tín hiệu `changed`. Thay đổi chỉ ghi xuống tệp khi bấm Lưu ở chân trang.
"""
from __future__ import annotations

import zlib

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.pages.settings_panels import VoiceSettingsPanel
from autodub_gui.ui.avatar import InitialAvatar
from autodub_gui.ui.buttons import GhostButton, IconButton, PrimaryButton
from autodub_gui.ui.inputs import SearchBox, polish_combo
from autodub_gui.ui.pagination import Pagination
from autodub_gui.ui.pill_tabs import PillTabBar
from autodub_gui.ui.style import clear_background
from autodub_gui.voice_preview import VoicePreview

_PAGE_SIZE  = 15
_RAIL_W     = 330
_ROW_H      = 56
_RECENT_MAX = 5
_AV_ROW     = 34    # avatar trong hàng danh sách và dải gần đây
_AV_RAIL    = 62    # avatar lớn ở cột chi tiết
_ROW_BTN    = 30    # nút nghe thử / ngôi sao trong hàng
_RAIL_BTN   = 42    # nút nghe thử ở cột chi tiết
_FILTER_W   = 126
_WAVE_BARS  = 44
_WAVE_H     = 48

_TAB_ALL, _TAB_FAV, _TAB_RECENT = 0, 1, 2
_TAB_LABELS = ("Tất cả", "Yêu thích", "Gần đây")
_SRC_OFFLINE, _SRC_CAPCUT = 0, 1
_SRC_LABELS = ("Giọng offline", "CapCut")
_HEADERS = ("Giọng đọc", "Thông tin", "Phong cách", "Thao tác")

_SORT_OPTIONS = (
    ("Tên A đến Z",          "name_asc"),
    ("Tên Z về A",           "name_desc"),
    ("Giọng bạn thêm trước", "custom"),
)

#: Tỉ lệ bề ngang các cột: tên · thông tin · phong cách · thao tác.
_COLS = (32, 28, 22, 18)
_SEP = " · "


def _text(content: str, color: str, size: int, weight: int = 400) -> QLabel:
    """Nhãn phẳng nền trong suốt — dùng khắp bảng và cột chi tiết."""
    label = QLabel(content)
    label.setStyleSheet(f"color: {color}; font-size: {size}px; "
                        f"font-weight: {weight}; background: transparent;")
    return label


def _muted(content: str) -> QLabel:
    label = _text(content, tokens.TEXT_MUTED, tokens.FS_META)
    label.setWordWrap(True)
    return label


def _pill(content: str, color: str, border: str, background: str) -> QLabel:
    """Nhãn bo tròn có viền — dùng cho giới tính và phong cách.

    Khóa kích thước theo nội dung: để mặc định thì nhãn giãn hết chiều cao
    hàng và viền biến thành một cái khung to trùm cả ô.
    """
    label = QLabel(content)
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(
        f"color: {color}; font-size: {tokens.FS_META}px; "
        f"background: {background}; border: 1px solid {border}; "
        f"border-radius: 5px; padding: 2px 8px;")
    return label


def _star(on: bool, button: IconButton | None = None) -> IconButton:
    """Dựng hoặc cập nhật nút ngôi sao theo trạng thái yêu thích.

    Nút dùng tín hiệu `clicked` chứ không phải `toggled`, nên gọi hàm này để
    đồng bộ trạng thái từ nơi khác không làm phát tín hiệu vòng lại.
    """
    if button is None:
        button = IconButton(icons.star(tokens.TEXT_MUTED), "", size=_ROW_BTN,
                            checkable=True)
    button.setChecked(on)
    button.setIcon(icons.star(tokens.WARNING if on else tokens.TEXT_MUTED))
    button.setToolTip("Bỏ khỏi danh sách yêu thích" if on
                      else "Đánh dấu giọng yêu thích")
    return button


def _labels() -> tuple[dict, dict, dict]:
    """Ba bảng tra khóa sang nhãn tiếng Việt: giới tính, quốc gia, phong cách."""
    from autodub.speech.tts.voices import COUNTRIES, GENDERS, STYLES

    return ({k: v for v, k in GENDERS}, {k: v for v, k in COUNTRIES},
            {k: v for v, k in STYLES})


def _clear(layout) -> None:
    """Xóa sạch mọi widget trong một layout."""
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.deleteLater()


class _Waveform(QWidget):
    """Dạng sóng trang trí — cao độ băm từ tên giọng nên mỗi giọng một vân."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._seed = ""
        self.setFixedHeight(_WAVE_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def set_seed(self, seed: str) -> None:
        if seed != self._seed:
            self._seed = seed
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        step = self.width() / _WAVE_BARS
        middle = self.height() / 2
        pen_w = max(1.6, step * 0.42)
        for i in range(_WAVE_BARS):
            digest = zlib.crc32(f"{self._seed}:{i}".encode("utf-8"))
            half = (self.height() - 6) * (0.18 + digest % 100 / 100 * 0.82) / 2
            color = tokens.WAVEFORM if digest % 3 else tokens.WAVEFORM_LIGHT
            painter.setPen(QPen(QColor(color), pen_w, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            x = step * (i + 0.5)
            painter.drawLine(QPointF(x, middle - half),
                             QPointF(x, middle + half))
        painter.end()


class _RecentAvatar(InitialAvatar):
    """Avatar nhỏ trong dải giọng gần đây — bấm để chọn lại giọng đó."""

    clicked = Signal(str)

    def __init__(self, name: str, parent: QWidget | None = None):
        super().__init__(name, _AV_ROW, parent)
        self.setToolTip(f"Chọn lại giọng «{name}».")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — quy ước Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name())
        super().mouseReleaseEvent(event)


class _VoiceRow(QFrame):
    """Một hàng giọng: ô chọn · avatar và tên · thông tin · phong cách · thao tác."""

    clicked = Signal(str)
    preview_requested = Signal(str)
    favorite_toggled = Signal(str, bool)

    def __init__(self, voice, favorite: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("voiceRow")
        self.voice = voice
        self._selected = False
        self.setFixedHeight(_ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build(favorite)
        self._apply_style()

    def _build(self, favorite: bool) -> None:
        genders, countries, styles = _labels()
        name = self.voice.name
        gender = genders.get(self.voice.gender, "")
        row = QHBoxLayout(self)
        row.setContentsMargins(tokens.SP_3, 0, tokens.SP_3, 0)
        row.setSpacing(tokens.SP_3)

        # Ô đánh dấu chỉ để nhìn — cả hàng đã bấm được nên nó không nhận chuột.
        self.check = QCheckBox()
        self.check.setFixedWidth(20)
        self.check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.check.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.check)

        name_w = QWidget()
        clear_background(name_w)
        name_box = QHBoxLayout(name_w)
        name_box.setContentsMargins(0, 0, 0, 0)
        name_box.setSpacing(tokens.SP_2)
        name_box.addWidget(InitialAvatar(name, _AV_ROW))
        name_box.addWidget(_text(name, tokens.TEXT_PRIMARY,
                                 tokens.FS_BODY, 600))
        if gender:
            name_box.addWidget(_pill(gender, tokens.TEXT_SECONDARY,
                                     tokens.BORDER_SUBTLE, tokens.CHIP_BG),
                               0, Qt.AlignmentFlag.AlignVCenter)
        name_box.addStretch()
        row.addWidget(name_w, _COLS[0])

        info = _SEP.join(p for p in (countries.get(self.voice.country, ""),
                                     gender) if p)
        row.addWidget(_text(info, tokens.TEXT_SECONDARY, tokens.FS_LABEL),
                      _COLS[1])

        # Pill thả thẳng vào hàng như ô tiêu đề, KHÔNG bọc thêm layout con:
        # lớp bọc kèm addStretch() tính chiều rộng khác ô tiêu đề nên cột
        # Phong cách bị lệch khỏi tiêu đề của chính nó.
        row.addWidget(_pill(styles.get(self.voice.style, ""),
                            tokens.PRIMARY, tokens.BORDER_ACTIVE,
                            tokens.CHIP_BG_ACTIVE),
                      _COLS[2],
                      Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Cột Thao tác: dùng widget container cố định thay vì layout con,
        # để stretch tính cùng kiểu với các cột label/widget bên cạnh.
        actions_w = QWidget()
        clear_background(actions_w)
        actions_w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                               False)
        actions_lay = QHBoxLayout(actions_w)
        actions_lay.setContentsMargins(0, 0, 0, 0)
        actions_lay.setSpacing(tokens.SP_2)
        self.btn_play = IconButton(icons.play(tokens.SUCCESS),
                                   f"Nghe thử giọng «{name}»", size=_ROW_BTN)
        self.btn_play.clicked.connect(
            lambda: self.preview_requested.emit(name))
        actions_lay.addWidget(self.btn_play)
        self.btn_star = _star(favorite)
        self.btn_star.clicked.connect(self._on_star)
        actions_lay.addWidget(self.btn_star)
        actions_lay.addStretch()
        row.addWidget(actions_w, _COLS[3])

    def _on_star(self, on: bool) -> None:
        _star(on, self.btn_star)
        self.favorite_toggled.emit(self.voice.name, on)

    def set_favorite(self, on: bool) -> None:
        """Đồng bộ ngôi sao khi cột phải bật hoặc tắt yêu thích giọng này."""
        _star(on, self.btn_star)

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.check.setChecked(selected)
            self._apply_style()

    def set_preview_enabled(self, enabled: bool) -> None:
        self.btn_play.setEnabled(enabled)

    def _apply_style(self) -> None:
        background = (tokens.VOICE_SELECTED_BG if self._selected
                      else tokens.BG_PANEL)
        border = (tokens.BORDER_ACTIVE if self._selected
                  else tokens.BORDER_SUBTLE)
        hover = "" if self._selected else (
            f"QFrame#voiceRow:hover {{ background: {tokens.BG_PANEL_HOVER}; "
            f"border-color: {tokens.BORDER_DEFAULT}; }}")
        self.setStyleSheet(
            f"QFrame#voiceRow {{ background: {background}; "
            f"border: 1px solid {border}; "
            f"border-radius: {tokens.RADIUS_MD}px; }}{hover}")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — quy ước Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.voice.name)
        super().mouseReleaseEvent(event)


class VoiceLibraryTab(QWidget):
    """Bảng giọng đọc bên trái và cột chi tiết bên phải."""

    changed = Signal()

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._preview = VoicePreview(self)
        self._preview.finished.connect(
            lambda _ok: self._set_preview_enabled(True))
        self._voices: list = []
        self._filtered: list = []
        self._rows: list[_VoiceRow] = []
        self._current = ""
        self._recent: list[str] = []
        self._favorites: set[str] = set()
        self._page = 1
        self._tab = _TAB_ALL
        self._src_tab = _SRC_OFFLINE
        clear_background(self)
        self._build()
        self._reload_voices()

    # -- Dựng giao diện --------------------------------------------------
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(tokens.SP_2, tokens.SP_2, 0, tokens.SP_2)
        root.setSpacing(tokens.SP_4)
        root.addWidget(self._build_main(), 1)
        root.addWidget(self._build_rail(), 0)

        shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.search.focus)

    def _build_main(self) -> QWidget:
        from autodub.speech.tts.voices import COUNTRIES, GENDERS, STYLES

        main = QWidget()
        clear_background(main)
        col = QVBoxLayout(main)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(tokens.SP_3)

        top = QHBoxLayout()
        top.setSpacing(tokens.SP_2)
        self.search = SearchBox("Tìm giọng theo tên (Ctrl+K)")
        self.search.search_changed.connect(lambda _t: self._reset_page())
        top.addWidget(self.search, 1)
        self._sort = QComboBox()
        self._sort.setToolTip("Thứ tự sắp xếp danh sách giọng.")
        for label, key in _SORT_OPTIONS:
            self._sort.addItem(f"Sắp xếp: {label}", key)
        polish_combo(self._sort)
        self._sort.currentIndexChanged.connect(lambda _i: self._reset_page())
        top.addWidget(self._sort)
        col.addLayout(top)

        filters = QHBoxLayout()
        filters.setSpacing(tokens.SP_3)
        self._f_country = self._add_filter(filters, "Quốc gia", COUNTRIES)
        self._f_gender = self._add_filter(filters, "Giới tính", GENDERS)
        self._f_style = self._add_filter(filters, "Phong cách", STYLES)
        clear = GhostButton("Xóa bộ lọc")
        clear.setToolTip("Bỏ mọi bộ lọc và ô tìm kiếm đang áp dụng.")
        clear.clicked.connect(self._clear_filters)
        filters.addWidget(clear)
        filters.addStretch()
        col.addLayout(filters)

        # Tab nguồn (Giọng offline / CapCut) — chỉ hiện khi có giọng CapCut.
        self._src_tabs = PillTabBar()
        for label in _SRC_LABELS:
            self._src_tabs.add_tab(label)
        self._src_tab_buttons = self._src_tabs.findChildren(QPushButton)
        self._src_tabs.changed.connect(self._on_src_tab)
        self._src_tabs.setVisible(False)
        col.addWidget(self._src_tabs)

        # CapCut đọc qua máy chủ — báo trước, đừng để người dùng chọn xong
        # rồi mới gặp lỗi mạng giữa lúc lồng tiếng.
        self._online_hint = _muted("Giọng CapCut cần kết nối mạng.")
        self._online_hint.setVisible(False)
        col.addWidget(self._online_hint)

        self._tabs = PillTabBar()
        for label in _TAB_LABELS:
            self._tabs.add_tab(label)
        self._tab_buttons = self._tabs.findChildren(QPushButton)
        self._tabs.changed.connect(self._on_tab)
        col.addWidget(self._tabs)
        col.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        clear_background(holder)
        self._list = QVBoxLayout(holder)
        self._list.setContentsMargins(0, 0, tokens.SP_2, 0)
        self._list.setSpacing(tokens.SP_2)
        self._empty = _muted(
            "Không có giọng nào khớp bộ lọc. Hãy nới bớt bộ lọc, hoặc học "
            "thêm giọng mới ở cột bên phải.")
        self._empty.setVisible(False)
        self._list.addWidget(self._empty)
        self._list.addStretch()
        scroll.setWidget(holder)
        col.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(tokens.SP_3)
        self._pager = Pagination()
        self._pager.page_changed.connect(self._on_page)
        bottom.addWidget(self._pager, 1)
        self._count = _muted("")
        bottom.addWidget(self._count)
        col.addLayout(bottom)

        self._status = _muted("")
        self._preview.status_changed.connect(self._status.setText)
        col.addWidget(self._status)
        return main

    def _add_filter(self, row: QHBoxLayout, label: str, options) -> QComboBox:
        row.addWidget(_text(label, tokens.TEXT_SECONDARY, tokens.FS_LABEL))
        combo = QComboBox()
        combo.setMinimumWidth(_FILTER_W)
        combo.setToolTip(f"Lọc danh sách theo {label.lower()}.")
        combo.addItem("Tất cả", "")
        for text, key in options:
            combo.addItem(text, key)
        polish_combo(combo)
        combo.currentIndexChanged.connect(lambda _i: self._reset_page())
        row.addWidget(combo)
        return combo

    def _build_header(self) -> QWidget:
        header = QWidget()
        clear_background(header)
        row = QHBoxLayout(header)
        row.setContentsMargins(tokens.SP_3, 0, tokens.SP_3, 0)
        row.setSpacing(tokens.SP_3)
        spacer = QWidget()
        spacer.setFixedWidth(20)
        row.addWidget(spacer)
        for title, stretch in zip(_HEADERS, _COLS):
            label = _text(title.upper(), tokens.SECTION_LABEL,
                          tokens.FS_BADGE, 700)
            label.setStyleSheet(label.styleSheet() + " letter-spacing: 0.8px;")
            row.addWidget(label, stretch)
        return header

    def _build_rail(self) -> QWidget:
        from autodub.speech.tts.voices import STYLES

        rail = QWidget()
        clear_background(rail)
        rail.setFixedWidth(_RAIL_W)
        col = QVBoxLayout(rail)
        col.setContentsMargins(0, 0, tokens.SP_2, 0)
        col.setSpacing(tokens.SP_4)
        col.addWidget(_text("Giọng đọc đã chọn", tokens.TEXT_PRIMARY,
                            tokens.FS_SECTION, 600))

        info = QHBoxLayout()
        info.setSpacing(tokens.SP_3)
        self._rail_avatar = InitialAvatar("", _AV_RAIL)
        info.addWidget(self._rail_avatar, 0, Qt.AlignmentFlag.AlignTop)
        name_col = QVBoxLayout()
        name_col.setSpacing(tokens.SP_1)
        name_row = QHBoxLayout()
        name_row.setSpacing(tokens.SP_2)
        self._rail_name = _text("", tokens.TEXT_PRIMARY,
                                tokens.FS_SECTION, 700)
        name_row.addWidget(self._rail_name)
        name_row.addStretch()
        self._rail_star = _star(False)
        self._rail_star.clicked.connect(self._on_rail_star)
        name_row.addWidget(self._rail_star)
        name_col.addLayout(name_row)
        self._rail_tags = _muted("")
        name_col.addWidget(self._rail_tags)
        info.addLayout(name_col, 1)
        col.addLayout(info)
        col.addWidget(self._build_preview_box())

        col.addWidget(_text("Phong cách", tokens.TEXT_SECONDARY,
                            tokens.FS_LABEL))
        self._style = QComboBox()
        for text, key in STYLES:
            self._style.addItem(text, key)
        polish_combo(self._style)
        self._style.setToolTip("Cách nhấn nhá chung khi đọc lời thoại.")
        self._style.currentIndexChanged.connect(lambda _i: self.changed.emit())
        col.addWidget(self._style)

        self._use = PrimaryButton("Sử dụng giọng này")
        self._use.setToolTip(
            "Ghi nhớ giọng này cho dự án mới (bấm Lưu ở cuối trang).")
        self._use.clicked.connect(self._on_use)
        col.addWidget(self._use)

        col.addWidget(_text("Giọng đọc gần đây", tokens.TEXT_SECONDARY,
                            tokens.FS_LABEL))
        self._recent_row = QHBoxLayout()
        self._recent_row.setSpacing(tokens.SP_2)
        col.addLayout(self._recent_row)

        self._panel = VoiceSettingsPanel()
        self._panel.set_title("Quản lý giọng")
        self._panel.set_content_indent(0)
        self._panel.picker.setVisible(False)
        self._panel.changed.connect(self._on_panel_changed)
        col.addWidget(self._panel)
        col.addStretch()

        outer = QScrollArea()
        outer.setWidgetResizable(True)
        outer.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.setFixedWidth(_RAIL_W)
        outer.setWidget(rail)
        return outer

    def _build_preview_box(self) -> QWidget:
        box = QFrame()
        box.setObjectName("previewBox")
        box.setStyleSheet(
            f"QFrame#previewBox {{ background: {tokens.BG_PANEL}; "
            f"border: 1px solid {tokens.BORDER_SUBTLE}; "
            f"border-radius: {tokens.RADIUS_LG}px; }}")
        inner = QVBoxLayout(box)
        inner.setContentsMargins(tokens.SP_3, tokens.SP_3,
                                 tokens.SP_3, tokens.SP_3)
        inner.setSpacing(tokens.SP_2)
        inner.addWidget(_text("Nghe thử giọng", tokens.TEXT_SECONDARY,
                              tokens.FS_LABEL))
        wave_row = QHBoxLayout()
        wave_row.setSpacing(tokens.SP_3)
        self._rail_play = IconButton(icons.play(tokens.SUCCESS),
                                     "Nghe thử giọng đang chọn",
                                     size=_RAIL_BTN)
        self._rail_play.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._rail_play.clicked.connect(lambda: self._play(self._current))
        wave_row.addWidget(self._rail_play)
        self._wave = _Waveform()
        wave_row.addWidget(self._wave, 1)
        inner.addLayout(wave_row)
        return box

    # -- Hợp đồng với trang Cài đặt --------------------------------------
    def load(self, env: dict[str, str]) -> None:
        """Nạp lại mọi giá trị từ tệp cấu hình."""
        from autodub.speech.tts.voices import DEFAULT_VOICE

        self._panel.load(env)
        self._current = (env.get("VIENEU_VOICE") or "").strip() or DEFAULT_VOICE
        self._recent = self._split(env.get("VOICE_RECENT"))[:_RECENT_MAX]
        self._favorites = set(self._split(env.get("VOICE_FAVORITES")))
        index = self._style.findData(env.get("VIENEU_STYLE") or "tu_nhien")
        if index >= 0:
            self._style.setCurrentIndex(index)
        self._reload_voices()

    def values(self) -> dict[str, str]:
        from autodub.speech.tts.voices import DEFAULT_VOICE

        return {
            "VIENEU_VOICE": self._current or DEFAULT_VOICE,
            "VIENEU_STYLE": self._style.currentData() or "tu_nhien",
            "VOICE_RECENT": ",".join(self._recent),
            "VOICE_FAVORITES": ",".join(sorted(self._favorites)),
        }

    def cleanup(self) -> None:
        self._preview.cleanup()
        self._panel.cleanup()

    @staticmethod
    def _split(raw: str | None) -> list[str]:
        return [name.strip() for name in (raw or "").split(",") if name.strip()]

    # -- Dữ liệu ---------------------------------------------------------
    def _reload_voices(self) -> None:
        from autodub.config import Settings
        from autodub.speech.tts import voices as catalog
        from autodub.speech.tts.voices import source_group

        try:
            self._voices = list(catalog.catalog(Settings.load()))
        except Exception:  # noqa: BLE001 — thiếu tệp thì danh mục coi như rỗng
            self._voices = []
        # Chưa có giọng CapCut nào (chưa tải được) thì ẩn tab nguồn, giao
        # diện y như trước.
        has_capcut = any(source_group(v) == "capcut" for v in self._voices)
        self._src_tabs.setVisible(has_capcut)
        if not has_capcut:
            self._src_tab = _SRC_OFFLINE
        self._apply_filters()
        self._update_rail()

    def _voice_of(self, name: str):
        return next((v for v in self._voices if v.name == name), None)

    def _reset_page(self) -> None:
        self._page = 1
        self._apply_filters()

    def _on_tab(self, index: int) -> None:
        self._tab = index
        self._reset_page()

    def _on_src_tab(self, index: int) -> None:
        if index == self._src_tab:
            return
        self._src_tab = index
        self._reset_page()

    def _src_voices(self) -> list:
        """Giọng thuộc tab nguồn đang chọn; tab ẩn thì trả cả danh mục."""
        if not self._src_tabs.isVisible():
            return self._voices
        from autodub.speech.tts.voices import source_group

        want = "capcut" if self._src_tab == _SRC_CAPCUT else "offline"
        return [v for v in self._voices if source_group(v) == want]

    def _on_page(self, page: int) -> None:
        self._page = page
        self._rebuild_rows()

    def _clear_filters(self) -> None:
        for combo in (self._f_country, self._f_gender, self._f_style):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.search.set_text("")
        self._reset_page()

    def _apply_filters(self) -> None:
        matched = [v for v in self._src_voices() if v.matches(
            country=self._f_country.currentData() or "",
            gender=self._f_gender.currentData() or "",
            style=self._f_style.currentData() or "",
            query=self.search.text())]

        if self._tab == _TAB_FAV:
            matched = [v for v in matched if v.name in self._favorites]
        if self._tab == _TAB_RECENT:
            # Tab Gần đây giữ đúng thứ tự vừa dùng, không theo ô sắp xếp.
            rank = {name: i for i, name in enumerate(self._recent)}
            matched = sorted((v for v in matched if v.name in rank),
                             key=lambda v: rank[v.name])
        elif self._sort.currentData() == "custom":
            matched.sort(key=lambda v: (not v.custom, v.name.lower()))
        else:
            matched.sort(key=lambda v: v.name.lower(),
                         reverse=self._sort.currentData() == "name_desc")

        self._filtered = matched
        self._update_tabs()
        pages = max(1, (len(matched) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self._page = min(self._page, pages)
        self._pager.set_range(self._page, pages)
        self._pager.setVisible(pages > 1)
        self._rebuild_rows()

    def _update_tabs(self) -> None:
        """Số đếm trên tab theo tab nguồn đang chọn, không theo bộ lọc."""
        from autodub.speech.tts.voices import source_group

        subset = self._src_voices()
        recent = set(self._recent)
        counts = (len(subset),
                  sum(1 for v in subset if v.name in self._favorites),
                  sum(1 for v in subset if v.name in recent))
        for button, label, count in zip(self._tab_buttons, _TAB_LABELS, counts):
            button.setText(f"{label} ({count})")
        if self._src_tabs.isVisible():
            capcut = sum(1 for v in self._voices
                         if source_group(v) == "capcut")
            src_counts = (len(self._voices) - capcut, capcut)
            for button, label, count in zip(self._src_tab_buttons,
                                            _SRC_LABELS, src_counts):
                button.setText(f"{label} ({count})")
        self._online_hint.setVisible(self._src_tabs.isVisible()
                                     and self._src_tab == _SRC_CAPCUT)

    def _rebuild_rows(self) -> None:
        for row in self._rows:
            self._list.removeWidget(row)
            row.deleteLater()
        self._rows = []

        start = (self._page - 1) * _PAGE_SIZE
        page_items = self._filtered[start:start + _PAGE_SIZE]
        enabled = self._preview.available() and not self._preview.is_busy()
        for index, voice in enumerate(page_items):
            row = _VoiceRow(voice, voice.name in self._favorites)
            row.set_selected(voice.name == self._current)
            row.set_preview_enabled(enabled)
            row.clicked.connect(self._on_select)
            row.preview_requested.connect(self._play)
            row.favorite_toggled.connect(self._on_favorite)
            self._list.insertWidget(index, row)
            self._rows.append(row)

        self._empty.setVisible(not page_items)
        total, shown = len(self._voices), len(self._filtered)
        self._count.setText(f"{total} giọng" if shown == total
                            else f"{shown} trên {total} giọng")

    # -- Chọn giọng ------------------------------------------------------
    def _on_select(self, name: str) -> None:
        if name == self._current:
            return
        self._current = name
        self._push_recent(name)
        self._panel.picker.set_voice(name)
        for row in self._rows:
            row.set_selected(row.voice.name == name)
        self._update_rail()
        self._update_tabs()
        self.changed.emit()

    def _on_use(self) -> None:
        """Đưa giọng đang xem lên đầu danh sách dùng gần đây."""
        if self._current:
            self._push_recent(self._current)
            self._update_rail()
            self._update_tabs()
            self.changed.emit()

    def _on_favorite(self, name: str, on: bool) -> None:
        if on:
            self._favorites.add(name)
        else:
            self._favorites.discard(name)
        if name == self._current:
            _star(on, self._rail_star)
        self._update_tabs()
        self.changed.emit()

    def _on_rail_star(self, on: bool) -> None:
        if not self._current:
            _star(False, self._rail_star)
            return
        self._on_favorite(self._current, on)
        for row in self._rows:
            if row.voice.name == self._current:
                row.set_favorite(on)

    def _push_recent(self, name: str) -> None:
        self._recent = [name, *(n for n in self._recent
                                if n != name)][:_RECENT_MAX]

    def _on_panel_changed(self) -> None:
        """Vừa học xong một giọng mới: nạp lại danh mục và chọn giọng đó."""
        name = self._panel.picker.voice()
        if name:
            self._current = name
            self._push_recent(name)
        self._reload_voices()
        self.changed.emit()

    def _update_rail(self) -> None:
        self._rail_avatar.set_name(self._current)
        self._rail_name.setText(self._current or "Chưa chọn giọng")
        self._wave.set_seed(self._current)
        _star(self._current in self._favorites, self._rail_star)
        self._rail_star.setEnabled(bool(self._current))
        self._use.setEnabled(bool(self._current))
        voice = self._voice_of(self._current)
        self._rail_tags.setText(self._tag_text(voice) if voice else "")

        _clear(self._recent_row)
        if not self._recent:
            self._recent_row.addWidget(
                _muted("Giọng bạn chọn sẽ được ghi nhớ ở đây."))
            return
        for name in self._recent:
            avatar = _RecentAvatar(name)
            avatar.clicked.connect(self._on_select)
            self._recent_row.addWidget(avatar)
        self._recent_row.addStretch()

    @staticmethod
    def _tag_text(voice) -> str:
        genders, countries, styles = _labels()
        return _SEP.join(p for p in (countries.get(voice.country, ""),
                                     genders.get(voice.gender, ""),
                                     styles.get(voice.style, ""),
                                     "CapCut" if voice.is_capcut else "") if p)

    # -- Nghe thử --------------------------------------------------------
    def _play(self, voice: str) -> None:
        if not voice or self._preview.is_busy():
            return
        try:
            settings = self._settings_provider()
        except Exception as e:  # noqa: BLE001 — báo lý do lên giao diện
            self._status.setText(f"Không đọc được cấu hình: {e}")
            return
        self._set_preview_enabled(False)
        self._preview.play(settings, voice)

    def _set_preview_enabled(self, enabled: bool) -> None:
        enabled = enabled and self._preview.available()
        self._rail_play.setEnabled(enabled and bool(self._current))
        for row in self._rows:
            row.set_preview_enabled(enabled)
