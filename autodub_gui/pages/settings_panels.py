"""Những phần đặc biệt của trang Cài đặt.

Đây là các khối không phải ô nhập đơn giản: chọn giọng mặc định và thêm giọng
mới, kiểm tra kết nối, và các nút bảo trì.
"""
from __future__ import annotations

import json
import os
import subprocess

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QWidget,
)

from autodub_gui import tokens
from autodub_gui.status_text import STATUS_OK, STATUS_WARN
from autodub_gui.ui.buttons import GhostButton
from autodub_gui.ui.collapsible import CollapsibleSection
from autodub_gui.ui.modal import ConfirmDialog
from autodub_gui.ui.toast import TOASTS
from autodub_gui.voice_picker import VoicePicker

_ENROLL_TIMEOUT_S = 600
_AUDIO_FILTER = "Âm thanh (*.wav *.mp3 *.m4a *.flac)"


def _hint_label(text: str, color: str = tokens.TEXT_MUTED) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"color: {color}; font-size: {tokens.FS_META}px; "
        f"background: transparent;")
    return label


class VoiceSettingsPanel(CollapsibleSection):
    """Chọn giọng mặc định cho dự án mới, và học thêm giọng từ ghi âm."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Giọng mặc định", expanded=True, parent=parent)
        self.picker = VoicePicker("Giọng dùng cho dự án mới",
                                  show_preview=False)
        self.picker.changed.connect(self.changed.emit)
        self.add_widget(self.picker)

        # Khối này nằm trong cột phải khá hẹp của thẻ Giọng đọc, nên hai nút
        # xếp DỌC — xếp ngang là chữ trên nút bị cắt đôi.
        self.btn_enroll = GhostButton("Thêm giọng từ đoạn ghi âm")
        self.btn_enroll.setToolTip(
            "Chọn một đoạn ghi âm 3 đến 10 giây, giọng rõ và không có nhạc "
            "nền. Ứng dụng sẽ học giọng đó rồi thêm vào danh sách.")
        self.btn_enroll.clicked.connect(self._enroll)
        self.btn_library = GhostButton("Nạp giọng từ thư mục voices")
        self.btn_library.setToolTip(
            "Học toàn bộ giọng mẫu bạn đã thả vào thư mục voices cạnh ứng "
            "dụng. Chạy một lần, sau đó chúng nằm luôn trong danh sách.")
        self.btn_library.clicked.connect(self._enroll_library)
        # Khối này nằm trong cột phải khá hẹp, nên nút chiếm trọn bề ngang
        # thay vì bị đẩy bởi khoảng chun — chữ dài không bao giờ bị cắt.
        for button in (self.btn_enroll, self.btn_library):
            self.add_widget(button)

        self.status = _hint_label("")
        self.add_widget(self.status)
        self._thread: QThread | None = None
        self._refresh_library_hint()

    def _refresh_library_hint(self) -> None:
        """Nói rõ thư viện đang có bao nhiêu giọng và còn bao nhiêu chưa học."""
        from autodub.config import Settings
        from autodub.speech.tts import voice_library

        try:
            total, todo = voice_library.summary(Settings.load())
        except Exception:  # noqa: BLE001 — thiếu thư mục thì ẩn nút đi
            total, todo = 0, 0
        self.btn_library.setVisible(bool(total))
        if not total:
            return
        self.btn_library.setEnabled(bool(todo))
        self.status.setText(
            f"Thư mục voices có {total} giọng mẫu, còn {todo} giọng chưa nạp."
            if todo else
            f"Đã nạp đủ {total} giọng mẫu trong thư mục voices.")

    def load(self, env: dict[str, str]) -> None:
        """Chọn lại giọng đã lưu trong tệp cấu hình."""
        from autodub.speech.tts.voices import DEFAULT_VOICE

        self.picker.reload()
        self.picker.set_voice(env.get("VIENEU_VOICE") or DEFAULT_VOICE)

    def values(self) -> dict[str, str]:
        from autodub.speech.tts.voices import DEFAULT_VOICE

        return {"VIENEU_VOICE": self.picker.voice() or DEFAULT_VOICE}

    # -- Học giọng mới -------------------------------------------------
    def _enroll(self) -> None:
        from autodub.config import Settings
        from autodub.speech.tts import NOT_INSTALLED_HINT

        settings = Settings.load(override=True)
        if not settings.vieneu_configured():
            self.status.setText(f"{STATUS_WARN} {NOT_INSTALLED_HINT}")
            return
        wav, _ = QFileDialog.getOpenFileName(
            self, "Chọn đoạn ghi âm giọng (3 đến 10 giây, không nhạc nền)",
            "", _AUDIO_FILTER)
        if not wav:
            return
        name, ok = QInputDialog.getText(
            self, "Đặt tên giọng",
            "Đặt tên cho giọng này, ví dụ Quốc Mạnh:")
        name = (name or "").strip()
        if not ok or not name:
            return
        gender = self._ask_gender(name)
        if gender is None:
            return
        region = self._ask_region(name)
        if region is None:
            return
        self._run_enroll(settings, wav, name, gender, region)

    def _enroll_library(self) -> None:
        """Học cả thư viện giọng mẫu trong một lần chạy nền."""
        from autodub.config import Settings
        from autodub.speech.tts import voice_library
        from autodub.speech.tts.vieneu_vi import _WORKER_SCRIPT

        settings = Settings.load(override=True)
        if not settings.vieneu_configured():
            from autodub.speech.tts import NOT_INSTALLED_HINT
            self.status.setText(f"{STATUS_WARN} {NOT_INSTALLED_HINT}")
            return
        todo = voice_library.pending(settings)
        if not todo:
            self._refresh_library_hint()
            return
        confirmed, _ = ConfirmDialog.ask(
            self, "Nạp giọng mẫu",
            f"Ứng dụng sẽ học {len(todo)} giọng mẫu trong thư mục voices. "
            "Việc này chạy một lần, mất khoảng vài phút và không tốn mạng. "
            "Trong lúc đó bạn vẫn dùng được ứng dụng.",
            kind="info", confirm_label="Bắt đầu nạp")
        if not confirmed:
            return

        import json as _json
        import tempfile

        fd, batch_path = tempfile.mkstemp(suffix=".json",
                                          prefix="voxdub_enroll_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump([v.to_batch_item() for v in todo], f,
                       ensure_ascii=False)
        command = [
            settings.vieneu_venv_python_path(), _WORKER_SCRIPT,
            "--model-dir", settings.vieneu_model_dir_path(),
            "--custom-voices", settings.vieneu_custom_voices_path(),
            "--enroll-batch", batch_path,
        ]
        self.status.setText(
            f"Đang nạp {len(todo)} giọng mẫu. Đừng tắt ứng dụng.")
        self.btn_library.set_loading(True, "Đang nạp giọng")

        class _Batch(QThread):
            def __init__(self, parent):
                super().__init__(parent)
                self.error = ""
                self.added = 0
                self.failed = 0

            def run(self) -> None:
                try:
                    flags = (subprocess.CREATE_NO_WINDOW
                             if os.name == "nt" else 0)
                    result = subprocess.run(
                        command, capture_output=True, encoding="utf-8",
                        errors="replace", timeout=3600, creationflags=flags)
                    payload = _last_json_line(result.stdout or "")
                    if not payload.get("ok"):
                        self.error = (payload.get("error")
                                      or (result.stderr or "")[-400:]
                                      or "không rõ nguyên nhân")
                        return
                    self.added = len(payload.get("added", []))
                    self.failed = len(payload.get("failed", []))
                except Exception as e:  # noqa: BLE001 — báo lên giao diện
                    self.error = f"{type(e).__name__}: {e}"
                finally:
                    if os.path.exists(batch_path):
                        os.remove(batch_path)

        worker = _Batch(self)

        def _done() -> None:
            self.btn_library.set_loading(False)
            self._thread = None
            if worker.error:
                self.status.setText("")
                ConfirmDialog.show_error(
                    self, "Không nạp được giọng mẫu",
                    "Ứng dụng không học được các giọng trong thư mục voices. "
                    "Hãy kiểm tra các tệp .wav còn nguyên vẹn rồi thử lại.",
                    detail=worker.error)
                return
            self.picker.reload()
            self._refresh_library_hint()
            TOASTS.success(f"Đã nạp thêm {worker.added} giọng."
                           + (f" {worker.failed} giọng bị bỏ qua."
                              if worker.failed else ""))
            self.changed.emit()

        worker.finished.connect(_done)
        self._thread = worker
        worker.start()

    def _ask_gender(self, name: str) -> str | None:
        confirmed, is_male = ConfirmDialog.ask(
            self, "Giọng nam hay giọng nữ",
            f"Giọng «{name}» là giọng nam hay giọng nữ? Câu trả lời chỉ dùng "
            "để lọc cho dễ tìm, không ảnh hưởng tới cách đọc.",
            kind="info", confirm_label="Tiếp tục", cancel_label="Hủy",
            checkbox_label="Đây là giọng nam", checkbox_checked=True)
        if not confirmed:
            return None
        return "male" if is_male else "female"

    def _ask_region(self, name: str) -> str | None:
        from autodub.speech.tts.voices import REGIONS

        labels = ["Không rõ", *(label for label, _key in REGIONS)]
        keys = ["", *(key for _label, key in REGIONS)]
        choice, ok = QInputDialog.getItem(
            self, "Vùng miền của giọng",
            f"Giọng «{name}» nghe giống vùng nào?", labels, 0, False)
        if not ok:
            return None
        return keys[labels.index(choice)]

    def _run_enroll(self, settings, wav: str, name: str, gender: str,
                    region: str) -> None:
        from autodub.speech.tts.vieneu_vi import _WORKER_SCRIPT

        command = [
            settings.vieneu_venv_python_path(), _WORKER_SCRIPT,
            "--model-dir", settings.vieneu_model_dir_path(),
            "--custom-voices", settings.vieneu_custom_voices_path(),
            "--enroll", wav, "--enroll-name", name,
            "--enroll-gender", gender, "--enroll-region", region,
        ]
        self.status.setText(
            f"Đang học giọng «{name}», khoảng một phút. Đừng tắt ứng dụng.")
        self.btn_enroll.set_loading(True, "Đang học giọng")

        class _Enroller(QThread):
            def __init__(self, parent):
                super().__init__(parent)
                self.error = ""

            def run(self) -> None:
                try:
                    flags = (subprocess.CREATE_NO_WINDOW
                             if os.name == "nt" else 0)
                    result = subprocess.run(
                        command, capture_output=True, encoding="utf-8",
                        errors="replace", timeout=_ENROLL_TIMEOUT_S,
                        creationflags=flags)
                    payload = _last_json_line(result.stdout or "")
                    if not payload.get("ok"):
                        self.error = (payload.get("error")
                                      or (result.stderr or "")[-300:]
                                      or "không rõ nguyên nhân")
                except Exception as e:  # noqa: BLE001 — báo lên giao diện
                    self.error = f"{type(e).__name__}: {e}"

        worker = _Enroller(self)

        def _done() -> None:
            self.btn_enroll.set_loading(False)
            self._thread = None
            if worker.error:
                self.status.setText("")
                ConfirmDialog.show_error(
                    self, "Không học được giọng",
                    "Ứng dụng không tạo được giọng từ đoạn ghi âm này. Hãy "
                    "thử một đoạn khác dài 3 đến 10 giây, giọng rõ và không "
                    "có nhạc nền.", detail=worker.error)
                return
            self.picker.reload()
            self.picker.set_voice(name)
            self.status.setText(
                f"{STATUS_OK} Đã thêm giọng «{name}». Bấm Nghe thử ở khung "
                "bên dưới để kiểm tra, rồi Lưu cài đặt để dùng.")
            self.changed.emit()

        worker.finished.connect(_done)
        self._thread = worker
        worker.start()

    def cleanup(self) -> None:
        """Chờ luồng học giọng xong — hủy QThread đang chạy làm Qt crash cứng."""
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(10_000)


class ConnectionChecks(CollapsibleSection):
    """Thử kết nối tới máy chủ VoxDub và hiện số Vox còn lại.

    Không còn API Key nào để kiểm tra: mô hình và mã đều nằm trên máy chủ.
    Thứ người dùng cần biết khi nghi ngờ chỉ còn hai điều — máy chủ có trả
    lời không, và ví còn bao nhiêu.
    """

    def __init__(self, values_provider=None, parent: QWidget | None = None):
        super().__init__("Kiểm tra kết nối", expanded=False, parent=parent)
        del values_provider     # giữ chữ ký cũ cho các nơi đang gọi
        self._threads: dict[str, QThread] = {}
        self._labels: dict[str, QLabel] = {}

        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        button = GhostButton("Kiểm tra máy chủ VoxDub")
        label = _hint_label("")
        self._labels["server"] = label
        button.clicked.connect(
            lambda _c=False, b=button: self._run("server", b, self._probe_server))
        row.addWidget(button)
        row.addWidget(label, 1)
        self.add_layout(row)

    def select_engine(self, engine: str) -> None:
        """Giữ chữ ký cũ — không còn nơi dịch nào để chọn."""
        del engine

    def _run(self, key: str, button: GhostButton, probe) -> None:
        """Chạy phép thử ở luồng nền để cửa sổ không bị đứng."""
        label = self._labels[key]
        button.set_loading(True, "Đang kiểm tra")
        label.setText("")

        class _Checker(QThread):
            def __init__(self, parent):
                super().__init__(parent)
                self.text = ""

            def run(self) -> None:
                try:
                    self.text = probe()
                except Exception as e:  # noqa: BLE001 — báo lên giao diện
                    self.text = f"Không kiểm tra được: {type(e).__name__}: {e}"

        checker = _Checker(self)

        def _done() -> None:
            button.set_loading(False)
            label.setText(checker.text)
            self._threads.pop(key, None)

        checker.finished.connect(_done)
        self._threads[key] = checker
        checker.start()

    def cleanup(self) -> None:
        """Chờ các luồng kiểm tra kết nối xong trước khi teardown."""
        for checker in list(self._threads.values()):
            if checker.isRunning():
                checker.wait(10_000)

    @staticmethod
    def _probe_server() -> str:
        from autodub.saas_client import SaasError, get_client, is_configured

        if not is_configured():
            return (f"{STATUS_OK} Đang chạy thuần trên máy — không cần máy "
                    "chủ. Bước dịch làm tay theo hướng dẫn hiện trong app.")
        client = get_client()
        try:
            device = client.ensure_session()
        except SaasError as e:
            return f"{STATUS_WARN} {e}"
        if not device.get("creditEnabled", True):
            return f"{STATUS_OK} Máy chủ trả lời bình thường. Đang miễn phí."
        return (f"{STATUS_OK} Máy chủ trả lời bình thường. "
                f"Ví còn {int(device.get('balance', 0)):,} Vox.")


class MaintenancePanel(CollapsibleSection):
    """Các nút mở thư mục, dọn dữ liệu tạm và xuất nhật ký chẩn đoán."""

    DIAGNOSTIC_FILE = "voxdub_diagnostics.txt"

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__("Bảo trì", expanded=False, parent=parent)
        self._settings_provider = settings_provider
        buttons = (
            ("Mở thư mục cấu hình", self._open_config),
            ("Mở thư mục dữ liệu giọng", self._open_models),
            ("Xóa dữ liệu đã lưu tạm", self._clear_cache),
            ("Xuất nhật ký chẩn đoán", self._export_diagnostics),
        )
        for text, handler in buttons:
            row = QHBoxLayout()
            button = GhostButton(text)
            button.clicked.connect(handler)
            row.addWidget(button)
            row.addStretch()
            self.add_layout(row)
        self.status = _hint_label(
            "Dữ liệu lưu tạm gồm ảnh đại diện và dạng sóng đã tính sẵn. "
            "Xóa đi chỉ làm lần mở sau chậm hơn một chút, không mất video nào.")
        self.add_widget(self.status)

    def _open_config(self) -> None:
        from autodub.utils import app_root
        from autodub_gui.system_open import open_folder

        ok, message = open_folder(app_root())
        if not ok:
            TOASTS.warn(message)

    def _open_models(self) -> None:
        from autodub.utils import app_root
        from autodub_gui.system_open import open_folder

        path = os.path.join(app_root(), "models")
        os.makedirs(path, exist_ok=True)
        ok, message = open_folder(path)
        if not ok:
            TOASTS.warn(message)

    def _clear_cache(self) -> None:
        """Xóa ảnh đại diện và dạng sóng đã tính sẵn của mọi dự án."""
        confirmed, _ = ConfirmDialog.ask(
            self, "Xóa dữ liệu đã lưu tạm",
            "Ảnh đại diện và dạng sóng đã tính sẵn sẽ bị xóa. Video và bản "
            "dịch của bạn không bị ảnh hưởng. Lần mở sau sẽ chậm hơn một chút "
            "vì phải tính lại.",
            kind="warning", confirm_label="Xóa dữ liệu tạm")
        if not confirmed:
            return
        removed = self._remove_cache_files()
        TOASTS.success(f"Đã xóa {removed} tệp lưu tạm.")

    def _remove_cache_files(self) -> int:
        from autodub_gui.projects import INDEX_FILE, THUMB_FILE

        try:
            output_dir = self._settings_provider().output_dir
        except Exception:  # noqa: BLE001 — cấu hình hỏng thì bỏ qua
            return 0
        targets = {THUMB_FILE, INDEX_FILE}
        removed = 0
        for root, _dirs, files in os.walk(output_dir):
            for name in files:
                # waveform_peaks*.json: đệm dạng sóng, gồm cả các track phụ
                if (name in targets
                        or (name.startswith("waveform_peaks")
                            and name.endswith(".json"))):
                    try:
                        os.remove(os.path.join(root, name))
                        removed += 1
                    except OSError:
                        continue
        return removed

    def _export_diagnostics(self) -> None:
        """Ghi một tệp chữ mô tả tình trạng máy, dùng khi cần nhờ hỗ trợ."""
        from autodub.utils import app_root

        path = os.path.join(app_root(), self.DIAGNOSTIC_FILE)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._diagnostic_lines()))
        except OSError as e:
            ConfirmDialog.show_error(
                self, "Không ghi được nhật ký",
                "Ứng dụng không tạo được tệp nhật ký chẩn đoán. Có thể thư "
                "mục cài đặt không cho ghi.", detail=str(e))
            return
        TOASTS.success("Đã ghi nhật ký chẩn đoán cạnh ứng dụng.",
                       action_label="Mở thư mục",
                       on_action=self._open_config)

    def _diagnostic_lines(self) -> list[str]:
        import platform
        import shutil
        import sys

        from autodub.utils import app_root, gpu_venv_dir

        try:
            settings = self._settings_provider()
            from autodub.speech.tts.voices import catalog

            ready = {
                "Giọng đọc VieNeu": settings.vieneu_configured(),
                "Nhận dạng Paraformer": settings.paraformer_configured(),
                "Dịch tự động": settings.translate_enabled,
            }
            voice_count = len(catalog(settings))
            output_dir = settings.output_dir
        except Exception as e:  # noqa: BLE001 — vẫn ghi được phần còn lại
            ready, output_dir, voice_count = {}, f"không đọc được ({e})", 0
        lines = [
            "Nhật ký chẩn đoán VoxDub Studio",
            f"Hệ điều hành: {platform.platform()}",
            f"Phiên bản Python: {sys.version.split()[0]}",
            f"Thư mục ứng dụng: {app_root()}",
            f"Thư mục lưu video: {output_dir}",
            f"FFmpeg: {'có' if shutil.which('ffmpeg') else 'chưa cài'}",
            f"FFprobe: {'có' if shutil.which('ffprobe') else 'chưa cài'}",
            f"Venv card đồ họa: {gpu_venv_dir() or 'chưa có'}",
            f"Số giọng đọc đang có: {voice_count}",
        ]
        lines.extend(f"{name}: {'sẵn sàng' if ok else 'chưa sẵn sàng'}"
                     for name, ok in ready.items())
        return lines


class DiskUsagePanel(CollapsibleSection):
    """Đo dung lượng thư mục kết quả và dọn tệp trung gian của dự án đã xong.

    Việc đo quét cả cây thư mục nên chạy ở luồng nền; nút dọn chỉ bật khi
    thật sự có gì để dọn, và luôn hỏi lại trước khi xóa.
    """

    def __init__(self, settings_provider, parent: QWidget | None = None):
        super().__init__("Dung lượng đĩa", expanded=False, parent=parent)
        self._settings_provider = settings_provider
        self._thread: QThread | None = None
        self._report = None

        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        self.btn_measure = GhostButton("Đo dung lượng")
        self.btn_measure.clicked.connect(self._measure)
        self.btn_clean = GhostButton("Dọn tệp trung gian")
        self.btn_clean.setEnabled(False)
        self.btn_clean.clicked.connect(self._clean)
        row.addWidget(self.btn_measure)
        row.addWidget(self.btn_clean)
        row.addStretch()
        self.add_layout(row)

        self.status = _hint_label(
            "Mỗi dự án đã xuất xong còn giữ tệp trung gian (âm thanh tách "
            "nhạc, từng đoạn giọng đọc) nặng gấp nhiều lần video kết quả. "
            "Bấm Đo dung lượng để xem đang chiếm bao nhiêu.")
        self.add_widget(self.status)

    def _output_dir(self) -> str:
        try:
            return self._settings_provider().output_dir
        except Exception:  # noqa: BLE001 — cấu hình hỏng thì bỏ qua
            return ""

    def _measure(self) -> None:
        from autodub.diskspace import measure

        output_dir = self._output_dir()
        if not output_dir:
            self.status.setText(f"{STATUS_WARN} Không đọc được thư mục kết quả "
                                "từ cấu hình.")
            return
        self.btn_measure.set_loading(True, "Đang đo")
        self.btn_clean.setEnabled(False)

        class _Scanner(QThread):
            def __init__(self, parent):
                super().__init__(parent)
                self.report = None

            def run(self) -> None:
                try:
                    self.report = measure(output_dir)
                except Exception:  # noqa: BLE001 — coi như thư mục rỗng
                    self.report = None

        worker = _Scanner(self)

        def _done() -> None:
            self.btn_measure.set_loading(False)
            self._thread = None
            self._report = worker.report
            self._show_report()

        worker.finished.connect(_done)
        self._thread = worker
        worker.start()

    def _show_report(self) -> None:
        from autodub_gui.formatting import format_size

        report = self._report
        if report is None or not report.project_count:
            self.status.setText(
                "Chưa có dự án nào trong thư mục kết quả, hoặc thư mục "
                "chưa tồn tại.")
            return
        cleanable = report.cleanable_bytes
        text = (f"{report.project_count} dự án đang chiếm "
                f"{format_size(report.total_bytes)}.")
        if cleanable:
            text += (f" Trong đó {format_size(cleanable)} là tệp trung gian "
                     "của dự án đã xong, dọn được ngay.")
        else:
            text += " Không có tệp trung gian nào dọn được."
        self.status.setText(text)
        self.btn_clean.setEnabled(bool(cleanable))

    def _clean(self) -> None:
        from autodub.diskspace import clean_all
        from autodub_gui.formatting import format_size

        report = self._report
        if report is None or not report.cleanable_bytes:
            return
        confirmed, _ = ConfirmDialog.ask(
            self, "Dọn tệp trung gian",
            f"Ứng dụng sẽ giải phóng {format_size(report.cleanable_bytes)} "
            "từ các dự án đã xuất xong. Video kết quả, phụ đề và nội dung "
            "đăng kênh được giữ nguyên. Lưu ý: sau khi dọn sẽ không sửa "
            "từng câu hay xuất lại được các dự án đó nữa.",
            kind="warning", confirm_label="Dọn ngay")
        if not confirmed:
            return
        output_dir = self._output_dir()
        self.btn_clean.set_loading(True, "Đang dọn")

        class _Cleaner(QThread):
            def __init__(self, parent):
                super().__init__(parent)
                self.cleaned = 0
                self.freed = 0

            def run(self) -> None:
                try:
                    self.cleaned, self.freed = clean_all(output_dir)
                except Exception:  # noqa: BLE001 — phần dọn được vẫn đã dọn
                    pass

        worker = _Cleaner(self)

        def _done() -> None:
            self.btn_clean.set_loading(False)
            self.btn_clean.setEnabled(False)
            self._thread = None
            self._report = None
            if worker.freed:
                TOASTS.success(f"Đã dọn {worker.cleaned} dự án, giải phóng "
                               f"{format_size(worker.freed)}.")
                self.status.setText("Bấm Đo dung lượng để xem lại con số mới.")
            else:
                TOASTS.warn("Không dọn được gì. Có thể tệp đang được mở "
                            "ở nơi khác.")

        worker.finished.connect(_done)
        self._thread = worker
        worker.start()

    def cleanup(self) -> None:
        """Chờ luồng đo/dọn đĩa xong trước khi teardown."""
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(10_000)


def _last_json_line(output: str) -> dict:
    """Lấy dòng JSON cuối cùng trong đầu ra của tiến trình con."""
    for line in reversed(output.strip().splitlines()):
        if line.lstrip().startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {}
