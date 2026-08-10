"""Cửa sổ chính và điểm khởi động của ứng dụng.

Bố cục: thanh bên trái, thanh tiêu đề và vùng nội dung xếp chồng. Mỗi trang
chỉ được dựng khi người dùng mở lần đầu, nhờ vậy ứng dụng khởi động nhanh.
"""
from __future__ import annotations

import os
import sys

from autodub_gui import _frozen

_frozen.init()  # phải chạy trước mọi thứ khác: PATH, PLAYWRIGHT_BROWSERS_PATH, chdir

from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMessageBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from autodub.config import Settings
from autodub_gui import icons, theme, tokens
from autodub_gui.startup_check import check_startup
from autodub_gui.run_state import REGISTRY
from autodub_gui.shell import AppHeader, NotificationPopup, Sidebar
from autodub_gui.ui.modal import ConfirmDialog
from autodub_gui.ui.style import panel_background
from autodub_gui.ui.toast import TOASTS

APP_NAME = "VoxDub Studio"
APP_TAGLINE = "Lồng tiếng video bằng AI"
APP_VERSION = "3.0.0"

# -- Danh mục trang ----------------------------------------------------
ROW_HOME, ROW_NEW, ROW_PROJECTS, ROW_BATCH, ROW_DOWNLOAD = 0, 1, 2, 3, 4
ROW_SETTINGS, ROW_HELP = 5, 6
ROW_EDITOR = 7          # trang ngữ cảnh (ẩn header khi mở)

# Trang công cụ (mới — trang riêng, không phải shortcut vào Settings)
ROW_VOICE    = 8    # Giọng đọc AI
ROW_TRANSLATE = 9   # Dịch thuật
ROW_SUBTITLE  = 10  # Phụ đề
ROW_QUALITY   = 11  # Báo cáo chất lượng

# Trang launcher editor (trung gian — không hiện trong sidebar)
ROW_EDITOR_LAUNCHER = 12

ROW_ACCOUNT = 13    # Tài khoản: ví Vox, kích hoạt mã, lịch sử

PAGE_COUNT = 14

# (số thứ tự, nhãn ở thanh bên, tiêu đề trang, mô tả trang, biểu tượng, nhóm)
PAGES: list[tuple[int, str, str, str, object, str]] = [
    # Nhóm "main" — LUỒNG LÀM VIỆC
    (ROW_HOME,      "Trang chủ",         "Chào {name}!",
     "Biến video của bạn thành nội dung tiếng Việt tự nhiên",
     icons.home, "main"),
    (ROW_NEW,       "Tạo dự án",         "Tạo dự án mới",
     "Lồng tiếng video chuyên nghiệp với AI",
     icons.file_plus, "main"),
    (ROW_PROJECTS,  "Dự án",             "Dự án của tôi",
     "Toàn bộ video đã và đang xử lý",
     icons.folder, "main"),
    (ROW_EDITOR,    "Trình chỉnh sửa",   "Trình chỉnh sửa",
     "Chỉnh sửa phụ đề, giọng đọc và xuất video",
     icons.edit, "main"),
    (ROW_BATCH,     "Xử lý hàng loạt",   "Xử lý hàng loạt",
     "Lồng tiếng nhiều video cùng lúc",
     icons.layers, "main"),
    (ROW_DOWNLOAD,  "Tải xuống",         "Tải xuống",
     "Chỉ tải video về máy, không lồng tiếng",
     icons.download, "main"),
    # Nhóm "tools" — CÔNG CỤ (trang riêng)
    (ROW_VOICE,     "Giọng đọc AI",      "Giọng đọc AI",
     "Quản lý và tùy chỉnh giọng đọc",
     icons.user, "tools"),
    (ROW_TRANSLATE, "Dịch thuật",        "Dịch thuật",
     "Cấu hình engine dịch và kết nối API",
     icons.globe, "tools"),
    (ROW_SUBTITLE,  "Phụ đề",            "Phụ đề",
     "Tùy chỉnh kiểu dáng và bố cục phụ đề",
     icons.captions, "tools"),
    (ROW_QUALITY,   "Báo cáo chất lượng","Báo cáo chất lượng",
     "Thống kê ASR, dịch thuật và cảnh báo timing",
     icons.chart_bar, "tools"),
    # Nhóm "second" — HỆ THỐNG
    (ROW_ACCOUNT,   "Tài khoản",         "Tài khoản",
     "Số Vox còn lại, kích hoạt mã và lịch sử sử dụng",
     icons.user, "second"),
    (ROW_SETTINGS,  "Cài đặt",           "Cài đặt",
     "Tùy chỉnh hệ thống theo nhu cầu của bạn",
     icons.gear, "second"),
    (ROW_HELP,      "Trợ giúp",          "Trợ giúp",
     "Hướng dẫn, khắc phục sự cố, thông tin phiên bản",
     icons.help_circle, "second"),
]

_PAGE_BY_ROW = {p[0]: p for p in PAGES}

# Mốc chiều rộng cửa sổ và bề rộng thanh bên tương ứng
_BREAKPOINTS = (
    (1440, "xl", tokens.SIDEBAR_W),
    (1200, "lg", tokens.SIDEBAR_W_COMPACT),
    (1024, "md", tokens.SIDEBAR_W_COMPACT),
    (0, "sm", tokens.SIDEBAR_W_ICON),
)

_MIN_W, _MIN_H = 1024, 680
_START_W, _START_H = 1360, 820
_STARTUP_RECHECK_MS = 30 * 60 * 1000
_SMOKE_DELAY_MS = 1500
_VIDEO_PROBE_MS = 4000     # thời gian chờ tối đa khi thử giải mã video

# Dựng sẵn các trang sau khi cửa sổ hiện lên: trang hay dùng trước, trang
# nặng nhất (Cài đặt) dựng sớm để lần bấm đầu tiên không phải chờ.
_PREWARM_ORDER = (ROW_HELP, ROW_SETTINGS, ROW_NEW, ROW_PROJECTS,
                  ROW_BATCH, ROW_DOWNLOAD, ROW_EDITOR,
                  ROW_VOICE, ROW_TRANSLATE, ROW_SUBTITLE, ROW_QUALITY,
                  ROW_EDITOR_LAUNCHER, ROW_ACCOUNT)
_PREWARM_START_MS = 700     # chờ khung hình đầu vẽ xong rồi mới dựng
_PREWARM_GAP_MS = 250       # nghỉ giữa hai trang để giao diện luôn mượt
_PREFLIGHT_DELAY_MS = 1200  # kiểm tra máy sau khi cửa sổ đã hiện xong
_FIRST_RUN_DELAY_MS = 400   # màn chào lần đầu, ngay sau khung hình đầu tiên
_UPDATE_CHECK_DELAY_MS = 5000  # hỏi bản mới sau cùng, khi mọi thứ đã yên


class MainWindow(QMainWindow):
    """Cửa sổ chính: thanh bên, thanh tiêu đề và vùng nội dung."""

    breakpoint_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(_START_W, _START_H)
        self.setMinimumSize(_MIN_W, _MIN_H)
        self._startup_watcher: QThread | None = None
        self._status_worker: QThread | None = None
        from autodub_gui.credit_widget import CreditWidget
        self.credit_badge = CreditWidget()
        self.credit_badge.clicked.connect(lambda: self.switch_page(ROW_ACCOUNT))
        self._force_close = False
        self._breakpoint = ""
        self._page_widgets: dict[int, QWidget] = {}

        central = QWidget()
        panel_background(central, tokens.BG_APP)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = self._build_sidebar()
        layout.addWidget(self.sidebar)
        layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(central)

        self._build_status_bar()
        TOASTS.attach(self)

        self.popup = NotificationPopup(self)
        self.popup.activity_opened.connect(self.open_editor)

        REGISTRY.activity_added.connect(self._on_activity)
        self.switch_page(ROW_HOME)
        self.refresh_system_status()
        self._install_shortcuts()
        self._schedule_prewarm()
        # Kiểm tra tiền chuyến bay sau khi cửa sổ đã hiện — không chặn mở app.
        self._preflight_worker: QThread | None = None
        QTimer.singleShot(_PREFLIGHT_DELAY_MS, self._run_preflight)
        # Màn chào lần chạy đầu tiên — hiện trước kiểm tra tiền chuyến bay
        # để người mới thấy bức tranh chung trước khi bị hỏi từng thứ thiếu.
        QTimer.singleShot(_FIRST_RUN_DELAY_MS, self._maybe_first_run)
        # Hỏi GitHub có bản mới không — nền, im lặng khi lỗi mạng.
        self._update_worker: QThread | None = None
        QTimer.singleShot(_UPDATE_CHECK_DELAY_MS, self._check_updates)

    # -- Dựng sẵn các trang lúc máy rảnh -------------------------------
    def _schedule_prewarm(self) -> None:
        """Dựng trước các trang còn lại ngay sau khi cửa sổ hiện lên.

        Trang được dựng lần đầu lúc người dùng bấm vào nó, nên lần bấm đầu
        tiên phải chờ (trang Cài đặt nhiều ô nhất, mất khoảng một giây). Dựng
        sẵn từng trang một trong lúc máy rảnh khiến mọi lần bấm sau đều mở
        tức thì, mà vẫn không làm chậm lúc mở ứng dụng.
        """
        self._prewarm_queue = list(_PREWARM_ORDER)
        QTimer.singleShot(_PREWARM_START_MS, self._prewarm_next)

    def _prewarm_next(self) -> None:
        while self._prewarm_queue:
            row = self._prewarm_queue.pop(0)
            if row in self._page_widgets:
                continue
            try:
                self._ensure_page(row)
            except Exception:  # noqa: BLE001 — dựng sẵn hỏng thì để lúc bấm dựng lại
                self._page_widgets.pop(row, None)
            break
        if self._prewarm_queue:
            QTimer.singleShot(_PREWARM_GAP_MS, self._prewarm_next)

    def _install_shortcuts(self) -> None:
        """Đăng ký phím tắt dùng chung ngay khi cửa sổ được dựng."""
        from autodub_gui.shortcuts import install_global_shortcuts

        install_global_shortcuts(self)

    # -- Dựng giao diện ------------------------------------------------
    def _build_sidebar(self) -> Sidebar:
        from autodub.saas_client import is_configured

        # Chạy thuần trên máy thì không có ví Vox — trang Tài khoản chỉ toàn
        # ô trống, giấu đi thay vì để người dùng bấm vào rồi ngơ ngác.
        rows = [p for p in PAGES
                if p[0] != ROW_ACCOUNT or is_configured()]
        main   = [(p[0], p[1], p[4]) for p in rows if p[5] == "main"]
        tools  = [(p[0], p[1], p[4]) for p in rows if p[5] == "tools"]
        second = [(p[0], p[1], p[4]) for p in rows if p[5] == "second"]
        sidebar = Sidebar(main, tools, second, APP_VERSION)
        sidebar.page_requested.connect(self.switch_page)
        sidebar.settings_requested.connect(lambda: self.switch_page(ROW_SETTINGS))
        sidebar.account_requested.connect(self._open_display_name_setting)
        sidebar.status_card.recheck_requested.connect(self.refresh_system_status)
        return sidebar

    def _open_tool(self, key: str) -> None:
        """Compat: nếu còn code cũ gọi _open_tool, chuyển sang trang tương ứng."""
        mapping = {"voice": ROW_VOICE, "translate": ROW_TRANSLATE,
                   "subtitle": ROW_SUBTITLE}
        row = mapping.get(key, ROW_SETTINGS)
        if row == ROW_SETTINGS:
            self.switch_page(ROW_SETTINGS)
            page = self._page_widgets.get(ROW_SETTINGS)
            if page is not None and hasattr(page, "open_tool"):
                page.open_tool(key)
        else:
            self.switch_page(row)

    def _build_content(self) -> QWidget:
        content = QWidget()
        panel_background(content, tokens.BG_MAIN)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = AppHeader()
        self.header.notifications_clicked.connect(self._show_notifications)
        self.header.help_clicked.connect(lambda: self.switch_page(ROW_HELP))
        # Huy hiệu Vox nằm cố định trên thanh tiêu đề (không phải nút của
        # từng trang) — người dùng phải thấy tài nguyên của mình ở mọi trang.
        self.header.set_persistent(self.credit_badge)
        layout.addWidget(self.header)

        self.pages = QStackedWidget()
        panel_background(self.pages, tokens.BG_MAIN)
        layout.addWidget(self.pages, 1)
        return content

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        bar.setStyleSheet(
            f"QStatusBar {{ background: {tokens.BG_SIDEBAR}; "
            f"color: {tokens.TEXT_SECONDARY}; "
            f"border-top: 1px solid {tokens.BORDER_SUBTLE}; "
            f"font-size: {tokens.FS_LABEL}px; padding: 4px 12px; }}")
        bar.showMessage("Sẵn sàng")

    # -- Điều hướng ----------------------------------------------------
    def _ensure_page(self, row: int) -> QWidget:
        """Dựng trang lần đầu được yêu cầu rồi giữ lại để dùng tiếp."""
        page = self._page_widgets.get(row)
        if page is not None:
            return page
        page = self._create_page(row)
        self._page_widgets[row] = page
        self.pages.addWidget(page)
        return page

    def _create_page(self, row: int) -> QWidget:
        """Nạp mô đun của trang đúng lúc cần, giúp ứng dụng mở nhanh hơn."""
        if row == ROW_HOME:
            from autodub_gui.pages.home_page import HomePage
            page = HomePage(self._fresh_settings, self.pages)
            page.create_requested.connect(self._start_new_project)
            page.projects_requested.connect(lambda: self.switch_page(ROW_PROJECTS))
            page.edit_requested.connect(self.open_editor)
            page.batch_requested.connect(lambda: self.switch_page(ROW_BATCH))
            page.voices_requested.connect(lambda: self._open_tool("voice"))
            page.settings_requested.connect(
                lambda: self.switch_page(ROW_SETTINGS))
        elif row == ROW_NEW:
            from autodub_gui.pages.new_project_page import NewProjectPage
            page = NewProjectPage(self._fresh_settings, self.pages)
            page.settings_needed.connect(lambda _m: self.switch_page(ROW_SETTINGS))
            page.edit_requested.connect(self.open_editor)
            page.home_requested.connect(lambda: self.switch_page(ROW_HOME))
            page.balance_changed.connect(self.credit_badge.set_balance)
        elif row == ROW_PROJECTS:
            from autodub_gui.pages.projects_page import ProjectsPage
            page = ProjectsPage(self._fresh_settings, self.pages)
            page.edit_requested.connect(self.open_editor)
            page.create_requested.connect(lambda: self.switch_page(ROW_NEW))
            page.settings_requested.connect(lambda: self.switch_page(ROW_SETTINGS))
        elif row == ROW_BATCH:
            from autodub_gui.pages.batch_page import BatchPage
            page = BatchPage(self._fresh_settings, self.pages)
            page.settings_needed.connect(lambda _m: self.switch_page(ROW_SETTINGS))
        elif row == ROW_DOWNLOAD:
            from autodub_gui.pages.download_page import DownloadPage
            page = DownloadPage(self.pages)
        elif row == ROW_SETTINGS:
            from autodub_gui.pages.settings_page import SettingsPage
            page = SettingsPage(self.pages)
            page.saved.connect(self._on_settings_saved)
        elif row == ROW_HELP:
            from autodub_gui.pages.help_page import HelpPage
            page = HelpPage(self._fresh_settings, self.pages)
            page.settings_requested.connect(lambda: self.switch_page(ROW_SETTINGS))
        elif row == ROW_EDITOR:
            from autodub_gui.pages.editor_page import EditorPage
            page = EditorPage(self._fresh_settings, self.pages)
            page.settings_needed.connect(lambda _m: self.switch_page(ROW_SETTINGS))
            page.close_requested.connect(lambda: self.switch_page(ROW_PROJECTS))
        elif row == ROW_VOICE:
            from autodub_gui.pages.voice_tool_page import VoiceToolPage
            page = VoiceToolPage(self._fresh_settings, self.pages)
        elif row == ROW_TRANSLATE:
            from autodub_gui.pages.translate_tool_page import TranslateToolPage
            page = TranslateToolPage(self._fresh_settings, self.pages)
        elif row == ROW_SUBTITLE:
            from autodub_gui.pages.subtitle_tool_page import SubtitleToolPage
            page = SubtitleToolPage(self._fresh_settings, self.pages)
        elif row == ROW_QUALITY:
            from autodub_gui.pages.quality_page import QualityPage
            page = QualityPage(self._fresh_settings, self.pages)
        elif row == ROW_ACCOUNT:
            from autodub_gui.pages.account_page import AccountPage
            page = AccountPage(self._fresh_settings, self.pages)
            page.balance_changed.connect(self.credit_badge.set_balance)
        elif row == ROW_EDITOR_LAUNCHER:
            from autodub_gui.pages.editor_launcher_page import EditorLauncherPage
            page = EditorLauncherPage(self._fresh_settings, self.pages)
            page.open_requested.connect(self.open_editor)
        else:
            from autodub_gui.ui.empty import EmptyState
            page = EmptyState("Trang không xác định", f"ROW={row}")
        return page

    def switch_page(self, row: int) -> None:
        """Chuyển sang một trang, có hỏi trước nếu trang cũ còn việc dở."""
        # ROW_EDITOR đặc biệt: nếu chưa có project mở → vào launcher
        if row == ROW_EDITOR:
            editor = self._page_widgets.get(ROW_EDITOR)
            if editor is None or not getattr(editor, "_work_dir", ""):
                row = ROW_EDITOR_LAUNCHER

        current = self.pages.currentWidget()
        if current is not None and self._blocked_by_unsaved(current):
            self.sidebar.select_row(self._row_of(current))
            return
        page = self._ensure_page(row)
        self.pages.setCurrentWidget(page)
        self.sidebar.select_row(row)
        self._apply_header(row)
        if hasattr(page, "on_shown"):
            page.on_shown()
        if self._breakpoint and hasattr(page, "on_breakpoint"):
            page.on_breakpoint(self._breakpoint)

    def _row_of(self, page: QWidget) -> int:
        for row, widget in self._page_widgets.items():
            if widget is page:
                return row
        return ROW_HOME

    def _blocked_by_unsaved(self, page: QWidget) -> bool:
        """True khi người dùng chọn ở lại vì trang còn thay đổi chưa lưu."""
        if not hasattr(page, "has_unsaved_changes"):
            return False
        if not page.has_unsaved_changes():
            return False
        from autodub_gui.ui.modal import confirm_discard
        return not confirm_discard(self, "Trang này")

    def _apply_header(self, row: int) -> None:
        """Đổi tiêu đề, ẩn thanh tiêu đề khi vào Trình chỉnh sửa."""
        if row in (ROW_EDITOR, ROW_EDITOR_LAUNCHER):
            self.header.setVisible(False)
            return
        self.header.setVisible(True)
        _row, _label, title, subtitle, _icon, _group = _PAGE_BY_ROW[row]
        from autodub_gui.shell import display_name
        self.header.set_page(title.format(name=display_name()), subtitle)
        self.header.set_actions(self._header_actions(row))

    def _header_actions(self, row: int) -> list[QWidget]:
        """Các nút riêng của từng trang trên thanh tiêu đề (dựng mới mỗi lần)."""
        if row != ROW_HOME:
            return []
        from autodub_gui.ui.buttons import GhostButton, PrimaryButton

        btn_import = GhostButton("Nhập video")
        btn_import.clicked.connect(self._browse_home_video)
        btn_new = PrimaryButton("+ Tạo dự án mới")
        btn_new.clicked.connect(lambda: self._start_new_project())
        return [btn_import, btn_new]

    def _browse_home_video(self) -> None:
        page = self._page_widgets.get(ROW_HOME)
        if page is not None and hasattr(page, "dropzone"):
            page.dropzone.browse()

    def open_editor(self, work_dir: str) -> None:
        """Mở một dự án trong Trình chỉnh sửa."""
        if not work_dir:
            return
        self.switch_page(ROW_EDITOR)
        editor = self._ensure_page(ROW_EDITOR)
        editor.open_work_dir(work_dir)
        # Cập nhật launcher banner để hiện project đang mở
        launcher = self._page_widgets.get(ROW_EDITOR_LAUNCHER)
        if launcher and hasattr(launcher, "set_current_project"):
            from pathlib import Path
            title = Path(work_dir).stem
            launcher.set_current_project(work_dir, title)

    def _start_new_project(self, file_path: str = "") -> None:
        """Sang trang Tạo dự án, điền sẵn tệp nếu người dùng vừa kéo thả."""
        self.switch_page(ROW_NEW)
        page = self._ensure_page(ROW_NEW)
        if file_path and hasattr(page, "preload_file"):
            page.preload_file(file_path)

    def _open_display_name_setting(self) -> None:
        self.switch_page(ROW_SETTINGS)
        page = self._page_widgets.get(ROW_SETTINGS)
        if page is not None and hasattr(page, "focus_display_name"):
            page.focus_display_name()

    def _on_settings_saved(self) -> None:
        TOASTS.success("Đã lưu cài đặt")
        self.statusBar().showMessage("Đã lưu cài đặt", 4000)
        self.sidebar.refresh_name()
        self._apply_header(self._row_of(self.pages.currentWidget()))
        self.refresh_system_status()

    # -- Trạng thái hệ thống -------------------------------------------
    def refresh_system_status(self) -> None:
        """Đọc lại cấu hình ở luồng nền rồi cập nhật thẻ ở thanh bên."""
        if self._status_worker is not None and self._status_worker.isRunning():
            return
        from autodub_gui.workers import SystemStatusWorker

        worker = SystemStatusWorker(self)
        self.sidebar.status_card.set_checking()
        worker.ready.connect(self._apply_system_status)
        worker.finished.connect(self.sidebar.status_card.set_checked)
        self._status_worker = worker
        worker.start()

    def _apply_system_status(self, result: dict) -> None:
        for key, (text, ok) in result.items():
            self.sidebar.status_card.set_row(key, text, ok)

    # -- Kiểm tra tiền chuyến bay --------------------------------------
    def _maybe_first_run(self) -> None:
        """Hiện wizard cài đặt nếu đây là lần chạy đầu tiên trên máy này."""
        try:
            from autodub_gui.setup_wizard import maybe_show_setup_wizard
            showed = maybe_show_setup_wizard(self)
        except Exception:  # noqa: BLE001 — wizard hỏng không được chặn app
            showed = False

        # Fallback: nếu wizard không hiện thì vẫn kiểm tra first_run cũ
        if not showed:
            try:
                from autodub_gui.first_run import maybe_show_first_run
                maybe_show_first_run(self)
            except Exception:  # noqa: BLE001
                pass

    def _check_updates(self) -> None:
        """Hỏi bản mới ở luồng nền; chỉ báo nhẹ khi thực sự có bản mới."""
        if os.environ.get("AUTODUB_SMOKE") == "1":
            return  # phiên chạy thử tự động không gọi mạng
        from autodub_gui.workers import UpdateCheckWorker

        try:
            repo = Settings.load(override=True).update_repo
        except Exception:  # noqa: BLE001 — cấu hình hỏng thì bỏ qua lượt này
            return
        if not repo:
            return
        worker = UpdateCheckWorker(repo, APP_VERSION, self)
        worker.found.connect(self._on_update_found)
        self._update_worker = worker
        worker.start()

    def _on_update_found(self, info) -> None:
        from autodub_gui.system_open import open_url

        TOASTS.info(
            f"Có bản VoxDub mới v{info.version} (bạn đang dùng v{APP_VERSION}).",
            action_label="Tải bản mới",
            on_action=lambda url=info.url: open_url(url))

    def _run_preflight(self) -> None:
        """Kiểm tra máy ở luồng nền; chỉ báo khi có mục chặn hoặc cảnh báo."""
        if os.environ.get("AUTODUB_SMOKE") == "1":
            return  # hộp thoại modal sẽ chặn phiên chạy thử tự động
        if self._preflight_worker is not None and self._preflight_worker.isRunning():
            return
        from autodub_gui.workers import PreflightWorker

        worker = PreflightWorker(self)
        worker.ready.connect(self._apply_preflight)
        self._preflight_worker = worker
        worker.start()

    def _apply_preflight(self, results: list) -> None:
        from autodub.preflight import blocking_failures, warnings_of

        failures = blocking_failures(results)
        warns = warnings_of(results)
        if not failures and not warns:
            return

        def _block(r) -> str:
            text = f"• {r.title}: {r.message}"
            if r.advice:
                text += f"\n  → {r.advice}"
            return text

        if failures:
            body = "\n\n".join(_block(r) for r in failures + warns)
            ConfirmDialog.show_error(
                self, "Máy chưa đủ điều kiện lồng tiếng",
                "Ứng dụng phát hiện thiếu thành phần bắt buộc. Hãy xử lý các "
                "mục dưới đây rồi mở lại ứng dụng:\n\n" + body)
        else:
            for r in warns:
                TOASTS.warn(f"{r.title}: {r.message}")

    # -- Thông báo -----------------------------------------------------
    def _show_notifications(self) -> None:
        self.popup.show_under(self.header.bell.anchor())

    def _on_activity(self, activity) -> None:
        self.statusBar().showMessage(activity.text, 6000)

    # -- Kích thước cửa sổ ---------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        super().resizeEvent(event)
        width = self.width()
        for threshold, name, sidebar_w in _BREAKPOINTS:
            if width >= threshold:
                self.sidebar.set_width_mode(sidebar_w)
                if name != self._breakpoint:
                    self._breakpoint = name
                    self._notify_breakpoint(name)
                break
        TOASTS.reposition()

    def _notify_breakpoint(self, name: str) -> None:
        self.breakpoint_changed.emit(name)
        for page in self._page_widgets.values():
            if hasattr(page, "on_breakpoint"):
                page.on_breakpoint(name)

    # -- Vòng đời ------------------------------------------------------
    def _built_pages(self) -> list[QWidget]:
        return list(self._page_widgets.values())

    def _fresh_settings(self) -> Settings:
        """Đọc lại tệp cấu hình mỗi lần chạy để thay đổi có hiệu lực ngay."""
        return Settings.load(override=True)

    def closeEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        running = [p for p in self._built_pages()
                   if hasattr(p, "is_running") and p.is_running()]
        if running and not self._force_close:
            confirmed, _ = ConfirmDialog.ask(
                self, "Đang có việc chạy dở",
                "Một tác vụ vẫn đang chạy. Nếu thoát bây giờ, phần đang làm "
                "sẽ dừng lại — nhưng tiến độ đã lưu trên đĩa vẫn còn, lần sau "
                "bạn có thể chạy tiếp từ chỗ dừng. Thoát luôn chứ?",
                kind="warning", confirm_label="Dừng và thoát",
                cancel_label="Ở lại")
            if not confirmed:
                event.ignore()
                return
        for page in running:
            page.shutdown()
        for page in self._built_pages():
            if hasattr(page, "cleanup"):
                page.cleanup()
        # Chờ mọi QThread phụ xong — hủy QThread đang chạy lúc teardown
        # sẽ làm Qt crash cứng (exit code 0xC0000409).
        for worker in (self._startup_watcher, self._status_worker,
                       self._preflight_worker, self._update_worker):
            if worker is not None and worker.isRunning():
                worker.wait(5000)
        self.credit_badge.wait_for_idle()
        event.accept()


class _NavKeyFilter(QObject):
    """Chặn ký tự rác do bộ gõ tiếng Việt sinh ra khi bấm phím mũi tên."""

    _NAV_KEYS = {Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up,
                 Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End,
                 Qt.Key.Key_PageUp, Qt.Key.Key_PageDown}

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — theo quy ước của Qt
        if (event.type() == QEvent.Type.KeyPress
                and event.key() in self._NAV_KEYS and event.text()):
            clean = QKeyEvent(event.type(), event.key(), event.modifiers())
            QApplication.sendEvent(obj, clean)
            return True
        return False


def _smoke_report(window: MainWindow) -> int:
    """Chế độ tự kiểm tra (AUTODUB_SMOKE=1): ghi kết quả chẩn đoán rồi thoát."""
    import json
    import shutil

    from autodub.utils import app_root

    for row in (*(p[0] for p in PAGES), ROW_EDITOR, ROW_EDITOR_LAUNCHER):
        window._ensure_page(row)

    settings = Settings.load(override=True)
    from autodub.speech.tts.voices import catalog

    checks = {
        "gui_constructed": window.pages.count() == PAGE_COUNT,
        "page_count": window.pages.count(),
        "app_root": app_root(),
        "cwd": os.getcwd(),
        "env_path_writable": True,
        "ffmpeg_found": bool(shutil.which("ffmpeg")),
        "ffprobe_found": bool(shutil.which("ffprobe")),
        "vieneu_installed": settings.vieneu_configured(),
        "voice_count": len(catalog(settings)),
        "translate_enabled": settings.translate_enabled,
        "worker_scripts_found": all(os.path.isfile(p) for p in (
            __import__("autodub.speech.tts.vieneu_vi",
                       fromlist=["_WORKER_SCRIPT"])._WORKER_SCRIPT,
            __import__("autodub.media.vocal_separator",
                       fromlist=["_WORKER_SCRIPT"])._WORKER_SCRIPT,
        )),
        "yt_dlp_importable": True,
        "faster_whisper_importable": True,
        "playwright_importable": True,
        "new_modules_importable": True,
        "multimedia_importable": True,
        "video_playable": None,
        "app_fonts_loaded": 0,
    }
    _probe_optional_imports(checks)
    _probe_video_playback(checks, settings)
    _probe_env_file(checks)

    required = ("gui_constructed", "env_path_writable", "yt_dlp_importable",
                "faster_whisper_importable", "worker_scripts_found",
                "new_modules_importable", "multimedia_importable")
    checks["ok"] = all(checks.get(k) for k in required)

    out = os.path.join(app_root(), "smoke_test_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(checks, f, ensure_ascii=False, indent=2)
    return 0 if checks["ok"] else 1


def _probe_optional_imports(checks: dict) -> None:
    """Thử nạp các thư viện tùy chọn, ghi lại thư viện nào thiếu."""
    probes = {
        "yt_dlp_importable": "yt_dlp",
        "faster_whisper_importable": "faster_whisper",
    }
    for key, module in probes.items():
        try:
            __import__(module)
        except Exception:  # noqa: BLE001 — thiếu thư viện tùy chọn là bình thường
            checks[key] = False
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:  # noqa: BLE001
        checks["playwright_importable"] = False
    try:
        from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401
        from PySide6.QtMultimediaWidgets import QGraphicsVideoItem  # noqa: F401
    except Exception as e:  # noqa: BLE001
        checks["multimedia_importable"] = False
        checks["multimedia_error"] = str(e)
    try:
        from autodub.media.timing import apply_soft_timing  # noqa: F401
        from autodub.speech.align import align_segments  # noqa: F401
        from autodub.speech.tts.voices import catalog  # noqa: F401
        from autodub.text.ass_karaoke import build_karaoke_ass  # noqa: F401
        from autodub.text.subtitles import refresh_subtitles  # noqa: F401
        from autodub.saas_client import SaasClient  # noqa: F401
        from autodub.text.translate_review import review_translations  # noqa: F401
        from autodub.text.translate_saas import translate_segments  # noqa: F401
    except Exception as e:  # noqa: BLE001
        checks["new_modules_importable"] = False
        checks["new_modules_error"] = str(e)
    try:
        from autodub_gui.fonts import load_app_fonts
        checks["app_fonts_loaded"] = len(load_app_fonts())
    except Exception:  # noqa: BLE001
        pass


def _probe_video_playback(checks: dict, settings) -> None:
    """Thử mở một video có thật xem bộ giải mã trong bản đóng gói có chạy không.

    Đây là phép thử quan trọng nhất của bản đóng gói: thiếu phần bổ trợ đa
    phương tiện thì Trình chỉnh sửa sẽ không phát được video, mà lỗi đó chỉ
    lộ ra khi người dùng mở dự án.
    """
    import glob

    from PySide6.QtCore import QEventLoop, QTimer, QUrl

    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    except ImportError:
        checks["video_playable"] = False
        return

    pattern = os.path.join(settings.output_dir, "**", "dubbed_video.mp4")
    videos = glob.glob(pattern, recursive=True)
    if not videos:
        checks["video_probe"] = "không có video nào để thử"
        return

    # Giữ tham chiếu QAudioOutput — setAudioOutput KHÔNG giữ hộ; để GC dọn
    # trong khi player còn dùng sẽ crash native (0xC0000409) lúc thoát.
    audio_out = QAudioOutput()
    player = QMediaPlayer()
    player.setAudioOutput(audio_out)
    loop = QEventLoop()
    player.durationChanged.connect(lambda _d: loop.quit())
    player.errorOccurred.connect(lambda *_a: loop.quit())
    QTimer.singleShot(_VIDEO_PROBE_MS, loop.quit)
    player.setSource(QUrl.fromLocalFile(videos[0]))
    loop.exec()

    duration = player.duration()
    checks["video_playable"] = duration > 0
    checks["video_probe"] = f"{os.path.basename(videos[0])}: {duration} ms"

    # Nhả backend đa phương tiện TRƯỚC khi app thoát — không thì tiến trình
    # ffmpeg/WMF của Qt còn sống lúc teardown và exe chết với mã lỗi ảo.
    player.stop()
    player.setSource(QUrl())
    player.setAudioOutput(None)
    del player, audio_out


def _probe_env_file(checks: dict) -> None:
    """Kiểm tra tệp cấu hình có ghi được không."""
    try:
        from autodub_gui.env_store import ENV_PATH, read_env, write_env
        before = read_env()
        write_env({"_SMOKE_TEST": "1"})
        checks["env_path_writable"] = read_env().get("_SMOKE_TEST") == "1"
        write_env({"_SMOKE_TEST": ""})
        checks["env_path"] = ENV_PATH
        checks["env_existed_before"] = bool(before)
    except Exception as e:  # noqa: BLE001
        checks["env_path_writable"] = False
        checks["env_error"] = str(e)


def _install_startup_watch(window: MainWindow) -> QTimer:
    """Hỏi máy chủ lúc khởi động rồi định kỳ nửa tiếng một lần.

    Fail-closed lúc MỞ APP: không liên lạc được máy chủ thì không vào —
    chỉ có Thử lại hoặc Thoát. Nhưng GIỮA PHIÊN thì mất mạng không đá
    người dùng ra (đang xuất video mà rớt wifi không phải lỗi của họ);
    chỉ lệnh rõ ràng từ máy chủ — bảo trì, app quá cũ — mới đóng app.
    """

    class _StartupWatcher(QThread):
        def __init__(self, parent):
            super().__init__(parent)
            self.result = None

        def run(self):
            self.result = check_startup(APP_VERSION)

    def _recheck(initial: bool = False) -> None:
        old = window._startup_watcher
        if old is not None and old.isRunning():
            return
        watcher = _StartupWatcher(window)

        def _done():
            result = watcher.result
            if result is None:
                return
            if not result.allowed:
                if result.offline:
                    if not initial:
                        return  # rớt mạng giữa phiên: lần kiểm tra sau tự xử
                    box = QMessageBox(window)
                    box.setIcon(QMessageBox.Icon.Critical)
                    box.setWindowTitle(APP_NAME)
                    box.setText(result.message)
                    retry = box.addButton("Thử lại", QMessageBox.ButtonRole.AcceptRole)
                    box.addButton("Thoát", QMessageBox.ButtonRole.RejectRole)
                    box.exec()
                    if box.clickedButton() is retry:
                        _recheck(initial=True)
                        return
                else:
                    QMessageBox.critical(window, APP_NAME, result.message)
                window._force_close = True
                window.close()
                return
            config = result.config or {}
            window.credit_badge.set_credit_enabled(
                bool(config.get("creditEnabled", True)))
            device = result.device or {}
            if device:
                window.credit_badge.set_balance(int(device.get("balance", 0)))

        watcher.finished.connect(_done)
        window._startup_watcher = watcher
        watcher.start()

    QTimer.singleShot(0, lambda: _recheck(initial=True))
    timer = QTimer(window)
    timer.setInterval(_STARTUP_RECHECK_MS)
    timer.timeout.connect(_recheck)
    timer.start()
    return timer


def main() -> int:
    """Điểm khởi động ứng dụng."""
    # Windows nhóm cửa sổ trên taskbar theo AppUserModelID — không đặt thì
    # app bị nhận là "python.exe"/host chung và taskbar hiện sai logo.
    # Phải gọi TRƯỚC khi tạo QApplication (trước khi có cửa sổ đầu tiên).
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "VoxDub.Studio")
        except (AttributeError, OSError):
            pass  # Windows quá cũ — taskbar dùng icon mặc định, không sao
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    nav_filter = _NavKeyFilter()
    app.installEventFilter(nav_filter)

    from autodub.utils import bundled_file
    icon_path = bundled_file("logo.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        app.setWindowIcon(QIcon(icons.brand_logo(64)))

    from autodub_gui.fonts import load_app_fonts
    load_app_fonts()

    # Ghi log ra tệp + lưới an toàn crash — trước khi dựng cửa sổ để lỗi
    # sớm nhất cũng được ghi lại.
    from autodub.utils import init_file_logging
    init_file_logging()
    from autodub_gui.crash import install_crash_handler
    install_crash_handler()

    # Tạo .env từ .env.example nếu chưa có — tránh Settings.load() dùng toàn
    # giá trị mặc định mà không ghi lại được gì cho lần sau.
    from autodub.utils import app_root as _app_root
    _env_path = os.path.join(_app_root(), ".env")
    _env_example = os.path.join(_app_root(), ".env.example")
    if not os.path.isfile(_env_path) and os.path.isfile(_env_example):
        import shutil as _shutil
        try:
            _shutil.copy(_env_example, _env_path)
        except OSError:
            pass

    # Nếu người dùng (hoặc wizard) đã tải FFmpeg về bin/ thì thêm ngay vào PATH
    # để shutil.which("ffmpeg") và preflight tìm thấy ngay trong cùng phiên.
    _local_bin = os.path.join(_app_root(), "bin")
    if os.path.isdir(_local_bin):
        _cur_path = os.environ.get("PATH", "")
        if _local_bin.lower() not in _cur_path.lower():
            os.environ["PATH"] = _local_bin + os.pathsep + _cur_path

    settings = Settings.load()
    window = MainWindow()      # phím tắt được cửa sổ tự đăng ký khi dựng
    window.show()

    # Tải + enroll voice library nếu chưa có (chỉ khi VieNeu đã cài).
    # Chạy SAU window.show() để app loop đã khởi động, dialog mới hiển thị đúng.
    if os.environ.get("AUTODUB_SMOKE") != "1":
        from autodub_gui.voice_setup_dialog import VoiceSetupDialog
        VoiceSetupDialog.ensure_voices(settings, window)

    startup_timer = _install_startup_watch(window)

    if os.environ.get("AUTODUB_SMOKE") == "1":
        result = {"code": 1}

        def _run_smoke() -> None:
            try:
                result["code"] = _smoke_report(window)
            finally:
                startup_timer.stop()
                # app.quit() không đi qua closeEvent — tự chờ luồng kiểm tra
                # máy chủ ở đây, không thì teardown crash (0xC0000409).
                watcher = window._startup_watcher
                if watcher is not None and watcher.isRunning():
                    watcher.wait(10000)
                window.credit_badge.wait_for_idle(10000)
                app.quit()

        QTimer.singleShot(_SMOKE_DELAY_MS, _run_smoke)
        app.exec()
        return result["code"]

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
