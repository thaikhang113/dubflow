"""Trang Tải xuống: chỉ tải video về máy, không lồng tiếng."""
from __future__ import annotations

import os
import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from autodub.media.bilibili import has_login_cookies, save_netscape_cookies
from autodub.media.douyin_cookies import (
    save_douyin_cookies,
    validate_douyin_cookies,
)
from autodub_gui import icons, tokens
from autodub_gui.log_text import error_line
from autodub_gui.pages import BasePage
from autodub_gui.run_state import REGISTRY, ActiveJob
from autodub_gui.system_open import open_file, open_folder, reveal_file
from autodub_gui.ui.badges import StatusBadge
from autodub_gui.ui.buttons import (
    DangerButton,
    GhostButton,
    IconButton,
    PrimaryButton,
)
from autodub_gui.ui.cards import Card
from autodub_gui.ui.inputs import FilePicker, LabeledCombo
from autodub_gui.ui.labels import ElidedLabel
from autodub_gui.ui.modal import ConfirmDialog
from autodub_gui.ui.style import clear_background
from autodub_gui.ui.table import Column, DataTable
from autodub_gui.ui.toast import TOASTS
from autodub_gui.widgets import LogPanel
from autodub_gui.workers import DownloadWorker


def download_finish_ok(success: int, failed: int) -> bool:
    return int(failed) == 0

def download_finish_detail(success: int, failed: int) -> str:
    detail = f"{int(success)} video tải xong"
    if failed:
        detail += f", {int(failed)} liên kết lỗi"
    return detail
from autodub.config import Settings
from autodub.utils import app_root
from autodub_gui.env_store import read_env, write_env

_PAGE_MARGIN = 28
_INPUT_MIN_H = 72
_INPUT_MAX_H = 112
_ACTION_ICON = 28
_STATUS_COL_W = 140
_ACTION_COL_W = 90

_COOKIE_SOURCES = [
    ("Không dùng cookie", ""),
    ("Lấy từ Chrome", "chrome"),
    ("Lấy từ Edge", "edge"),
    ("Lấy từ Firefox", "firefox"),
]

_STATUS_VIEW = {
    "waiting": ("Đang chờ", "neutral"),
    "start": ("Đang tải", "processing"),
    "success": ("Xong", "success"),
    "failed": ("Lỗi", "error"),
}

# Tệp đánh dấu người dùng đã đọc và đồng ý lưu ý bản quyền — hỏi đúng một lần
# cho mỗi máy, trừ khi họ bỏ tích "không hỏi lại".
_DISCLAIMER_MARKER = "download_disclaimer_ok"


def _disclaimer_marker_path() -> str:
    from autodub_gui.pages.new_project_page import cache_dir

    return os.path.join(cache_dir(), _DISCLAIMER_MARKER)


class DownloadPage(BasePage):
    """Tải nhiều liên kết video một lượt."""

    finished_all = Signal(int, int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._worker: DownloadWorker | None = None
        self._urls: list[str] = []
        self._status: dict[str, tuple[str, str]] = {}
        self._rows: dict[str, int] = {}
        self._build()

    # -- Dựng giao diện ------------------------------------------------
    def _build(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        clear_background(scroll)
        clear_background(scroll.viewport())

        body = QWidget()
        clear_background(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(_PAGE_MARGIN, tokens.SP_2,
                                _PAGE_MARGIN, tokens.SP_5)
        root.setSpacing(tokens.SP_4)
        root.addWidget(self._build_bilibili_login_card())
        root.addWidget(self._build_douyin_cookie_card())
        root.addWidget(self._build_input_card())
        root.addLayout(self._build_actions())

        self.table = DataTable(
            [Column("Liên kết", stretch=True),
             Column("Trạng thái", width=_STATUS_COL_W),
             Column("Thao tác", width=_ACTION_COL_W)],
            empty_title="Chưa tải liên kết nào",
            empty_description="Dán liên kết vào ô phía trên rồi bấm Tải xuống. "
                              "Kết quả từng liên kết sẽ hiện ở đây.")
        self.table.setMinimumHeight(320)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.table.verticalHeader().setDefaultSectionSize(44)
        root.addWidget(self.table, 1)

        self.log = LogPanel()
        self.log.setMaximumHeight(78)
        root.addWidget(self.log)
        scroll.setWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _build_bilibili_login_card(self) -> QWidget:
        card = Card(padding=tokens.SP_4)
        card.add_header("Đăng nhập Bilibili")
        hint = QLabel(
            "Mở trang đăng nhập, đăng nhập trên trình duyệt, rồi dán cookie "
            "Netscape vào ô dưới. Cookie lưu cục bộ, không đưa vào Git.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            "background: transparent;")
        card.body.addWidget(hint)

        actions = QHBoxLayout()
        open_login = GhostButton("Mở Bilibili để đăng nhập")
        open_login.clicked.connect(
            lambda: webbrowser.open("https://passport.bilibili.com/login"))
        actions.addWidget(open_login)
        self.cookie_status = QLabel("")
        self.cookie_status.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            "background: transparent;")
        actions.addWidget(self.cookie_status, 1)
        save_button = GhostButton("Lưu cookie")
        save_button.clicked.connect(self._save_bilibili_cookies)
        actions.addWidget(save_button)
        clear_button = GhostButton("Xóa cookie")
        clear_button.clicked.connect(self._clear_bilibili_cookies)
        actions.addWidget(clear_button)
        card.body.addLayout(actions)

        self.cookie_edit = QPlainTextEdit()
        self.cookie_edit.setPlaceholderText(
            "# Netscape HTTP Cookie File\n"
            ".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\t...\n"
            ".bilibili.com\tTRUE\t/\tFALSE\t0\tDedeUserID\t...\n"
            ".bilibili.com\tTRUE\t/\tFALSE\t0\tbili_jct\t...")
        self.cookie_edit.setMinimumHeight(64)
        self.cookie_edit.setMaximumHeight(80)
        card.body.addWidget(self.cookie_edit)
        self._refresh_bilibili_cookie_status()
        return card

    def _bilibili_cookie_path(self) -> str:
        return os.path.join(app_root(), "bilibili-cookies.txt")

    def _save_bilibili_cookies(self) -> None:
        try:
            path = self._bilibili_cookie_path()
            save_netscape_cookies(self.cookie_edit.toPlainText(), path)
            write_env({"BILIBILI_COOKIES_FILE": path})
        except (OSError, ValueError) as exc:
            self.cookie_status.setText(f"Không lưu được cookie: {str(exc)[:180]}")
            return
        self.cookie_edit.clear()
        self._refresh_bilibili_cookie_status()

    def _clear_bilibili_cookies(self) -> None:
        path = self._bilibili_cookie_path()
        try:
            if os.path.exists(path):
                os.remove(path)
            write_env({"BILIBILI_COOKIES_FILE": ""})
        except OSError as exc:
            self.cookie_status.setText(f"Không xóa được cookie: {str(exc)[:180]}")
            return
        self._refresh_bilibili_cookie_status()

    def _refresh_bilibili_cookie_status(self) -> None:
        path = read_env().get("BILIBILI_COOKIES_FILE", "").strip()
        if has_login_cookies(path):
            self.cookie_status.setText("Cookie Bilibili đã lưu và có đủ dấu đăng nhập.")
        else:
            self.cookie_status.setText("Chưa có cookie Bilibili hợp lệ.")

    def _build_douyin_cookie_card(self) -> QWidget:
        card = Card(padding=tokens.SP_4)
        card.add_header("Cookie Douyin")
        hint = QLabel(
            "Dán nội dung Netscape cookies.txt xuất từ trình duyệt. Cookie lưu "
            "cục bộ và chỉ dùng cho luồng tải Douyin.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            "background: transparent;")
        card.body.addWidget(hint)

        actions = QHBoxLayout()
        self.douyin_cookie_status = QLabel("")
        self.douyin_cookie_status.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            "background: transparent;")
        actions.addWidget(self.douyin_cookie_status, 1)
        save_button = GhostButton("Lưu cookie")
        save_button.clicked.connect(self._save_douyin_cookies)
        actions.addWidget(save_button)
        clear_button = GhostButton("Xóa cookie")
        clear_button.clicked.connect(self._clear_douyin_cookies)
        actions.addWidget(clear_button)
        card.body.addLayout(actions)

        self.douyin_cookie_edit = QPlainTextEdit()
        self.douyin_cookie_edit.setPlaceholderText(
            "# Netscape HTTP Cookie File\n"
            ".douyin.com\tTRUE\t/\tFALSE\t0\tsessionid\t...\n"
            ".iesdouyin.com\tTRUE\t/\tFALSE\t0\tmsToken\t...")
        self.douyin_cookie_edit.setMinimumHeight(64)
        self.douyin_cookie_edit.setMaximumHeight(80)
        card.body.addWidget(self.douyin_cookie_edit)
        self._refresh_douyin_cookie_status()
        return card

    def _douyin_cookie_path(self) -> str:
        return os.path.join(app_root(), "douyin-cookies.txt")

    def _save_douyin_cookies(self) -> None:
        try:
            path = self._douyin_cookie_path()
            save_douyin_cookies(self.douyin_cookie_edit.toPlainText(), path)
            write_env({"DOUYIN_COOKIES_FILE": path})
        except (OSError, ValueError) as exc:
            self.douyin_cookie_status.setText(
                f"Không lưu được cookie: {str(exc)[:180]}")
            return
        self.douyin_cookie_edit.clear()
        self._refresh_douyin_cookie_status()

    def _clear_douyin_cookies(self) -> None:
        path = self._douyin_cookie_path()
        try:
            if os.path.exists(path):
                os.remove(path)
            write_env({"DOUYIN_COOKIES_FILE": ""})
        except OSError as exc:
            self.douyin_cookie_status.setText(
                f"Không xóa được cookie: {str(exc)[:180]}")
            return
        self._refresh_douyin_cookie_status()

    def _refresh_douyin_cookie_status(self) -> None:
        path = read_env().get("DOUYIN_COOKIES_FILE", "").strip()
        try:
            with open(path, encoding="utf-8") as handle:
                valid = bool(validate_douyin_cookies(handle.read()))
        except (OSError, ValueError):
            valid = False
        self.douyin_cookie_status.setText(
            "Cookie Douyin đã lưu." if valid
            else "Chưa có cookie Douyin hợp lệ.")

    def _build_input_card(self) -> QWidget:
        card = Card(padding=tokens.SP_4)
        card.add_header("Liên kết cần tải")
        self.urls_edit = QPlainTextEdit()
        self.urls_edit.setPlaceholderText(
            "Mỗi dòng một liên kết. Dòng bắt đầu bằng dấu thăng sẽ bị bỏ qua.\n"
            "https://www.youtube.com/watch?v=...\n"
            "https://v.douyin.com/...")
        self.urls_edit.setMinimumHeight(_INPUT_MIN_H)
        self.urls_edit.setMaximumHeight(_INPUT_MAX_H)
        card.body.addWidget(self.urls_edit)

        helper = QHBoxLayout()
        helper.setSpacing(tokens.SP_2)
        paste = GhostButton("Dán từ bộ nhớ tạm")
        paste.setToolTip("Dán nội dung bạn vừa sao chép vào ô liên kết")
        paste.clicked.connect(self._paste_clipboard)
        import_file = GhostButton("Nhập từ tệp danh sách")
        import_file.setToolTip("Đọc một tệp chữ, mỗi dòng một liên kết")
        import_file.clicked.connect(self._import_list)
        clear = GhostButton("Xóa hết")
        clear.clicked.connect(self.urls_edit.clear)
        helper.addWidget(paste)
        helper.addWidget(import_file)
        helper.addWidget(clear)
        helper.addStretch()
        card.body.addLayout(helper)

        options = QHBoxLayout()
        options.setSpacing(tokens.SP_3)
        self.output = FilePicker("Thư mục lưu", "downloads",
                                 "Nơi lưu các video tải về", directory=True)
        self.output.set_text("downloads")
        self.cookies = LabeledCombo(
            "Cookie đăng nhập", _COOKIE_SOURCES,
            "Một số video yêu cầu đăng nhập. Chọn trình duyệt bạn đang đăng "
            "nhập để dùng lại phiên đó.")
        options.addWidget(self.output, 2)
        options.addWidget(self.cookies, 1)
        card.body.addLayout(options)
        return card

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_LABEL}px; "
            f"background: transparent;")
        row.addWidget(self.summary, 1)
        open_button = GhostButton("Mở thư mục lưu")
        open_button.clicked.connect(self._open_output)
        self.btn_stop = DangerButton("Dừng")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._cancel)
        self.btn_start = PrimaryButton("Tải xuống")
        self.btn_start.clicked.connect(self._start)
        row.addWidget(open_button)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_start)
        return row

    # -- Nhập liên kết -------------------------------------------------
    def _paste_clipboard(self) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            TOASTS.warn("Bộ nhớ tạm đang trống, chưa có gì để dán.")
            return
        current = self.urls_edit.toPlainText().rstrip()
        self.urls_edit.setPlainText(f"{current}\n{text}".strip())

    def _import_list(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn tệp danh sách liên kết", "",
            "Tệp văn bản (*.txt);;Tất cả tệp (*.*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            TOASTS.error("Không đọc được tệp danh sách.", detail=str(e))
            return
        current = self.urls_edit.toPlainText().rstrip()
        self.urls_edit.setPlainText(f"{current}\n{content}".strip())
        TOASTS.success("Đã nạp danh sách liên kết từ tệp.")

    def _collect_urls(self) -> list[str]:
        """Lọc lấy các liên kết hợp lệ, bỏ dòng trống và dòng ghi chú."""
        from autodub.batch import parse_lines

        return [item.url for item in parse_lines(self.urls_edit.toPlainText())
                if item.url]

    # -- Chạy ----------------------------------------------------------
    def _confirm_disclaimer(self) -> bool:
        """Lưu ý bản quyền trước lần tải đầu tiên. True = được phép tải."""
        if os.path.isfile(_disclaimer_marker_path()):
            return True
        accepted, dont_ask = ConfirmDialog.ask(
            self, "Lưu ý về bản quyền",
            "Video bạn tải về có thể thuộc bản quyền của người khác. Hãy chỉ "
            "dùng cho mục đích cá nhân, học tập, hoặc khi bạn có quyền sử "
            "dụng nội dung đó. Đăng lại video của người khác khi chưa được "
            "phép có thể vi phạm pháp luật và điều khoản của nền tảng — bạn "
            "tự chịu trách nhiệm về cách mình dùng video tải về.",
            kind="info", confirm_label="Tôi hiểu, tiếp tục tải",
            cancel_label="Thôi", checkbox_label="Không hỏi lại trên máy này",
            checkbox_checked=True)
        if accepted and dont_ask:
            try:
                with open(_disclaimer_marker_path(), "w",
                          encoding="utf-8") as f:
                    f.write("accepted\n")
            except OSError:
                pass  # không ghi được thì lần sau hỏi lại, không sao
        return accepted

    def _start(self) -> None:
        if self.is_running():
            return
        urls = self._collect_urls()
        if not urls:
            TOASTS.warn("Chưa có liên kết nào hợp lệ. Mỗi dòng cần một liên "
                        "kết bắt đầu bằng http:// hoặc https://")
            return
        if not self._confirm_disclaimer():
            return
        self._urls = urls
        self._status = {url: ("waiting", "") for url in urls}
        self._refresh_table()
        self.log.reset_log()
        self._set_running(True)

        cookies_file = (
            read_env().get("BILIBILI_COOKIES_FILE", "").strip()
            if not self.cookies.current_key() else None
        ) or None
        douyin_cookies_file = (
            read_env().get("DOUYIN_COOKIES_FILE", "").strip() or None)
        settings = Settings.load()
        worker = DownloadWorker(urls, self.output.text() or "downloads",
                                self.cookies.current_key(), cookies_file, self,
                                douyin_cookies_file=douyin_cookies_file,
                                url_workers=settings.download_url_workers,
                                fragment_workers=settings.download_fragment_workers)
        worker.item_status.connect(self._on_item_status)
        worker.log.connect(self.log.append_log)
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(lambda: self._set_running(False))
        self._worker = worker
        REGISTRY.start_job(
            ActiveJob(kind="download", title=f"Tải {len(urls)} video",
                      # Chuông thông báo mở được thư mục chứa video tải về.
                      work_dir=os.path.abspath(self.output.text() or "downloads")),
            on_cancel=self._cancel)
        worker.start()

    def _cancel(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            return
        self._worker.cancel()
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("Đang dừng…")

    def _set_running(self, running: bool) -> None:
        self.btn_start.set_loading(running, "Đang tải")
        self.btn_stop.setEnabled(running)
        self.btn_stop.setText("Dừng")
        self.urls_edit.setReadOnly(running)

    def _on_item_status(self, _index: int, _total: int, url: str,
                        status: str, detail: str) -> None:
        self._status[url] = (status, detail)
        self._update_row(url)

    def _on_finished(self, success: int, failed: int) -> None:
        detail = download_finish_detail(success, failed)
        REGISTRY.finish_job(download_finish_ok(success, failed), detail)
        self.summary.setText(
            f"Đã tải xong {success} video" +
            (f", {failed} liên kết lỗi" if failed else ""))
        if download_finish_ok(success, failed):
            TOASTS.success(f"Tải xong {success} video.",
                           action_label="Mở thư mục", on_action=self._open_output)
        else:
            TOASTS.warn(f"Lượt tải chưa hoàn tất: {detail}.")
        self.finished_all.emit(success, failed)

    def _on_failed(self, message: str) -> None:
        text, level = error_line(message)
        self.log.append_log(text, level)
        REGISTRY.finish_job(False, message[:120])
        ConfirmDialog.show_error(
            self, "Không tải được",
            "Ứng dụng không ghi được vào thư mục lưu. Hãy chọn một thư mục "
            "khác mà bạn có quyền ghi, rồi thử lại.", detail=message)

    def _on_cancelled(self) -> None:
        import logging as _log
        REGISTRY.finish_job(False, "bạn đã bấm dừng")
        self.log.append_log("Đã dừng theo yêu cầu của bạn.", _log.WARNING)
        TOASTS.info("Đã dừng tải. Những video tải xong vẫn còn trên máy.")

    # -- Bảng ----------------------------------------------------------
    def _refresh_table(self) -> None:
        self.table.clear_rows()
        self._rows.clear()
        for url in self._urls:
            row = self.table.add_row()
            self._rows[url] = row
            label = ElidedLabel(url)
            label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_META}px; "
                f"background: transparent;")
            self.table.set_widget(row, 0, label)
            self._fill_status(url, row)
        self.table.auto_state()
        self.summary.setText(f"{len(self._urls)} liên kết trong danh sách")

    def _fill_status(self, url: str, row: int) -> None:
        status, detail = self._status.get(url, ("waiting", ""))
        label, kind = _STATUS_VIEW.get(status, _STATUS_VIEW["waiting"])
        badge = StatusBadge(label, kind)
        if detail:
            badge.setToolTip(detail)
        self.table.set_widget(row, 1, badge)
        self.table.set_widgets(row, 2, self._actions(url, status, detail))

    def _actions(self, url: str, status: str, detail: str) -> list[QWidget]:
        """Hai nút, đổi theo trạng thái của dòng. Không có nút chết."""
        if status == "success" and detail:
            first = IconButton(icons.play(tokens.SUCCESS), "Mở video",
                               size=_ACTION_ICON)
            first.clicked.connect(lambda _c=False, p=detail: self._open(p))
            second = IconButton(icons.folder(tokens.TEXT_SECONDARY),
                                "Mở thư mục chứa video", size=_ACTION_ICON)
            second.clicked.connect(lambda _c=False, p=detail: reveal_file(p))
            return [first, second]
        first = IconButton(icons.external(tokens.TEXT_SECONDARY),
                           "Mở liên kết trong trình duyệt", size=_ACTION_ICON)
        first.clicked.connect(lambda _c=False, u=url: self._open_link(u))
        second = IconButton(icons.trash(tokens.DANGER),
                            "Bỏ khỏi danh sách", size=_ACTION_ICON)
        second.clicked.connect(lambda _c=False, u=url: self._remove(u))
        second.setEnabled(not self.is_running())
        return [first, second]

    def _update_row(self, url: str) -> None:
        row = self._rows.get(url)
        if row is not None:
            self._fill_status(url, row)

    def _remove(self, url: str) -> None:
        self._urls = [u for u in self._urls if u != url]
        self._status.pop(url, None)
        self._refresh_table()

    def _open(self, path: str) -> None:
        ok, message = open_file(path)
        if not ok:
            TOASTS.warn(message)

    def _open_link(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(url))

    def _open_output(self) -> None:
        path = self.output.text() or "downloads"
        os.makedirs(path, exist_ok=True)
        ok, message = open_folder(path)
        if not ok:
            TOASTS.warn(message)

    # -- Vòng đời ------------------------------------------------------
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def shutdown(self) -> None:
        if self.is_running():
            self._worker.cancel()
            self._worker.wait(5000)
