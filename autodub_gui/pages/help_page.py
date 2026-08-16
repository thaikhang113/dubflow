"""Trang Trợ giúp: hướng dẫn nhanh, cách cài thêm, khắc phục sự cố.

Nội dung ở đây được sinh từ chính dữ liệu của ứng dụng: bảng phím tắt lấy từ
`shortcuts.py`, mục khắc phục sự cố lấy từ bảng lỗi thân thiện, tình trạng cài
đặt đọc trực tiếp từ máy. Nhờ vậy trang này không bao giờ nói sai so với thực
tế của ứng dụng.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget,
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

# (tên, mô tả, dung lượng, loại cài, script, hàm kiểm tra tình trạng)
INSTALL_ITEMS = (
    ("Bộ giọng đọc VieNeu",
     "Giọng Việt chạy trên bộ xử lý trung tâm nên nhanh và không cần card "
     "đồ họa. Đây là bộ giọng duy nhất của ứng dụng.",
     MODEL_SIZES["vieneu"], "script", "scripts/setup_vieneu.py",
     "vieneu_configured"),
    ("Thư viện giọng mẫu",
     "Nạp thêm các giọng trong thư mục voices cạnh ứng dụng. Chạy một lần, "
     "sau đó chọn giọng theo tên trong Cài đặt.",
     "không cần tải", "voices", "", "voices_enrolled"),
    ("Paraformer", "Nghe tiếng Trung chính xác hơn Whisper, chạy trên CPU.",
     MODEL_SIZES["paraformer"], "script", "scripts/setup_paraformer.py",
     "paraformer_configured"),
    ("Whisper ASR",
     "Nhận dạng lời nói cho ngôn ngữ khác tiếng Trung. Cài riêng để không làm "
     "phình bản DubFlow.",
     MODEL_SIZES["medium"], "script", "scripts/setup_whisper.py",
     "whisper_venv_configured"),
    ("PaddleOCR",
     "Tự tìm chữ Trung trong vùng phụ đề để làm mờ. Chỉ cần khi muốn tự động "
     "che phụ đề gốc; logo gốc có thể tự dò bằng Vision hoặc chọn vùng riêng "
     "trong Trình chỉnh sửa.",
     "khoảng 2–3 GB (GPU)", "script", "scripts/setup_ocr.py",
     "ocr_configured"),
    ("DeepSeek-OCR (tùy chọn)",
      "Fallback cho PaddleOCR và hỗ trợ tìm logo/chữ khó. Cài riêng và bật "
      "trong Cài đặt; NVIDIA dùng CUDA, AMD dùng ROCm trên Linux hoặc DirectML "
      "trên Windows nếu backend tương thích. Không tương thích thì PaddleOCR "
      "vẫn hoạt động.",
     "tải riêng theo model", "script", "scripts/setup_deepseek_ocr.py",
     "deepseek_ocr_configured"),
    ("AI xóa phụ đề VSR",
     "Phục hồi nền video sau khi OCR tìm phụ đề cứng. Dùng STTN detection mặc định; "
     "nếu lỗi sẽ tự quay về làm mờ để không chặn xuất video.",
     "tải riêng theo model", "script", "scripts/setup_vsr.py",
     "vsr_configured"),
)

EXTRA_PROBLEMS = (
    ("Máy chưa có FFmpeg",
     "Bản Debian dùng FFmpeg của hệ thống và đã khai báo gói cần thiết. Bản "
     "portable Linux không tự tải FFmpeg; hãy cài ffmpeg và ffprobe bằng trình "
     "quản lý gói của hệ điều hành rồi mở lại ứng dụng. Windows sẽ tự tải bản "
     "FFmpeg phù hợp khi cần."),
    ("Làm mờ phụ đề hoặc logo gốc",
     "Trong Trình chỉnh sửa, mở Tùy chỉnh phụ đề và vùng che. Bật OCR để tự "
     "tìm chữ Trung trong vùng 35% phía dưới; bật Tự dò logo gốc bằng Vision "
     "hoặc bật Khoanh vùng logo gốc rồi kéo một vùng riêng để làm mờ logo "
     "cố định suốt video."),
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
        self._install_rows: dict[str, dict[str, object]] = {}
        self._active_install: str | None = None
        self._install_worker: QThread | None = None
        self._doctor_section: CollapsibleSection | None = None
        self._doctor_layout: QVBoxLayout | None = None
        self._doctor_rows: dict[str, dict[str, object]] = {}
        self._doctor_worker: QThread | None = None
        self._doctor_repair_worker: QThread | None = None
        self._doctor_check_button: GhostButton | None = None
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
        layout.addWidget(self._build_doctor())
        layout.addWidget(self._build_install())
        layout.addWidget(self._build_problems())
        layout.addWidget(self._build_shortcuts())
        layout.addWidget(self._build_about())
        layout.addStretch()

        scroll.setWidget(holder)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _build_doctor(self) -> QWidget:
        section = CollapsibleSection("Kiểm tra hệ thống", expanded=True)
        section.add_widget(_body_label(
            "Kiểm tra môi trường phát hành, thư viện và các bộ cài. "
            "Mục lỗi có thể Tải lại riêng; dữ liệu dự án, model và cookie được giữ nguyên."
        ))
        controls = QHBoxLayout()
        status = QLabel("Chưa kiểm tra")
        status.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            "background: transparent;")
        button = GhostButton("Kiểm tra hệ thống")
        button.clicked.connect(self._start_doctor_check)
        controls.addWidget(status)
        controls.addStretch()
        controls.addWidget(button)
        section.add_layout(controls)
        layout = QVBoxLayout()
        layout.setSpacing(tokens.SP_1)
        section.add_layout(layout)
        self._doctor_section = section
        self._doctor_layout = layout
        self._doctor_rows["__summary__"] = {"status": status}
        self._doctor_check_button = button
        return section

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
        for name, description, size, kind, script, checker in INSTALL_ITEMS:
            section.add_layout(
                self._install_row(settings, name, description, size, kind,
                                  script, checker))
        return section

    def _install_row(self, settings, name: str, description: str, size: str,
                     kind: str, script: str, checker: str) -> QVBoxLayout:
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
        install_button = GhostButton("Đã cài" if ready else "Tải và cài")
        install_button.setEnabled(not ready and settings is not None)
        install_button.clicked.connect(
            lambda _checked=False, key=checker: self._start_install(key))
        head.addWidget(install_button)
        column.addLayout(head)
        column.addWidget(_body_label(description))
        error = ElidedLabel("")
        error.setStyleSheet(
            f"color: {tokens.DANGER}; font-size: {tokens.FS_META}px; "
            "background: transparent;")
        error.hide()
        column.addWidget(error)
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setTextVisible(False)
        progress.setFixedHeight(8)
        progress.hide()
        column.addWidget(progress)
        self._install_rows[checker] = {
            "name": name,
            "kind": kind,
            "script": script,
            "checker": checker,
            "state": state,
            "button": install_button,
            "error": error,
            "progress": progress,
        }
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

    def _start_install(self, checker: str) -> None:
        if self._active_install is not None:
            return
        row = self._install_rows.get(checker)
        settings = self._safe_settings()
        if row is None or settings is None:
            TOASTS.error("Không đọc được cấu hình để cài thành phần.")
            return

        self._active_install = checker
        self._set_install_controls(False)
        row["button"].setText("Đang cài...")
        row["button"].setEnabled(False)
        row["state"].setText("đang cài")
        row["state"].setStyleSheet(
            f"color: {tokens.ACCENT_BLUE}; font-size: {tokens.FS_META}px; "
            "background: transparent;")
        row["progress"].setValue(0)
        row["progress"].show()

        if row["kind"] == "voices":
            from autodub_gui.voice_setup_dialog import VoiceSetupDialog

            ok = VoiceSetupDialog.ensure_voices(settings, self)
            self._finish_install(checker, ok, "")
            return

        from autodub_gui.workers_setup import SetupScriptWorker

        worker = SetupScriptWorker(row["script"], self)
        worker.progress.connect(row["progress"].setValue)
        worker.log.connect(lambda message: row["button"].setToolTip(message))
        worker.finished_ok.connect(
            lambda key=checker: self._finish_install(key, True, ""))
        worker.failed.connect(
            lambda message, key=checker: self._finish_install(
                key, False, message))
        worker.finished.connect(worker.deleteLater)
        self._install_worker = worker
        worker.start()

    def _start_doctor_check(self) -> None:
        if self._doctor_worker is not None or self._doctor_repair_worker is not None:
            return
        settings = self._safe_settings()
        if settings is None:
            TOASTS.error("Không đọc được cấu hình để kiểm tra hệ thống.")
            return
        if self._doctor_check_button is not None:
            self._doctor_check_button.setEnabled(False)
        summary = self._doctor_rows.get("__summary__", {}).get("status")
        if isinstance(summary, QLabel):
            summary.setText("Đang kiểm tra...")
        from autodub_gui.workers_setup import DoctorWorker

        worker = DoctorWorker(settings, self)
        worker.results.connect(self._show_doctor_results)
        worker.failed.connect(self._doctor_failed)
        worker.finished.connect(self._doctor_worker_finished)
        self._doctor_worker = worker
        worker.start()

    def _doctor_worker_finished(self) -> None:
        worker = self._doctor_worker
        self._doctor_worker = None
        if worker is not None:
            worker.deleteLater()

    def _doctor_failed(self, message: str) -> None:
        summary = self._doctor_rows.get("__summary__", {}).get("status")
        if isinstance(summary, QLabel):
            summary.setText("Kiểm tra thất bại")
            summary.setToolTip(message)
        if self._doctor_check_button is not None:
            self._doctor_check_button.setEnabled(True)
        TOASTS.error("Doctor không kiểm tra được hệ thống.")

    def _show_doctor_results(self, results: object) -> None:
        if self._doctor_layout is None:
            return
        while self._doctor_layout.count():
            item = self._doctor_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._doctor_rows = {
            "__summary__": self._doctor_rows.get("__summary__", {})
        }
        checks = [item for item in results if hasattr(item, "key")]
        failures = [item for item in checks if item.level == "fail"]
        warnings = [item for item in checks if item.level == "warn"]
        summary = self._doctor_rows["__summary__"].get("status")
        if isinstance(summary, QLabel):
            summary.setText(
                f"{len(failures)} lỗi, {len(warnings)} cảnh báo, "
                f"{len(checks) - len(failures) - len(warnings)} đạt"
            )
        for check in checks:
            self._add_doctor_row(check)
        if self._doctor_check_button is not None:
            self._doctor_check_button.setEnabled(True)

    def _add_doctor_row(self, check) -> None:
        row = QHBoxLayout()
        state = QLabel({"ok": "Đạt", "warn": "Cảnh báo", "fail": "Lỗi"}
                       .get(check.level, check.level))
        colors = {"ok": tokens.SUCCESS, "warn": tokens.WARNING,
                  "fail": tokens.DANGER}
        state.setStyleSheet(
            f"color: {colors.get(check.level, tokens.TEXT_MUTED)}; "
            f"font-size: {tokens.FS_META}px; background: transparent;")
        title = QLabel(check.title)
        title.setMinimumWidth(_LABEL_W)
        message = ElidedLabel(check.message)
        message.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            "background: transparent;")
        row.addWidget(title)
        row.addWidget(state)
        row.addWidget(message, 1)
        if check.repairable:
            repair = GhostButton("Tải lại")
            repair.clicked.connect(
                lambda _checked=False, key=check.key: self._start_doctor_repair(key))
            row.addWidget(repair)
        self._doctor_layout.addLayout(row)
        self._doctor_rows[check.key] = {"check": check, "layout": row}

    def _start_doctor_repair(self, check_key: str) -> None:
        if self._doctor_repair_worker is not None or self._active_install is not None:
            return
        row = self._doctor_rows.get(check_key, {})
        check = row.get("check")
        script = getattr(check, "repair_script", "")
        if not script:
            return
        from autodub_gui.workers_setup import (
            FFmpegDownloadWorker, SetupScriptWorker,
        )

        worker = (
            FFmpegDownloadWorker()
            if script == "__ffmpeg__"
            else SetupScriptWorker(script, self)
        )
        worker.log.connect(lambda message: self._doctor_rows[check_key].update(
            {"last_log": message}))
        worker.finished_ok.connect(
            lambda key=check_key: self._finish_doctor_repair(key, True, ""))
        worker.failed.connect(
            lambda message, key=check_key: self._finish_doctor_repair(
                key, False, message))
        worker.finished.connect(worker.deleteLater)
        self._doctor_repair_worker = worker
        worker.start()

    def _finish_doctor_repair(
        self, check_key: str, ok: bool, message: str
    ) -> None:
        worker = self._doctor_repair_worker
        self._doctor_repair_worker = None
        if worker is not None:
            worker.deleteLater()
        if ok:
            TOASTS.success("Đã tải lại thành phần. Kiểm tra lại hệ thống.")
            self._start_doctor_check()
        else:
            TOASTS.error("Tải lại thành phần thất bại.")
            row = self._doctor_rows.get(check_key, {})
            check = row.get("check")
            if check is not None:
                check = type(check)(
                    check.key, check.title, "fail", check.message, message,
                    check.repair_script)
                row["check"] = check

    def _finish_install(self, checker: str, ok: bool, message: str) -> None:
        row = self._install_rows.get(checker)
        if row is None:
            return
        self._active_install = None
        self._install_worker = None
        row["progress"].hide()
        if ok:
            row["error"].clear()
            row["error"].hide()
            self._refresh_install_row(checker)
            TOASTS.success(f"Đã cài {row['name']}.")
        else:
            row["state"].setText("cài thất bại")
            row["state"].setStyleSheet(
                f"color: {tokens.DANGER}; font-size: {tokens.FS_META}px; "
                "background: transparent;")
            row["state"].setToolTip(message)
            row["error"].setText(message.splitlines()[-1][:240])
            row["error"].setToolTip(message)
            row["error"].show()
            row["button"].setText("Thử lại")
            row["button"].setEnabled(True)
            TOASTS.error(f"Cài {row['name']} thất bại.")
        self._set_install_controls(True)

    def _refresh_install_row(self, checker: str) -> None:
        row = self._install_rows.get(checker)
        settings = self._safe_settings()
        if row is None:
            return
        ready = self._is_ready(settings, checker)
        row["state"].setText("đã sẵn sàng" if ready else "chưa cài")
        row["state"].setStyleSheet(
            f"color: {tokens.SUCCESS if ready else tokens.WARNING}; "
            f"font-size: {tokens.FS_META}px; background: transparent;")
        row["button"].setText("Đã cài" if ready else "Tải và cài")
        row["button"].setEnabled(not ready and settings is not None)
        row["state"].setToolTip("")

    def _set_install_controls(self, enabled: bool) -> None:
        settings = self._safe_settings() if enabled else None
        for checker in self._install_rows:
            if checker == self._active_install:
                continue
            row = self._install_rows[checker]
            if not enabled:
                row["button"].setEnabled(False)
                continue
            row["button"].setEnabled(
                settings is not None and not self._is_ready(settings, checker))

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

        for name in ("HUONG_DAN_CAI_DAT.md", "README.md"):
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
