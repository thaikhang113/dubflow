"""In-app release download and installation dialog."""
from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QMessageBox, QProgressBar,
    QVBoxLayout,
)

from autodub_gui import tokens


class UpdateDownloadWorker(QThread):
    progress = Signal(int)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info

    def run(self) -> None:
        from autodub.updates import download_verified

        try:
            path = download_verified(self.info, progress=self.progress.emit)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.completed.emit(path)


class UpdateDialog(QDialog):
    """Download, verify, and hand off a platform installer."""

    install_requested = Signal(str)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.package_path = ""
        self.worker: UpdateDownloadWorker | None = None
        self.setWindowTitle("Cập nhật DubFlow")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        title = QLabel(f"Có bản DubFlow mới: v{info.version}")
        title.setStyleSheet(
            f"font-size: {tokens.FS_SECTION}px; font-weight: 700;")
        layout.addWidget(title)

        notes = QLabel(info.notes or "Bản phát hành mới có sẵn.")
        notes.setWordWrap(True)
        notes.setTextInteractionFlags(
            notes.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(notes)

        self.status = QLabel("Tải gói cập nhật để cài đặt.")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.buttons = QDialogButtonBox()
        self.download_button = self.buttons.addButton(
            "Tải bản cập nhật", QDialogButtonBox.ButtonRole.AcceptRole)
        self.install_button = self.buttons.addButton(
            "Cài đặt và khởi động lại",
            QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = self.buttons.addButton(
            "Đóng", QDialogButtonBox.ButtonRole.RejectRole)
        self.install_button.setEnabled(False)
        self.download_button.clicked.connect(self._download)
        self.install_button.clicked.connect(self._install)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.buttons)

    def _download(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.download_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.status.setText("Đang tải và kiểm tra SHA256...")
        self.worker = UpdateDownloadWorker(self.info, self)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.completed.connect(self._downloaded)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _downloaded(self, path: str) -> None:
        self.package_path = path
        self.status.setText("Đã tải và xác minh gói cập nhật.")
        self.install_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.worker = None

    def _failed(self, message: str) -> None:
        self.status.setText("Tải cập nhật thất bại.")
        self.download_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.worker = None
        QMessageBox.critical(self, "Không thể cập nhật", message)

    def _install(self) -> None:
        if not self.package_path:
            return
        self.install_requested.emit(self.package_path)
        self.accept()

    def closeEvent(self, event) -> None:
        if self.worker is not None and self.worker.isRunning():
            event.ignore()
            return
        event.accept()
