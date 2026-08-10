"""Dialog tự động tải + enroll voice library khi lần đầu chạy app.

Chạy ở luồng nền (QThread) để không đóng băng giao diện, hiện tiến độ
realtime theo từng bước: tải ZIP → giải nén → enroll từng giọng.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from autodub_gui import tokens


class _VoiceSetupWorker(QThread):
    """Luồng nền thực hiện: tải → giải nén → enroll."""

    stage_changed = Signal(str)          # "Đang tải...", "Đang giải nén...", ...
    download_progress = Signal(int, int) # (bytes_downloaded, total_bytes)
    enroll_progress = Signal(int, int, str)  # (current, total, voice_name)
    finished_ok = Signal(int)            # tổng số giọng enrolled
    finished_err = Signal(str)           # thông báo lỗi

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._total_enrolled = 0

    def run(self) -> None:
        from autodub.speech.tts.voice_downloader import ensure_voices_available

        def _cb(event, a, b, *rest):
            if event == "download_start":
                self.stage_changed.emit("Đang tải dữ liệu giọng đọc...")
            elif event == "download_progress":
                self.download_progress.emit(a or 0, b or 0)
            elif event == "extract_start":
                self.stage_changed.emit("Đang giải nén...")
            elif event == "enroll_start":
                self.stage_changed.emit(f"Đang mã hóa giọng (0/{a or 0})...")
            elif event == "enroll_progress":
                current, total = a, b
                name = rest[0] if rest else ""
                self.enroll_progress.emit(current or 0, total or 0, name or "")
            elif event == "done":
                pass
            elif event == "error":
                self.finished_err.emit(str(a))

        ok = ensure_voices_available(self.settings, _cb)
        if ok:
            # Đếm số giọng đã enrolled
            try:
                import json
                with open(self.settings.vieneu_custom_voices_path(),
                          encoding="utf-8") as f:
                    data = json.load(f)
                self._total_enrolled = len(data.get("presets", {}))
            except Exception:
                self._total_enrolled = 0
            self.finished_ok.emit(self._total_enrolled)
        else:
            self.finished_err.emit(
                "Không thể tải voice library. Kiểm tra kết nối mạng và thử lại.")


class VoiceSetupDialog(QDialog):
    """Modal tiến trình cài đặt voice library."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._worker: _VoiceSetupWorker | None = None
        self._success = False

        self.setWindowTitle("Cài đặt thư viện giọng đọc")
        self.setFixedWidth(460)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # Tiêu đề
        title = QLabel("Tải thư viện giọng đọc")
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        layout.addWidget(title)

        # Mô tả
        desc = QLabel(
            "Lần đầu chạy app, VoxDub cần tải bộ giọng đọc từ máy chủ.\n"
            "Quá trình này chỉ diễn ra MỘT LẦN DUY NHẤT.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        layout.addWidget(desc)

        # Nhãn bước hiện tại
        self.stage_label = QLabel("Đang khởi động...")
        self.stage_label.setStyleSheet(f"color: {tokens.TEXT_PRIMARY};")
        layout.addWidget(self.stage_label)

        # Thanh tiến độ download
        self.dl_bar = QProgressBar()
        self.dl_bar.setRange(0, 100)
        self.dl_bar.setValue(0)
        self.dl_bar.setTextVisible(True)
        self.dl_bar.setFormat("Tải xuống: %p%")
        self.dl_bar.setFixedHeight(20)
        layout.addWidget(self.dl_bar)

        # Thanh tiến độ enroll
        self.enroll_bar = QProgressBar()
        self.enroll_bar.setRange(0, 100)
        self.enroll_bar.setValue(0)
        self.enroll_bar.setTextVisible(True)
        self.enroll_bar.setFormat("Mã hóa giọng: %p%")
        self.enroll_bar.setFixedHeight(20)
        layout.addWidget(self.enroll_bar)

        # Nhãn giọng đang enroll
        self.voice_label = QLabel("")
        self.voice_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_LABEL}px;")
        layout.addWidget(self.voice_label)

        # Nút bấm
        self.btn = QPushButton("Huỷ")
        self.btn.setFixedHeight(36)
        self.btn.clicked.connect(self._on_btn)
        layout.addWidget(self.btn)

        self._start_worker()

    # -- Khởi động worker -----------------------------------------------

    def _start_worker(self) -> None:
        self._worker = _VoiceSetupWorker(self.settings, self)
        self._worker.stage_changed.connect(self._on_stage)
        self._worker.download_progress.connect(self._on_dl_progress)
        self._worker.enroll_progress.connect(self._on_enroll_progress)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.finished_err.connect(self._on_err)
        self._worker.start()

    # -- Xử lý tín hiệu -----------------------------------------------

    def _on_stage(self, text: str) -> None:
        self.stage_label.setText(text)

    def _on_dl_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            pct = min(100, int(downloaded * 100 / total))
            self.dl_bar.setValue(pct)
            mb_dl = downloaded / 1024 / 1024
            mb_total = total / 1024 / 1024
            self.dl_bar.setFormat(f"Tải xuống: {mb_dl:.1f} / {mb_total:.1f} MB")
        else:
            self.dl_bar.setRange(0, 0)  # marquee mode

    def _on_enroll_progress(self, current: int, total: int, name: str) -> None:
        if total > 0:
            pct = min(100, int(current * 100 / total))
            self.enroll_bar.setValue(pct)
            self.enroll_bar.setFormat(f"Mã hóa giọng: {current}/{total}")
        if name:
            self.voice_label.setText(f"Đang xử lý: {name}")
        self.stage_label.setText(
            f"Đang mã hóa giọng ({current}/{total})...")

    def _on_ok(self, count: int) -> None:
        self._success = True
        self.stage_label.setText(f"Hoàn tất! Đã cài đặt {count} giọng đọc.")
        self.stage_label.setStyleSheet(
            f"color: {tokens.SUCCESS}; font-weight: bold;")
        self.dl_bar.setValue(100)
        self.dl_bar.setFormat("Tải xuống: hoàn tất")
        self.enroll_bar.setValue(100)
        self.enroll_bar.setFormat(f"Đã mã hóa {count} giọng")
        self.voice_label.setText("")
        self.btn.setText("Bắt đầu sử dụng")
        self.btn.setStyleSheet(
            f"background: {tokens.SUCCESS}; color: white; font-weight: 600; "
            f"border-radius: 6px; padding: 8px 16px;")

    def _on_err(self, msg: str) -> None:
        self.stage_label.setText(f"Lỗi: {msg}")
        self.stage_label.setStyleSheet(
            f"color: {tokens.DANGER}; font-weight: bold;")
        self.btn.setText("Thử lại")
        self.btn.setStyleSheet("")
        self._worker = None  # allow retry

    def _on_btn(self) -> None:
        if self._success:
            self.accept()
            return
        # Nếu worker đang chạy → ngắt tín hiệu rồi đóng dialog.
        # KHÔNG gọi QThread.terminate() — trên Windows hàm đó để ngỏ pipe
        # của tiến trình con (enroll worker), gây rò rỉ. Worker tự kết thúc
        # sau khi I/O hiện tại xong; các tín hiệu đã ngắt nên không cập nhật
        # giao diện đã đóng.
        if self._worker and self._worker.isRunning():
            w = self._worker
            self._worker = None
            try:
                w.stage_changed.disconnect()
                w.download_progress.disconnect()
                w.enroll_progress.disconnect()
                w.finished_ok.disconnect()
                w.finished_err.disconnect()
            except RuntimeError:
                pass  # đã disconnect hoặc object C++ đã bị hủy
            self.reject()
            return
        # Worker đã kết thúc (thành công hoặc lỗi) → nếu có lỗi, thử lại
        lbl = self.btn.text()
        if lbl == "Thử lại":
            # Reset UI và chạy lại
            self.stage_label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY};")
            self.stage_label.setText("Đang kết nối...")
            self.dl_bar.setValue(0)
            self.dl_bar.setFormat("Tải xuống: %p%")
            self.enroll_bar.setValue(0)
            self.enroll_bar.setFormat("Mã hóa giọng: %p%")
            self.voice_label.setText("")
            self.btn.setText("Huỷ")
            self._start_worker()
        else:
            self.reject()

    # -- API công khai -------------------------------------------------

    @classmethod
    def ensure_voices(cls, settings, parent=None) -> bool:
        """Hiện dialog nếu cần; trả về True nếu voice library sẵn sàng.

        Gọi từ MainWindow trước khi show() lần đầu.
        """
        from autodub.speech.tts.voice_downloader import voices_installed

        if voices_installed(settings):
            return True
        # Chỉ show dialog nếu VieNeu đã được cài
        if not settings.vieneu_configured():
            return False  # VieNeu chưa cài → không tải, preflight sẽ báo sau
        dlg = cls(settings, parent)
        dlg.exec()
        return dlg._success
