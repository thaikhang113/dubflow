"""Sáu ô cấu hình của trang Tạo dự án.

Mỗi bước là một widget độc lập, tự giữ giá trị của mình và báo ra ngoài khi
có thay đổi. Trang cha chỉ lo chuyển qua lại giữa các bước và gom dữ liệu.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from autodub_gui import dub_constants as consts
from autodub_gui import tokens
from autodub_gui.formatting import format_size
from autodub_gui.ui.buttons import GhostButton, SegmentedControl
from autodub_gui.ui.inputs import (
    LabeledCombo, LabeledLineEdit, LabeledSlider, LabeledWidget,
)
from autodub_gui.ui.labels import ElidedLabel
from autodub_gui.ui.style import clear_background

STEP_NAMES = ("Video", "Nhận dạng", "Dịch thuật", "Giọng & Phụ đề",
              "Chạy dịch", "Xuất video")

VIDEO_FILTER = ("Video (*.mp4 *.mkv *.mov *.avi *.webm);;Tất cả tệp (*.*)")
_LARGE_FILE_BYTES = 4 * 1024 ** 3


class _StepPanel(QWidget):
    """Khung chung cho một bước: tiêu đề, mô tả ngắn rồi tới các ô nhập."""

    changed = Signal()

    def __init__(self, title: str, description: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        # Mỗi bước nằm trong một thẻ — để nền trong suốt thì nó ăn theo nền
        # của thẻ, không tự vẽ ra một khối tối rời rạc bên trong.
        clear_background(self)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(tokens.SP_4)
        heading = QLabel(title)
        heading.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_CARD_TITLE}px; "
            f"font-weight: 700; background: transparent;")
        note = QLabel(description)
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.body.addWidget(heading)
        self.body.addWidget(note)

    def finish(self) -> None:
        """Đẩy phần còn lại lên trên, gọi sau khi thêm hết các ô nhập."""
        self.body.addStretch()

    def is_complete(self) -> tuple[bool, str]:
        """Bước này đã đủ dữ liệu chưa, kèm lý do nếu chưa."""
        return True, ""


class VideoStep(_StepPanel):
    """Bước 1: chọn nguồn video."""

    SOURCES = [("Dán liên kết", "url"), ("Tải tệp lên", "file"),
               ("Tiếp tục dang dở", "resume")]

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Chọn video", "Dán liên kết, chọn tệp từ máy, hoặc "
                                       "chạy tiếp một dự án đang dở.", parent)
        self.source = SegmentedControl(self.SOURCES)
        self.source.selection_changed.connect(self._on_source)
        self.body.addWidget(LabeledWidget("Nguồn video", self.source))

        self.url = LabeledLineEdit(
            "Liên kết video", "https://www.youtube.com/watch?v=...",
            "Dán liên kết YouTube, Douyin hoặc liên kết tải trực tiếp")
        self.url.changed.connect(lambda _t: self.changed.emit())
        self.body.addWidget(self.url)

        self.file_row, self.file_edit = self._picker(
            "Tệp video trên máy", "Chưa chọn tệp nào", self._pick_file)
        self.body.addWidget(self.file_row)

        self.resume_row, self.resume_edit = self._picker(
            "Thư mục dự án đang dở", "Chọn thư mục kết quả của lần chạy trước",
            self._pick_folder)
        self.body.addWidget(self.resume_row)

        self.info = ElidedLabel("")
        self.info.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.body.addWidget(self.info)
        self.finish()
        self._on_source("url")

    def _picker(self, label: str, placeholder: str,
                handler) -> tuple[QWidget, LabeledLineEdit]:
        holder = QWidget()
        clear_background(holder)     # ăn theo nền của thẻ chứa nó
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SP_2)
        edit = LabeledLineEdit(label, placeholder)
        edit.changed.connect(lambda _t: self._on_path_changed())
        row = QHBoxLayout()
        row.addStretch()
        button = GhostButton("Chọn…")
        button.clicked.connect(handler)
        row.addWidget(button)
        layout.addWidget(edit)
        layout.addLayout(row)
        return holder, edit

    def _on_source(self, key: str) -> None:
        self.url.setVisible(key == "url")
        self.file_row.setVisible(key == "file")
        self.resume_row.setVisible(key == "resume")
        self.changed.emit()

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn video", os.path.expanduser("~"), VIDEO_FILTER)
        if path:
            self.file_edit.set_text(path)
            self.source.set_key("file")
            self._on_source("file")

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục dự án đang dở", "output")
        if path:
            self.resume_edit.set_text(path)
            self.source.set_key("resume")
            self._on_source("resume")

    def _on_path_changed(self) -> None:
        path = self.file_edit.text()
        if path and os.path.isfile(path):
            size = os.path.getsize(path)
            warn = ("  —  video rất lớn, xử lý có thể mất nhiều giờ"
                    if size > _LARGE_FILE_BYTES else "")
            self.info.setText(f"{os.path.basename(path)} · "
                              f"{format_size(size)}{warn}")
        else:
            self.info.setText("")
        self.changed.emit()

    def set_file(self, path: str) -> None:
        """Điền sẵn tệp khi người dùng kéo thả từ Trang chủ."""
        self.source.set_key("file")
        self._on_source("file")
        self.file_edit.set_text(path)

    def set_resume(self, work_dir: str) -> None:
        """Chuyển bước 1 sang «Tiếp tục dang dở» trỏ vào một dự án có sẵn.

        Trang cha gọi khi một lượt chạy dừng giữa chừng (lỗi, hết Vox, chờ
        dịch tay) — bấm chạy lại sẽ đi tiếp đúng dự án cũ thay vì tạo dự án
        mới và bị trừ Vox lần nữa.
        """
        self.source.set_key("resume")
        self._on_source("resume")
        self.resume_edit.set_text(work_dir)

    def values(self) -> dict:
        return {
            "source": self.source.current_key(),
            "url": self.url.text(),
            "file_path": self.file_edit.text(),
            "resume_dir": self.resume_edit.text(),
        }

    def load(self, data: dict) -> None:
        self.source.set_key(data.get("source", "url"))
        self.url.set_text(data.get("url", ""))
        self.file_edit.set_text(data.get("file_path", ""))
        self.resume_edit.set_text(data.get("resume_dir", ""))
        self._on_source(self.source.current_key())

    def is_complete(self) -> tuple[bool, str]:
        key = self.source.current_key()
        if key == "url" and not self.url.text():
            return False, "Hãy dán liên kết video trước khi đi tiếp."
        if key == "file":
            path = self.file_edit.text()
            if not path:
                return False, "Hãy chọn một tệp video trước khi đi tiếp."
            if not os.path.isfile(path):
                return False, "Không tìm thấy tệp này nữa. Hãy chọn lại."
        if key == "resume" and not os.path.isdir(self.resume_edit.text()):
            return False, "Hãy chọn thư mục dự án đang dở có thật trên máy."
        return True, ""


class RecognizeStep(_StepPanel):
    """Bước 2: nghe và chép lời video gốc, kèm cách xử lý nhạc nền."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Nghe và chép lời",
                         "Ứng dụng nghe video gốc rồi chép lại thành chữ. "
                         "Chép càng đúng thì bản dịch càng sát.", parent)
        from autodub_gui.ui.collapsible import CollapsibleSection

        self.engine = LabeledCombo(
            "Bộ nhận dạng", consts.ASR_ENGINES,
            "Whisper nghe được mọi ngôn ngữ. Paraformer chính xác hơn với "
            "video tiếng Trung nhưng phải cài thêm một lần.")
        self.model = LabeledCombo(
            "Độ chính xác", consts.WHISPER_MODELS,
            "Mức càng cao thì nghe càng đúng nhưng chạy càng lâu và tải "
            "về càng nặng.")
        self.language = LabeledCombo(
            "Ngôn ngữ trong video", consts.SOURCE_LANGS,
            "Cho biết video gốc nói tiếng gì.")
        self.auto_detect = QCheckBox("Để ứng dụng tự nhận ra ngôn ngữ")
        self.auto_detect.setToolTip(
            "Bật khi bạn không chắc video nói tiếng gì. Tắt thì dùng đúng "
            "ngôn ngữ bạn chọn ở trên, thường chính xác hơn.")
        self.auto_detect.toggled.connect(self._on_auto)
        for widget in (self.engine, self.model, self.language):
            widget.changed.connect(self.changed.emit)
        self.body.addWidget(self.engine)
        self.body.addWidget(self.model)
        self.body.addWidget(self.language)
        self.body.addWidget(self.auto_detect)

        # Nhạc nền — dọn về đây từ bước Xuất video cũ, vì tách giọng chạy
        # ngay sau bước nghe; gập lại mặc định cho gọn.
        self._bg_section = CollapsibleSection("Nhạc nền")
        self.background = LabeledCombo(
            "Cách giữ nhạc nền", consts.BG_MODES,
            "Tách giọng gốc giữ được nhạc nền hay nhất nhưng chạy lâu hơn.")
        self.background.changed.connect(self._on_background)
        self.duck = LabeledSlider(
            "Mức giảm tiếng gốc", -40.0, 0.0, 1.0,
            "Càng âm thì tiếng gốc càng nhỏ khi có lời thoại tiếng Việt.",
            " dB", decimals=0)
        self.duck.set_value(-12.0)
        self.duck.changed.connect(lambda _v: self.changed.emit())
        self._bg_section.add_widget(self.background)
        self._bg_section.add_widget(self.duck)
        self.body.addWidget(self._bg_section)
        self.finish()
        self._on_background()

    def _on_auto(self, checked: bool) -> None:
        self.language.setEnabled(not checked)
        self.changed.emit()

    def _on_background(self) -> None:
        self.duck.setEnabled(self.background.current_key() == "duck")
        self.changed.emit()

    def values(self) -> dict:
        return {
            "asr_engine": self.engine.current_key(),
            "whisper_model": self.model.current_key(),
            "source_lang": self.language.current_key(),
            "auto_detect": self.auto_detect.isChecked(),
            "bg_mode": self.background.current_key(),
            "bg_duck_db": self.duck.value(),
        }

    def load(self, data: dict) -> None:
        self.engine.set_key(data.get("asr_engine", "whisper"))
        self.model.set_key(data.get("whisper_model", "auto"))
        self.language.set_key(data.get("source_lang", "zh-CN"))
        self.auto_detect.setChecked(bool(data.get("auto_detect", False)))
        self.background.set_key(data.get("bg_mode", "demucs"))
        self.duck.set_value(float(data.get("bg_duck_db", -12.0)))
        self._on_background()


class TranslateStep(_StepPanel):
    """Bước 3: dịch sang tiếng Việt."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Dịch sang tiếng Việt",
                         "Chọn cách dịch và giọng văn cho bản dịch. Ngôn ngữ "
                         "đích luôn là tiếng Việt.", parent)
        self.source_view = QLabel("")
        self.source_view.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px; "
            f"background: {tokens.BG_INPUT}; border-radius: 8px; "
            f"padding: 8px 12px;")
        self.body.addWidget(LabeledWidget(
            "Dịch từ", self.source_view,
            "Lấy theo ngôn ngữ bạn chọn ở bước Nghe và chép lời."))

        target = QLabel("Tiếng Việt")
        target.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_BODY}px; "
            f"font-weight: 600; background: {tokens.BG_INPUT}; "
            f"border-radius: 8px; padding: 8px 12px;")
        self.body.addWidget(LabeledWidget(
            "Dịch sang", target, "Bản này chỉ lồng tiếng Việt."))

        # Hai lựa chọn quyết định giá của video — lưu lại vào Cài đặt khi
        # bấm chạy để các video sau dùng luôn, khỏi chọn lại.
        self.auto_translate = QCheckBox("Dịch tự động qua máy chủ VoxDub")
        self.auto_translate.setToolTip(
            "Bật: máy chủ dịch toàn bộ, 12 Vox mỗi câu thoại. Tắt: ứng dụng "
            "dừng ở bước dịch và hướng dẫn bạn dịch tay, còn 10 Vox mỗi câu.")
        self.auto_translate.setChecked(True)
        self.auto_translate.toggled.connect(self._on_auto_translate)
        self.body.addWidget(self.auto_translate)

        self.metadata = QCheckBox("Tạo tiêu đề + mô tả đăng bài (+20 Vox)")
        self.metadata.setToolTip(
            "Máy chủ viết sẵn tiêu đề, mô tả và thẻ cho mạng xã hội, lưu vào "
            "tệp youtube_post.txt trong thư mục dự án. Tắt đi nếu bạn tự viết.")
        self.metadata.setChecked(True)
        self.metadata.toggled.connect(lambda _c: self.changed.emit())
        self.body.addWidget(self.metadata)

        self.style = LabeledCombo(
            "Phong cách dịch",
            [(label, key) for label, key, _note in consts.TRANSLATE_STYLES],
            "Quyết định giọng văn của bản dịch, ví dụ trang trọng hay đời thường.")
        self.engine_row = LabeledWidget(
            "Dịch bằng", self._engine_view(),
            "Máy chủ VoxDub tự chọn mô hình tốt nhất — bạn không phải cấu "
            "hình gì.")
        self.note = LabeledLineEdit(
            "Ghi chú thêm cho người dịch",
            "ví dụ: giữ tên nhân vật Hán Việt, xưng hô mình với các bạn",
            "Ghi chú này được gửi kèm mỗi lần dịch.")
        self.style.changed.connect(self.changed.emit)
        self.note.changed.connect(lambda _t: self.changed.emit())
        self.body.addWidget(self.style)
        self.body.addWidget(self.engine_row)
        self.body.addWidget(self.note)

        self.manual_note = QLabel(
            "Đã tắt dịch tự động: chạy tới bước dịch, ứng dụng sẽ dừng lại và "
            "mở hướng dẫn để bạn tự dịch (theo TRANSLATE_PENDING.txt), xong "
            "bấm tiếp tục. Giá video vẫn tính theo số câu thoại.")
        self.manual_note.setWordWrap(True)
        self.manual_note.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.manual_note.setVisible(False)
        self.body.addWidget(self.manual_note)
        self.finish()

    @staticmethod
    def _engine_view() -> QLabel:
        view = QLabel("VoxDub Cloud")
        view.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_BODY}px; "
            f"font-weight: 600; background: {tokens.BG_INPUT}; "
            f"border-radius: 8px; padding: 8px 12px;")
        return view

    def _on_auto_translate(self, checked: bool) -> None:
        # Tắt dịch tự động thì phong cách và ghi chú không được gửi đi đâu
        # cả — mờ chúng đi cho khỏi gây hiểu lầm.
        for widget in (self.style, self.engine_row, self.note):
            widget.setEnabled(checked)
        self.manual_note.setVisible(not checked)
        self.changed.emit()

    def set_source_language(self, label: str) -> None:
        self.source_view.setText(label)

    def values(self) -> dict:
        return {
            "auto_translate": self.auto_translate.isChecked(),
            "generate_metadata": self.metadata.isChecked(),
            "translate_style": self.style.current_key(),
            "translate_note": self.note.text(),
        }

    def load(self, data: dict) -> None:
        # Nháp chưa có hai mục mới thì rơi về giá trị trong Cài đặt — hai
        # nơi luôn thống nhất, giống cách VoiceStep xử lý phụ đề.
        try:
            from autodub.config import Settings
            settings = Settings.load()
            fb_auto = settings.translate_enabled
            fb_meta = settings.generate_metadata
        except Exception:  # noqa: BLE001 — cấu hình hỏng thì dùng mặc định
            fb_auto, fb_meta = True, True
        self.auto_translate.setChecked(bool(data.get("auto_translate", fb_auto)))
        self.metadata.setChecked(bool(data.get("generate_metadata", fb_meta)))
        self.style.set_key(data.get("translate_style", "natural"))
        self.note.set_text(data.get("translate_note", ""))
        self._on_auto_translate(self.auto_translate.isChecked())


class VoiceStep(_StepPanel):
    """Bước 4: giọng đọc + phụ đề — hai lựa chọn cuối trước khi chạy."""

    preview_requested = Signal(str)     # tên giọng
    style_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Giọng đọc & phụ đề",
                         "Video này sẽ đọc bằng giọng mặc định bạn chọn trong "
                         "Cài đặt. Chọn thêm cách hiện phụ đề — sau khi chạy "
                         "xong vẫn sửa được trong Trình chỉnh sửa.",
                         parent)
        from autodub.media.subtitle import PRESET_CHOICES
        from autodub_gui.ui.collapsible import CollapsibleSection
        from autodub_gui.voice_picker import VoicePicker

        # Giọng mặc định đang dùng + nút nghe thử ngay
        default_row = QHBoxLayout()
        default_row.setSpacing(tokens.SP_2)
        self._default_label = ElidedLabel("")
        self._default_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_BODY}px; "
            f"font-weight: 600; background: transparent;")
        self._btn_default_preview = GhostButton("Nghe thử")
        self._btn_default_preview.clicked.connect(
            lambda: self.preview_requested.emit(self._default_voice()))
        default_row.addWidget(self._default_label, 1)
        default_row.addWidget(self._btn_default_preview)
        self.body.addLayout(default_row)

        # Đổi giọng riêng — gập lại mặc định; mở ra nghĩa là muốn ghi đè.
        self._override = CollapsibleSection("Đổi giọng riêng cho video này")
        self._override.toggled.connect(lambda _e: self.changed.emit())
        self.picker = VoicePicker("Giọng đọc")
        self.picker.changed.connect(self.changed.emit)
        self.picker.preview_requested.connect(self.preview_requested.emit)
        self._override.add_widget(self.picker)
        self.body.addWidget(self._override)

        self.speed = LabeledSlider(
            "Tốc độ đọc", 0.5, 2.0, 0.05,
            "1.00 là tốc độ tự nhiên. Tăng lên khi câu tiếng Việt dài hơn câu "
            "gốc và bị chồng sang câu sau.", "x")
        self.speed.set_value(1.0)
        self.speed.changed.connect(lambda _v: self.changed.emit())
        self.body.addWidget(self.speed)

        # Phụ đề — dọn về đây từ bước Phụ đề cũ (bước 5 giờ là Chạy dịch).
        self.mode = LabeledCombo(
            "Kiểu phụ đề", consts.SUBTITLE_MODES,
            "Phụ đề rời là tệp riêng, người xem tự bật tắt. Ghi thẳng vào "
            "hình thì chữ nằm luôn trên video.")
        self.mode.changed.connect(self.changed.emit)
        self.body.addWidget(self.mode)

        self.preset = LabeledCombo(
            "Bộ kiểu chữ", PRESET_CHOICES,
            "Chọn một bộ có sẵn là xong. Muốn tự quyết từng thông số thì bấm "
            "Kiểu chữ và vùng che.")
        self.preset.changed.connect(self.changed.emit)
        self.body.addWidget(self.preset)

        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        self.btn_style = GhostButton("Kiểu chữ và vùng che…")
        self.btn_style.clicked.connect(self.style_requested.emit)
        row.addWidget(self.btn_style)
        row.addStretch()
        self.body.addLayout(row)

        self.summary = QLabel("Kiểu mặc định, chưa che vùng nào")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.body.addWidget(self.summary)

        self.audio_only = QCheckBox("Chỉ xuất âm thanh và phụ đề, bỏ ghép video")
        self.audio_only.setToolTip(
            "Bật khi bạn tự dựng video ở phần mềm khác và chỉ cần tiếng Việt "
            "cùng tệp phụ đề.")
        self.audio_only.toggled.connect(lambda _c: self.changed.emit())
        self.body.addWidget(self.audio_only)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.body.addWidget(self.status)
        self.finish()
        self._refresh_default_label()

    @staticmethod
    def _default_voice() -> str:
        """Tên giọng mặc định trong Cài đặt, đọc lại mỗi lần cần."""
        from autodub.speech.tts.voices import DEFAULT_VOICE

        try:
            from autodub.config import Settings
            return Settings.load(override=True).vieneu_voice or DEFAULT_VOICE
        except Exception:  # noqa: BLE001 — cấu hình hỏng thì dùng giọng gốc
            return DEFAULT_VOICE

    def _refresh_default_label(self) -> None:
        self._default_label.setText(
            f"Giọng mặc định: {self._default_voice()}")
        self._default_label.setToolTip(
            "Đổi giọng mặc định trong Cài đặt, thẻ Giọng đọc.")

    def showEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        # Người dùng có thể vừa đổi giọng mặc định trong Cài đặt.
        self._refresh_default_label()
        super().showEvent(event)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)

    def values(self) -> dict:
        # Không mở phần đổi giọng thì trả về rỗng — pipeline sẽ tự dùng
        # giọng mặc định trong Cài đặt.
        return {
            "voice": (self.picker.voice()
                      if self._override.is_expanded() else ""),
            "voice_speed": self.speed.value(),
            "subtitle_mode": self.mode.current_key(),
            "subtitle_preset": self.preset.current_key(),
            "skip_video": self.audio_only.isChecked(),
        }

    def load(self, data: dict) -> None:
        voice = (data.get("voice") or "").strip()
        self.picker.reload()
        if voice:
            self.picker.set_voice(voice)
        self._override.set_expanded(bool(voice))
        self.speed.set_value(float(data.get("voice_speed", 1.0)))
        # Nháp không có mục nào thì rơi về giá trị trong Cài đặt, không
        # phải "none"/"clean" cứng — để hai nơi luôn thống nhất.
        try:
            from autodub.config import Settings
            settings = Settings.load()
            fb_mode = settings.subtitle_mode
            fb_preset = settings.subtitle_preset
        except Exception:  # noqa: BLE001 — cấu hình hỏng thì dùng mặc định
            fb_mode, fb_preset = "none", "clean"
        self.mode.set_key(data.get("subtitle_mode", fb_mode))
        self.preset.set_key(data.get("subtitle_preset", fb_preset))
        self.audio_only.setChecked(bool(data.get("skip_video", False)))
        self._refresh_default_label()


class RunStep(_StepPanel):
    """Bước 5: xem lại lựa chọn rồi chạy thật — tiến trình hiện ở cột trái."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Chạy dịch và lồng tiếng",
                         "Xem lại các lựa chọn rồi bấm Bắt đầu lồng tiếng. "
                         "Ứng dụng sẽ nghe, dịch và đọc toàn bộ video — "
                         "tiến trình và nhật ký hiện ở khung bên trái.", parent)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            f"background: {tokens.BG_INPUT}; border-radius: 8px; "
            f"padding: 10px 12px;")
        self.body.addWidget(LabeledWidget("Tóm tắt lựa chọn", self.summary))

        note = QLabel(
            "Giá của video chốt ngay sau bước nghe-chép, theo số câu thoại "
            "(10 Vox/câu, 12 nếu bật dịch tự động, +20 cho gói tiêu đề + mô "
            "tả) và không đổi nữa — ứng dụng báo tổng Vox trước khi trừ ví.")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.body.addWidget(note)
        self.finish()

    def set_summary(self, rows: list[tuple[str, str]]) -> None:
        """Đổ bảng tóm tắt hai cột."""
        lines = [f"<b>{name}:</b> {value}" for name, value in rows]
        self.summary.setText("<br>".join(lines))

    def values(self) -> dict:
        return {}

    def load(self, data: dict) -> None:
        pass


class ExportSummaryStep(_StepPanel):
    """Bước 6: tổng kết lần chạy và chốt Vox khi bấm Xuất video.

    Nút Xuất video là nút chính ở chân trang (do trang cha đổi nhãn khi
    đến bước này) — bước chỉ lo hiển thị số liệu.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Xuất video",
                         "Video đã lồng tiếng xong. Bấm Xuất video để nhận "
                         "video hoàn chỉnh — Vox của video này đã tính từ "
                         "đầu, bước này không tốn thêm.", parent)
        self.summary = QLabel("Chưa có lần chạy nào chờ xuất.")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px; "
            f"background: {tokens.BG_INPUT}; border-radius: 8px; "
            f"padding: 12px 14px;")
        self.body.addWidget(LabeledWidget("Tổng kết lần chạy", self.summary))

        self.notice = QLabel(
            "Chưa xuất thì chưa xem được bản dịch hay âm thanh — dữ liệu "
            "đang được khóa. Bỏ qua bước này thì dự án tự mở khóa sau 48 "
            "giờ, không tốn thêm Vox.")
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.body.addWidget(self.notice)
        self.finish()

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        mins, secs = divmod(int(seconds or 0), 60)
        return f"{mins} phút {secs:02d} giây" if mins else f"{secs} giây"

    def set_stats(self, sentences: int, duration_s: float,
                  usage: dict | None, hold: dict | None) -> None:
        """Đổ bảng tổng kết: thời lượng, số câu thoại, tổng Vox, số dư.

        Chỉ một con số tiền: TỔNG Vox của video, chốt từ lúc giữ chỗ và không
        đổi nữa. Không tách theo bước xử lý — người dùng không trả theo bước,
        bày ra chỉ khiến họ đi tìm cách tối ưu một thứ không tồn tại.

        ``usage``: snapshot từ USAGE ({"calls", "vox", "balance_after"}).
        ``hold``: dict hold từ máy chủ, dùng ``estimatedVox`` làm tổng.
        """
        total = int((hold or {}).get("estimatedVox")
                    or (usage or {}).get("vox") or 0)
        rows = [
            ("Thời lượng video", self._fmt_duration(duration_s)),
            ("Số câu thoại", f"{sentences:,}"),
            ("Tổng Vox của video", f"<b>{total:,} Vox</b>"),
        ]
        balance = int((usage or {}).get("balance_after") or 0)
        if balance:
            rows.append(("Số dư còn lại", f"{balance:,} Vox"))
        self.summary.setText(
            "<br>".join(f"<b>{name}:</b> {value}" for name, value in rows))

    def set_error(self, message: str) -> None:
        """Xuất trượt (thường do mất mạng) — nói rõ không tốn thêm Vox."""
        self.notice.setText(
            f"Chưa xuất được: {message}\nKhông tốn thêm Vox nào và dữ liệu "
            "vẫn được khóa an toàn. Kiểm tra mạng rồi bấm Xuất video lần nữa.")

    def values(self) -> dict:
        return {}

    def load(self, data: dict) -> None:
        pass
