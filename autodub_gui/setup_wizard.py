"""Wizard cài đặt lần đầu — thay thế FirstRunDialog tĩnh.

Tự động cài FFmpeg, VieNeu TTS và Whisper ASR với progress bar + live log.
Hiện đúng một lần cho mỗi máy (kiểm tra marker file, giống first_run.py cũ).

Giao diện:  Stepper 5 bước → QStackedWidget 6 trang → footer Back/Skip/Next
"""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QProgressBar, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.status_text import STATUS_ERROR, STATUS_OK
from autodub_gui.ui.buttons import GhostButton, PrimaryButton, SecondaryButton
from autodub_gui.ui.stepper import Stepper

# --------------------------------------------------------------------------- #
# Hằng
# --------------------------------------------------------------------------- #

_MIN_W, _MIN_H = 620, 500
_LOG_H = 140

# Chỉ số trang trong QStackedWidget
_PAGE_WELCOME = 0
_PAGE_FFMPEG  = 1
_PAGE_VIENEU  = 2
_PAGE_WHISPER = 3
_PAGE_APIKEY  = 4
_PAGE_DONE    = 5

# Nhãn bước trên Stepper (không kể trang Welcome & Done — stepper chỉ 4 bước)
_STEP_LABELS = ["FFmpeg", "VieNeu TTS", "Whisper ASR", "Kích hoạt"]

_AUTO_NEXT_MS = 900   # tự chuyển trang sau khi hoàn thành (ms)


# --------------------------------------------------------------------------- #
# Helpers kiểm tra đã cài chưa
# --------------------------------------------------------------------------- #

def _ffmpeg_ready() -> bool:
    from autodub.utils import app_root
    local_bin = os.path.join(app_root(), "bin", "ffmpeg.exe")
    return bool(shutil.which("ffmpeg")) or os.path.isfile(local_bin)


def _vieneu_ready() -> bool:
    try:
        from autodub.config import Settings
        return Settings.load(override=True).vieneu_configured()
    except Exception:
        return False


def _whisper_ready() -> bool:
    try:
        from autodub.utils import app_root
        marker = os.path.join(app_root(), "models", "whisper", "installed_ok.json")
        return os.path.isfile(marker)
    except Exception:
        return False


def _all_ready() -> bool:
    return _ffmpeg_ready() and _vieneu_ready() and _whisper_ready()


# --------------------------------------------------------------------------- #
# Marker file (giống first_run.py nhưng check kỹ hơn)
# --------------------------------------------------------------------------- #

def _marker_path() -> str:
    from autodub_gui.pages.new_project_page import cache_dir
    return os.path.join(cache_dir(), "setup_wizard_done")


def _is_setup_needed() -> bool:
    """True nếu chưa chạy wizard LẦN NÀO, hoặc tất cả components đã sẵn sàng
    (trường hợp người dùng install thủ công trước khi mở app)."""
    if os.path.isfile(_marker_path()):
        return False          # wizard đã chạy xong
    return True               # chưa chạy → cần wizard


def _mark_done() -> None:
    try:
        with open(_marker_path(), "w", encoding="utf-8") as f:
            f.write("done\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Widget trang setup chung (FFmpeg / VieNeu / Whisper)
# --------------------------------------------------------------------------- #

class _InstallPage(QWidget):
    """Trang cài đặt một component: title, mô tả, progressbar, live log."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SP_6, tokens.SP_5,
                                  tokens.SP_6, tokens.SP_4)
        layout.setSpacing(tokens.SP_3)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_SECTION}px; "
            f"font-weight: 700; background: transparent;")
        layout.addWidget(lbl_title)

        if subtitle:
            lbl_sub = QLabel(subtitle)
            lbl_sub.setWordWrap(True)
            lbl_sub.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px; "
                f"background: transparent;")
            layout.addWidget(lbl_sub)

        self._status_label = QLabel("Đang chuẩn bị…")
        self._status_label.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        layout.addWidget(self._status_label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(True)
        self._bar.setFixedHeight(10)
        self._bar.setStyleSheet(
            f"QProgressBar {{ background: {tokens.BG_PANEL}; border: none; "
            f"border-radius: 5px; }}"
            f"QProgressBar::chunk {{ background: {tokens.PRIMARY}; "
            f"border-radius: 5px; }}")
        layout.addWidget(self._bar)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(_LOG_H)
        self._log.setMinimumHeight(_LOG_H)
        self._log.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Fixed)
        self._log.setStyleSheet(
            f"QPlainTextEdit {{ background: {tokens.BG_INPUT}; "
            f"color: {tokens.TEXT_SECONDARY}; "
            f"font-family: {tokens.FONT_MONO}; "
            f"font-size: {tokens.FS_META}px; "
            f"border: 1px solid {tokens.BORDER_SUBTLE}; "
            f"border-radius: {tokens.RADIUS_MD}px; "
            f"padding: 6px; }}")
        layout.addWidget(self._log)

        self._retry_btn = SecondaryButton("Thử lại")
        self._retry_btn.setVisible(False)
        layout.addWidget(self._retry_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    # -- Giao diện cập nhật từ worker ---
    def set_progress(self, pct: int) -> None:
        self._bar.setValue(pct)

    def append_log(self, line: str) -> None:
        self._log.appendPlainText(line)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_status(self, text: str, color: str = tokens.TEXT_MUTED) -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            f"color: {color}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")

    def show_retry(self, show: bool) -> None:
        self._retry_btn.setVisible(show)

    @property
    def retry_btn(self):
        return self._retry_btn

    def mark_done(self) -> None:
        self.set_progress(100)
        self.set_status(f"{STATUS_OK}  Hoàn tất!", tokens.SUCCESS)
        self.show_retry(False)

    def mark_error(self, msg: str) -> None:
        self.set_status(f"{STATUS_ERROR}  Lỗi: {msg[:120]}", tokens.DANGER)
        self.show_retry(True)

    def mark_skipped(self) -> None:
        self.set_progress(100)
        self.set_status(f"{STATUS_OK}  Đã cài sẵn — bỏ qua.", tokens.SUCCESS)


# --------------------------------------------------------------------------- #
# Trang Welcome
# --------------------------------------------------------------------------- #

class _WelcomePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SP_6, tokens.SP_6,
                                  tokens.SP_6, tokens.SP_4)
        layout.setSpacing(tokens.SP_4)

        # Icon + tiêu đề
        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.brand_logo(48).pixmap(48, 48))
        layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("Chào mừng đến VoxDub Studio!")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 22px; "
            f"font-weight: 700; background: transparent;")
        layout.addWidget(title)

        tagline = QLabel(
            "Ứng dụng tự động lồng tiếng video sang tiếng Việt\n"
            "Tách nhạc nền · Nhận dạng giọng nói · Dịch · Đọc bằng giọng Việt tự nhiên")
        tagline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        tagline.setWordWrap(True)
        tagline.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px; "
            f"background: transparent;")
        layout.addWidget(tagline)

        layout.addSpacing(tokens.SP_2)

        # Danh sách những gì sẽ được cài
        info_card = QWidget()
        info_card.setStyleSheet(
            f"background: {tokens.BG_PANEL}; border-radius: {tokens.RADIUS_LG}px;")
        card_layout = QVBoxLayout(info_card)
        card_layout.setContentsMargins(tokens.SP_5, tokens.SP_4,
                                       tokens.SP_5, tokens.SP_4)
        card_layout.setSpacing(tokens.SP_2)

        card_title = QLabel("Wizard sẽ tự động cài 3 thành phần:")
        card_title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 600; background: transparent;")
        card_layout.addWidget(card_title)

        steps = [
            ("FFmpeg",        "Bộ xử lý video/audio",              "~100 MB"),
            ("VieNeu TTS",    "Bộ giọng đọc tiếng Việt (CPU)",     "~300 MB"),
            ("Whisper ASR",   "Nhận dạng giọng nói (AI model)",    "~1.5 GB"),
        ]
        for name, desc, size in steps:
            row = QHBoxLayout()
            bullet = QLabel("-")
            bullet.setFixedWidth(14)
            bullet.setStyleSheet(
                f"color: {tokens.PRIMARY}; font-size: {tokens.FS_BODY}px; "
                f"background: transparent;")
            row.addWidget(bullet)
            lbl = QLabel(f"<b>{name}</b> — {desc}")
            lbl.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px; "
                f"background: transparent;")
            row.addWidget(lbl, 1)
            size_lbl = QLabel(size)
            size_lbl.setStyleSheet(
                f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
                f"background: transparent;")
            row.addWidget(size_lbl)
            card_layout.addLayout(row)

        note = QLabel("Ước tính: 15-20 phút tuỳ tốc độ mạng")
        note.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        card_layout.addSpacing(tokens.SP_1)
        card_layout.addWidget(note)

        layout.addWidget(info_card)
        layout.addStretch()


# --------------------------------------------------------------------------- #
# Trang Kích hoạt
# --------------------------------------------------------------------------- #

class _ApiKeyPage(QWidget):
    """Nhập mã kích hoạt (không bắt buộc — máy mới đã có Vox dùng thử)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SP_6, tokens.SP_5,
                                  tokens.SP_6, tokens.SP_4)
        layout.setSpacing(tokens.SP_3)

        title = QLabel("Kích hoạt VoxDub")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_SECTION}px; "
            f"font-weight: 700; background: transparent;")
        layout.addWidget(title)

        sub = QLabel(
            "Máy này đã được tặng Vox dùng thử, bạn dùng ngay được. Nếu đã "
            "mua thêm và có mã kích hoạt thì dán vào đây — hoặc bỏ qua rồi "
            "nhập sau ở trang Tài khoản.")
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px; "
            f"background: transparent;")
        layout.addWidget(sub)

        card = QWidget()
        card.setStyleSheet(
            f"background: {tokens.BG_PANEL}; "
            f"border-radius: {tokens.RADIUS_LG}px;")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(tokens.SP_5, tokens.SP_4,
                                       tokens.SP_5, tokens.SP_4)
        card_layout.setSpacing(tokens.SP_2)

        card_title = QLabel("Mã kích hoạt")
        card_title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 600; background: transparent;")
        card_layout.addWidget(card_title)

        desc = QLabel(
            "Mã có trong email đơn hàng, dạng VOX-XXXX-XXXX-XXXX.\n"
            "Mỗi mã chỉ kích hoạt được một lần trên một máy.")
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        card_layout.addWidget(desc)

        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("VOX-XXXX-XXXX-XXXX")
        self._key_input.setStyleSheet(
            f"QLineEdit {{ background: {tokens.BG_INPUT}; "
            f"color: {tokens.TEXT_PRIMARY}; "
            f"border: 1px solid {tokens.BORDER_DEFAULT}; "
            f"border-radius: {tokens.RADIUS_MD}px; "
            f"padding: 6px 10px; font-size: {tokens.FS_BODY}px; }}"
            f"QLineEdit:focus {{ border-color: {tokens.BORDER_ACTIVE}; }}")
        card_layout.addWidget(self._key_input)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        card_layout.addWidget(self._status)

        layout.addWidget(card)
        layout.addStretch()

    def get_key(self) -> str:
        return self._key_input.text().strip()

    def set_status(self, text: str) -> None:
        self._status.setText(text)


# --------------------------------------------------------------------------- #
# Trang Done
# --------------------------------------------------------------------------- #

class _DonePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: dict[str, bool] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SP_6, tokens.SP_6,
                                  tokens.SP_6, tokens.SP_4)
        layout.setSpacing(tokens.SP_4)
        layout.addStretch()

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.check(tokens.SUCCESS).pixmap(56, 56))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(icon_lbl)

        title = QLabel("Cài đặt hoàn tất!")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet(
            f"color: {tokens.SUCCESS}; font-size: 22px; "
            f"font-weight: 700; background: transparent;")
        layout.addWidget(title)

        self._summary_label = QLabel()
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px; "
            f"background: transparent;")
        layout.addWidget(self._summary_label)

        layout.addStretch()

    def set_results(self, ffmpeg: bool, vieneu: bool, whisper: bool,
                    api_saved: bool) -> None:
        parts = []
        for name, ok in [("FFmpeg", ffmpeg), ("VieNeu TTS", vieneu),
                          ("Whisper ASR", whisper)]:
            parts.append(f"{STATUS_OK if ok else STATUS_ERROR}  {name}")
        if api_saved:
            parts.append(f"{STATUS_OK}  Đã kích hoạt mã")
        self._summary_label.setText("   ·   ".join(parts))


# --------------------------------------------------------------------------- #
# SetupWizard — dialog chính
# --------------------------------------------------------------------------- #

class SetupWizard(QDialog):
    """Wizard 6 trang cài đặt lần đầu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thiết lập VoxDub Studio")
        self.setModal(True)
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_MIN_W, _MIN_H)

        self._worker = None           # worker đang chạy
        self._ffmpeg_ok  = False
        self._vieneu_ok  = False
        self._whisper_ok = False
        self._api_saved  = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Stepper ở trên (chỉ hiện ở trang 1–4)
        self._stepper_wrapper = QWidget()
        sw_layout = QVBoxLayout(self._stepper_wrapper)
        sw_layout.setContentsMargins(tokens.SP_6, tokens.SP_4,
                                     tokens.SP_6, 0)
        self._stepper = Stepper(_STEP_LABELS)
        self._stepper.set_live_mode(True)
        self._stepper.set_live_progress(0)
        sw_layout.addWidget(self._stepper)
        root.addWidget(self._stepper_wrapper)

        # Trang nội dung
        self._stack = QStackedWidget()
        self._page_welcome = _WelcomePage()
        self._page_ffmpeg  = _InstallPage(
            "1 / 3 · Cài FFmpeg",
            "Bộ xử lý video/audio bắt buộc. Đang tải bản đầy đủ (~100 MB) "
            "về thư mục bin/ trong ứng dụng.")
        self._page_vieneu  = _InstallPage(
            "2 / 3 · Cài VieNeu TTS",
            "Bộ giọng đọc tiếng Việt chạy hoàn toàn trên máy bạn (~300 MB).")
        self._page_whisper = _InstallPage(
            "3 / 3 · Cài Whisper ASR",
            "Model nhận dạng giọng nói AI (~1.5 GB). "
            "Bước này lâu nhất — có thể mất 5–15 phút tuỳ tốc độ mạng.")
        self._page_apikey  = _ApiKeyPage()
        self._page_done    = _DonePage()

        for page in (self._page_welcome, self._page_ffmpeg, self._page_vieneu,
                     self._page_whisper, self._page_apikey, self._page_done):
            self._stack.addWidget(page)
        root.addWidget(self._stack, 1)

        # Dải phân cách + footer
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {tokens.BORDER_SUBTLE};")
        root.addWidget(sep)

        footer = QHBoxLayout()
        footer.setContentsMargins(tokens.SP_6, tokens.SP_3,
                                  tokens.SP_6, tokens.SP_4)
        footer.setSpacing(tokens.SP_2)

        self._btn_back = GhostButton("← Quay lại")
        self._btn_back.setVisible(False)
        self._btn_back.clicked.connect(self._go_back)
        footer.addWidget(self._btn_back)

        footer.addStretch()

        self._btn_skip = SecondaryButton("Bỏ qua bước này")
        self._btn_skip.setVisible(False)
        self._btn_skip.clicked.connect(self._skip_step)
        footer.addWidget(self._btn_skip)

        self._btn_next = PrimaryButton("Bắt đầu cài đặt →")
        self._btn_next.setDefault(True)
        self._btn_next.clicked.connect(self._next_or_start)
        footer.addWidget(self._btn_next)

        root.addLayout(footer)

        # Nối retry buttons
        self._page_ffmpeg.retry_btn.clicked.connect(
            lambda: self._start_worker(_PAGE_FFMPEG))
        self._page_vieneu.retry_btn.clicked.connect(
            lambda: self._start_worker(_PAGE_VIENEU))
        self._page_whisper.retry_btn.clicked.connect(
            lambda: self._start_worker(_PAGE_WHISPER))

        self._goto(_PAGE_WELCOME)

    # -- Điều hướng -------------------------------------------------------

    def _current(self) -> int:
        return self._stack.currentIndex()

    def _goto(self, page_idx: int) -> None:
        self._stack.setCurrentIndex(page_idx)
        is_welcome = page_idx == _PAGE_WELCOME
        is_done    = page_idx == _PAGE_DONE
        is_apikey  = page_idx == _PAGE_APIKEY

        self._stepper_wrapper.setVisible(
            not is_welcome and not is_done)

        if not is_welcome and not is_done:
            # stepper step index: page_idx - 1 (pages 1-4 → steps 0-3)
            self._stepper.set_live_progress(page_idx - 1)

        self._btn_back.setVisible(is_apikey)

        if is_welcome:
            self._btn_next.setText("Bắt đầu cài đặt →")
            self._btn_skip.setVisible(False)
        elif is_done:
            self._btn_next.setText("Bắt đầu dùng VoxDub Studio")
            self._btn_skip.setVisible(False)
            self._stepper.mark_all_done()
        elif page_idx in (_PAGE_FFMPEG, _PAGE_VIENEU, _PAGE_WHISPER):
            self._btn_next.setText("Tiếp theo →")
            self._btn_next.setEnabled(False)
            self._btn_skip.setVisible(True)
        elif is_apikey:
            self._btn_next.setText("Lưu và tiếp theo →")
            self._btn_next.setEnabled(True)
            self._btn_skip.setVisible(True)
            self._btn_skip.setText("Bỏ qua")

    def _next_or_start(self) -> None:
        cur = self._current()
        if cur == _PAGE_WELCOME:
            self._goto(_PAGE_FFMPEG)
            self._start_worker(_PAGE_FFMPEG)
        elif cur == _PAGE_APIKEY:
            self._save_api_key()
            self._finish()
        elif cur == _PAGE_DONE:
            self.accept()
        else:
            # Nút next enable chỉ sau khi worker xong
            self._advance()

    def _skip_step(self) -> None:
        cur = self._current()
        if self._worker and self._worker.isRunning():
            return   # không skip khi đang chạy
        if cur == _PAGE_APIKEY:
            self._finish()
        else:
            self._advance()

    def _go_back(self) -> None:
        cur = self._current()
        if cur > _PAGE_WELCOME:
            self._goto(cur - 1)

    def _advance(self) -> None:
        cur = self._current()
        next_page = cur + 1
        if next_page >= _PAGE_DONE:
            self._finish()
            return
        self._goto(next_page)
        if next_page in (_PAGE_FFMPEG, _PAGE_VIENEU, _PAGE_WHISPER):
            self._start_worker(next_page)

    def _finish(self) -> None:
        self._page_done.set_results(
            self._ffmpeg_ok, self._vieneu_ok,
            self._whisper_ok, self._api_saved)
        self._goto(_PAGE_DONE)
        self._btn_next.setEnabled(True)

    # -- Chạy worker -------------------------------------------------------

    def _start_worker(self, page_idx: int) -> None:
        from autodub_gui.workers_setup import (
            FFmpegDownloadWorker, SetupScriptWorker,
        )

        # Kiểm tra đã cài chưa — nếu rồi thì skip ngay
        if page_idx == _PAGE_FFMPEG and _ffmpeg_ready():
            self._page_ffmpeg.mark_skipped()
            self._ffmpeg_ok = True
            self._btn_next.setEnabled(True)
            return
        if page_idx == _PAGE_VIENEU and _vieneu_ready():
            self._page_vieneu.mark_skipped()
            self._vieneu_ok = True
            self._btn_next.setEnabled(True)
            return
        if page_idx == _PAGE_WHISPER and _whisper_ready():
            self._page_whisper.mark_skipped()
            self._whisper_ok = True
            self._btn_next.setEnabled(True)
            return

        page: _InstallPage = {
            _PAGE_FFMPEG:  self._page_ffmpeg,
            _PAGE_VIENEU:  self._page_vieneu,
            _PAGE_WHISPER: self._page_whisper,
        }[page_idx]

        page.set_status("Đang chạy…")
        page.show_retry(False)
        page.set_progress(0)
        self._btn_next.setEnabled(False)
        self._btn_skip.setVisible(True)

        if page_idx == _PAGE_FFMPEG:
            worker = FFmpegDownloadWorker(self)
        elif page_idx == _PAGE_VIENEU:
            worker = SetupScriptWorker("scripts/setup_vieneu.py", self)
        else:
            worker = SetupScriptWorker("scripts/setup_whisper.py", self)

        worker.progress.connect(page.set_progress)
        worker.log.connect(page.append_log)
        worker.finished_ok.connect(lambda idx=page_idx: self._on_done(idx))
        worker.failed.connect(lambda msg, idx=page_idx: self._on_failed(idx, msg))

        self._worker = worker
        worker.start()

    def _on_done(self, page_idx: int) -> None:
        page: _InstallPage = {
            _PAGE_FFMPEG:  self._page_ffmpeg,
            _PAGE_VIENEU:  self._page_vieneu,
            _PAGE_WHISPER: self._page_whisper,
        }[page_idx]
        page.mark_done()
        if page_idx == _PAGE_FFMPEG:
            self._ffmpeg_ok = True
        elif page_idx == _PAGE_VIENEU:
            self._vieneu_ok = True
        else:
            self._whisper_ok = True

        self._btn_next.setEnabled(True)
        # Tự động chuyển trang sau _AUTO_NEXT_MS
        QTimer.singleShot(_AUTO_NEXT_MS, self._advance)

    def _on_failed(self, page_idx: int, msg: str) -> None:
        page: _InstallPage = {
            _PAGE_FFMPEG:  self._page_ffmpeg,
            _PAGE_VIENEU:  self._page_vieneu,
            _PAGE_WHISPER: self._page_whisper,
        }[page_idx]
        page.mark_error(msg)
        self._btn_next.setEnabled(True)   # cho phép skip qua

    # -- Lưu API key -------------------------------------------------------

    def _save_api_key(self) -> None:
        """Kích hoạt mã người dùng vừa nhập (nếu có).

        Gọi đồng bộ trên luồng giao diện: đây là bước cuối của trình cài đặt,
        người dùng đang chờ sẵn và một lượt gọi mất vài giây. Hỏng thì bỏ
        qua — họ nhập lại được ở trang Tài khoản bất cứ lúc nào.
        """
        code = self._page_apikey.get_key()
        if not code:
            return
        from autodub.saas_client import SaasError, get_client

        try:
            result = get_client().activate_key(code)
        except SaasError as e:
            self._page_apikey.set_status(str(e))
            return
        except Exception:  # noqa: BLE001
            return
        self._api_saved = True
        vox = int(result.get("vox", 0))
        self._page_apikey.set_status(f"Đã cộng {vox:,} Vox.".replace(",", "."))


# --------------------------------------------------------------------------- #
# Hàm công khai dùng từ app.py
# --------------------------------------------------------------------------- #

def maybe_show_setup_wizard(window) -> bool:
    """Hiện wizard nếu cần. Trả về True nếu đã hiện.

    Bỏ qua hoàn toàn nếu:
    - Biến môi trường AUTODUB_SMOKE=1 (phiên test tự động)
    - Marker file đã tồn tại (đã chạy xong lần trước)
    - Tất cả components đều sẵn sàng (user tự cài thủ công)
    """
    if os.environ.get("AUTODUB_SMOKE") == "1":
        return False
    if not _is_setup_needed():
        return False
    if _all_ready():
        # Tất cả đã sẵn sàng từ trước — đánh dấu done rồi bỏ qua wizard
        _mark_done()
        return False

    wizard = SetupWizard(window)
    wizard.exec()
    _mark_done()
    return True




