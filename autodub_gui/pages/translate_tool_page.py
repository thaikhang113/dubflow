"""Trang Dịch thuật: cấu hình provider và kiểm tra model."""
from __future__ import annotations

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from autodub.providers.openai_compatible import OpenAICompatibleProvider
from autodub_gui import tokens
from autodub_gui.pages import settings_fields as spec
from autodub_gui.pages.tool_page_base import ToolPage
from autodub_gui.ui.buttons import GhostButton
from autodub_gui.ui.collapsible import CollapsibleSection
from autodub_gui.ui.inputs import polish_combo


def model_choices(models: list[str], current: str) -> list[str]:
    """Merge endpoint models with the saved choice, preserving the saved one."""
    merged: list[str] = []
    for model in (str(current or "").strip(), *models):
        if model and model not in merged:
            merged.append(model)
    return merged


def _hint(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
        "background: transparent;")
    return label


class ProviderChecks(CollapsibleSection):
    """Test endpoint/key/model and load models returned by /models."""

    def __init__(self, values_provider, model_setter, parent: QWidget | None = None):
        super().__init__("Kiểm tra API và model", expanded=True, parent=parent)
        self._values_provider = values_provider
        self._model_setter = model_setter
        self._threads: dict[str, QThread] = {}

        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setPlaceholderText(
            "Chọn hoặc gõ model")
        self.model_combo.setMinimumContentsLength(18)
        self.model_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.model_combo.currentTextChanged.connect(self._select_model)
        polish_combo(self.model_combo)
        row.addWidget(self.model_combo, 1)

        self.load_button = GhostButton("Tải model")
        self.load_button.setToolTip("Lấy model từ endpoint bằng API key đang nhập")
        self.load_button.clicked.connect(self.load_models)
        row.addWidget(self.load_button)

        self.check_button = GhostButton("Kiểm tra API + model")
        self.check_button.setToolTip(
            "Kiểm tra endpoint, API key và model đang chọn")
        self.check_button.clicked.connect(self.check_provider)
        row.addWidget(self.check_button)
        self.add_layout(row)

        self.status = _hint(
            "Nhập endpoint, API key và model ở phía trên rồi tải danh sách.")
        self.add_widget(self.status)

    def _provider(self) -> OpenAICompatibleProvider:
        values = self._values_provider()
        return OpenAICompatibleProvider(
            values.get("TRANSLATION_ENDPOINT", ""),
            values.get("TRANSLATION_API_KEY", ""),
            values.get("TRANSLATION_MODEL", ""),
        )

    def _select_model(self, model: str) -> None:
        if model:
            self._model_setter(model)

    def load_models(self) -> None:
        self._run("models", self.load_button, "Đang tải model", self._load)

    def check_provider(self) -> None:
        self._run("check", self.check_button, "Đang kiểm tra", self._check)

    def _load(self) -> tuple[str, list[str]]:
        models = self._provider().list_models()
        return f"Đã tìm thấy {len(models)} model.", models

    def _check(self) -> tuple[str, list[str]]:
        provider = self._provider()
        models = provider.list_models()
        model = provider.model
        if not model:
            return f"API key hoạt động, có {len(models)} model.", models
        provider.check_model()
        listed = model in models
        return (f"API key và model “{model}” hoạt động"
                + ("" if listed else
                   " (model không nằm trong /models nhưng đã chạy thử được)."),
                models)

    def _run(self, key: str, button: GhostButton, busy_text: str, task) -> None:
        if key in self._threads:
            return
        button.set_loading(True, busy_text)
        self.status.setText("")

        class _Worker(QThread):
            def __init__(self, parent):
                super().__init__(parent)
                self.result = None
                self.error = ""

            def run(self) -> None:
                try:
                    self.result = task()
                except Exception as exc:  # noqa: BLE001
                    self.error = str(exc)

        worker = _Worker(self)

        def done() -> None:
            button.set_loading(False)
            self._threads.pop(key, None)
            if worker.error:
                self.status.setText(f"Không hoạt động: {worker.error[:240]}")
                return
            message, models = worker.result
            if models:
                current = self._values_provider().get("TRANSLATION_MODEL", "")
                self.model_combo.blockSignals(True)
                self.model_combo.clear()
                self.model_combo.addItems(model_choices(models, current))
                selected = self.model_combo.findText(current)
                self.model_combo.setCurrentIndex(max(selected, 0))
                self.model_combo.blockSignals(False)
                polish_combo(self.model_combo)
                self._select_model(self.model_combo.currentText())
            self.status.setText(message)

        worker.finished.connect(done)
        self._threads[key] = worker
        worker.start()

    def cleanup(self) -> None:
        for worker in list(self._threads.values()):
            if worker.isRunning():
                worker.wait(10_000)


class TranslateToolPage(ToolPage):
    """Ngữ cảnh dịch và trạng thái provider dịch."""

    TAB = spec.TAB_TRANSLATE
    TITLE = "Dịch thuật"
    SUBTITLE = (
        "Nhập API key và endpoint, tải danh sách model, chọn model rồi "
        "kiểm tra trước khi chạy."
    )
    EXPANDED = {"Ngữ cảnh video"}
    SAVE_LABEL = "Lưu cấu hình dịch"
    SAVED_TOAST = "Đã lưu cấu hình dịch."

    def extra_panels(self) -> list[QWidget]:
        self.checks_panel = ProviderChecks(
            self.current_values, self._set_translation_model, self)
        return [self.checks_panel]

    def _set_translation_model(self, model: str) -> None:
        widget = self._widget_of("TRANSLATION_MODEL")
        if widget is not None:
            widget.set_text(model)
            self._mark_dirty()

    def load_extra(self, env: dict[str, str]) -> None:
        current = str(env.get("TRANSLATION_MODEL", "") or "").strip()
        panel = getattr(self, "checks_panel", None)
        if panel is None:
            return
        combo = panel.model_combo
        combo.blockSignals(True)
        if current and combo.findText(current) < 0:
            combo.addItem(current)
        combo.setCurrentText(current)
        combo.blockSignals(False)

    def cleanup(self) -> None:
        panel = getattr(self, "checks_panel", None)
        if panel is not None:
            panel.cleanup()
