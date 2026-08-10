"""Dialog to style subtitles and pick blur regions on a video frame.

One place for everything drawn over the video:

- **Subtitle styling** — font, size, outline, colours, position. A live preview
  line is painted straight onto the frame and can be dragged up/down to set
  its position; controls on the right stay in sync.
- **Blur regions** — drag rectangles over hardcoded captions to blur them
  (same normalized 0..1 dicts as before).

Scaling note: ffmpeg's SRT→ASS conversion uses a PlayResY=288 canvas, so a
``FontSize``/``MarginV`` of N means N pixels *on a 288-line screen*. The
preview multiplies by ``frame_height / 288`` to show the real rendered size.

Works without a video too (URL mode before download): the canvas falls back to
a placeholder frame so styling is still possible; only region picking needs a
real frame.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QThread, Signal
from PySide6.QtGui import (QColor, QFont, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from autodub_gui import tokens
from autodub_gui.ui.inputs import polish_combo

# ffmpeg renders SRT subtitles on an ASS canvas of this height; FontSize and
# MarginV in force_style are expressed in this coordinate space.
ASS_PLAY_RES_Y = 288

PREVIEW_TEXT = "Xin chào, đây là phụ đề xem trước"
# Preview ở chế độ karaoke: một cụm chữ ngắn như lúc render thật.
PREVIEW_TEXT_KARAOKE = "đây là phụ đề"

_POSITIONS = [("Dưới", "bottom"), ("Giữa", "middle"), ("Trên", "top")]

_BOXES = [("Không", "none"), ("Khối nền sau chữ", "box")]

_DISPLAYS = [("Cả câu", "sentence"),
             ("Cụm chữ theo giọng đọc", "karaoke")]

_EFFECTS = [("Nảy nhẹ", "pop"),
            ("Mờ dần", "fade"),
            ("Đổi màu theo lời", "karaoke"),
            ("Không", "none")]


def extract_frame(video_path: str, out_png: str, at_seconds: float = 1.0) -> str:
    """Grab a single frame from the video as a PNG via ffmpeg.

    Designed to be called from a background thread — never call this on the
    UI thread because a corrupt/long video can make ffmpeg block for 30s.
    """
    cmd = [
        "ffmpeg", "-v", "error",
        "-ss", str(at_seconds), "-i", video_path,
        "-frames:v", "1", "-y", out_png,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0 or not os.path.exists(out_png):
        # Retry from the very start — the video may be shorter than at_seconds.
        cmd[cmd.index("-ss") + 1] = "0"
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or not os.path.exists(out_png):
            raise RuntimeError(f"Could not extract a frame: {result.stderr}")
    return out_png


class _FrameWorker(QThread):
    """Chạy ffmpeg trong luồng nền để không chặn UI thread."""

    ready = Signal(str)   # đường dẫn tệp PNG khi thành công
    failed = Signal(str)  # thông báo lỗi

    def __init__(self, video_path: str, out_png: str,
                 at_seconds: float = 1.0, parent=None):
        super().__init__(parent)
        self._video = video_path
        self._out = out_png
        self._at = at_seconds

    def run(self) -> None:
        try:
            path = extract_frame(self._video, self._out, self._at)
            self.ready.emit(path)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


def subtitle_zone(center_ratio: float) -> str:
    """Map a dragged text's vertical centre (0=top, 1=bottom) to a position."""
    if center_ratio < 0.38:
        return "top"
    if center_ratio < 0.62:
        return "middle"
    return "bottom"


class _FrameCanvas(QWidget):
    """Frame + blur rectangles + draggable live subtitle preview."""

    def __init__(self, pixmap: QPixmap, style: dict,
                 allow_regions: bool = True, parent=None):
        super().__init__(parent)
        self._source = pixmap
        self._scaled = pixmap
        self._style = dict(style)
        self._allow_regions = allow_regions
        self._rects: list[QRect] = []
        self._drag_origin: QPoint | None = None
        self._drag_current: QRect | None = None
        self._dragging_text = False
        self._text_rect = QRectF()
        self.on_style_dragged = None      # callback(position: str, margin_v: int)
        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)

    # ------------------------------------------------------- geometry ----- #

    def _pixmap_rect(self) -> QRect:
        pw, ph = self._scaled.width(), self._scaled.height()
        ox = (self.width() - pw) // 2
        oy = (self.height() - ph) // 2
        return QRect(ox, oy, pw, ph)

    def _ass_scale(self) -> float:
        """Canvas pixels per ASS unit (PlayResY=288 space)."""
        return max(self._scaled.height(), 1) / ASS_PLAY_RES_Y

    def resizeEvent(self, event):
        self._scaled = self._source.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        super().resizeEvent(event)
        self.update()

    # --------------------------------------------------------- style ------ #

    def set_style(self, style: dict) -> None:
        self._style = dict(style)
        self.update()

    def set_rects_from_normalized(self, regions: list[dict]) -> None:
        """Restore previously picked regions onto the current canvas."""
        pr = self._pixmap_rect()
        self._rects = [
            QRect(int(pr.x() + r["x"] * pr.width()),
                  int(pr.y() + r["y"] * pr.height()),
                  int(r["w"] * pr.width()),
                  int(r["h"] * pr.height()))
            for r in regions
        ]
        self.update()

    # --------------------------------------------------------- mouse ------ #

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        if self._text_rect.adjusted(-8, -8, 8, 8).contains(pos):
            self._dragging_text = True
        elif self._allow_regions:
            self._drag_origin = pos.toPoint()
            self._drag_current = None

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._dragging_text:
            self._apply_text_drag(pos.y())
        elif self._drag_origin is not None:
            self._drag_current = QRect(
                self._drag_origin, pos.toPoint()).normalized()
            self.update()
        else:
            inside = self._text_rect.adjusted(-8, -8, 8, 8).contains(pos)
            self.setCursor(Qt.SizeVerCursor if inside else Qt.CrossCursor)

    def mouseReleaseEvent(self, event):
        if self._dragging_text:
            self._dragging_text = False
        elif self._drag_origin is not None and self._drag_current is not None:
            clipped = self._drag_current.intersected(self._pixmap_rect())
            if clipped.width() > 4 and clipped.height() > 4:
                self._rects.append(clipped)
        self._drag_origin = None
        self._drag_current = None
        self.update()

    def _apply_text_drag(self, mouse_y: float) -> None:
        """Move the preview line to the cursor; report position + margin back."""
        pr = self._pixmap_rect()
        if pr.height() == 0:
            return
        scale = self._ass_scale()
        text_h = self._text_rect.height() or 1

        center_ratio = (mouse_y - pr.y()) / pr.height()
        position = subtitle_zone(min(max(center_ratio, 0.0), 1.0))
        if position == "bottom":
            margin = round((pr.bottom() - (mouse_y + text_h / 2)) / scale)
        elif position == "top":
            margin = round(((mouse_y - text_h / 2) - pr.y()) / scale)
        else:
            margin = self._style.get("margin_v", 40)
        margin = max(0, min(int(margin), 280))

        self._style["position"] = position
        if position != "middle":
            self._style["margin_v"] = margin
        self.update()
        if self.on_style_dragged is not None:
            self.on_style_dragged(position, self._style.get("margin_v", 40))

    # --------------------------------------------------------- rects ------ #

    def clear_last(self):
        if self._rects:
            self._rects.pop()
            self.update()

    def clear_all(self):
        self._rects.clear()
        self.update()

    def normalized_regions(self) -> list[dict]:
        """Convert stored displayed rectangles to normalized 0..1 dicts."""
        pr = self._pixmap_rect()
        if pr.width() == 0 or pr.height() == 0:
            return []
        out = []
        for r in self._rects:
            out.append({
                "x": round((r.x() - pr.x()) / pr.width(), 4),
                "y": round((r.y() - pr.y()) / pr.height(), 4),
                "w": round(r.width() / pr.width(), 4),
                "h": round(r.height() / pr.height(), 4),
            })
        return out

    # --------------------------------------------------------- paint ------ #

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pr = self._pixmap_rect()
        painter.fillRect(self.rect(), QColor(tokens.PREVIEW_CANVAS_BG))
        painter.drawPixmap(pr.topLeft(), self._scaled)

        # Blur regions
        pen = QPen(QColor(tokens.PREVIEW_GUIDE), 2)
        painter.setPen(pen)
        fill = QColor(63, 111, 181, 70)
        for r in self._rects:
            painter.fillRect(r, fill)
            painter.drawRect(r)
        if self._drag_current is not None:
            painter.setPen(QPen(QColor(tokens.PREVIEW_BLUR_EDGE), 2, Qt.DashLine))
            painter.drawRect(self._drag_current)

        self._paint_subtitle(painter, pr)

    def _paint_subtitle(self, painter: QPainter, pr: QRect) -> None:
        """Render the preview line exactly as ffmpeg/libass would place it."""
        s = self._style
        scale = self._ass_scale()

        font = QFont(s.get("font", "Arial"))
        font.setPixelSize(max(6, round(int(s.get("font_size", 22)) * scale)))
        font.setBold(bool(s.get("bold", True)))

        preview = (PREVIEW_TEXT_KARAOKE
                   if s.get("display") == "karaoke" else PREVIEW_TEXT)
        if s.get("all_caps"):
            preview = preview.upper()
        path = QPainterPath()
        path.addText(0, 0, font, preview)
        bounds = path.boundingRect()

        margin_px = int(s.get("margin_v", 40)) * scale
        x = pr.x() + (pr.width() - bounds.width()) / 2
        position = s.get("position", "bottom")
        if position == "top":
            top = pr.y() + margin_px
        elif position == "middle":
            top = pr.y() + (pr.height() - bounds.height()) / 2
        else:
            top = pr.bottom() - margin_px - bounds.height()
        dx, dy = x - bounds.x(), top - bounds.y()
        path.translate(dx, dy)
        self._text_rect = path.boundingRect()

        # Khối nền sau chữ (BorderStyle=4 của libass): vẽ TRƯỚC chữ, chừa
        # đệm quanh chữ như libass chừa theo Outline.
        if s.get("box") == "box":
            pad = max(4.0, int(s.get("outline", 2)) * scale * 2)
            box_rect = self._text_rect.adjusted(-pad, -pad, pad, pad)
            box_color = QColor(s.get("box_color", tokens.SUBTITLE_BOXFILL_DEFAULT))
            opacity = int(s.get("box_opacity", 60))
            box_color.setAlpha(round(255 * max(0, min(opacity, 100)) / 100))
            painter.setPen(Qt.NoPen)
            painter.fillRect(box_rect, box_color)

        # Bóng đổ: libass dịch chữ màu viền xuống dưới-phải Shadow điểm ảnh.
        shadow_px = int(s.get("shadow", 0)) * scale
        if shadow_px > 0 and s.get("box") != "box":
            sh = QPainterPath(path)
            sh.translate(shadow_px, shadow_px)
            shadow_color = QColor(s.get("outline_color", tokens.SUBTITLE_OUTLINE_DEFAULT))
            shadow_color.setAlpha(160)
            painter.setPen(Qt.NoPen)
            painter.fillPath(sh, shadow_color)

        outline_px = int(s.get("outline", 2)) * scale * 2
        if outline_px > 0 and s.get("box") != "box":
            painter.setPen(QPen(QColor(s.get("outline_color", tokens.SUBTITLE_OUTLINE_DEFAULT)),
                                outline_px, Qt.SolidLine, Qt.RoundCap,
                                Qt.RoundJoin))
            painter.drawPath(path)
        painter.setPen(Qt.NoPen)
        painter.fillPath(path, QColor(s.get("color", tokens.SUBTITLE_TEXT_DEFAULT)))

        # Karaoke đổi màu: minh hoạ chữ đầu cụm đang được "đọc" — vẽ đè
        # bằng màu highlight với CÙNG phép dịch (dx, dy) của dòng chính,
        # nên chữ đè khít lên chữ gốc.
        if s.get("display") == "karaoke" and s.get("effect") == "karaoke":
            hi = QPainterPath()
            hi.addText(0, 0, font, preview.split()[0])
            hi.translate(dx, dy)
            painter.fillPath(hi, QColor(s.get("highlight_color", tokens.SUBTITLE_HIGHLIGHT_DEFAULT)))


def _placeholder_frame() -> QPixmap:
    """A neutral 16:9 frame used when no video is available yet."""
    pm = QPixmap(1280, 720)
    pm.fill(QColor(tokens.PREVIEW_EMPTY_BG))
    painter = QPainter(pm)
    painter.setPen(QColor(tokens.PREVIEW_EMPTY_TEXT))
    f = QFont("Arial")
    f.setPixelSize(40)
    painter.setFont(f)
    painter.drawText(pm.rect(), Qt.AlignCenter,
                     "(Chưa có video — xem trước phụ đề trên nền mẫu)")
    painter.end()
    return pm


class StyleDialog(QDialog):
    """Style the subtitles and pick blur regions in one place."""

    def __init__(self, video_path: str | None, style: dict,
                 regions: list[dict] | None = None, parent=None,
                 preview_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Phụ đề & che chữ")
        # Đủ chỗ cho panel phải hiện trọn cả 3 nhóm không phải cuộn.
        self.resize(1150, 700)
        self.setMinimumSize(1050, 620)
        self._style = dict(style)
        self._video_path = video_path
        self._regions_pending = regions
        self._frame_worker = None
        # Chữ xem trước: dùng câu thật của người dùng nếu được truyền vào,
        # không thì dùng mẫu mặc định. Điều này giúp xem trước đúng với độ
        # dài thực tế của câu thoại đang chỉnh.
        if preview_text:
            global PREVIEW_TEXT, PREVIEW_TEXT_KARAOKE  # noqa: PLW0603
            PREVIEW_TEXT = preview_text
            words = preview_text.split()
            PREVIEW_TEXT_KARAOKE = " ".join(words[:3]) if len(words) >= 3 else preview_text

        has_video = bool(video_path)
        # Bắt đầu bằng placeholder — frame thật sẽ thay thế sau khi ffmpeg
        # chạy xong trong luồng nền. Người dùng thấy dialog ngay lập tức
        # thay vì phải chờ ffmpeg (có thể mất 2-5 giây trên file lớn).
        # Cho phép vẽ vùng che CẢ KHI chưa có video (chỉ có URL): tọa độ
        # được chuẩn hóa 0..1 theo khung hình, nên vùng vẽ trên placeholder
        # 16:9 áp đúng lên video thật khi pipeline tải về.
        pixmap = _placeholder_frame()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        # --- Left: canvas (7 phần) ---
        left = QVBoxLayout()
        left.setSpacing(6)
        # allow_regions luôn True — placeholder đủ để khoanh vùng; tọa độ 0..1
        self.canvas = _FrameCanvas(pixmap, self._style, allow_regions=True)
        self.canvas.on_style_dragged = self._on_canvas_drag
        left.addWidget(self.canvas, 1)
        hint = QLabel(
            "Kéo dòng phụ đề để đặt vị trí. "
            "Kéo chuột trên hình để khoanh vùng che chữ (làm mờ suốt video)."
            + ("" if has_video else
               " Đang dùng khung mẫu — vùng che sẽ áp đúng lên video khi xử lý."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        left.addWidget(hint)
        body.addLayout(left, 6)

        # --- Right: panel phẳng (3 phần) — nhóm bằng tiêu đề + khoảng
        # trắng, KHÔNG viền lồng nhau; cuộn được khi cửa sổ thấp ---
        from PySide6.QtWidgets import QScrollArea
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        # Sàn bề rộng: dưới mức này hàng "nhãn + 2 ô số" bị cắt chữ.
        panel_scroll.setMinimumWidth(400)
        panel_scroll.setMaximumWidth(460)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QWidget()
        panel_l = QVBoxLayout(panel)
        panel_l.setContentsMargins(4, 0, 10, 4)
        panel_l.setSpacing(6)

        def _section(title: str) -> None:
            """Tiêu đề nhóm phẳng; khoảng trắng phía trên tách nhóm."""
            if panel_l.count():
                panel_l.addSpacing(14)
            lb = QLabel(title)
            lb.setObjectName("sectionHeader")
            panel_l.addWidget(lb)

        # Nhóm 1: chữ (font, cỡ, màu, vị trí)
        _section("Kiểu chữ")
        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        f.setLabelAlignment(Qt.AlignRight)
        f.setSpacing(7)
        panel_l.addLayout(f)
        # Hộp font tự đổ: font KÈM APP (thư mục fonts/) đứng đầu — các font
        # này render đúng trên video ở mọi máy; font Windows có đủ dấu
        # tiếng Việt xếp sau. Không dùng QFontComboBox vì nó chỉ biết font
        # hệ thống và không tách được 2 nhóm.
        self.cb_font = QComboBox()
        self._populate_fonts()
        self.cb_font.setToolTip(
            "Font trong nhóm 'Font của app' hiển thị đúng trên video ở mọi "
            "máy (khuyên dùng).\n"
            "Thêm font mới: bấm nút + để mở thư mục font, thả file .ttf "
            "vào đó rồi mở lại hộp thoại này.\n"
            "Nguồn font miễn phí: fonts.google.com (lọc Language → "
            "Vietnamese).")
        self.btn_fonts_dir = QPushButton("+")
        self.btn_fonts_dir.setFixedWidth(28)
        self.btn_fonts_dir.setToolTip(
            "Thêm font: mở thư mục font của app.\nThả file font (.ttf/.otf) "
            "vào đó rồi mở lại hộp thoại này là dùng được.\nTải font miễn "
            "phí tại fonts.google.com (lọc Language → Vietnamese).")
        self.btn_fonts_dir.clicked.connect(self._open_fonts_dir)
        font_row = QHBoxLayout()
        font_row.setSpacing(4)
        font_row.addWidget(self.cb_font, 1)
        font_row.addWidget(self.btn_fonts_dir)
        self.sp_size = QSpinBox()
        self.sp_size.setRange(8, 120)
        self.sp_size.setToolTip("Cỡ chữ — tự co giãn theo độ phân giải video")
        self.sp_outline = QSpinBox()
        self.sp_outline.setRange(0, 10)
        self.sp_outline.setToolTip("Độ dày viền quanh chữ")
        # Cỡ chữ + viền chung một hàng cho gọn.
        size_row = QHBoxLayout()
        size_row.setSpacing(4)
        size_row.addWidget(self.sp_size, 1)
        size_row.addWidget(QLabel("Viền"))
        size_row.addWidget(self.sp_outline, 1)
        # Chữ đậm + bóng đổ chung một hàng — đủ cặp thông số như Cài đặt.
        self.chk_bold = QCheckBox("Chữ đậm")
        self.chk_bold.setToolTip("Chữ đậm dễ đọc hơn khi xem trên điện thoại")
        self.sp_shadow = QSpinBox()
        self.sp_shadow.setRange(0, 8)
        self.sp_shadow.setToolTip("Bóng nhẹ phía sau chữ. Đặt 0 để tắt.")
        bold_row = QHBoxLayout()
        bold_row.setSpacing(4)
        bold_row.addWidget(self.chk_bold, 1)
        bold_row.addWidget(QLabel("Bóng"))
        bold_row.addWidget(self.sp_shadow, 1)
        self.btn_color = QPushButton()
        self.btn_color.clicked.connect(lambda: self._pick_color("color"))
        self.btn_outline_color = QPushButton()
        self.btn_outline_color.clicked.connect(
            lambda: self._pick_color("outline_color"))
        color_row = QHBoxLayout()
        color_row.setSpacing(4)
        color_row.addWidget(self.btn_color, 1)
        color_row.addWidget(self.btn_outline_color, 1)
        self.cb_pos = QComboBox()
        for label, key in _POSITIONS:
            self.cb_pos.addItem(label, key)
        polish_combo(self.cb_pos)
        self.sp_margin = QSpinBox()
        self.sp_margin.setRange(0, 280)
        self.sp_margin.setToolTip("Khoảng cách tới mép trên/dưới của video")
        pos_row = QHBoxLayout()
        pos_row.setSpacing(4)
        pos_row.addWidget(self.cb_pos, 1)
        pos_row.addWidget(QLabel("Lề"))
        pos_row.addWidget(self.sp_margin, 1)
        # Nền sau chữ (BorderStyle=4): khối nền mờ giúp đọc trên nền rối.
        self.cb_box = QComboBox()
        for label, key in _BOXES:
            self.cb_box.addItem(label, key)
        polish_combo(self.cb_box)
        self.cb_box.setToolTip(
            "Khối nền mờ sau chữ giúp đọc được trên nền video nhiều chi "
            "tiết.\nKhi bật nền thì viền và bóng chữ không dùng nữa.")
        self.btn_box_color = QPushButton()
        self.btn_box_color.setToolTip("Màu của khối nền sau chữ")
        self.btn_box_color.clicked.connect(
            lambda: self._pick_color("box_color"))
        self.sp_box_opacity = QSpinBox()
        self.sp_box_opacity.setRange(0, 100)
        self.sp_box_opacity.setSuffix("%")
        self.sp_box_opacity.setToolTip(
            "Độ đục của nền: 0 là trong suốt hẳn, 100 là che kín hoàn toàn")
        box_row = QHBoxLayout()
        box_row.setSpacing(4)
        box_row.addWidget(self.btn_box_color, 1)
        box_row.addWidget(QLabel("Đục"))
        box_row.addWidget(self.sp_box_opacity, 1)
        f.addRow("Font:", font_row)
        f.addRow("Cỡ chữ:", size_row)
        f.addRow("Đậm / bóng:", bold_row)
        f.addRow("Màu / viền:", color_row)
        f.addRow("Vị trí:", pos_row)
        f.addRow("Nền chữ:", self.cb_box)
        f.addRow("Màu nền:", box_row)
        # Nhóm 2: cách hiện chữ (cả câu / cụm chữ) + hiệu ứng
        _section("Cách hiện chữ")
        fd = QFormLayout()
        fd.setContentsMargins(0, 0, 0, 0)
        fd.setLabelAlignment(Qt.AlignRight)
        fd.setSpacing(7)
        panel_l.addLayout(fd)
        self.cb_display = QComboBox()
        for label, key in _DISPLAYS:
            self.cb_display.addItem(label, key)
        polish_combo(self.cb_display)
        self.cb_display.setToolTip(
            "Cụm chữ theo giọng đọc: chữ hiện từng cụm ngắn đúng nhịp lời "
            "thoại — hợp video đăng TikTok/Shorts.\nChỉ áp dụng khi chọn "
            "'Ghi phụ đề vào video'. File phụ đề thường (.srt) vẫn được "
            "xuất kèm.")
        # Số chữ mỗi hàng cho phụ đề CẢ CÂU (0 = tự xuống dòng theo bề rộng).
        self.sp_line_words = QSpinBox()
        self.sp_line_words.setRange(0, 12)
        self.sp_line_words.setSpecialValueText("Tự động")
        self.sp_line_words.setToolTip(
            "Số chữ tối đa trên một hàng phụ đề (chế độ Cả câu).\n"
            "Tự động: xuống dòng theo bề rộng màn hình (khuyên dùng).\n"
            "Chọn số nhỏ (4-6) cho video dọc TikTok để chữ không tràn mép.")
        self.sp_max_lines = QSpinBox()
        self.sp_max_lines.setRange(1, 4)
        self.sp_max_lines.setToolTip(
            "Mỗi lần hiện nhiều nhất bấy nhiêu dòng chữ")
        lines_row = QHBoxLayout()
        lines_row.setSpacing(4)
        lines_row.addWidget(self.sp_line_words, 1)
        lines_row.addWidget(QLabel("Tối đa"))
        lines_row.addWidget(self.sp_max_lines, 1)
        self.chk_all_caps = QCheckBox("Viết hoa toàn bộ")
        self.chk_all_caps.setToolTip(
            "Chữ hoa hết nhìn mạnh hơn nhưng đọc chậm hơn, hợp video ngắn")
        self.cb_effect = QComboBox()
        for label, key in _EFFECTS:
            self.cb_effect.addItem(label, key)
        polish_combo(self.cb_effect)
        self.sp_words = QSpinBox()
        self.sp_words.setRange(1, 5)
        self.sp_words.setToolTip("Số chữ hiện mỗi lần (2 = dồn dập, "
                                 "3 = cân bằng)")
        self.btn_highlight = QPushButton()
        self.btn_highlight.setToolTip("Màu của chữ đang được đọc "
                                      "(hiệu ứng Đổi màu theo lời)")
        self.btn_highlight.clicked.connect(
            lambda: self._pick_color("highlight_color"))
        words_row = QHBoxLayout()
        words_row.setSpacing(4)
        words_row.addWidget(self.sp_words, 1)
        words_row.addWidget(QLabel("Màu nhấn"))
        words_row.addWidget(self.btn_highlight, 1)
        fd.addRow("Hiển thị:", self.cb_display)
        fd.addRow("Chữ mỗi hàng:", lines_row)
        fd.addRow("", self.chk_all_caps)
        fd.addRow("Hiệu ứng:", self.cb_effect)
        fd.addRow("Chữ mỗi lần:", words_row)

        _section("Che chữ trên hình")
        b = QHBoxLayout()
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(6)
        panel_l.addLayout(b)
        self.btn_undo = QPushButton("Xoá vùng cuối")
        self.btn_undo.clicked.connect(self.canvas.clear_last)
        self.btn_clear = QPushButton("Xoá tất cả")
        self.btn_clear.clicked.connect(self.canvas.clear_all)
        b.addWidget(self.btn_undo)
        b.addWidget(self.btn_clear)
        panel_l.addStretch()
        panel_scroll.setWidget(panel)
        body.addWidget(panel_scroll, 4)

        # --- Bottom: actions ---
        actions = QHBoxLayout()
        actions.addStretch()
        btn_cancel = QPushButton("Huỷ")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Xong")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        actions.addWidget(btn_cancel)
        actions.addWidget(btn_ok)
        root.addLayout(actions)

        self._load_controls()
        self._connect_controls()
        if regions:
            # Defer until the canvas has its final size, then restore rects.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                0, lambda: self.canvas.set_rects_from_normalized(regions))

        # Bắt đầu trích xuất frame video trong luồng nền NGAY SAU KHI
        # dialog đã dựng xong — người dùng thấy dialog lập tức với placeholder,
        # frame thật thay thế khi ffmpeg xong (thường < 2 giây).
        if has_video:
            self._start_frame_extract(video_path)

    def _start_frame_extract(self, video_path: str) -> None:
        """Trích xuất frame từ video trong luồng nền."""
        tmp_png = os.path.join(tempfile.gettempdir(), "autodub_style_frame.png")
        worker = _FrameWorker(video_path, tmp_png, at_seconds=1.0, parent=self)
        worker.ready.connect(self._on_frame_ready)
        worker.failed.connect(self._on_frame_failed)
        self._frame_worker = worker
        worker.start()

    def _on_frame_ready(self, path: str) -> None:
        """Cập nhật canvas với frame thật vừa trích xuất xong."""
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        self.canvas._source = pixmap
        self.canvas._scaled = pixmap.scaled(
            self.canvas.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation)
        self.canvas.update()
        # Khôi phục vùng blur lên frame thật nếu có
        if self._regions_pending:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                0, lambda: self.canvas.set_rects_from_normalized(
                    self._regions_pending))

    def _on_frame_failed(self, message: str) -> None:
        """Hiện cảnh báo nhẹ; không đóng dialog — phụ đề vẫn chỉnh được."""
        from autodub_gui.ui.toast import TOASTS
        TOASTS.warn(f"Không lấy được frame video: {message}")

    # ------------------------------------------------------- controls ----- #

    def _load_controls(self) -> None:
        s = self._style
        d_idx = self.cb_display.findData(s.get("display", "sentence"))
        self.cb_display.setCurrentIndex(d_idx if d_idx >= 0 else 0)
        self.sp_line_words.setValue(int(s.get("line_words", 0) or 0))
        self.sp_max_lines.setValue(int(s.get("max_lines", 2)))
        self.chk_all_caps.setChecked(bool(s.get("all_caps", False)))
        e_idx = self.cb_effect.findData(s.get("effect", "pop"))
        self.cb_effect.setCurrentIndex(e_idx if e_idx >= 0 else 0)
        self.sp_words.setValue(int(s.get("words_per_cue", 3)))
        self._paint_color_button(self.btn_highlight,
                                 s.get("highlight_color", tokens.SUBTITLE_HIGHLIGHT_DEFAULT))
        idx = self.cb_pos.findData(s.get("position", "bottom"))
        self.cb_pos.setCurrentIndex(idx if idx >= 0 else 0)
        self._select_font(s.get("font", "Arial"))
        self.sp_size.setValue(int(s.get("font_size", 22)))
        self.sp_margin.setValue(int(s.get("margin_v", 40)))
        self.sp_outline.setValue(int(s.get("outline", 2)))
        self.sp_shadow.setValue(int(s.get("shadow", 0)))
        self.chk_bold.setChecked(bool(s.get("bold", True)))
        b_idx = self.cb_box.findData(s.get("box", "none"))
        self.cb_box.setCurrentIndex(b_idx if b_idx >= 0 else 0)
        self.sp_box_opacity.setValue(int(s.get("box_opacity", 60)))
        self._paint_color_button(self.btn_box_color,
                                 s.get("box_color", tokens.SUBTITLE_BOXFILL_DEFAULT))
        self._paint_color_button(self.btn_color, s.get("color", tokens.SUBTITLE_TEXT_DEFAULT))
        self._paint_color_button(self.btn_outline_color,
                                 s.get("outline_color", tokens.SUBTITLE_OUTLINE_DEFAULT))
        self._update_karaoke_enabled()
        self._update_box_enabled()

    def _connect_controls(self) -> None:
        self.cb_display.currentIndexChanged.connect(self._sync_from_controls)
        self.sp_line_words.valueChanged.connect(self._sync_from_controls)
        self.sp_max_lines.valueChanged.connect(self._sync_from_controls)
        self.chk_all_caps.toggled.connect(self._sync_from_controls)
        self.cb_effect.currentIndexChanged.connect(self._sync_from_controls)
        self.sp_words.valueChanged.connect(self._sync_from_controls)
        self.cb_pos.currentIndexChanged.connect(self._sync_from_controls)
        self.cb_font.currentIndexChanged.connect(self._sync_from_controls)
        self.sp_size.valueChanged.connect(self._sync_from_controls)
        self.sp_margin.valueChanged.connect(self._sync_from_controls)
        self.sp_outline.valueChanged.connect(self._sync_from_controls)
        self.sp_shadow.valueChanged.connect(self._sync_from_controls)
        self.chk_bold.toggled.connect(self._sync_from_controls)
        self.cb_box.currentIndexChanged.connect(self._sync_from_controls)
        self.sp_box_opacity.valueChanged.connect(self._sync_from_controls)

    def _update_karaoke_enabled(self) -> None:
        karaoke = self.cb_display.currentData() == "karaoke"
        self.cb_effect.setEnabled(karaoke)
        self.sp_words.setEnabled(karaoke)
        # "Chữ mỗi hàng" là của chế độ CẢ CÂU — karaoke tự chia cụm riêng.
        self.sp_line_words.setEnabled(not karaoke)
        self.sp_max_lines.setEnabled(not karaoke)
        self.btn_highlight.setEnabled(
            karaoke and self.cb_effect.currentData() == "karaoke")

    def _update_box_enabled(self) -> None:
        """Nền chữ bật thì màu nền/độ đục dùng được; viền + bóng thì không
        (libass BorderStyle=4 bỏ qua Outline/Shadow khi có khối nền)."""
        boxed = self.cb_box.currentData() == "box"
        self.btn_box_color.setEnabled(boxed)
        self.sp_box_opacity.setEnabled(boxed)
        self.sp_outline.setEnabled(not boxed)
        self.sp_shadow.setEnabled(not boxed)
        self.btn_outline_color.setEnabled(not boxed)

    def _sync_from_controls(self, *_args) -> None:
        font = self.cb_font.currentData()
        self._style.update({
            "display": self.cb_display.currentData(),
            "line_words": self.sp_line_words.value(),
            "max_lines": self.sp_max_lines.value(),
            "all_caps": self.chk_all_caps.isChecked(),
            "effect": self.cb_effect.currentData(),
            "words_per_cue": self.sp_words.value(),
            "position": self.cb_pos.currentData(),
            **({"font": font} if font else {}),   # header không có data
            "font_size": self.sp_size.value(),
            "margin_v": self.sp_margin.value(),
            "outline": self.sp_outline.value(),
            "shadow": self.sp_shadow.value(),
            "bold": self.chk_bold.isChecked(),
            "box": self.cb_box.currentData(),
            "box_opacity": self.sp_box_opacity.value(),
        })
        self.sp_margin.setEnabled(self._style["position"] != "middle")
        self._update_karaoke_enabled()
        self._update_box_enabled()
        self.canvas.set_style(self._style)

    def _on_canvas_drag(self, position: str, margin_v: int) -> None:
        """Dragging the preview updates the spinners without echo loops."""
        for w in (self.cb_pos, self.sp_margin):
            w.blockSignals(True)
        idx = self.cb_pos.findData(position)
        if idx >= 0:
            self.cb_pos.setCurrentIndex(idx)
        self.sp_margin.setValue(margin_v)
        for w in (self.cb_pos, self.sp_margin):
            w.blockSignals(False)
        self._style["position"] = position
        self._style["margin_v"] = margin_v
        self.sp_margin.setEnabled(position != "middle")

    def _paint_color_button(self, btn: QPushButton, hex_color: str) -> None:
        btn.setText(hex_color)
        # Chữ đen/trắng theo độ sáng thật của màu (so sánh chuỗi hex là
        # so sánh từ điển, nên màu đỏ sẫm cũng bị coi nhầm là màu sáng).
        c = QColor(hex_color)
        luminance = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        btn.setStyleSheet(
            f"background: {hex_color}; color: "
            f"{tokens.BG_APP if luminance > 140 else tokens.TEXT_ON_ACCENT};")

    def _populate_fonts(self) -> None:
        """Đổ danh sách phông chữ, CHỈ lấy từ thư mục phông của dự án.

        Phông có sẵn trong máy không được liệt kê, vì chữ phụ đề ghi lên
        video chỉ chắc chắn hiện đúng khi phông nằm trong thư mục này.
        Phông thiếu dấu tiếng Việt vẫn hiện nhưng gắn cảnh báo, vì chữ
        thiếu dấu sẽ thành ô vuông ngay trên video.
        """
        from autodub_gui.fonts import font_choices

        self.cb_font.clear()
        for label, family in font_choices():
            self.cb_font.addItem(label, family)
            self.cb_font.setItemData(
                self.cb_font.count() - 1, QFont(family), Qt.FontRole)
        if self.cb_font.count() == 0:
            self.cb_font.addItem(
                "Thư mục phông chữ đang trống — hãy thả tệp .ttf vào đó", "")
            self.cb_font.setEnabled(False)
        polish_combo(self.cb_font)

    def _select_font(self, family: str) -> None:
        idx = self.cb_font.findData(family)
        if idx < 0:
            # Font đã lưu không còn (bị xoá/máy khác) — chọn font app đầu
            # tiên, không im lặng giữ tên font sẽ render sai.
            for i in range(self.cb_font.count()):
                if self.cb_font.itemData(i):
                    idx = i
                    break
        if idx >= 0:
            self.cb_font.setCurrentIndex(idx)

    def changeEvent(self, event) -> None:  # noqa: N802 — Qt API
        # Quay lại dialog sau khi thả font vào thư mục (Explorer) → đổ lại
        # danh sách để font mới hiện ngay, không phải mở lại app.
        from PySide6.QtCore import QEvent
        if (event.type() == QEvent.ActivationChange and self.isActiveWindow()
                and hasattr(self, "cb_font")):
            current = self.cb_font.currentData()
            self.cb_font.blockSignals(True)
            self._populate_fonts()
            self._select_font(current or self._style.get("font", "Arial"))
            self.cb_font.blockSignals(False)
        super().changeEvent(event)

    def _open_fonts_dir(self) -> None:
        """Mở (tạo nếu chưa có) thư mục fonts/ cạnh app trong Explorer."""
        from autodub.utils import fonts_dir
        d = fonts_dir()
        os.makedirs(d, exist_ok=True)
        # README để người mở thư mục lần đầu biết phải làm gì.
        readme = os.path.join(d, "THEM_FONT_O_DAY.txt")
        if not os.path.exists(readme):
            try:
                with open(readme, "w", encoding="utf-8") as f:
                    f.write(
                        "THÊM FONT CHO PHỤ ĐỀ\n"
                        "=====================\n\n"
                        "1. Tải font tại https://fonts.google.com\n"
                        "   (lọc Language → Vietnamese để font có đủ dấu "
                        "tiếng Việt).\n"
                        "2. Giải nén, thả các file .ttf / .otf vào thư mục "
                        "này.\n"
                        "3. Quay lại cửa sổ chỉnh phụ đề — font mới hiện "
                        "ngay trong danh sách\n   và hiển thị đúng trên "
                        "video ở mọi máy.\n\n"
                        "Gợi ý font hợp kiểu chữ video: Be Vietnam Pro, "
                        "Montserrat, Lexend, Baloo 2.\n"
                        "Font Google Fonts dùng giấy phép mở (OFL) — đóng "
                        "gói kèm app thoải mái.\n")
            except OSError:
                pass
        os.startfile(d)  # noqa: S606

    def _pick_color(self, key: str) -> None:
        from PySide6.QtWidgets import QColorDialog
        defaults = {"color": tokens.SUBTITLE_TEXT_DEFAULT,
                    "outline_color": tokens.SUBTITLE_OUTLINE_DEFAULT,
                    "box_color": tokens.SUBTITLE_BOXFILL_DEFAULT,
                    "highlight_color": tokens.SUBTITLE_HIGHLIGHT_DEFAULT}
        current = self._style.get(key, defaults.get(key, tokens.SUBTITLE_TEXT_DEFAULT))
        color = QColorDialog.getColor(QColor(current), self, "Chọn màu")
        if not color.isValid():
            return
        hex_color = color.name().upper()
        self._style[key] = hex_color
        btn = {"color": self.btn_color,
               "outline_color": self.btn_outline_color,
               "box_color": self.btn_box_color,
               "highlight_color": self.btn_highlight}[key]
        self._paint_color_button(btn, hex_color)
        self.canvas.set_style(self._style)

    # -------------------------------------------------------- results ----- #

    def style(self) -> dict:
        return dict(self._style)

    def regions(self) -> list[dict]:
        return self.canvas.normalized_regions()
