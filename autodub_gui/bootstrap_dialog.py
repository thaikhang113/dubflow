"""Mandatory first-run dependency installer."""
from __future__ import annotations

import shutil

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QPlainTextEdit, QVBoxLayout,
)

from autodub_gui import bootstrap, tokens


class BootstrapDialog(QDialog):
    """Install every local engine before allowing normal app use."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.current: QThread | None = None
        self.index = 0
        self._closing = False
        self.setWindowTitle("DubFlow setup")
        self.setMinimumSize(720, 520)
        self.setModal(True)

        root = QVBoxLayout(self)
        title = QLabel("Complete DubFlow setup")
        title.setStyleSheet(
            f"font-size: {tokens.FS_SECTION}px; font-weight: 700;")
        root.addWidget(title)
        root.addWidget(QLabel(
            "Required engines download once. Setup resumes after interruption."))

        self.list = QListWidget()
        self.items = []
        for step in bootstrap.steps():
            item = QListWidgetItem(f"{step.label}  -  waiting")
            self.items.append(item)
            self.list.addItem(item)
        root.addWidget(self.list)

        self.status = QLabel("Preparing...")
        root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.retry = QPushButton("Retry")
        self.retry.setVisible(False)
        self.retry.clicked.connect(self._run_current)
        buttons.addWidget(self.retry)
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(self._cancel)
        buttons.addWidget(self.cancel)
        root.addLayout(buttons)
        self._advance_to_pending()

    def _advance_to_pending(self) -> None:
        state = bootstrap.load_state()
        completed = state.get("completed", {})
        while self.index < len(bootstrap.steps()):
            step = bootstrap.steps()[self.index]
            if (step.key == "ffmpeg" and __import__("sys").platform.startswith("linux")):
                from autodub_gui.workers_setup import _system_ffmpeg_pair

                if _system_ffmpeg_pair():
                    bootstrap.mark_completed(step.key)
                    completed[step.key] = True
            if completed.get(step.key) is True:
                self.items[self.index].setText(f"{step.label}  -  complete")
                self.index += 1
                continue
            self._run_current()
            return
        self.status.setText("Setup complete.")
        self.progress.setValue(100)
        self.cancel.setText("Start DubFlow")
        self.cancel.setEnabled(True)
        self.retry.setVisible(False)

    def _run_current(self) -> None:
        if self.index >= len(bootstrap.steps()):
            self.accept()
            return
        step = bootstrap.steps()[self.index]
        self.retry.setVisible(False)
        self.cancel.setText("Cancel")
        self.cancel.setEnabled(True)
        self.status.setText(f"Installing {step.label}...")
        self.items[self.index].setText(f"{step.label}  -  installing")
        self.progress.setValue(0)
        self.log.appendPlainText(f"== {step.label} ==")

        if step.kind == "voices":
            if self.settings is None:
                self._step_error("Không đọc được cấu hình để cài voice library.")
                return
            from autodub_gui.voice_setup_dialog import VoiceSetupDialog
            if VoiceSetupDialog.ensure_voices(self.settings, self):
                self._step_ok()
            else:
                self._step_error("Voice library setup failed.")
            return

        from autodub_gui.workers_setup import (
            FFmpegDownloadWorker, PythonRuntimeWorker, SetupScriptWorker,
        )
        if step.kind == "python":
            worker = PythonRuntimeWorker(self)
            worker.progress.connect(self.progress.setValue)
            worker.log.connect(self.log.appendPlainText)
            worker.finished_ok.connect(self._step_ok)
            worker.failed.connect(self._step_error)
        elif step.kind == "ffmpeg":
            worker = FFmpegDownloadWorker(self)
            worker.progress.connect(self.progress.setValue)
            worker.log.connect(self.log.appendPlainText)
            worker.finished_ok.connect(self._step_ok)
            worker.failed.connect(self._step_error)
        else:
            worker = SetupScriptWorker(step.script, self)
            worker.progress.connect(self.progress.setValue)
            worker.log.connect(self.log.appendPlainText)
            worker.finished_ok.connect(self._step_ok)
            worker.failed.connect(self._step_error)
        self.current = worker
        self.cancel.setEnabled(False)
        worker.start()

    def _step_ok(self) -> None:
        step = bootstrap.steps()[self.index]
        bootstrap.mark_completed(step.key)
        self.items[self.index].setText(f"{step.label}  -  complete")
        self.current = None
        self.index += 1
        self._advance_to_pending()

    def _step_error(self, message: str) -> None:
        step = bootstrap.steps()[self.index]
        bootstrap.mark_failed(step.key, message)
        self.items[self.index].setText(f"{step.label}  -  failed")
        self.status.setText(str(message))
        self.log.appendPlainText(str(message))
        self.retry.setVisible(True)
        self.cancel.setText("Close")
        self.cancel.setEnabled(True)
        self.current = None

    def _cancel(self) -> None:
        if self.index >= len(bootstrap.steps()):
            self.accept()
            return
        if self.current and self.current.isRunning():
            return
        self.reject()

    def closeEvent(self, event) -> None:
        if self.index < len(bootstrap.steps()) and self.current and self.current.isRunning():
            event.ignore()
            QMessageBox.information(
                self, "Setup running", "Wait for current step or use Cancel.")
            return
        event.accept()
