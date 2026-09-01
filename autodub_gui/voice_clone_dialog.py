"""Dialog for creating one local VieNeu clone voice."""
from __future__ import annotations

import os

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from autodub.speech.tts.voice_clone_service import (
    validate_clone_request as _validate_clone_request,
)

_AUDIO_FILTER = "Audio (*.wav *.mp3 *.m4a *.flac *.ogg *.aac)"
_VIDEO_FILTER = "Video (*.mp4 *.mkv *.webm *.mov *.avi)"

def validate_clone_request(values: dict) -> bool:
    return _validate_clone_request(values) is None

class _EnrollThread(QThread):
    done = Signal(str, str)

    def __init__(self, settings, values, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.values_data = values

    def run(self):
        try:
            from autodub.speech.tts import voice_clone_service
            if self.values_data["source"] == "audio":
                name = voice_clone_service.enroll_from_audio(
                    self.settings, self.values_data["path"],
                    self.values_data["name"])
            else:
                name = voice_clone_service.enroll_from_video(
                    self.settings, self.values_data["path"],
                    self.values_data["name"])
            self.done.emit(name, "")
        except Exception as exc:
            self.done.emit("", f"{type(exc).__name__}: {exc}")

class VoiceCloneDialog(QDialog):
    enrolled = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thêm giọng clone")
        self._settings = settings
        self._thread = None
        form = QFormLayout()
        self.source = QComboBox()
        self.source.addItem("Đoạn audio", "audio")
        self.source.addItem("Video", "video")
        self.path = QLineEdit()
        self.path.setPlaceholderText("Chọn file nguồn 1 đến 8 giây thoại rõ")
        browse = QPushButton("Chọn...")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Ví dụ: Giọng nữ nhẹ")
        self.error = QLabel("")
        self.error.setWordWrap(True)
        form.addRow("Nguồn", self.source)
        form.addRow("File", path_row)
        form.addRow("Tên giọng", self.name)
        form.addRow("", self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(QLabel("Xử lý cục bộ. File nguồn không bị xóa hoặc tải lên."))
        root.addWidget(buttons)
        self._buttons = buttons

    def values(self) -> dict:
        return {
            "source": self.source.currentData(),
            "path": self.path.text().strip(),
            "name": self.name.text().strip(),
        }

    def _browse(self):
        if self.source.currentData() == "audio":
            path, _ = QFileDialog.getOpenFileName(
                self, "Chọn audio mẫu", os.path.expanduser("~"), _AUDIO_FILTER)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Chọn video mẫu", os.path.expanduser("~"), _VIDEO_FILTER)
        if path:
            self.path.setText(path)

    def _submit(self):
        values = self.values()
        error = _validate_clone_request(values)
        if error or not os.path.isfile(values["path"]):
            self.error.setText(error or "File không tồn tại.")
            return
        self._buttons.setEnabled(False)
        self.error.setText("Đang học giọng cục bộ...")
        self._thread = _EnrollThread(self._settings, values, self)
        self._thread.done.connect(self._finish)
        self._thread.start()

    def _finish(self, name: str, error: str):
        self._thread = None
        self._buttons.setEnabled(True)
        if error:
            self.error.setText(error)
            return
        self.enrolled.emit(name)
        self.accept()

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(10000)
        super().closeEvent(event)
