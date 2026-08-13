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

STEP_NAMES = ("Chuẩn bị", "Nhận dạng", "Dịch thuật", "Giọng đọc",
              "Ghép tiếng", "Xuất video")

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

        self.mirror = QCheckBox("Lật ngang video")
        self.mirror.setToolTip(
            "Lật hình ảnh trước khi che chữ và ghi phụ đề. Có thể đổi lại "
            "trong Trình chỉnh sửa trước khi xuất.")
        self.mirror.stateChanged.connect(lambda _state: self.changed.emit())
        self.body.addWidget(self.mirror)

        self.ocr_enabled = QCheckBox("Tự động tìm và làm mờ chữ Trung")
        self.ocr_enabled.setToolTip(
            "OCR chỉ tìm phụ đề Trung để làm mờ. Tắt nếu video không có phụ đề cứng "
            "hoặc bạn chỉ muốn dùng vùng khoanh thủ công.")
        self.ocr_enabled.stateChanged.connect(lambda _state: self.changed.emit())
        self.body.addWidget(self.ocr_enabled)
        self.ocr_device = LabeledCombo(
            "Thiết bị OCR",
            [("Tự chọn GPU/CPU", "auto"), ("GPU", "gpu"), ("CPU", "cpu")],
            "GPU lỗi thì OCR tự quay về CPU để job vẫn chạy.")
        self.ocr_confidence = LabeledSlider(
            "Độ tin cậy OCR tối thiểu", 0.5, 0.99, 0.05,
            "Tăng lên nếu OCR nhận nhầm chữ.", decimals=2)
        self.ocr_region_area = LabeledSlider(
            "Diện tích vùng OCR tối đa", 0.02, 0.8, 0.05,
            "Bỏ qua vùng nhận diện quá lớn để tránh làm mờ nhầm.", decimals=2)
        self.ocr_y_min = LabeledSlider(
            "Vị trí bắt đầu phụ đề", 0.0, 0.95, 0.05,
            "Chỉ nhận chữ từ vị trí này xuống đáy khung hình.", decimals=2)
        self.ocr_interval = LabeledSlider(
            "Khoảng quét OCR", 0.5, 5.0, 0.5,
            "Khoảng thời gian giữa hai lần quét.", " giây", decimals=1)

        from autodub_gui.ui.collapsible import CollapsibleSection
        self._video_options = CollapsibleSection("Che chữ và branding")
        self.logo_path, self.logo_edit = self._picker(
            "Logo cá nhân", "Chưa chọn logo PNG/JPG", self._pick_logo,
        )
        self.intro_path, self.intro_edit = self._picker(
            "Video intro", "Không dùng intro", self._pick_intro,
        )
        self.outro_path, self.outro_edit = self._picker(
            "Video outro", "Không dùng outro", self._pick_outro,
        )
        self.logo_region = LabeledLineEdit(
            "Vùng logo nguồn (JSON tùy chọn)", "",
            "Ví dụ: {\"x\":0.8,\"y\":0.05,\"w\":0.18,\"h\":0.12}. "
            "Để trống để dùng Vision hoặc vùng mặc định.")
        self.vision_enabled = QCheckBox("Tự dò logo nguồn bằng Vision/Ollama")
        self.vision_model = LabeledLineEdit(
            "Model Vision", "deepseek-vl", "Tên model Ollama đã cài.")
        self.logo_opacity = LabeledSlider(
            "Độ trong logo", 0.0, 1.0, 0.05, suffix="", decimals=2)
        self.logo_scale = LabeledSlider(
            "Kích thước logo", 0.01, 1.0, 0.01, suffix="", decimals=2)
        for widget in (
            self.ocr_device, self.ocr_confidence, self.ocr_region_area,
            self.ocr_y_min, self.ocr_interval,
            self.logo_region, self.vision_enabled, self.vision_model,
            self.logo_opacity, self.logo_scale,
        ):
            self._video_options.add_widget(widget)
        self._video_options.add_widget(self.logo_path)
        self._video_options.add_widget(self.intro_path)
        self._video_options.add_widget(self.outro_path)
        self.body.addWidget(self._video_options)

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

    def _pick_asset(self, title: str, edit: LabeledLineEdit,
                    filters: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, title, os.path.expanduser("~"), filters)
        if path:
            edit.set_text(path)
            self.changed.emit()

    def _pick_logo(self) -> None:
        self._pick_asset("Chọn logo cá nhân", self.logo_edit,
                         "Ảnh (*.png *.jpg *.jpeg *.webp);;Tất cả tệp (*.*)")

    def _pick_intro(self) -> None:
        self._pick_asset("Chọn video intro", self.intro_edit, VIDEO_FILTER)

    def _pick_outro(self) -> None:
        self._pick_asset("Chọn video outro", self.outro_edit, VIDEO_FILTER)

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
            "mirror": self.mirror.isChecked(),
            "ocr_enabled": self.ocr_enabled.isChecked(),
            "ocr_device": self.ocr_device.current_key(),
            "ocr_min_confidence": self.ocr_confidence.value(),
            "ocr_max_region_area": self.ocr_region_area.value(),
            "ocr_subtitle_y_min": self.ocr_y_min.value(),
            "ocr_sample_interval": self.ocr_interval.value(),
            "logo_path": self.logo_edit.text(),
            "intro_path": self.intro_edit.text(),
            "outro_path": self.outro_edit.text(),
            "logo_region": self.logo_region.text(),
            "logo_opacity": self.logo_opacity.value(),
            "logo_scale": self.logo_scale.value(),
            "vision_enabled": self.vision_enabled.isChecked(),
            "vision_model": self.vision_model.text(),
        }

    def load(self, data: dict) -> None:
        self.source.set_key(data.get("source", "url"))
        self.url.set_text(data.get("url", ""))
        self.file_edit.set_text(data.get("file_path", ""))
        self.resume_edit.set_text(data.get("resume_dir", ""))
        self.mirror.setChecked(bool(data.get("mirror", False)))
        self.ocr_enabled.setChecked(
            bool(data.get("ocr_enabled", self.ocr_enabled.isChecked())))
        self.ocr_device.set_key(data.get("ocr_device", "auto"))
        self.ocr_confidence.set_value(float(
            data.get("ocr_min_confidence", 0.8)))
        self.ocr_region_area.set_value(float(
            data.get("ocr_max_region_area", 0.25)))
        self.ocr_y_min.set_value(float(data.get("ocr_subtitle_y_min", 0.65)))
        self.ocr_interval.set_value(float(data.get("ocr_sample_interval", 1.0)))
        self.logo_edit.set_text(data.get("logo_path", ""))
        self.intro_edit.set_text(data.get("intro_path", ""))
        self.outro_edit.set_text(data.get("outro_path", ""))
        self.logo_region.set_text(data.get("logo_region", ""))
        self.logo_opacity.set_value(float(data.get("logo_opacity", 1.0)))
        self.logo_scale.set_value(float(data.get("logo_scale", 0.2)))
        self.vision_enabled.setChecked(bool(data.get("vision_enabled", True)))
        self.vision_model.set_text(data.get("vision_model", "deepseek-vl"))
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
        self.engine = LabeledCombo(
            "Bộ nhận dạng", consts.ASR_ENGINES,
            "Whisper nghe được mọi ngôn ngữ. Paraformer chính xác hơn với "
            "video tiếng Trung nhưng phải cài thêm một lần.")
        self.model = LabeledCombo(
            "Độ chính xác", consts.WHISPER_MODELS,
            "Mức càng cao thì nghe càng đúng nhưng chạy càng lâu và tải "
            "về càng nặng.")
        self.quality = LabeledCombo(
            "Preset chất lượng",
            [("Nhanh", "fast"), ("Cân bằng", "balanced"),
             ("Chất lượng cao", "quality")],
            "Chọn mức cân bằng giữa tốc độ, độ chính xác và chất lượng âm thanh.")
        self.language = LabeledCombo(
            "Ngôn ngữ trong video", consts.SOURCE_LANGS,
            "Cho biết video gốc nói tiếng gì.")
        self.auto_detect = QCheckBox("Để ứng dụng tự nhận ra ngôn ngữ")
        self.auto_detect.setToolTip(
            "Bật khi bạn không chắc video nói tiếng gì. Tắt thì dùng đúng "
            "ngôn ngữ bạn chọn ở trên, thường chính xác hơn.")
        self.auto_detect.toggled.connect(self._on_auto)
        for widget in (self.engine, self.model, self.quality, self.language):
            widget.changed.connect(lambda: self.changed.emit())
        self.body.addWidget(self.engine)
        self.body.addWidget(self.model)
        self.body.addWidget(self.quality)
        self.body.addWidget(self.language)
        self.body.addWidget(self.auto_detect)

        self.asr_threads = LabeledSlider(
            "Số luồng nhận dạng", 1, 16, 1,
            "Tăng để nhận dạng nhanh hơn nếu máy còn dư CPU.",
            " luồng", decimals=0)
        self.beam_size = LabeledSlider(
            "Beam size Whisper", 1, 10, 1,
            "Cao hơn thường chính xác hơn nhưng chạy lâu hơn.",
            "", decimals=0)
        self.sample_rate = LabeledCombo(
            "Tần số âm thanh xử lý",
            [("16 kHz · nhẹ hơn", "16000"),
             ("24 kHz · cân bằng", "24000"),
             ("48 kHz · giữ chi tiết", "48000")],
            "Tần số cao giữ âm thanh tốt hơn nhưng tốn thêm CPU và đĩa.")
        self.body.addWidget(self.asr_threads)
        self.body.addWidget(self.beam_size)
        self.body.addWidget(self.sample_rate)
        self.sample_rate.changed.connect(lambda: self.changed.emit())

        self.finish()

    def _on_auto(self, checked: bool) -> None:
        self.language.setEnabled(not checked)
        self.changed.emit()

    def values(self) -> dict:
        return {
            "asr_engine": self.engine.current_key(),
            "whisper_model": self.model.current_key(),
            "quality_preset": self.quality.current_key(),
            "source_lang": self.language.current_key(),
            "auto_detect": self.auto_detect.isChecked(),
            "asr_threads": int(self.asr_threads.value()),
            "beam_size": int(self.beam_size.value()),
            "audio_sample_rate": int(self.sample_rate.current_key()),
        }

    def load(self, data: dict) -> None:
        self.engine.set_key(data.get("asr_engine", "whisper"))
        self.model.set_key(data.get("whisper_model", "auto"))
        self.quality.set_key(data.get("quality_preset", "balanced"))
        self.language.set_key(data.get("source_lang", "zh-CN"))
        self.auto_detect.setChecked(bool(data.get("auto_detect", False)))
        self.asr_threads.set_value(float(data.get("asr_threads", 4)))
        self.beam_size.set_value(float(data.get("beam_size", 5)))
        self.sample_rate.set_key(str(data.get("audio_sample_rate", 16000)))


class TranslateStep(_StepPanel):
    """Bước 3: dịch sang tiếng Việt."""

    style_requested = Signal()

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
        self.auto_translate = QCheckBox("Dịch tự động qua API đã cấu hình")
        self.auto_translate.setToolTip(
            "Bật: dùng endpoint, API key và model đã chọn trong trang Dịch thuật.")
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
            "Dùng model đã chọn trong trang Dịch thuật.")
        self.note = LabeledLineEdit(
            "Ghi chú thêm cho người dịch",
            "ví dụ: giữ tên nhân vật Hán Việt, xưng hô mình với các bạn",
            "Ghi chú này được gửi kèm mỗi lần dịch.")
        self.domain = LabeledLineEdit(
            "Chủ đề / lĩnh vực",
            "ví dụ: review công nghệ, cổ trang, game",
            "Giúp model chọn thuật ngữ và giọng văn đúng ngữ cảnh.")
        self.video_title = LabeledLineEdit(
            "Tiêu đề hoặc tên video",
            "Ví dụ: Review điện thoại mới",
            "Dùng làm ngữ cảnh cho model dịch; để trống thì lấy tiêu đề từ video.")
        self.context = LabeledLineEdit(
            "Bối cảnh nội dung",
            "Mô tả nhân vật, tình huống, nội dung video",
            "Thông tin nền gửi kèm khi dịch.")
        self.pronouns = LabeledLineEdit(
            "Quy ước xưng hô",
            "ví dụ: mình - các bạn, ta - ngươi",
            "Giữ cách xưng hô nhất quán.")
        self.glossary = LabeledLineEdit(
            "Bảng thuật ngữ",
            "Mỗi dòng: từ gốc = bản dịch",
            "Thuật ngữ cố định ưu tiên hơn bản dịch tự do.")
        self.cps_budget = LabeledSlider(
            "Độ dài bản dịch mỗi giây", 8.0, 20.0, 0.5,
            "Thấp hơn giúp câu tiếng Việt ngắn, dễ khớp thời lượng.",
            " ký tự/giây", decimals=1)
        self.batch_size = LabeledSlider(
            "Số câu mỗi lượt dịch", 1, 40, 1,
            "Lượt nhỏ dễ retry hơn; lượt lớn giảm số lần gọi API.",
            " câu", decimals=0)
        self.style.changed.connect(lambda: self.changed.emit())
        self.note.changed.connect(lambda _t: self.changed.emit())
        self.video_title.changed.connect(lambda _t: self.changed.emit())
        self.domain.changed.connect(lambda _t: self.changed.emit())
        self.context.changed.connect(lambda _t: self.changed.emit())
        self.pronouns.changed.connect(lambda _t: self.changed.emit())
        self.glossary.changed.connect(lambda _t: self.changed.emit())
        self.cps_budget.changed.connect(lambda _v: self.changed.emit())
        self.batch_size.changed.connect(lambda _v: self.changed.emit())
        self.body.addWidget(self.style)
        self.body.addWidget(self.engine_row)
        self.body.addWidget(self.note)
        self.body.addWidget(self.domain)
        self.body.addWidget(self.video_title)
        self.body.addWidget(self.context)
        self.body.addWidget(self.pronouns)
        self.body.addWidget(self.glossary)
        self.body.addWidget(self.cps_budget)
        self.body.addWidget(self.batch_size)

        style_row = QHBoxLayout()
        self.btn_subtitle_style = GhostButton("Tùy chỉnh phụ đề và vùng che…")
        self.btn_subtitle_style.setToolTip(
            "Chỉnh font, màu, viền, vị trí phụ đề và khoanh vùng chữ cần che.")
        self.btn_subtitle_style.clicked.connect(self.style_requested.emit)
        style_row.addWidget(self.btn_subtitle_style)
        style_row.addStretch()
        self.body.addLayout(style_row)
        self.subtitle_style_summary = QLabel(
            "Kiểu mặc định, chưa che vùng nào")
        self.subtitle_style_summary.setWordWrap(True)
        self.subtitle_style_summary.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.body.addWidget(self.subtitle_style_summary)

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
        view = QLabel("API provider")
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
            "translate_domain": self.domain.text(),
            "translate_video_title": self.video_title.text(),
            "translate_context": self.context.text(),
            "translate_pronouns": self.pronouns.text(),
            "translate_glossary": self.glossary.text(),
            "translate_cps_budget": self.cps_budget.value(),
            "translate_batch_size": int(self.batch_size.value()),
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
        self.domain.set_text(data.get("translate_domain", ""))
        self.video_title.set_text(data.get("translate_video_title", ""))
        self.context.set_text(data.get("translate_context", ""))
        self.pronouns.set_text(data.get("translate_pronouns", ""))
        self.glossary.set_text(data.get("translate_glossary", ""))
        self.cps_budget.set_value(float(data.get("translate_cps_budget", 12.5)))
        self.batch_size.set_value(float(data.get("translate_batch_size", 20)))
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
        self.picker.changed.connect(lambda: self.changed.emit())
        self.picker.preview_requested.connect(self.preview_requested.emit)
        self._override.add_widget(self.picker)
        self.body.addWidget(self._override)

        self.clone_voice = QCheckBox(
            "Tu dong nhan dien va clone tung nguoi noi"
        )
        self.clone_voice.setToolTip(
            "Tự động gom các câu theo từng nhân vật, tạo voice clone VieNeu "
            "riêng và gán lại khi lồng tiếng. Nếu thiếu audio, dùng voice preset."
        )
        self.clone_voice.toggled.connect(self._on_clone_toggled)
        self.body.addWidget(self.clone_voice)

        self.clone_source = LabeledCombo(
            "Nguon audio mau",
            [("Tu lay tu video", "video"),
             ("Chon file audio mau", "file")],
            "Video can bat tach giong. File mau nen la WAV/MP3/M4A, dai 1 den 8 giay.")
        self.clone_source.changed.connect(self._on_clone_source)
        self.body.addWidget(self.clone_source)

        clone_holder = QWidget()
        clear_background(clone_holder)
        clone_layout = QVBoxLayout(clone_holder)
        clone_layout.setContentsMargins(0, 0, 0, 0)
        clone_layout.setSpacing(tokens.SP_2)
        self.clone_reference_audio = LabeledLineEdit(
            "File audio mau",
            "Chua chon file audio",
            "Chon mot doan giong sach cua nguoi can clone.")
        self.clone_reference_audio.changed.connect(
            lambda _text: self.changed.emit())
        clone_layout.addWidget(self.clone_reference_audio)
        clone_button_row = QHBoxLayout()
        clone_button_row.addStretch()
        clone_button = GhostButton("Chon file...")
        clone_button.clicked.connect(self._pick_clone_reference)
        clone_button_row.addWidget(clone_button)
        clone_layout.addLayout(clone_button_row)
        self.clone_reference_holder = clone_holder
        self.body.addWidget(clone_holder)

        self.clone_min_seconds = LabeledSlider(
            "Độ dài audio tối thiểu để clone", 1.0, 8.0, 0.5,
            "Đoạn quá ngắn sẽ dùng giọng preset thay vì clone.",
            " giây", decimals=1)
        self.clone_max_seconds = LabeledSlider(
            "Độ dài audio tối đa để clone", 1.0, 8.0, 0.5,
            "Giới hạn đoạn lấy mẫu cho mỗi người nói.",
            " giây", decimals=1)
        self.clone_workers = LabeledSlider(
            "Số luồng tạo giọng", 1, 8, 1,
            "Tăng tốc clone nếu máy còn RAM; mỗi luồng dùng thêm bộ nhớ.",
            " luồng", decimals=0)
        for widget in (self.clone_min_seconds, self.clone_max_seconds,
                       self.clone_workers):
            self.body.addWidget(widget)
            widget.changed.connect(lambda _v: self.changed.emit())

        self.speed = LabeledSlider(
            "Tốc độ đọc", 0.5, 2.0, 0.05,
            "1.00 là tốc độ tự nhiên. Tăng lên khi câu tiếng Việt dài hơn câu "
            "gốc và bị chồng sang câu sau.", "x")
        self.speed.set_value(1.0)
        self.speed.changed.connect(lambda _v: self.changed.emit())
        self.body.addWidget(self.speed)
        self.voice_style = LabeledCombo(
            "Phong cách giọng đọc",
            [("Tự nhiên", "tu_nhien"),
             ("Tin tức", "tin_tuc"),
             ("Đọc truyện", "doc_truyen")],
            "Chọn cách thể hiện giọng VieNeu.")
        self.voice_style.changed.connect(lambda: self.changed.emit())
        self.body.addWidget(self.voice_style)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.body.addWidget(self.status)
        self.finish()
        self._on_clone_toggled(False)

    def _on_clone_toggled(self, enabled: bool) -> None:
        self.clone_source.setEnabled(enabled)
        self.clone_reference_holder.setEnabled(enabled)
        self.clone_min_seconds.setEnabled(enabled)
        self.clone_max_seconds.setEnabled(enabled)
        self.clone_workers.setEnabled(enabled)
        self._on_clone_source()
        self.changed.emit()

    def _on_clone_source(self) -> None:
        self.clone_reference_audio.setVisible(
            self.clone_voice.isChecked()
            and self.clone_source.current_key() == "file")
        self.clone_reference_holder.setVisible(self.clone_voice.isChecked())
        self.changed.emit()

    def _pick_clone_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chon audio mau cho clone giong",
            os.path.expanduser("~"),
            "Audio (*.wav *.mp3 *.m4a *.flac);;Tat ca tep (*.*)",
        )
        if path:
            self.clone_reference_audio.set_text(path)
            self.clone_source.set_key("file")
            self._on_clone_source()

    def _clone_is_complete(self) -> tuple[bool, str]:
        if not self.clone_voice.isChecked():
            return True, ""
        if self.clone_min_seconds.value() > self.clone_max_seconds.value():
            return False, "Do dai audio toi thieu khong duoc lon hon toi da."
        if self.clone_source.current_key() != "file":
            return True, ""
        path = self.clone_reference_audio.text().strip()
        if not path:
            return False, "Hay chon file audio mau truoc khi clone giong."
        if not os.path.isfile(path):
            return False, "Khong tim thay file audio mau. Hay chon lai."
        return True, ""

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

    def values(self) -> dict:
        # Không mở phần đổi giọng thì trả về rỗng — pipeline sẽ tự dùng
        # giọng mặc định trong Cài đặt.
        return {
            "voice": (self.picker.voice()
                      if self._override.is_expanded() else ""),
            "voice_speed": self.speed.value(),
            "voice_style": self.voice_style.current_key(),
            "clone_voice": self.clone_voice.isChecked(),
            "clone_source": self.clone_source.current_key(),
            "clone_reference_audio": self.clone_reference_audio.text(),
            "clone_min_seconds": self.clone_min_seconds.value(),
            "clone_max_seconds": self.clone_max_seconds.value(),
            "clone_workers": int(self.clone_workers.value()),
        }

    def load(self, data: dict) -> None:
        voice = (data.get("voice") or "").strip()
        self.picker.reload()
        if voice:
            self.picker.set_voice(voice)
        self._override.set_expanded(bool(voice))
        self.speed.set_value(float(data.get("voice_speed", 1.0)))
        self.voice_style.set_key(data.get("voice_style", "tu_nhien"))
        self.clone_voice.setChecked(bool(data.get("clone_voice", False)))
        self.clone_source.set_key(data.get("clone_source", "video"))
        self.clone_reference_audio.set_text(
            data.get("clone_reference_audio", ""))
        self.clone_min_seconds.set_value(
            float(data.get("clone_min_seconds", 1.0)))
        self.clone_max_seconds.set_value(
            float(data.get("clone_max_seconds", 8.0)))
        self.clone_workers.set_value(float(data.get("clone_workers", 3)))
        self._on_clone_toggled(self.clone_voice.isChecked())
        self._refresh_default_label()

    def is_complete(self) -> tuple[bool, str]:
        return self._clone_is_complete()


class RunStep(_StepPanel):
    """Bước 5: cấu hình ghép tiếng."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Ghép tiếng",
                         "Chọn nhạc nền, nhịp video và cách xử lý thời lượng "
                         "trước khi sang bước xuất video.", parent)
        from autodub_gui.ui.collapsible import CollapsibleSection

        self._audio_section = CollapsibleSection("Nhạc nền")
        self.background = LabeledCombo(
            "Cách giữ nhạc nền", consts.BG_MODES,
            "Tách giọng giữ nhạc nền tốt hơn nhưng chạy lâu hơn.")
        self.duck = LabeledSlider(
            "Mức giảm tiếng gốc", -40.0, 0.0, 1.0,
            "Chỉ dùng khi chọn hạ tiếng gốc.", " dB", decimals=0)
        self.background.changed.connect(self._on_background)
        self.duck.changed.connect(lambda _value: self.changed.emit())
        self._audio_section.add_widget(self.background)
        self._audio_section.add_widget(self.duck)
        self.body.addWidget(self._audio_section)

        self.hq_background = QCheckBox("Giữ nhạc nền chất lượng cao")
        self.hq_background.setToolTip(
            "Tốn thêm thời gian và dung lượng, đổi lại nhạc nền rõ hơn.")
        self.hq_background.toggled.connect(lambda _checked: self.changed.emit())
        self.body.addWidget(self.hq_background)

        self.audio_only = QCheckBox(
            "Chỉ xuất âm thanh và phụ đề, bỏ ghép video")
        self.audio_only.setToolTip(
            "Dùng khi bạn tự dựng hình ở phần mềm khác.")
        self.audio_only.toggled.connect(lambda _checked: self.changed.emit())
        self.body.addWidget(self.audio_only)

        self.video_speed = LabeledSlider(
            "Tốc độ video", 0.5, 1.0, 0.02,
            "Hạ tốc độ để lời Việt có thêm thời gian.", "x", decimals=2)
        self.soft_timing = QCheckBox(
            "Tự căn lại thời điểm để tránh chồng tiếng")
        self.timing_drift = LabeledSlider(
            "Độ trễ cộng dồn tối đa", 0.0, 5.0, 0.1,
            "Giới hạn dồn trễ giữa các câu.", " giây", decimals=1)
        self.timing_gap = LabeledSlider(
            "Khoảng nghỉ tối thiểu", 0.0, 1.0, 0.01,
            "Khoảng thở tối thiểu giữa hai câu.", " giây", decimals=2)
        self.timing_atempo = LabeledSlider(
            "Mức nén câu tối đa", 1.0, 1.5, 0.01,
            "Giới hạn nén tốc độ khi câu quá dài.", "x", decimals=2)
        for widget in (
            self.video_speed, self.soft_timing, self.timing_drift,
            self.timing_gap, self.timing_atempo,
        ):
            self.body.addWidget(widget)
            signal = (widget.toggled
                      if isinstance(widget, QCheckBox)
                      else widget.changed)
            signal.connect(lambda *_args: self.changed.emit())

        self.voice_postprocess = QCheckBox("Làm đều âm lượng giọng đọc")
        self.voice_target_lufs = LabeledSlider(
            "Mức âm lượng giọng đọc", -24.0, -10.0, 0.5,
            "Mức thường dùng cho video là -16 dB.", " dB", decimals=1)
        self.bg_duck_voice_db = LabeledSlider(
            "Giảm nhạc nền khi có lời", -24.0, 0.0, 0.5,
            "Nhạc nền tự hạ khi có giọng tiếng Việt.", " dB", decimals=1)
        self.parallel_workers = LabeledSlider(
            "Số luồng ghép và xử lý", 1, 16, 1,
            "Tăng tốc xử lý hậu kỳ; giảm nếu máy thiếu RAM.",
            " luồng", decimals=0)
        self.worker_mode = LabeledCombo(
            "Điều phối worker",
            [("Tự động theo máy", "auto"), ("Thủ công", "manual")],
            "Tự động tính theo CPU/RAM/GPU. Số thủ công vẫn chịu trần an toàn.")
        self.body.addWidget(self.voice_postprocess)
        self.body.addWidget(self.voice_target_lufs)
        self.body.addWidget(self.bg_duck_voice_db)
        self.body.addWidget(self.worker_mode)
        self.body.addWidget(self.parallel_workers)
        self.worker_summary = QLabel("")
        self.worker_summary.setWordWrap(True)
        self.worker_summary.setTextFormat(Qt.TextFormat.RichText)
        self.worker_summary.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            f"background: {tokens.BG_INPUT}; border-radius: 8px; "
            f"padding: 10px 12px;")
        self.body.addWidget(
            LabeledWidget("Worker du kien", self.worker_summary))
        self.voice_postprocess.toggled.connect(
            lambda _checked: self.changed.emit())
        self.voice_target_lufs.changed.connect(
            lambda _value: self.changed.emit())
        self.bg_duck_voice_db.changed.connect(
            lambda _value: self.changed.emit())
        self.parallel_workers.changed.connect(
            lambda _value: self.changed.emit())
        self.worker_mode.changed.connect(lambda: self._update_worker_summary())
        self.parallel_workers.changed.connect(
            lambda _value: self._update_worker_summary())

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
        self._on_background()

    def _on_background(self) -> None:
        self.duck.setEnabled(self.background.current_key() == "duck")
        self._update_worker_summary()
        self.changed.emit()

    def _update_worker_summary(self) -> None:
        import os

        from autodub.sysinfo import available_ram_gb
        from autodub.worker_plan import build_worker_plan

        plan = build_worker_plan(
            mode=self.worker_mode.current_key(),
            cpu_count=os.cpu_count(),
            available_ram_gb=available_ram_gb(),
            gpu_available=False,
            configured={
                "tts": 3,
                "parallel": int(self.parallel_workers.value()),
                "asr": 4,
            },
        )
        labels = (
            ("ASR", "asr"), ("OCR", "ocr"), ("Dich", "translate"),
            ("TTS", "tts"), ("Demucs", "demucs"), ("Ghep", "merge"),
        )
        self.worker_summary.setText(" | ".join(
            f"<b>{label}:</b> {plan[key]['effective']} luong"
            for label, key in labels
        ))

    def set_summary(self, rows: list[tuple[str, str]]) -> None:
        """Đổ bảng tóm tắt hai cột."""
        lines = [f"<b>{name}:</b> {value}" for name, value in rows]
        self.summary.setText("<br>".join(lines))

    def values(self) -> dict:
        return {
            "bg_mode": self.background.current_key(),
            "bg_duck_db": self.duck.value(),
            "hq_background": self.hq_background.isChecked(),
            "skip_video": self.audio_only.isChecked(),
            "video_speed": self.video_speed.value(),
            "soft_timing_fit": self.soft_timing.isChecked(),
            "timing_max_drift_s": self.timing_drift.value(),
            "timing_min_gap_s": self.timing_gap.value(),
            "timing_max_atempo": self.timing_atempo.value(),
            "voice_postprocess": self.voice_postprocess.isChecked(),
            "voice_target_lufs": self.voice_target_lufs.value(),
            "bg_duck_voice_db": self.bg_duck_voice_db.value(),
            "worker_mode": self.worker_mode.current_key(),
            "parallel_workers": int(self.parallel_workers.value()),
        }

    def load(self, data: dict) -> None:
        self.background.set_key(data.get("bg_mode", "demucs"))
        self.duck.set_value(float(data.get("bg_duck_db", -12.0)))
        self.hq_background.setChecked(bool(data.get("hq_background", True)))
        self.audio_only.setChecked(bool(data.get("skip_video", False)))
        self.video_speed.set_value(float(data.get("video_speed", 1.0)))
        self.soft_timing.setChecked(bool(data.get("soft_timing_fit", True)))
        self.timing_drift.set_value(float(data.get("timing_max_drift_s", 1.5)))
        self.timing_gap.set_value(float(data.get("timing_min_gap_s", 0.12)))
        self.timing_atempo.set_value(float(data.get("timing_max_atempo", 1.1)))
        self.voice_postprocess.setChecked(
            bool(data.get("voice_postprocess", True)))
        self.voice_target_lufs.set_value(
            float(data.get("voice_target_lufs", -16.0)))
        self.bg_duck_voice_db.set_value(
            float(data.get("bg_duck_voice_db", -7.0)))
        self.worker_mode.set_key(data.get("worker_mode", "auto"))
        self.parallel_workers.set_value(
            float(data.get("parallel_workers", 4)))
        self._update_worker_summary()
        self._on_background()


class ExportSummaryStep(_StepPanel):
    style_requested = Signal()

    """Bước 6: tổng kết lần chạy và chốt Vox khi bấm Xuất video.

    Nút Xuất video là nút chính ở chân trang (do trang cha đổi nhãn khi
    đến bước này) — bước chỉ lo hiển thị số liệu.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Xuất video",
                         "Chọn nơi lưu và rà lại cách xuất trước khi chạy "
                         "toàn bộ pipeline.", parent)
        self.output_dir = LabeledLineEdit(
            "Thư mục lưu kết quả", "./output",
            "Để trống để dùng thư mục đầu ra trong Cài đặt.")
        self.body.addWidget(self.output_dir)
        self.auto_clean = QCheckBox(
            "Tự dọn file trung gian sau khi xuất")
        self.auto_clean.setToolTip(
            "Tắt nếu cần mở Trình chỉnh sửa hoặc xuất lại từ project này.")
        self.auto_clean.toggled.connect(lambda _checked: self.changed.emit())
        self.body.addWidget(self.auto_clean)
        self.export_note = QLabel(
            "Phụ đề, vùng che, logo cá nhân, intro và outro đã chọn ở các "
            "bước trước sẽ được áp dụng khi xuất.")
        self.export_note.setWordWrap(True)
        self.export_note.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.body.addWidget(self.export_note)
        from autodub.media.subtitle import PRESET_CHOICES
        self.subtitle_mode = LabeledCombo(
            "Kiểu phụ đề", consts.SUBTITLE_MODES,
            "Tắt, xuất tệp phụ đề rời, hoặc ghi thẳng vào hình.")
        self.subtitle_preset = LabeledCombo(
            "Bộ kiểu chữ", PRESET_CHOICES,
            "Bộ kiểu chữ dùng khi ghi phụ đề vào hình.")
        self.karaoke_alignment = QCheckBox(
            "Khớp karaoke bằng audio thật")
        self.karaoke_alignment.setToolTip(
            "Dùng audio giọng đọc để canh thời điểm từng cụm chữ. "
            "Tắt để xử lý nhanh hơn.")
        self.karaoke_alignment.toggled.connect(
            lambda _checked: self.changed.emit())
        self.body.addWidget(self.subtitle_mode)
        self.body.addWidget(self.subtitle_preset)
        self.body.addWidget(self.karaoke_alignment)
        style_row = QHBoxLayout()
        self.btn_style = GhostButton("Kiểu chữ và vùng che…")
        self.btn_style.clicked.connect(self.style_requested.emit)
        style_row.addWidget(self.btn_style)
        style_row.addStretch()
        self.body.addLayout(style_row)
        self.style_summary = QLabel("Kiểu mặc định, chưa che vùng nào")
        self.style_summary.setWordWrap(True)
        self.style_summary.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self.body.addWidget(self.style_summary)
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

    def set_summary(self, rows: list[tuple[str, str]]) -> None:
        lines = [f"<b>{name}:</b> {value}" for name, value in rows]
        self.summary.setText("<br>".join(lines))

    def set_style_summary(self, text: str) -> None:
        self.style_summary.setText(text)

    def set_stats(self, sentences: int, duration_s: float,
                  usage: dict | None, hold: dict | None) -> None:
        """Đổ bảng tổng kết: thời lượng, số câu thoại, tổng Vox, số dư.

        Chỉ một con số tiền: TỔNG Vox của video, chốt từ lúc giữ chỗ và không
        đổi nữa. Không tách theo bước xử lý — người dùng không trả theo bước,
        bày ra chỉ khiến họ đi tìm cách tối ưu một thứ không tồn tại.
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
        return {
            "output_dir": self.output_dir.text(),
            "auto_clean_intermediates": self.auto_clean.isChecked(),
            "subtitle_mode": self.subtitle_mode.current_key(),
            "subtitle_preset": self.subtitle_preset.current_key(),
            "karaoke_alignment": self.karaoke_alignment.isChecked(),
        }

    def load(self, data: dict) -> None:
        self.output_dir.set_text(data.get("output_dir", ""))
        self.auto_clean.setChecked(
            bool(data.get("auto_clean_intermediates", False)))
        self.subtitle_mode.set_key(data.get("subtitle_mode", "none"))
        self.subtitle_preset.set_key(data.get("subtitle_preset", "clean"))
        self.karaoke_alignment.setChecked(
            bool(data.get("karaoke_alignment", True)))
