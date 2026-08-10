"""Dải thời gian: thước đo, dạng sóng, khối câu thoại và con trỏ phát.

Hiệu năng là yêu cầu chính ở đây. Với video dài và hàng trăm câu, mỗi lần vẽ
chỉ được đụng tới phần đang nhìn thấy, nên mọi phép vẽ đều cắt theo khoảng
thời gian hiện ra trên màn hình.
"""
from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF

from autodub_gui import icons, tokens
from autodub_gui.formatting import format_duration
from autodub_gui.ui.buttons import IconButton

RULER_H = 22
BAND_H = 34          # chiều cao mỗi dải sóng của một track
LABEL_W = 88         # cột nhãn bên trái (tên track + chấm màu)
TRACK_H = 30
TOOLBAR_H = 34
THUMB_H = 36         # chiều cao dải thumbnail video
# WAVE_H và TOTAL_H giữ lại tên để code nhập khẩu cũ không vỡ
WAVE_H = BAND_H      # alias compat — 1 band = 34px
TOTAL_H = RULER_H + WAVE_H + TRACK_H + TOOLBAR_H + 12   # giá trị 1-track
# Khoảng cách tối thiểu giữa hai thumbnail để không vẽ chồng lên nhau
_THUMB_MIN_GAP_PX = 4

MIN_ZOOM, MAX_ZOOM = 1.0, 40.0
_ZOOM_STEP = 1.25
_SNAP_S = 0.05                 # bám mốc 0,05 giây khi kéo
_MIN_BLOCK_S = 0.2
_EDGE_GRAB_PX = 6              # vùng bắt mép trái phải của khối
_PLAYHEAD_W = 2
_HANDLE_W = 10
_LABEL_STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800)
_MIN_LABEL_GAP_PX = 70

# Thứ tự cố định: (kind, nhãn hiển thị, mã màu sóng, mã màu nền)
_TRACK_META: tuple[tuple[str, str, str, str], ...] = (
    ("original", "Âm gốc",   "TRACK_ORIGINAL", "TRACK_ORIGINAL_BG"),
    ("voice",    "Giọng AI",  "TRACK_VOICE",    "TRACK_VOICE_BG"),
    ("music",    "Nhạc nền",  "TRACK_MUSIC",    "TRACK_MUSIC_BG"),
)


class TimelineCanvas(QWidget):
    """Phần vẽ chính: thước, dạng sóng, khối câu và con trỏ phát."""

    seek_requested = Signal(float)
    segment_clicked = Signal(int)
    segment_moved = Signal(int, float, float)     # số câu, mốc đầu, mốc cuối
    split_requested = Signal(int, float)
    layout_changed = Signal()                     # số band đổi → cha chỉnh cao
    selection_changed = Signal(float, float)      # (start_s, end_s) vùng chọn mới

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        self.setMinimumHeight(RULER_H + BAND_H + TRACK_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self._peaks: list[float] = []
        self._track_peaks: dict[str, list[float]] = {}
        self._track_avail: dict[str, bool] = {}
        self._track_visible: dict[str, bool] = {}  # toggle hiển thị band
        self._thumbnails: list[tuple[float, str]] = []  # (timestamp_s, path)
        self._thumb_cache: dict[str, QPixmap] = {}      # path → pixmap
        self._segments: list[dict] = []
        self._duration = 0.0
        self._position = 0.0
        self._zoom = MIN_ZOOM
        self._offset = 0.0            # thời điểm ở mép trái, tính bằng giây
        self._selected = -1
        self._scissors = False
        self._drag: dict | None = None
        self._loading = False
        self._selection: tuple[float, float] | None = None  # (start, end) giây

    # -- Dữ liệu -------------------------------------------------------
    def set_duration(self, seconds: float) -> None:
        self._duration = max(0.0, seconds)
        self.update()

    def set_peaks(self, values: list[float]) -> None:
        """API cũ: một dải sóng duy nhất, dùng khi dự án chỉ có một nguồn."""
        self._peaks = values or []
        self._loading = False
        self.setToolTip("" if self._peaks else
                        "Không đọc được dạng sóng của tệp âm thanh này")
        self.update()

    def set_track_available(self, kind: str, available: bool) -> None:
        """Bật hoặc ẩn một band; track thiếu tệp thì ẩn hẳn, không vẽ giả."""
        before = self._band_kinds()
        self._track_avail[kind] = bool(available)
        if available and kind not in self._track_visible:
            self._track_visible[kind] = True  # mặc định hiện khi có file
        if self._band_kinds() != before:
            self.layout_changed.emit()
        self.update()

    def toggle_track_visible(self, kind: str) -> None:
        """Bật/tắt hiển thị một track; emit layout_changed nếu số band thay đổi."""
        if kind not in self._track_avail or not self._track_avail[kind]:
            return
        before = self._band_kinds()
        self._track_visible[kind] = not self._track_visible.get(kind, True)
        if self._band_kinds() != before:
            self.layout_changed.emit()
        self.update()

    def set_thumbnails(self, thumbs: list[tuple[float, str]]) -> None:
        """Nhận danh sách (timestamp_giây, đường_dẫn) từ TimelineThumbnailWorker.

        Xóa cache cũ rồi load lại. Nếu thumbs rỗng thì ẩn dải thumbnail.
        """
        self._thumbnails = sorted(thumbs, key=lambda t: t[0])
        self._thumb_cache.clear()
        # Pre-load pixmap cho tất cả file hiện có
        for _ts, path in self._thumbnails:
            if path not in self._thumb_cache:
                px = QPixmap(path)
                if not px.isNull():
                    self._thumb_cache[path] = px.scaled(
                        px.width(), THUMB_H,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
        if self._thumbnails:
            self.layout_changed.emit()
        self.update()

    def set_track_peaks(self, kind: str, values: list[float]) -> None:
        self._track_peaks[kind] = values or []
        self._loading = False
        self.update()

    def _band_kinds(self) -> list[str]:
        """Các band đang hiển thị, theo thứ tự cố định; rỗng → 1 band cũ."""
        kinds = [k for k, *_ in _TRACK_META
                 if self._track_avail.get(k)
                 and self._track_visible.get(k, True)]
        return kinds or ["default"]

    def wave_height(self) -> int:
        h = len(self._band_kinds()) * BAND_H
        if self._thumbnails:
            h += THUMB_H
        return h

    def _thumb_band_top(self) -> int:
        """Vị trí Y của dải thumbnail — ngay dưới ruler, trước các band sóng."""
        return RULER_H if self._thumbnails else -1

    def set_loading(self, loading: bool) -> None:
        self._loading = loading
        self.update()

    def set_segments(self, segments: list[dict]) -> None:
        self._segments = sorted(segments,
                                key=lambda s: float(s.get("start", 0.0)))
        self.update()

    def set_position(self, seconds: float) -> None:
        self._position = max(0.0, seconds)
        self._keep_playhead_visible()
        self.update()

    def set_selected(self, seg_id: int) -> None:
        self._selected = seg_id
        self.update()

    def set_scissors(self, on: bool) -> None:
        """Bật chế độ cắt: bấm vào một khối để tách câu tại đó."""
        self._scissors = on
        self.setCursor(Qt.CursorShape.SplitHCursor if on
                       else Qt.CursorShape.ArrowCursor)

    def get_selection(self) -> tuple[float, float] | None:
        """Trả về vùng thời gian đã chọn (start, end) giây, hoặc None."""
        return self._selection

    def clear_selection(self) -> None:
        """Xóa vùng chọn hiện tại."""
        if self._selection is not None:
            self._selection = None
            self.update()

    # -- Thu phóng -----------------------------------------------------
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, value: float, anchor: float | None = None) -> None:
        """Đổi mức phóng to, giữ nguyên thời điểm đang ở giữa màn hình."""
        center = anchor if anchor is not None else self._center_time()
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, value))
        self._offset = center - self._visible_span() / 2
        self._clamp_offset()
        self.update()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * _ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / _ZOOM_STEP)

    def _visible_span(self) -> float:
        return self._duration / self._zoom if self._duration else 1.0

    def _center_time(self) -> float:
        return self._offset + self._visible_span() / 2

    def _clamp_offset(self) -> None:
        span = self._visible_span()
        self._offset = max(0.0, min(self._offset, max(0.0, self._duration - span)))

    def _keep_playhead_visible(self) -> None:
        """Cuộn theo con trỏ phát khi nó chạy ra ngoài vùng nhìn thấy."""
        span = self._visible_span()
        if self._position < self._offset or self._position > self._offset + span:
            self._offset = self._position - span / 2
            self._clamp_offset()

    # -- Đổi qua lại giữa thời gian và điểm ảnh -------------------------
    def _content_w(self) -> int:
        """Bề rộng vùng vẽ sóng, không tính cột nhãn bên trái."""
        return max(1, self.width() - LABEL_W)

    def _to_x(self, seconds: float) -> float:
        span = self._visible_span()
        if span <= 0:
            return float(LABEL_W)
        return LABEL_W + (seconds - self._offset) / span * self._content_w()

    def _to_time(self, x: float) -> float:
        span = self._visible_span()
        return (self._offset
                + max(0.0, x - LABEL_W) / self._content_w() * span)

    # -- Vẽ ------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tokens.BG_MAIN))
        if self._duration <= 0:
            self._paint_placeholder(painter)
            painter.end()
            return
        self._paint_ruler(painter)
        if self._thumbnails:
            self._paint_thumbnails(painter)
        self._paint_waveform(painter)
        self._paint_segments(painter)
        self._paint_labels(painter)
        self._paint_playhead(painter)
        painter.end()

    def _paint_placeholder(self, painter: QPainter) -> None:
        painter.setPen(QColor(tokens.TEXT_DISABLED))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                         "Chưa có dự án nào được mở")

    def _label_step(self) -> int:
        """Khoảng cách giữa hai mốc chữ trên thước, đủ thưa để không chồng nhau."""
        span = self._visible_span()
        for step in _LABEL_STEPS:
            if step / span * self.width() >= _MIN_LABEL_GAP_PX:
                return step
        return _LABEL_STEPS[-1]

    def _paint_ruler(self, painter: QPainter) -> None:
        rect = QRectF(0, 0, self.width(), RULER_H)
        painter.fillRect(rect, QColor(tokens.BG_SIDEBAR))
        # Vùng selection (Shift+drag) — highlight trước khi vẽ ticks
        if self._selection:
            s, e = self._selection
            xs, xe = self._to_x(s), self._to_x(e)
            sel_rect = QRectF(max(xs, LABEL_W), 0,
                              max(0.0, xe - max(xs, LABEL_W)), RULER_H)
            sel_color = QColor(tokens.PRIMARY)
            sel_color.setAlpha(40)
            painter.fillRect(sel_rect, sel_color)
            # Đường viền hai đầu vùng chọn
            border_pen = QPen(QColor(tokens.PRIMARY), 1)
            border_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(border_pen)
            if xs >= LABEL_W:
                painter.drawLine(QLineF(xs, 0, xs, RULER_H))
            if xe <= self.width():
                painter.drawLine(QLineF(xe, 0, xe, RULER_H))
        step = self._label_step()
        font = QFont(self.font())
        font.setPixelSize(tokens.FS_BADGE)
        painter.setFont(font)
        start = int(self._offset // step) * step
        end = self._offset + self._visible_span()
        tick = start
        while tick <= end:
            x = self._to_x(tick)
            if x < LABEL_W:
                tick += step
                continue          # khuất sau cột nhãn
            painter.setPen(QPen(QColor(tokens.BORDER_DEFAULT), 1))
            painter.drawLine(QLineF(x, RULER_H - 6, x, RULER_H))
            painter.setPen(QColor(tokens.RULER_TEXT))
            painter.drawText(QPointF(x + 3, RULER_H - 8),
                             format_duration(tick))
            tick += step

    def _paint_thumbnails(self, painter: QPainter) -> None:
        """Vẽ dải thumbnail video ngay dưới ruler, trước các band sóng."""
        top = self._thumb_band_top()
        if top < 0:
            return
        # Nền đen cho dải thumbnail
        painter.fillRect(QRectF(LABEL_W, top, self._content_w(), THUMB_H),
                         QColor(tokens.BG_VIDEO))
        visible_start = self._offset
        visible_end = self._offset + self._visible_span()
        last_right = -9999.0
        for ts, path in self._thumbnails:
            if ts < visible_start or ts > visible_end:
                continue
            px = self._thumb_cache.get(path)
            if px is None or px.isNull():
                continue
            x = self._to_x(ts)
            # Vẽ thumbnail căn giữa timestamp; không chồng lên thumbnail trước
            left = x - px.width() / 2
            if left < last_right + _THUMB_MIN_GAP_PX:
                continue
            # Clip vào vùng nhìn thấy
            if left < LABEL_W:
                left = LABEL_W
            if left + px.width() > self.width():
                break
            painter.drawPixmap(int(left), top, px)
            last_right = left + px.width()

    def _paint_waveform(self, painter: QPainter) -> None:
        kinds = self._band_kinds()
        top = RULER_H + (THUMB_H if self._thumbnails else 0)
        for kind in kinds:
            if kind == "default":
                self._paint_band(painter, top, self._peaks,
                                 tokens.WAVEFORM, tokens.BG_PANEL,
                                 show_hint=True)
            else:
                meta = next(m for m in _TRACK_META if m[0] == kind)
                self._paint_band(painter, top,
                                 self._track_peaks.get(kind, []),
                                 getattr(tokens, meta[2]),
                                 getattr(tokens, meta[3]))
            top += BAND_H

    def _paint_band(self, painter: QPainter, top: float,
                    peaks: list[float], wave_color: str, bg_color: str,
                    show_hint: bool = False) -> None:
        """Một dải sóng cao BAND_H: nền pastel + thanh biên độ màu track."""
        rect = QRectF(LABEL_W, top, self._content_w(), BAND_H)
        painter.fillRect(rect, QColor(bg_color))
        middle = top + BAND_H / 2
        if not peaks:
            if show_hint:
                self._paint_flat_band(painter, middle)
            else:
                painter.setPen(QPen(QColor(tokens.BORDER_DEFAULT), 1))
                painter.drawLine(QLineF(LABEL_W, middle,
                                        self.width(), middle))
            return
        lines: list[QLineF] = []
        total = len(peaks)
        for x in range(LABEL_W, self.width()):
            seconds = self._to_time(x)
            index = int(seconds / self._duration * total) if self._duration else 0
            if not 0 <= index < total:
                continue
            half = peaks[index] * (BAND_H / 2 - 2)
            lines.append(QLineF(x, middle - half, x, middle + half))
        painter.setPen(QPen(QColor(wave_color), 1))
        painter.drawLines(lines)

    def _paint_labels(self, painter: QPainter) -> None:
        """Cột nhãn trái: tên track kèm chấm màu + nút toggle, đè lên mọi band."""
        visible_kinds = self._band_kinds()
        height = RULER_H + self.wave_height() + TRACK_H
        painter.fillRect(QRectF(0, 0, LABEL_W, height),
                         QColor(tokens.TRACK_LABEL_BG))
        painter.setPen(QPen(QColor(tokens.TRACK_LABEL_BORDER), 1))
        painter.drawLine(QLineF(LABEL_W - 0.5, 0, LABEL_W - 0.5, height))
        font = QFont(self.font())
        font.setPixelSize(tokens.FS_BADGE)
        font.setBold(True)
        painter.setFont(font)
        # Nhãn cho dải thumbnail (nếu có)
        thumb_top = self._thumb_band_top()
        if thumb_top >= 0:
            painter.setPen(QColor(tokens.TEXT_MUTED))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(QRectF(4, thumb_top, LABEL_W - 8, THUMB_H),
                             Qt.AlignmentFlag.AlignVCenter, "Video")
        # Vẽ nhãn cho các track đang hiển thị
        top = RULER_H + (THUMB_H if self._thumbnails else 0)
        for kind in visible_kinds:
            self._paint_track_label(painter, top, kind)
            top += BAND_H
        # Nhãn cho dòng khối câu thoại
        painter.setPen(QColor(tokens.TEXT_MUTED))
        painter.drawText(QRectF(24, top, LABEL_W - 28, TRACK_H),
                         Qt.AlignmentFlag.AlignVCenter, "Câu thoại")
        # Vẽ nút toggle cho các track có sẵn nhưng bị ẩn (ở cuối cột)
        hidden = [k for k, *_ in _TRACK_META
                  if self._track_avail.get(k)
                  and not self._track_visible.get(k, True)]
        if hidden:
            toggle_top = height - len(hidden) * 20 - 4
            for kind in hidden:
                meta = next(m for m in _TRACK_META if m[0] == kind)
                self._paint_toggle_btn(painter, 4, toggle_top, kind,
                                      meta[1], False)
                toggle_top += 20

    def _paint_track_label(self, painter: QPainter, top: float,
                           kind: str) -> None:
        """Vẽ một dòng nhãn track: chấm màu + tên + nút toggle."""
        if kind == "default":
            dot, text = tokens.WAVEFORM, "Âm thanh"
        else:
            meta = next(m for m in _TRACK_META if m[0] == kind)
            dot, text = getattr(tokens, meta[2]), meta[1]
        # Chấm màu
        painter.setBrush(QColor(dot))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(14, top + BAND_H / 2), 3.5, 3.5)
        # Tên track
        painter.setPen(QColor(tokens.TEXT_SECONDARY))
        painter.drawText(QRectF(24, top, LABEL_W - 48, BAND_H),
                         Qt.AlignmentFlag.AlignVCenter, text)
        # Nút toggle (mắt) nếu không phải default
        if kind != "default":
            visible = self._track_visible.get(kind, True)
            self._paint_toggle_btn(painter, LABEL_W - 20, top + BAND_H / 2 - 8,
                                  kind, text, visible)

    def _paint_toggle_btn(self, painter: QPainter, x: float, y: float,
                          kind: str, tooltip: str, visible: bool) -> None:
        """Vẽ nút toggle hiển thị track (icon mắt 16×16)."""
        from autodub_gui import icons
        icon = icons.eye(tokens.TEXT_MUTED) if visible else icons.eye_off(
            tokens.TEXT_DISABLED)
        icon.paint(painter, int(x), int(y), 16, 16)

    def _paint_flat_band(self, painter: QPainter, middle: float) -> None:
        """Không đọc được dạng sóng thì vẽ một dải phẳng mờ, không vẽ sóng giả."""
        color = QColor(tokens.BORDER_DEFAULT)
        painter.setPen(QPen(color, 2))
        painter.drawLine(QLineF(LABEL_W, middle, self.width(), middle))
        painter.setPen(QColor(tokens.TEXT_DISABLED))
        painter.drawText(
            QRectF(LABEL_W, middle + 6, self._content_w(), 18),
            Qt.AlignmentFlag.AlignCenter,
            "Đang đọc dạng sóng…" if self._loading
            else "Không đọc được dạng sóng của tệp âm thanh này")

    def _paint_segments(self, painter: QPainter) -> None:
        top = RULER_H + self.wave_height()
        painter.fillRect(QRectF(0, top, self.width(), TRACK_H),
                         QColor(tokens.BG_MAIN))
        visible_end = self._offset + self._visible_span()
        font = QFont(self.font())
        font.setPixelSize(tokens.FS_BADGE)
        painter.setFont(font)
        for segment in self._segments:
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", 0.0))
            if end < self._offset or start > visible_end:
                continue          # ngoài vùng nhìn thấy, khỏi vẽ
            self._paint_block(painter, segment, start, end, top)

    def _paint_block(self, painter: QPainter, segment: dict,
                     start: float, end: float, top: float) -> None:
        x0, x1 = self._to_x(start), self._to_x(end)
        rect = QRectF(x0, top + 3, max(2.0, x1 - x0), TRACK_H - 6)
        selected = segment.get("id") == self._selected
        painter.setBrush(QColor(tokens.SUB_BLOCK_BG))
        painter.setPen(QPen(QColor(tokens.BORDER_ACTIVE if selected
                                   else tokens.SUB_BLOCK_BORDER),
                            2 if selected else 1))
        painter.drawRoundedRect(rect, 4, 4)
        if rect.width() > 30:
            painter.setPen(QColor(tokens.SUB_BLOCK_TEXT))
            text = painter.fontMetrics().elidedText(
                str(segment.get("text_vi", "")), Qt.TextElideMode.ElideRight,
                int(rect.width()) - 8)
            painter.drawText(rect.adjusted(4, 0, -4, 0),
                             Qt.AlignmentFlag.AlignVCenter, text)

    def _paint_playhead(self, painter: QPainter) -> None:
        x = self._to_x(self._position)
        if x < LABEL_W or x > self.width():
            return
        painter.setPen(QPen(QColor(tokens.PLAYHEAD), _PLAYHEAD_W))
        painter.drawLine(QLineF(x, 0, x, self.height()))
        painter.setBrush(QColor(tokens.PLAYHEAD))
        painter.setPen(Qt.PenStyle.NoPen)
        half = _HANDLE_W / 2
        painter.drawPolygon(QPolygonF([QPointF(x - half, 0),
                                       QPointF(x + half, 0),
                                       QPointF(x, _HANDLE_W)]))

    # -- Tương tác chuột -----------------------------------------------
    def _segment_at(self, x: float, y: float) -> dict | None:
        wave_h = self.wave_height()
        if x < LABEL_W:
            return None
        if not (RULER_H + wave_h <= y <= RULER_H + wave_h + TRACK_H):
            return None
        seconds = self._to_time(x)
        for segment in self._segments:
            if (float(segment.get("start", 0.0)) <= seconds
                    <= float(segment.get("end", 0.0))):
                return segment
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        # --- Cột nhãn: chỉ xử lý click nút toggle mắt ---
        if x < LABEL_W:
            self._handle_label_click(x, y)
            return
        # --- Shift + bấm trên ruler → bắt đầu chọn vùng ---
        if y <= RULER_H and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            t = self._to_time(x)
            self._drag = {"mode": "selection", "anchor": t}
            self._selection = (t, t)
            self.update()
            return
        segment = self._segment_at(x, y)
        if segment is not None:
            if self._scissors:
                self.split_requested.emit(int(segment["id"]), self._to_time(x))
                return
            self._begin_drag(segment, x)
            self.segment_clicked.emit(int(segment["id"]))
            return
        # Bấm trên ruler không Shift → seek
        if y <= RULER_H:
            self._drag = {"mode": "playhead"}
            self.seek_requested.emit(self._to_time(x))
            return
        self._drag = {"mode": "playhead"}
        self.seek_requested.emit(self._to_time(x))

    def _handle_label_click(self, x: float, y: float) -> None:
        """Xử lý click trong cột nhãn — chỉ vùng nút mắt (toggle) là tương tác."""
        # Nút mắt nằm ở cột phải LABEL_W-20..LABEL_W, giữa band sóng
        if x < LABEL_W - 20:
            return
        thumb_offset = THUMB_H if self._thumbnails else 0
        visible_kinds = self._band_kinds()
        top = RULER_H + thumb_offset
        for kind in visible_kinds:
            if kind == "default":
                top += BAND_H
                continue
            btn_top = top + BAND_H / 2 - 8
            btn_bot = btn_top + 16
            if btn_top <= y <= btn_bot:
                self.toggle_track_visible(kind)
                return
            top += BAND_H
        # Click vào track đang ẩn (hiển thị ở cuối cột)
        hidden = [k for k, *_ in _TRACK_META
                  if self._track_avail.get(k)
                  and not self._track_visible.get(k, True)]
        if hidden:
            height = RULER_H + self.wave_height() + TRACK_H
            toggle_top = height - len(hidden) * 20 - 4
            for kind in hidden:
                if toggle_top <= y <= toggle_top + 16:
                    self.toggle_track_visible(kind)
                    return
                toggle_top += 20

    def _begin_drag(self, segment: dict, x: float) -> None:
        """Bấm vào giữa khối là dời cả câu, bấm sát mép là kéo dài hoặc rút ngắn."""
        start, end = float(segment["start"]), float(segment["end"])
        left, right = self._to_x(start), self._to_x(end)
        if abs(x - left) <= _EDGE_GRAB_PX:
            mode = "start"
        elif abs(x - right) <= _EDGE_GRAB_PX:
            mode = "end"
        else:
            mode = "move"
        self._drag = {"mode": mode, "id": int(segment["id"]),
                      "start": start, "end": end,
                      "grab": self._to_time(x)}

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        x, y = event.position().x(), event.position().y()
        if self._drag is None:
            self._update_hover_cursor(x, y)
            return
        if self._drag["mode"] == "playhead":
            self.seek_requested.emit(self._to_time(x))
            return
        if self._drag["mode"] == "selection":
            t = self._to_time(x)
            anchor = self._drag["anchor"]
            self._selection = (min(anchor, t), max(anchor, t))
            self.update()
            return
        self._apply_drag(self._to_time(x))

    def _update_hover_cursor(self, x: float, y: float) -> None:
        if self._scissors:
            return
        segment = self._segment_at(x, y)
        if segment is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        left = self._to_x(float(segment["start"]))
        right = self._to_x(float(segment["end"]))
        near_edge = min(abs(x - left), abs(x - right)) <= _EDGE_GRAB_PX
        self.setCursor(Qt.CursorShape.SizeHorCursor if near_edge
                       else Qt.CursorShape.OpenHandCursor)

    def _apply_drag(self, seconds: float) -> None:
        """Tính mốc mới khi kéo, có bám lưới và giữ không lấn câu bên cạnh."""
        drag = self._drag
        start, end = drag["start"], drag["end"]
        if drag["mode"] == "move":
            shift = _snap(seconds - drag["grab"])
            start, end = start + shift, end + shift
        elif drag["mode"] == "start":
            start = min(_snap(seconds), end - _MIN_BLOCK_S)
        else:
            end = max(_snap(seconds), start + _MIN_BLOCK_S)
        start, end = self._limit_to_neighbours(drag["id"], start, end)
        self._preview_move(drag["id"], start, end)

    def _limit_to_neighbours(self, seg_id: int, start: float,
                             end: float) -> tuple[float, float]:
        """Không cho khối lấn sang câu liền trước hoặc câu liền sau."""
        index = next((i for i, s in enumerate(self._segments)
                      if s.get("id") == seg_id), -1)
        if index < 0:
            return start, end
        length = end - start
        if index > 0:
            floor = float(self._segments[index - 1].get("end", 0.0))
            if start < floor:
                start = floor
                end = max(start + length, start + _MIN_BLOCK_S)
        if index < len(self._segments) - 1:
            ceiling = float(self._segments[index + 1].get("start", 0.0))
            if end > ceiling:
                end = ceiling
                start = min(start, end - _MIN_BLOCK_S)
        return max(0.0, start), min(end, self._duration or end)

    def _preview_move(self, seg_id: int, start: float, end: float) -> None:
        """Cập nhật ngay trên màn hình, chưa ghi xuống đĩa."""
        for segment in self._segments:
            if segment.get("id") == seg_id:
                segment["start"], segment["end"] = start, end
                break
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — quy ước Qt
        drag = self._drag
        self._drag = None
        if drag is None:
            return
        if drag["mode"] == "playhead":
            return
        if drag["mode"] == "selection":
            if self._selection:
                s, e = self._selection
                if e - s > 0.05:          # vùng đủ rộng mới emit
                    self.selection_changed.emit(s, e)
            return
        for segment in self._segments:
            if segment.get("id") == drag["id"]:
                new_start = float(segment["start"])
                new_end = float(segment["end"])
                if (abs(new_start - drag["start"]) > 1e-6
                        or abs(new_end - drag["end"]) > 1e-6):
                    self.segment_moved.emit(drag["id"], new_start, new_end)
                break

    def wheelEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        """Giữ Ctrl để phóng to thu nhỏ, còn lại là cuộn ngang."""
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            anchor = self._to_time(event.position().x())
            self.set_zoom(self._zoom * (_ZOOM_STEP if delta > 0
                                        else 1 / _ZOOM_STEP), anchor)
            return
        self._offset -= delta / 120 * self._visible_span() * 0.1
        self._clamp_offset()
        self.update()


def _snap(seconds: float) -> float:
    """Làm tròn về mốc 0,05 giây gần nhất cho dễ canh."""
    return round(seconds / _SNAP_S) * _SNAP_S


class Timeline(QWidget):
    """Dải thời gian hoàn chỉnh: phần vẽ cộng thanh công cụ bên dưới."""

    seek_requested = Signal(float)
    segment_clicked = Signal(int)
    segment_moved = Signal(int, float, float)
    split_requested = Signal(int, float)
    selection_play_requested = Signal(float, float)  # phát vùng đã chọn

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.canvas = TimelineCanvas()
        self.canvas.seek_requested.connect(self.seek_requested.emit)
        self.canvas.segment_clicked.connect(self.segment_clicked.emit)
        self.canvas.segment_moved.connect(self.segment_moved.emit)
        self.canvas.split_requested.connect(self.split_requested.emit)
        self.canvas.layout_changed.connect(self._update_height)
        self.canvas.selection_changed.connect(self._on_selection_changed)
        root.addWidget(self.canvas, 1)
        root.addWidget(self._build_toolbar())
        self._update_height()

    def _update_height(self) -> None:
        """Cao vừa đủ số band đang hiện; track ẩn thì không chiếm chỗ."""
        self.setFixedHeight(RULER_H + self.canvas.wave_height()
                            + TRACK_H + TOOLBAR_H + 12)

    def _on_selection_changed(self, start: float, end: float) -> None:
        """Có vùng chọn mới → hiện nút phát vùng và nhãn thời lượng."""
        self.btn_play_selection.show()
        self.btn_clear_selection.show()
        self.selection_label.setText(
            f"{format_duration(start)} – {format_duration(end)}")
        self.selection_label.show()

    def _play_selection(self) -> None:
        sel = self.canvas.get_selection()
        if sel:
            self.selection_play_requested.emit(sel[0], sel[1])

    def _clear_selection(self) -> None:
        self.canvas.clear_selection()
        self.btn_play_selection.hide()
        self.btn_clear_selection.hide()
        self.selection_label.hide()

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(TOOLBAR_H)
        bar.setStyleSheet(f"background: {tokens.BG_SIDEBAR};")
        row = QHBoxLayout(bar)
        row.setContentsMargins(tokens.SP_2, 0, tokens.SP_2, 0)
        row.setSpacing(tokens.SP_2)

        self.btn_scissors = IconButton(
            icons.scissors(tokens.TEXT_SECONDARY),
            "Chế độ cắt: bấm vào một câu để tách nó tại chỗ bấm",
            size=26, checkable=True)
        self.btn_scissors.toggled.connect(self.canvas.set_scissors)
        row.addWidget(self.btn_scissors)

        # Nút phát vùng chọn + xóa vùng chọn — chỉ hiện khi có selection
        self.btn_play_selection = IconButton(
            icons.play(tokens.PRIMARY),
            "Phát vùng đã chọn (giữ Shift và kéo trên thước để chọn vùng)",
            size=26)
        self.btn_play_selection.clicked.connect(self._play_selection)
        self.btn_play_selection.hide()
        row.addWidget(self.btn_play_selection)

        self.btn_clear_selection = IconButton(
            icons.error(tokens.TEXT_MUTED),
            "Bỏ vùng chọn",
            size=26)
        self.btn_clear_selection.clicked.connect(self._clear_selection)
        self.btn_clear_selection.hide()
        row.addWidget(self.btn_clear_selection)

        self.selection_label = QLabel("")
        self.selection_label.setStyleSheet(
            f"color: {tokens.PRIMARY}; font-size: {tokens.FS_BADGE}px; "
            f"background: transparent;")
        self.selection_label.hide()
        row.addWidget(self.selection_label)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(int(MIN_ZOOM * 10), int(MAX_ZOOM * 10))
        self.zoom_slider.setValue(int(MIN_ZOOM * 10))
        self.zoom_slider.setToolTip("Phóng to hoặc thu nhỏ dải thời gian")
        self.zoom_slider.valueChanged.connect(
            lambda v: self.canvas.set_zoom(v / 10))
        row.addWidget(self.zoom_slider, 1)

        for icon, tip, handler in (
                (icons.zoom_out(tokens.TEXT_SECONDARY), "Thu nhỏ",
                 self._zoom_out),
                (icons.zoom_in(tokens.TEXT_SECONDARY), "Phóng to",
                 self._zoom_in)):
            button = IconButton(icon, tip, size=26)
            button.clicked.connect(handler)
            row.addWidget(button)

        self.zoom_label = QLabel("1.0x")
        self.zoom_label.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_BADGE}px; "
            f"background: transparent;")
        row.addWidget(self.zoom_label)
        return bar

    def _zoom_in(self) -> None:
        self.canvas.zoom_in()
        self._sync_zoom()

    def _zoom_out(self) -> None:
        self.canvas.zoom_out()
        self._sync_zoom()

    def _sync_zoom(self) -> None:
        value = self.canvas.zoom()
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(value * 10))
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText(f"{value:.1f}x")

    # -- Cửa cho trang cha gọi vào -------------------------------------
    def set_duration(self, seconds: float) -> None:
        self.canvas.set_duration(seconds)

    def set_peaks(self, values: list[float]) -> None:
        self.canvas.set_peaks(values)

    def set_track_peaks(self, kind: str, values: list[float]) -> None:
        self.canvas.set_track_peaks(kind, values)

    def set_track_available(self, kind: str, available: bool) -> None:
        self.canvas.set_track_available(kind, available)

    def set_thumbnails(self, thumbs: list[tuple[float, str]]) -> None:
        self.canvas.set_thumbnails(thumbs)

    def set_loading(self, loading: bool) -> None:
        self.canvas.set_loading(loading)

    def set_segments(self, segments: list[dict]) -> None:
        self.canvas.set_segments(segments)

    def set_position(self, seconds: float) -> None:
        self.canvas.set_position(seconds)

    def set_selected(self, seg_id: int) -> None:
        self.canvas.set_selected(seg_id)
