"""Trang Xử lý hàng loạt: lồng tiếng nhiều video lần lượt.

Các video được xử lý lần lượt từng cái một chứ không song song, vì tách nhạc
nền, nghe lời và tạo giọng đều dùng chung card đồ họa; chạy cùng lúc sẽ hết
bộ nhớ. Điều này được nói rõ trên giao diện.
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMenu,
    QScrollArea, QVBoxLayout, QWidget,
)

from autodub.batch import BatchItem
from autodub.pipeline import DubRequest
from autodub.utils import save_json_atomic
from autodub_gui import dub_constants as consts
from autodub_gui import icons, tokens
from autodub_gui.pages import BasePage
from autodub_gui.run_state import REGISTRY, ActiveJob
from autodub_gui.run_state import step_percent
from autodub_gui.system_open import open_folder
from autodub_gui.ui.badges import StatusBadge
from autodub_gui.ui.buttons import (
    DangerButton, GhostButton, IconButton, PrimaryButton,
)
from autodub_gui.ui.collapsible import CollapsibleSection
from autodub_gui.ui.dropzone import DragDropZone, is_video_file
from autodub_gui.ui.inputs import LabeledCombo, LabeledSlider, LabeledWidget
from autodub_gui.ui.labels import ElidedLabel
from autodub_gui.ui.modal import ConfirmDialog
from autodub_gui.ui.progress import ThinProgressBar
from autodub_gui.ui.table import Column, DataTable
from autodub_gui.ui.toast import TOASTS
from autodub_gui.widgets import LogPanel
from autodub_gui.workers import BatchWorker
from autodub_gui.ui.style import clear_background
from autodub_gui.log_text import Narrator, error_line

_PAGE_MARGIN = 28
_THUMB_W, _THUMB_H = 56, 32
_ACTION_ICON = 28
_STATUS_COL_W = 150
_PROGRESS_COL_W = 190
_ACTION_COL_W = 96
_TABLE_MIN_H = 220      # bảng luôn đủ chỗ cho vài dòng, kể cả khi phải cuộn
_OPTION_COLS = 2        # tùy chọn xếp hai cột cho đỡ dài

# Trạng thái nội bộ của một dòng trong bảng
WAITING, RUNNING, DONE, FAILED, PAUSED = ("waiting", "running", "done",
                                          "failed", "paused")

_STATUS_VIEW: dict[str, tuple[str, str, str]] = {
    # trạng thái -> (nhãn, kiểu huy hiệu, màu thanh tiến trình)
    WAITING: ("Đang chờ", "neutral", tokens.TEXT_MUTED),
    RUNNING: ("Đang xử lý", "processing", tokens.PROCESSING),
    DONE: ("Hoàn thành", "success", tokens.SUCCESS),
    FAILED: ("Lỗi", "error", tokens.DANGER),
    PAUSED: ("Đã dừng", "warning", tokens.WARNING),
}

_PAUSE_TOOLTIP = ("Dừng lại — video đang xử lý sẽ tiếp tục từ chỗ dừng khi "
                  "bạn chạy lại, phần đã làm không mất.")

QUEUE_FILE = "batch_queue.json"     # danh sách chờ, sống qua các lần mở app


class BatchPage(BasePage):
    """Danh sách video chờ lồng tiếng."""

    settings_needed = Signal(str)

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._worker: BatchWorker | None = None
        self._items: list[BatchItem] = []
        self._state: dict[str, str] = {}
        self._percent: dict[str, int] = {}
        self._detail: dict[str, str] = {}
        self._done_steps: dict[str, set[str]] = {}
        self._current_key = ""
        self._chain_next = False       # lượt trước xong, còn video mới chờ
        self._pending_adds: set[str] = set()   # video thêm vào khi đang chạy
        self._shared_style: dict | None = None
        self._shared_regions: list[dict] = []
        self._rows: dict[str, int] = {}
        self._narrator = Narrator()
        self._build()
        self.setAcceptDrops(True)
        self._load_queue()
        self._refresh_table()

    # -- Lưu hàng chờ qua các lần mở app -------------------------------
    def _queue_path(self) -> str:
        from autodub_gui.pages.new_project_page import cache_dir
        return os.path.join(cache_dir(), QUEUE_FILE)

    def _load_queue(self) -> None:
        """Đọc lại danh sách chờ của lần trước — tắt app không mất hàng chờ."""
        try:
            with open(self._queue_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            return
        for entry in data["items"]:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url") or None
            file_path = entry.get("file_path") or None
            if file_path and not os.path.isfile(file_path):
                continue           # tệp đã bị xóa/di chuyển thì bỏ dòng đó
            if not url and not file_path:
                continue
            item = BatchItem(url=url, file_path=file_path)
            if item.key in self._state:
                continue
            self._items.append(item)
            state = entry.get("state")
            # Dòng đang chạy dở lúc tắt app coi như "Đã dừng" — chạy lại sẽ
            # tiếp tục từ chỗ dừng nhờ thư mục dự án còn nguyên.
            if state == RUNNING:
                state = PAUSED
            self._state[item.key] = (state if state in (WAITING, DONE, FAILED,
                                                        PAUSED) else WAITING)
            if self._state[item.key] == DONE:
                self._percent[item.key] = 100
            detail = entry.get("detail")
            if detail:
                self._detail[item.key] = str(detail)

    def _save_queue(self) -> None:
        """Ghi danh sách chờ xuống đĩa (nguyên tử) mỗi khi nó thay đổi."""
        items = [{"url": it.url, "file_path": it.file_path,
                  "state": self._state.get(it.key, WAITING),
                  "detail": self._detail.get(it.key, "")}
                 for it in self._items]
        try:
            save_json_atomic({"items": items}, self._queue_path())
        except OSError:
            pass      # không lưu được hàng chờ thì cũng không cản việc chính

    # -- Dựng giao diện ------------------------------------------------
    def _build(self) -> None:
        """Thanh trên và thanh dưới đứng yên, phần giữa cuộn được.

        Mục tùy chọn khi mở ra cao hơn cả khung nhìn ở cửa sổ nhỏ nhất, nên
        phần giữa phải cuộn; nếu không, Qt sẽ bóp bẹp bảng danh sách và khung
        nhật ký xuống dưới đáy cửa sổ, coi như mất hẳn.
        """
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._wrap(self._build_header(), bottom=0))
        root.addWidget(self._build_body(), 1)
        root.addWidget(self._wrap(self._build_footer(), top=tokens.SP_3,
                                  bottom=tokens.SP_5))

    @staticmethod
    def _wrap(layout, *, top: int = tokens.SP_2, bottom: int = 0) -> QWidget:
        """Đặt một hàng ngang vào khung riêng để nó giữ đúng lề của trang."""
        holder = QWidget()
        clear_background(holder)
        box = QVBoxLayout(holder)
        box.setContentsMargins(_PAGE_MARGIN, top, _PAGE_MARGIN, bottom)
        box.setSpacing(0)
        box.addLayout(layout)
        return holder

    def _build_body(self) -> QScrollArea:
        body = QWidget()
        clear_background(body)
        inner = QVBoxLayout(body)
        inner.setContentsMargins(_PAGE_MARGIN, tokens.SP_4,
                                 _PAGE_MARGIN, tokens.SP_2)
        inner.setSpacing(tokens.SP_4)

        self.dropzone = DragDropZone(compact=True)
        self.dropzone.file_selected.connect(lambda p: self._add_files([p]))
        self.dropzone.files_rejected.connect(self._add_files)
        inner.addWidget(self.dropzone)

        self.options = CollapsibleSection("Áp dụng cho tất cả video")
        self._build_options(self.options)
        inner.addWidget(self.options)

        note = QLabel("Các video được xử lý lần lượt từng cái để máy không quá tải.")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        inner.addWidget(note)

        self.table = DataTable(
            [Column("Video", stretch=True),
             Column("Trạng thái", width=_STATUS_COL_W),
             Column("Tiến trình", width=_PROGRESS_COL_W),
             Column("Thao tác", width=_ACTION_COL_W)],
            empty_title="Chưa có video nào trong danh sách",
            empty_description="Kéo thả video vào ô phía trên, chọn tệp từ máy "
                              "hoặc dán liên kết để bắt đầu.",
            empty_action="Thêm video")
        self.table.empty.action_clicked.connect(self._pick_files)
        self.table.setMinimumHeight(_TABLE_MIN_H)
        inner.addWidget(self.table, 1)

        self.log = LogPanel()
        self.log.setMaximumHeight(110)
        inner.addWidget(self.log)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        return scroll

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        row.addStretch()
        self.btn_add = PrimaryButton("Thêm video")
        self.btn_add.setToolTip("Chọn tệp từ máy, dán liên kết hoặc nhập từ "
                                "tệp danh sách")
        self.btn_add.clicked.connect(self._show_add_menu)
        self.btn_clear = GhostButton("Xóa tất cả")
        self.btn_clear.clicked.connect(self._clear_all)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_clear)
        return row

    def _build_options(self, section) -> None:
        self.opt_lang = LabeledCombo("Ngôn ngữ gốc", consts.SOURCE_LANGS,
                                     "Ngôn ngữ nói trong các video này")
        from autodub_gui.voice_picker import VoicePicker

        self.opt_voice = VoicePicker("Giọng đọc", show_preview=False)
        self.opt_bg = LabeledCombo("Nhạc nền", consts.BG_MODES,
                                   "Cách xử lý âm thanh gốc")
        self.opt_bg.changed.connect(
            lambda: self.opt_duck.setEnabled(
                self.opt_bg.current_key() == "duck"))
        self.opt_duck = LabeledSlider(
            "Mức giảm tiếng gốc", -40.0, 0.0, 1.0,
            "Càng âm thì tiếng gốc càng nhỏ khi có lời thoại tiếng Việt.",
            " dB", decimals=0)
        self.opt_duck.set_value(-12.0)
        self.opt_duck.setEnabled(False)
        self.opt_subtitle = LabeledCombo("Phụ đề", consts.SUBTITLE_MODES,
                                         "Cách hiện phụ đề trên video kết quả")
        # Chọn sẵn theo Cài đặt — trước đây luôn rơi về "Không" dù người
        # dùng đã đặt kiểu phụ đề mặc định khác.
        try:
            self.opt_subtitle.set_key(self._settings_provider().subtitle_mode)
        except Exception:  # noqa: BLE001 — cấu hình hỏng thì giữ mặc định
            pass
        section.add_layout(self._grid(
            [self.opt_lang, self.opt_voice, self.opt_bg, self.opt_duck,
             self.opt_subtitle, self._build_style_block()]))

        self.chk_audio_only = QCheckBox("Chỉ xuất âm thanh và phụ đề")
        self.chk_reuse = QCheckBox("Giữ bộ giọng giữa các video để chạy nhanh hơn")
        self.chk_reuse.setChecked(True)
        self.chk_retry = QCheckBox("Làm lại cả những video đã xong")
        section.add_layout(self._grid(
            [self.chk_audio_only, self.chk_reuse, self.chk_retry]))

    @staticmethod
    def _grid(widgets: list[QWidget]) -> QGridLayout:
        """Rải các ô thành lưới hai cột, hai cột rộng bằng nhau."""
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(tokens.SP_5)
        grid.setVerticalSpacing(tokens.SP_3)
        for column in range(_OPTION_COLS):
            grid.setColumnStretch(column, 1)
        for i, widget in enumerate(widgets):
            grid.addWidget(widget, i // _OPTION_COLS, i % _OPTION_COLS)
        return grid

    def _build_style_block(self) -> QWidget:
        """Nút mở hộp chỉnh kiểu chữ, dòng tóm tắt nằm hẳn xuống dưới.

        Dòng tóm tắt dùng nhãn rút gọn chứ không tự xuống dòng: nhãn tự xuống
        dòng nằm trong khung bọc thì Qt không biết nó cần mấy dòng, nên chỉ
        dành cho một dòng rồi cắt cụt phần chữ còn lại. Bản đầy đủ vẫn xem
        được ở chú giải.
        """
        self.btn_style = GhostButton("Kiểu chữ và vùng che…")
        self.btn_style.clicked.connect(self._customize_all)
        self.lbl_style = ElidedLabel("Kiểu mặc định cho cả danh sách")
        self.lbl_style.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        holder = QWidget()
        clear_background(holder)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(tokens.SP_1)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.btn_style)
        row.addStretch()
        box.addLayout(row)
        box.addWidget(self.lbl_style)
        return LabeledWidget(
            "Kiểu chữ phụ đề", holder,
            "Đặt phông chữ, cỡ chữ và vùng che cho cả danh sách")

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_3)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_LABEL}px; "
            f"background: transparent;")
        row.addWidget(self.summary, 1)
        self.btn_stop = DangerButton("Dừng")
        self.btn_stop.setToolTip(_PAUSE_TOOLTIP)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._cancel)
        self.btn_start = PrimaryButton("Bắt đầu tất cả")
        self.btn_start.clicked.connect(self._start_all)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_start)
        return row

    # -- Thêm và bớt video ---------------------------------------------
    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Chọn tệp từ máy…", self._pick_files)
        menu.addAction("Thêm liên kết…", self._add_link)
        menu.addAction("Nhập từ tệp danh sách…", self._import_list)
        menu.exec(self.btn_add.mapToGlobal(self.btn_add.rect().bottomLeft()))

    def _pick_files(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from autodub_gui.ui.dropzone import VIDEO_FILTER

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Chọn video", os.path.expanduser("~"), VIDEO_FILTER)
        self._add_files(paths)

    def _add_link(self) -> None:
        url, ok = QInputDialog.getText(
            self, "Thêm liên kết video",
            "Dán liên kết YouTube, TikTok, Douyin hoặc Bilibili:")
        url = (url or "").strip()
        if not ok or not url:
            return
        if not url.lower().startswith(("http://", "https://")):
            TOASTS.warn("Liên kết phải bắt đầu bằng http:// hoặc https://")
            return
        self._append([BatchItem(url=url)])

    def _import_list(self) -> None:
        """Đọc một tệp chữ, mỗi dòng một liên kết, bỏ dòng bắt đầu bằng dấu thăng."""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn tệp danh sách liên kết", "",
            "Tệp văn bản (*.txt);;Tất cả tệp (*.*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError as e:
            TOASTS.error("Không đọc được tệp danh sách.", detail=str(e))
            return
        urls = [line.strip() for line in lines
                if line.strip() and not line.strip().startswith("#")]
        urls = [u for u in urls if u.lower().startswith(("http://", "https://"))]
        if not urls:
            TOASTS.warn("Tệp này không có liên kết nào hợp lệ. Mỗi dòng cần "
                        "một liên kết bắt đầu bằng http:// hoặc https://")
            return
        self._append([BatchItem(url=u) for u in urls])
        TOASTS.success(f"Đã thêm {len(urls)} liên kết từ tệp danh sách.")

    def _add_files(self, paths: list[str]) -> None:
        valid = [p for p in paths if p and os.path.isfile(p) and is_video_file(p)]
        skipped = len(paths) - len(valid)
        self._append([BatchItem(file_path=p) for p in valid])
        if skipped:
            TOASTS.warn(f"Bỏ qua {skipped} tệp không phải video.")

    def _append(self, items: list[BatchItem]) -> None:
        existing = {it.key for it in self._items}
        added = 0
        for item in items:
            if item.key in existing:
                continue
            self._items.append(item)
            self._state[item.key] = WAITING
            existing.add(item.key)
            added += 1
            if self.is_running():
                self._pending_adds.add(item.key)
        if added:
            self._refresh_table()
            if self.is_running():
                TOASTS.info(f"Đã thêm {added} video vào hàng chờ — sẽ tự chạy "
                            "tiếp khi lượt hiện tại xong.")

    def _remove(self, key: str) -> None:
        self._items = [it for it in self._items if it.key != key]
        self._pending_adds.discard(key)
        for store in (self._state, self._percent, self._detail,
                      self._done_steps):
            store.pop(key, None)
        self._refresh_table()

    def _clear_all(self) -> None:
        if not self._items:
            return
        if self.is_running():
            TOASTS.warn("Đang chạy hàng loạt, hãy dừng trước khi xóa danh sách.")
            return
        confirmed, _ = ConfirmDialog.ask(
            self, "Xóa danh sách",
            f"Bỏ toàn bộ {len(self._items)} video khỏi danh sách chờ? "
            "Việc này không xóa tệp nào trên máy.",
            kind="warning", confirm_label="Xóa danh sách")
        if not confirmed:
            return
        self._items.clear()
        self._state.clear()
        self._percent.clear()
        self._detail.clear()
        self._done_steps.clear()
        self._refresh_table()

    # -- Bảng ----------------------------------------------------------
    def _refresh_table(self) -> None:
        self.table.clear_rows()
        self._rows.clear()
        for item in self._items:
            row = self.table.add_row()
            self._rows[item.key] = row
            self.table.set_widget(row, 0, self._video_cell(item))
            self._fill_status_cells(item.key, row)
        self.table.auto_state()
        self._refresh_summary()
        self._save_queue()

    def _video_cell(self, item: BatchItem) -> QWidget:
        """Ô đầu tiên: tên video và dòng mô tả nguồn."""
        holder = QWidget()
        clear_background(holder)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(1)
        title = ElidedLabel(self._title_of(item))
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_BODY}px; "
            f"font-weight: 500; background: transparent;")
        source = ElidedLabel(
            "Tệp trên máy" if item.file_path else "Tải từ liên kết")
        source.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        layout.addWidget(title)
        layout.addWidget(source)
        return holder

    @staticmethod
    def _title_of(item: BatchItem) -> str:
        if item.file_path:
            return os.path.basename(item.file_path)
        return item.url or item.key

    def _fill_status_cells(self, key: str, row: int) -> None:
        state = self._state.get(key, WAITING)
        label, kind, color = _STATUS_VIEW[state]
        badge = StatusBadge(label, kind)
        detail = self._detail.get(key, "")
        if detail:
            badge.setToolTip(detail)
        self.table.set_widget(row, 1, badge)

        holder = QWidget()
        clear_background(holder)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(3)
        bar = ThinProgressBar(color=color)
        percent = self._percent.get(key, 100 if state == DONE else 0)
        bar.setValue(percent)
        text = QLabel(f"{percent}%")
        text.setStyleSheet(
            f"color: {color}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        layout.addWidget(bar)
        layout.addWidget(text)
        self.table.set_widget(row, 2, holder)
        self.table.set_widgets(row, 3, self._action_buttons(key, state))

    def _action_buttons(self, key: str, state: str) -> list[QWidget]:
        """Hai nút thao tác, đổi theo trạng thái của dòng. Không có nút chết."""
        if state == RUNNING:
            first = IconButton(icons.pause(tokens.WARNING),
                               "Dừng sau video này", size=_ACTION_ICON)
            first.clicked.connect(self._cancel)
            second = IconButton(icons.trash(tokens.TEXT_DISABLED),
                                "Không xóa được khi đang chạy",
                                size=_ACTION_ICON)
            second.setEnabled(False)
            return [first, second]
        if state == DONE:
            first = IconButton(icons.folder(tokens.TEXT_SECONDARY),
                               "Mở thư mục kết quả", size=_ACTION_ICON)
            first.clicked.connect(lambda _c=False, k=key: self._open_result(k))
        elif state == FAILED:
            first = IconButton(icons.reload(tokens.WARNING),
                               "Chạy lại video này", size=_ACTION_ICON)
            first.clicked.connect(lambda _c=False, k=key: self._run_single(k))
        else:
            tooltip = ("Chạy tiếp video này ngay" if state == PAUSED
                       else "Chạy riêng video này ngay")
            first = IconButton(icons.play(tokens.SUCCESS), tooltip,
                               size=_ACTION_ICON)
            first.clicked.connect(lambda _c=False, k=key: self._run_single(k))
        second = IconButton(icons.trash(tokens.DANGER),
                            "Bỏ khỏi danh sách", size=_ACTION_ICON)
        second.clicked.connect(lambda _c=False, k=key: self._remove(k))
        return [first, second]

    def _update_row(self, key: str) -> None:
        row = self._rows.get(key)
        if row is not None:
            self._fill_status_cells(key, row)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        total = len(self._items)
        done = sum(1 for s in self._state.values() if s == DONE)
        running = sum(1 for s in self._state.values() if s == RUNNING)
        failed = sum(1 for s in self._state.values() if s == FAILED)
        self.summary.setText(
            f"Tổng: {total} video    Hoàn thành: {done}    "
            f"Đang xử lý: {running}    Lỗi: {failed}")
        self.btn_start.setEnabled(bool(total) and not self.is_running())

    # -- Kiểu phụ đề chung ---------------------------------------------
    def _customize_all(self) -> None:
        from autodub_gui.style_dialog import StyleDialog

        video = next((it.file_path for it in self._items
                      if it.file_path and os.path.isfile(it.file_path)), None)
        style = self._shared_style or self._settings_provider().subtitle_style()
        try:
            dialog = StyleDialog(video, style, list(self._shared_regions), self)
        except Exception as e:  # noqa: BLE001 — thường do thiếu ffmpeg
            ConfirmDialog.show_error(
                self, "Không mở được khung xem trước",
                "Ứng dụng cần một khung hình từ video để bạn canh chữ, nhưng "
                "lần này không lấy được. Hãy thêm ít nhất một tệp video từ máy "
                "rồi thử lại.", detail=str(e))
            return
        if not dialog.exec():
            return
        self._shared_style = dialog.style()
        if video:
            self._shared_regions = dialog.regions()
        count = len(self._shared_regions)
        self.lbl_style.setText(
            f"Cỡ chữ {self._shared_style.get('font_size', 22)}, "
            + (f"che {count} vùng" if count else "chưa che vùng nào")
            + " — áp dụng cho cả danh sách")
        if self.opt_subtitle.current_key() != "burn":
            self.opt_subtitle.set_key("burn")
            TOASTS.info("Kiểu chữ tự chỉnh cần ghi thẳng vào hình, nên phụ đề "
                        "đã chuyển sang Ghi thẳng vào hình.")

    # -- Chạy ----------------------------------------------------------
    def _template(self) -> DubRequest:
        settings = self._settings_provider()
        return DubRequest(
            source_lang=self.opt_lang.current_key(),
            voice=self.opt_voice.voice(),
            bg_mode=self.opt_bg.current_key(),
            bg_duck_db=self.opt_duck.value(),
            skip_video=self.chk_audio_only.isChecked(),
            subtitle_mode=self.opt_subtitle.current_key(),
            subtitle_style=self._shared_style or settings.subtitle_style(),
            blur_regions=list(self._shared_regions),
        )

    def _start_all(self) -> None:
        if not self._items:
            TOASTS.warn("Hãy thêm ít nhất một video trước khi chạy.")
            return
        self._launch(list(self._items))

    def _run_single(self, key: str) -> None:
        item = next((it for it in self._items if it.key == key), None)
        if item is None:
            return
        self._launch([item])

    def _warn_if_low_credit(self, count: int) -> bool:
        """Cảnh báo khi ví không đủ cho một lượt chạy hàng loạt.

        Không gọi mạng: đọc số dư đã lấy về lúc khởi động và cập nhật sau mỗi
        video. Chạy 30 video rồi hết Vox ở video thứ 8 là kiểu hỏng tệ nhất —
        mất thời gian tách nhạc và nghe chép của 22 video còn lại. Chặn trước
        thì người dùng nạp thêm rồi chạy một lần cho xong.

        Trả về True nếu người dùng vẫn muốn chạy tiếp.
        """
        from autodub.saas_client import get_client

        client = get_client()
        device = client.device
        if not device or not device.get("creditEnabled", True):
            return True
        balance = int(device.get("balance", 0))
        # Giá theo segment: 10 Vox nền (+2 nếu bật dịch tự động, +20 cho gói
        # đăng bài). Một video chừng 150-400 câu; lấy 150 câu × 10 Vox làm
        # mốc dè dặt để không dọa người dùng khi họ thật sự đủ Vox.
        needed = count * 150 * 10
        if balance >= needed:
            return True

        confirmed, _ = ConfirmDialog.ask(
            self, "Có thể không đủ Vox",
            (f"Bạn còn {balance:,} Vox. Chạy {count} video thường tốn khoảng "
             f"{needed:,} Vox trở lên (tính theo số câu thoại của từng "
             "video), nên lượt chạy có thể dừng giữa chừng vì hết Vox."
             "\n\nVideo đã xong vẫn giữ nguyên; các video sau dừng ngay sau "
             "bước nghe-chép (chưa bị trừ Vox) và chạy tiếp được sau khi "
             "bạn nạp thêm."
             ).replace(",", "."),
            kind="warning", confirm_label="Vẫn chạy",
            cancel_label="Để tôi nạp thêm")
        return confirmed

    def _launch(self, items: list[BatchItem]) -> None:
        if self.is_running():
            TOASTS.warn("Đang có video chạy dở. Hãy đợi xong hoặc bấm Dừng.")
            return
        if REGISTRY.is_busy():
            job = REGISTRY.current()
            TOASTS.warn(f"Đang chạy «{job.title}» ở trang khác. "
                        "Hãy đợi xong hoặc dừng việc đó trước.")
            return
        if not self._warn_if_low_credit(len(items)):
            return
        self._pending_adds -= {it.key for it in items}
        self.log.reset_log()
        self._narrator.reset()
        for item in items:
            if self._state.get(item.key) != DONE or self.chk_retry.isChecked():
                self._state[item.key] = WAITING
                self._percent[item.key] = 0
        self._refresh_table()
        self._set_running(True)

        worker = BatchWorker(
            self._settings_provider(), self._template(), items,
            retry_done=self.chk_retry.isChecked(),
            reuse_tts=self.chk_reuse.isChecked())
        worker.progress.connect(self._on_progress)
        worker.item_status.connect(self._on_item_status)
        worker.log.connect(self.log.append_log)
        worker.progress.connect(self._on_progress_log)
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(self._on_worker_done)
        self._worker = worker
        REGISTRY.start_job(
            ActiveJob(kind="batch",
                      title=f"Xử lý hàng loạt {len(items)} video"),
            on_cancel=self._cancel)
        worker.start()

    def _cancel(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            return
        self._worker.cancel()
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("Đang dừng…")

    def _set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running and bool(self._items))
        self.btn_stop.setEnabled(running)
        self.btn_stop.setText("Dừng")
        # Vẫn cho thêm video khi đang chạy (vào hàng chờ); chỉ khóa những gì
        # ảnh hưởng đến lượt đang chạy: xóa danh sách, kiểu chữ và tùy chọn.
        for widget in (self.btn_clear, self.btn_style,
                       self.chk_retry, self.chk_reuse, self.options):
            widget.setEnabled(not running)
        if not running:
            self._current_key = ""

    def _on_worker_done(self) -> None:
        """Luồng chạy xong: mở khóa giao diện, chạy tiếp hàng chờ nếu có."""
        self._set_running(False)
        if not self._chain_next:
            return
        self._chain_next = False
        pending = [it for it in self._items if it.key in self._pending_adds]
        if not pending:
            return
        TOASTS.info(f"Chạy tiếp {len(pending)} video vừa thêm vào hàng chờ.")
        QTimer.singleShot(0, lambda: self._launch(pending))

    def _on_progress(self, event) -> None:
        """Đưa tiến độ của video đang chạy vào đúng dòng của nó."""
        REGISTRY.update_job(event)
        # Pipeline báo work_dir trong sự kiện «acquire/start» — gắn vào việc
        # đang chạy để chuông thông báo mở được thư mục của video hiện tại.
        if (getattr(event, "step", "") == "acquire"
                and getattr(event, "status", "") == "start"
                and getattr(event, "detail", "")):
            job = REGISTRY.current()
            if job is not None:
                job.work_dir = event.detail
        key = self._current_key
        if not key:
            return
        step = getattr(event, "step", "")
        status = getattr(event, "status", "")
        finished = self._done_steps.setdefault(key, set())
        if status in ("done", "skip"):
            finished.add(step)
        percent = step_percent(finished, step,
                               int(getattr(event, "current", 0) or 0),
                               int(getattr(event, "total", 0) or 0))
        # Chỉ cho phần trăm tăng lên, tránh nhảy giật khi bước sau bắt đầu.
        self._percent[key] = max(self._percent.get(key, 0), percent)
        self._update_row(key)

    def _on_item_status(self, _index: int, _total: int, key: str,
                        status: str, detail: str) -> None:
        mapping = {"start": RUNNING, "success": DONE, "failed": FAILED}
        state = mapping.get(status, WAITING)
        self._state[key] = state
        self._detail[key] = detail
        if state == RUNNING:
            self._current_key = key
            self._percent[key] = 0
            self._done_steps[key] = set()
        elif state == DONE:
            self._percent[key] = 100
        self._update_row(key)
        # Lưu ngay khi một video đổi trạng thái (không lưu theo từng phần
        # trăm) — app có bị tắt ngang thì hàng chờ vẫn đúng tới video đó.
        self._save_queue()

    def _on_finished(self, summary) -> None:
        REGISTRY.finish_job(True,
                            f"{summary.success}/{summary.total} video xong")
        skipped = (f", bỏ qua {summary.skipped} video đã xong"
                   if summary.skipped else "")
        TOASTS.success(
            f"Xong hàng loạt: {summary.success} thành công, "
            f"{summary.failed} lỗi{skipped}.")
        self._refresh_table()
        # Chỉ lượt kết thúc bình thường mới nối tiếp hàng chờ; lượt bị dừng
        # hay lỗi thì để người dùng tự quyết chạy tiếp hay không.
        self._chain_next = bool(self._pending_adds)

    def _on_failed(self, message: str) -> None:
        import logging as _log
        text, level = error_line(message)
        self.log.append_log(text, level)
        REGISTRY.finish_job(False, message[:120])
        friendly = consts.friendly_error(message)
        if friendly is not None:
            title, advice = friendly
            ConfirmDialog.show_error(self, title, advice, detail=message)
            return
        ConfirmDialog.show_error(
            self, "Không chạy được danh sách",
            "Có lỗi ngoài dự tính nên cả lượt chạy phải dừng. Những video đã "
            "xong vẫn còn nguyên kết quả trên máy.", detail=message)

    def _on_cancelled(self) -> None:
        import logging as _log
        self.log.append_log("Đã dừng theo yêu cầu của bạn.", _log.WARNING)
        for key, state in self._state.items():
            if state == RUNNING:
                self._state[key] = PAUSED
        REGISTRY.finish_job(False, "bạn đã bấm dừng")
        self._refresh_table()
        TOASTS.info("Đã dừng. Video đang dở sẽ chạy tiếp từ chỗ dừng khi bạn "
                    "bấm chạy lại.")

    def _on_progress_log(self, event) -> None:
        """Kể lại tiến trình bằng lời thường vào Nhật ký."""
        result = self._narrator.narrate(event)
        if result is None:
            return
        text, level, is_progress = result
        self.log.append_log(text, level, is_progress=is_progress)

    def _open_result(self, key: str) -> None:
        detail = self._detail.get(key, "")
        target = detail if detail and os.path.exists(detail) else ""
        if not target:
            item = next((it for it in self._items if it.key == key), None)
            target = item.file_path if item and item.file_path else ""
        ok, message = open_folder(target)
        if not ok:
            TOASTS.warn(message)

    # -- Kéo thả -------------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self._add_files(paths)

    # -- Vòng đời ------------------------------------------------------
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def shutdown(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)

