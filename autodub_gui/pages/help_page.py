"""Trang Trợ giúp: hướng dẫn nhanh, cách cài thêm, khắc phục sự cố.

Nội dung ở đây được sinh từ chính dữ liệu của ứng dụng: bảng phím tắt lấy từ
`shortcuts.py`, mục khắc phục sự cố lấy từ bảng lỗi thân thiện, tình trạng cài
đặt đọc trực tiếp từ máy. Nhờ vậy trang này không bao giờ nói sai so với thực
tế của ứng dụng.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from autodub_gui import tokens
from autodub_gui.ui.style import clear_background
from autodub_gui.dub_constants import FRIENDLY_ERRORS, MODEL_SIZES
from autodub_gui.pages import BasePage
from autodub_gui.shortcuts import ALL_SHORTCUTS
from autodub_gui.system_open import open_file, open_folder
from autodub_gui.ui.buttons import GhostButton
from autodub_gui.ui.collapsible import CollapsibleSection
from autodub_gui.ui.labels import ElidedLabel
from autodub_gui.ui.toast import TOASTS

_PAGE_MARGIN = 28
_LABEL_W = 190

QUICK_START = (
    ("Bước 1 — Đưa video vào",
     "Kéo thả tệp video vào Trang chủ, hoặc dán liên kết ở trang Tạo dự án. "
     "Ứng dụng nhận MP4, MKV, MOV, AVI và WebM."),
    ("Bước 2 — Chọn giọng và phụ đề",
     "Đi qua sáu bước ở trang Tạo dự án. Mọi mục đều đã có sẵn giá trị hợp lý, "
     "bạn chỉ cần đổi thứ mình quan tâm."),
    ("Bước 3 — Bắt đầu và chờ",
     "Bấm Bắt đầu lồng tiếng. Bạn có thể tắt máy giữa chừng: tiến độ được lưu "
     "trên đĩa, lần sau chọn Tiếp tục dang dở là chạy tiếp từ chỗ dừng."),
    ("Bước 4 — Xem lại và chỉnh",
     "Mở dự án trong Trình chỉnh sửa để sửa từng câu, nghe lại, rồi bấm Xuất "
     "video để ghép bản cuối cùng."),
)

# (tên, mô tả, dung lượng, lệnh cài, hàm kiểm tra tình trạng)
INSTALL_ITEMS = (
    ("Bộ giọng đọc VieNeu",
     "Giọng Việt chạy trên bộ xử lý trung tâm nên nhanh và không cần card "
     "đồ họa. Đây là bộ giọng duy nhất của ứng dụng.",
     MODEL_SIZES["vieneu"], "py scripts/setup_vieneu.py", "vieneu_configured"),
    ("Thư viện giọng mẫu",
     "Nạp thêm các giọng trong thư mục voices cạnh ứng dụng. Chạy một lần, "
     "sau đó chọn giọng theo tên trong Cài đặt.",
     "không cần tải", "py scripts/setup_voices.py", "voices_enrolled"),
    ("Paraformer", "Nghe tiếng Trung chính xác hơn Whisper, chạy trên CPU.",
     MODEL_SIZES["paraformer"], "py scripts/setup_paraformer.py",
     "paraformer_configured"),
)

EXTRA_PROBLEMS = (
    ("Máy chưa có FFmpeg",
     "FFmpeg là công cụ ghép hình và tiếng. Hãy tải bản đầy đủ, giải nén rồi "
     "thêm thư mục bin vào đường dẫn hệ thống, sau đó mở lại ứng dụng."),
    ("Card đồ họa không đủ bộ nhớ",
     "Đóng bớt trò chơi hoặc trình duyệt đang mở nhiều video. Hoặc đổi Nhạc "
     "nền sang Giảm nhỏ tiếng gốc cho nhẹ hơn, rồi chạy tiếp thư mục dự án "
     "đang dở."),
    ("Video không phát được trong Trình chỉnh sửa",
     "Máy chưa có bộ giải mã cho định dạng đó. Bạn vẫn mở được bằng trình "
     "phát ngoài, và việc xuất video không bị ảnh hưởng."),
    ("Phụ đề hiện thành ô vuông",
     "Phông chữ đang chọn không có dấu tiếng Việt. Vào Cài đặt, thẻ Phụ đề, "
     "chọn một phông không có ghi chú cảnh báo."),
)


def _body_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_LABEL}px; "
        f"background: transparent;")
    return label


class HelpPage(BasePage):
    """Mọi thứ người dùng cần biết để tự xử lý."""

    settings_requested = Signal()

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._build()

    def _build(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        holder = QWidget()
        clear_background(holder)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(_PAGE_MARGIN, tokens.SP_2,
                                  _PAGE_MARGIN, tokens.SP_5)
        layout.setSpacing(tokens.SP_4)

        layout.addWidget(self._build_quick_start())
        layout.addWidget(self._build_install())
        layout.addWidget(self._build_problems())
        layout.addWidget(self._build_shortcuts())
        layout.addWidget(self._build_about())
        layout.addStretch()

        scroll.setWidget(holder)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _build_quick_start(self) -> QWidget:
        section = CollapsibleSection("Bắt đầu nhanh", expanded=True)
        for title, body in QUICK_START:
            heading = QLabel(title)
            heading.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_LABEL}px; "
                f"font-weight: 600; background: transparent;")
            section.add_widget(heading)
            section.add_widget(_body_label(body))
        return section

    def _build_install(self) -> QWidget:
        section = CollapsibleSection("Cài thêm tính năng", expanded=True)
        section.add_widget(_body_label(
            "Ứng dụng chạy được ngay mà không cần cài gì thêm. Những phần dưới "
            "đây là tùy chọn, cài rồi thì chất lượng tốt hơn."))
        settings = self._safe_settings()
        for name, description, size, command, checker in INSTALL_ITEMS:
            section.add_layout(
                self._install_row(settings, name, description, size,
                                  command, checker))
        return section

    def _install_row(self, settings, name: str, description: str, size: str,
                     command: str, checker: str) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(tokens.SP_1)
        head = QHBoxLayout()
        head.setSpacing(tokens.SP_2)
        title = QLabel(name)
        title.setMinimumWidth(_LABEL_W)
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 600; background: transparent;")
        ready = self._is_ready(settings, checker)
        state = QLabel("đã sẵn sàng" if ready else "chưa cài")
        state.setStyleSheet(
            f"color: {tokens.SUCCESS if ready else tokens.WARNING}; "
            f"font-size: {tokens.FS_META}px; background: transparent;")
        size_label = QLabel(size)
        size_label.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        head.addWidget(title)
        head.addWidget(state)
        head.addWidget(size_label)
        head.addStretch()
        if command:
            copy_button = GhostButton("Sao chép lệnh cài")
            copy_button.setToolTip(command)
            copy_button.clicked.connect(
                lambda _c=False, cmd=command: self._copy(cmd))
            head.addWidget(copy_button)
        column.addLayout(head)
        column.addWidget(_body_label(description))
        return column

    def _build_problems(self) -> QWidget:
        section = CollapsibleSection("Khắc phục sự cố", expanded=False)
        seen: set[str] = set()
        # Dựng từ chính bảng lỗi mà ứng dụng dùng, không chép lại.
        for _needle, title, advice in FRIENDLY_ERRORS:
            if title in seen:
                continue
            seen.add(title)
            section.add_widget(self._problem_block(title, advice))
        for title, advice in EXTRA_PROBLEMS:
            if title not in seen:
                section.add_widget(self._problem_block(title, advice))
        return section

    def _problem_block(self, title: str, advice: str) -> QWidget:
        holder = QWidget()
        clear_background(holder)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, tokens.SP_2)
        layout.setSpacing(2)
        heading = QLabel(title)
        heading.setWordWrap(True)
        heading.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 600; background: transparent;")
        layout.addWidget(heading)
        layout.addWidget(_body_label(advice))
        return holder

    def _build_shortcuts(self) -> QWidget:
        section = CollapsibleSection("Phím tắt", expanded=False)
        for shortcut in ALL_SHORTCUTS:
            row = QHBoxLayout()
            row.setSpacing(tokens.SP_3)
            keys = QLabel(shortcut.keys)
            keys.setMinimumWidth(120)
            keys.setStyleSheet(
                f"color: {tokens.ACCENT_BLUE}; font-size: {tokens.FS_META}px; "
                f"font-family: {tokens.FONT_MONO}; background: transparent;")
            action = ElidedLabel(shortcut.action)
            action.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; "
                f"font-size: {tokens.FS_META}px; background: transparent;")
            scope = QLabel(shortcut.scope)
            scope.setStyleSheet(
                f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_BADGE}px; "
                f"background: transparent;")
            row.addWidget(keys)
            row.addWidget(action, 1)
            row.addWidget(scope)
            section.add_layout(row)
        return section

    def _build_about(self) -> QWidget:
        from autodub.utils import app_root
        from autodub_gui.app import APP_VERSION
        from autodub_gui.env_store import ENV_PATH

        section = CollapsibleSection("Về ứng dụng", expanded=True)
        for label, value in (("Phiên bản", f"v{APP_VERSION}"),
                             ("Thư mục ứng dụng", app_root()),
                             ("Tệp cấu hình", ENV_PATH)):
            row = QHBoxLayout()
            row.setSpacing(tokens.SP_2)
            name = QLabel(label)
            name.setMinimumWidth(_LABEL_W)
            name.setStyleSheet(
                f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
                f"background: transparent;")
            text = ElidedLabel(value)
            text.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_META}px; "
                f"background: transparent;")
            row.addWidget(name)
            row.addWidget(text, 1)
            section.add_layout(row)

        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.SP_2)
        for text, handler in (("Mở thư mục cấu hình", self._open_app_folder),
                              ("Mở thư mục log", self._open_logs_folder),
                              ("Mở hướng dẫn kèm ứng dụng", self._open_readme),
                              ("Gửi báo lỗi và góp ý", self._open_support),
                              ("Mở Cài đặt", self.settings_requested.emit)):
            button = GhostButton(text)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addStretch()
        section.add_layout(buttons)
        return section

    # -- Tiện ích ------------------------------------------------------
    def _safe_settings(self):
        try:
            return self._settings_provider()
        except Exception:  # noqa: BLE001 — cấu hình hỏng thì vẫn mở được trang
            return None

    @staticmethod
    def _is_ready(settings, checker: str) -> bool:
        if settings is None:
            return False
        if checker == "voices_enrolled":
            # Không phải một mục trong cấu hình mà là một câu hỏi về dữ liệu:
            # thư viện giọng mẫu đã được nạp hết chưa.
            try:
                from autodub.speech.tts import voice_library
                total, todo = voice_library.summary(settings)
                return bool(total) and not todo
            except Exception:  # noqa: BLE001 — chưa có thư mục thì coi như chưa
                return False
        method = getattr(settings, checker, None)
        try:
            return bool(method()) if callable(method) else False
        except Exception:  # noqa: BLE001 — không kiểm tra được thì coi là chưa cài
            return False

    def _copy(self, command: str) -> None:
        QApplication.clipboard().setText(command)
        TOASTS.success("Đã sao chép lệnh. Dán vào cửa sổ dòng lệnh rồi chạy.")

    def _open_app_folder(self) -> None:
        from autodub.utils import app_root

        ok, message = open_folder(app_root())
        if not ok:
            TOASTS.warn(message)

    def _open_logs_folder(self) -> None:
        from autodub.utils import logs_dir

        ok, message = open_folder(logs_dir())
        if not ok:
            TOASTS.warn(message)

    def _open_readme(self) -> None:
        from autodub.utils import app_root

        for name in ("HUONG DAN.md", "README.md"):
            path = os.path.join(app_root(), name)
            if os.path.isfile(path):
                ok, message = open_file(path)
                if not ok:
                    TOASTS.warn(message)
                return
        TOASTS.warn("Không tìm thấy tệp hướng dẫn cạnh ứng dụng.")

    def _open_support(self) -> None:
        from autodub_gui.system_open import open_url

        settings = self._safe_settings()
        url = settings.support_url if settings is not None else ""
        if not url:
            TOASTS.warn("Chưa cấu hình địa chỉ biểu mẫu hỗ trợ (SUPPORT_URL).")
            return
        ok, message = open_url(url)
        if not ok:
            TOASTS.warn(message)

    def on_shown(self) -> None:
        """Không cần nạp lại gì, nội dung sinh sẵn lúc dựng trang."""
