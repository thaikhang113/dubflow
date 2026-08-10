"""Hệ biểu tượng vẽ bằng QPainter — không cần tệp SVG hay PNG bên ngoài.

Mỗi biểu tượng là một QIcon 20x20 nền trong suốt, vẽ có khử răng cưa.
Màu lấy từ bảng màu tối của ứng dụng để mọi nơi trông nhất quán.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from autodub_gui import theme, tokens

_ICON_SIZE = 20
_STROKE = 1.5


def _make_icon(draw_fn, color: str | QColor) -> QIcon:
    """Tạo QIcon từ hàm vẽ draw_fn(painter, rect, color)."""
    px = QPixmap(_ICON_SIZE, _ICON_SIZE)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(1.5, 1.5, _ICON_SIZE - 3, _ICON_SIZE - 3)
    draw_fn(p, r, QColor(color))
    p.end()
    return QIcon(px)


def nav_icon(icon_fn, normal: str | None = None,
             selected: str | None = None) -> QIcon:
    """Biểu tượng hai trạng thái cho mục điều hướng.

    Trạng thái thường vẽ màu chữ phụ; khi hàng được chọn, item view của Qt
    tự dùng pixmap ở chế độ Selected — vẽ màu chàm để khớp pill sáng.
    """
    icon = icon_fn(normal or tokens.TEXT_SECONDARY)
    sel = icon_fn(selected or tokens.PRIMARY)
    px = sel.pixmap(_ICON_SIZE, _ICON_SIZE)
    icon.addPixmap(px, QIcon.Mode.Selected)
    return icon


def app_logo(size: int = 32) -> QPixmap:
    """Biểu trưng ứng dụng lấy từ logo.ico; thiếu tệp thì vẽ tay."""
    try:
        from autodub.utils import bundled_file
        path = bundled_file("logo.ico")
        if path and os.path.exists(path):
            px = QIcon(str(path)).pixmap(size, size)
            if not px.isNull():
                return px
    except Exception:
        pass
    return brand_logo(size)


# ---- Các hàm vẽ biểu tượng ----


def _draw_play(p: QPainter, r: QRectF, c: QColor) -> None:
    """Tam giác phát."""
    path = QPainterPath()
    path.moveTo(r.left() + r.width() * 0.30, r.top() + r.height() * 0.15)
    path.lineTo(r.left() + r.width() * 0.30, r.top() + r.height() * 0.85)
    path.lineTo(r.left() + r.width() * 0.80, r.top() + r.height() * 0.50)
    path.closeSubpath()
    p.setBrush(c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(path)


def _draw_folder(p: QPainter, r: QRectF, c: QColor) -> None:
    """Thư mục đơn giản."""
    w, h = r.width(), r.height()
    tab_w = w * 0.30
    tab_h = h * 0.15
    p.setPen(QPen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(r.left() + 1, r.top() + tab_h)
    path.lineTo(r.left() + 1, r.top() + h - 1)
    path.lineTo(r.right() - 1, r.top() + h - 1)
    path.lineTo(r.right() - 1, r.top() + tab_h + tab_h * 0.5)
    path.lineTo(r.left() + tab_w + tab_w * 0.2, r.top() + tab_h + tab_h * 0.5)
    path.lineTo(r.left() + tab_w, r.top() + 1)
    path.lineTo(r.left() + 1, r.top() + 1)
    path.closeSubpath()
    p.drawPath(path)


def _draw_reload(p: QPainter, r: QRectF, c: QColor) -> None:
    """Mũi tên vòng cung tải lại."""
    p.setPen(QPen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    rad = r.width() * 0.32
    # Arc
    arc_rect = QRectF(cx - rad, cy - rad, rad * 2, rad * 2)
    p.drawArc(arc_rect, 30 * 16, 300 * 16)
    # Arrow head
    end_angle = -60
    import math
    ex = cx + rad * math.cos(math.radians(end_angle))
    ey = cy - rad * math.sin(math.radians(end_angle))
    path = QPainterPath()
    path.moveTo(ex - 3, ey - 3)
    path.lineTo(ex, ey)
    path.lineTo(ex + 3, ey + 2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _draw_trash(p: QPainter, r: QRectF, c: QColor) -> None:
    """Thùng rác."""
    w, h = r.width(), r.height()
    p.setPen(QPen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Lid
    lid_y = r.top() + h * 0.20
    p.drawLine(QPointF(r.left() + 2, lid_y), QPointF(r.right() - 2, lid_y))
    # Handle
    handle_x = r.center().x()
    p.drawLine(QPointF(handle_x - w * 0.1, lid_y),
               QPointF(handle_x - w * 0.1, r.top() + 1))
    p.drawLine(QPointF(handle_x + w * 0.1, lid_y),
               QPointF(handle_x + w * 0.1, r.top() + 1))
    p.drawLine(QPointF(handle_x - w * 0.1, r.top() + 1),
               QPointF(handle_x + w * 0.1, r.top() + 1))
    # Body
    body = QRectF(r.left() + 3, lid_y + 1, w - 6, h - lid_y - 2)
    p.drawRect(body)
    # Lines inside
    line_y1 = body.top() + body.height() * 0.35
    line_y2 = body.top() + body.height() * 0.60
    p.drawLine(QPointF(body.left() + 2, line_y1),
               QPointF(body.right() - 2, line_y1))
    p.drawLine(QPointF(body.left() + 2, line_y2),
               QPointF(body.right() - 2, line_y2))


def _draw_edit(p: QPainter, r: QRectF, c: QColor) -> None:
    """Bút chì chỉnh sửa."""
    p.setPen(QPen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Pencil body (diagonal line)
    p.drawLine(QPointF(r.left() + 2, r.bottom() - 2),
               QPointF(r.right() - 6, r.top() + 6))
    # Pencil tip
    p.drawLine(QPointF(r.right() - 6, r.top() + 6),
               QPointF(r.right() - 2, r.top() + 2))
    # Horizontal line bottom
    p.drawLine(QPointF(r.left() + 2, r.bottom() - 2),
               QPointF(r.left() + 9, r.bottom() - 7))


def _draw_download(p: QPainter, r: QRectF, c: QColor) -> None:
    """Mũi tên tải xuống."""
    cx = r.center().x()
    p.setPen(QPen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Arrow shaft
    p.drawLine(QPointF(cx, r.top() + 2), QPointF(cx, r.bottom() - 4))
    # Arrow head
    ah = r.bottom() - 2
    p.drawLine(QPointF(cx - r.width() * 0.22, ah - r.height() * 0.18),
               QPointF(cx, ah))
    p.drawLine(QPointF(cx, ah),
               QPointF(cx + r.width() * 0.22, ah - r.height() * 0.18))
    # Base line
    p.drawLine(QPointF(r.left() + 2, r.bottom() - 1),
               QPointF(r.right() - 2, r.bottom() - 1))


def _draw_mic(p: QPainter, r: QRectF, c: QColor) -> None:
    """Micrô thu âm."""
    w, h = r.width(), r.height()
    p.setPen(QPen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Mic body (oval)
    mic_w = w * 0.28
    mic_h = h * 0.45
    mic_x = r.center().x() - mic_w / 2
    mic_y = r.top() + 2
    p.drawRoundedRect(QRectF(mic_x, mic_y, mic_w, mic_h), mic_w / 2, mic_w / 2)
    # Stand
    stand_top = mic_y + mic_h
    stand_bottom = r.bottom() - 2
    p.drawLine(QPointF(r.center().x(), stand_top),
               QPointF(r.center().x(), stand_bottom))
    # Base
    base_w = w * 0.45
    p.drawLine(QPointF(r.center().x() - base_w / 2, stand_bottom),
               QPointF(r.center().x() + base_w / 2, stand_bottom))


def _draw_layers(p: QPainter, r: QRectF, c: QColor) -> None:
    """Nhiều lớp chồng nhau — xử lý hàng loạt."""
    w, h = r.width(), r.height()
    p.setPen(QPen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    offset = w * 0.1
    rect_w = w * 0.55
    rect_h = h * 0.35
    # Back layer
    back = QRectF(r.center().x() - rect_w / 2 - offset,
                  r.center().y() - rect_h / 2 + offset,
                  rect_w, rect_h)
    p.drawRect(back)
    # Front layer
    front = QRectF(r.center().x() - rect_w / 2 + offset,
                   r.center().y() - rect_h / 2 - offset,
                   rect_w, rect_h)
    p.drawRect(front)


def _draw_gear(p: QPainter, r: QRectF, c: QColor) -> None:
    """Bánh răng cài đặt."""
    p.setPen(QPen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    outer = r.width() * 0.38
    inner = r.width() * 0.22
    p.drawEllipse(QPointF(cx, cy), outer, outer)
    p.drawEllipse(QPointF(cx, cy), inner, inner)


def _draw_check(p: QPainter, r: QRectF, c: QColor) -> None:
    """Dấu tích."""
    p.setPen(QPen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(r.left() + r.width() * 0.15, r.center().y())
    path.lineTo(r.center().x() - r.width() * 0.05, r.bottom() - r.height() * 0.20)
    path.lineTo(r.right() - r.width() * 0.10, r.top() + r.height() * 0.20)
    p.drawPath(path)


def _draw_warning(p: QPainter, r: QRectF, c: QColor) -> None:
    """Tam giác cảnh báo."""
    w, h = r.width(), r.height()
    p.setPen(QPen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(r.center().x(), r.top() + 2)
    path.lineTo(r.right() - 2, r.bottom() - 2)
    path.lineTo(r.left() + 2, r.bottom() - 2)
    path.closeSubpath()
    p.drawPath(path)
    # Exclamation mark
    ex_y = r.top() + h * 0.40
    p.drawLine(QPointF(r.center().x(), ex_y),
               QPointF(r.center().x(), r.bottom() - h * 0.28))
    p.drawPoint(QPointF(r.center().x(), r.bottom() - h * 0.15))


def _draw_error(p: QPainter, r: QRectF, c: QColor) -> None:
    """Dấu nhân trong vòng tròn."""
    p.setPen(QPen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    rad = r.width() * 0.38
    p.drawEllipse(QPointF(cx, cy), rad, rad)
    inset = rad * 0.55
    p.drawLine(QPointF(cx - inset, cy - inset),
               QPointF(cx + inset, cy + inset))
    p.drawLine(QPointF(cx + inset, cy - inset),
               QPointF(cx - inset, cy + inset))


def _draw_external(p: QPainter, r: QRectF, c: QColor) -> None:
    """Mũi tên chéo ra ngoài — mở bằng trình quản lý tệp."""
    w, h = r.width(), r.height()
    p.setPen(QPen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Box
    box = QRectF(r.left() + 1, r.top() + 1, w * 0.55, h * 0.55)
    p.drawRect(box)
    # Arrow
    p.drawLine(QPointF(box.right(), box.top()),
               QPointF(r.right() - 1, r.top() + 1))
    p.drawLine(QPointF(r.right() - 1, r.top() + 1),
               QPointF(r.right() - 1, r.top() + h * 0.3))
    p.drawLine(QPointF(r.right() - 1, r.top() + 1),
               QPointF(r.right() - w * 0.3, r.top() + 1))


# ---- Public API ----


def play(color: str | None = None) -> QIcon:
    return _make_icon(_draw_play, color or theme.SUCCESS)


def folder(color: str | None = None) -> QIcon:
    return _make_icon(_draw_folder, color or theme.TEXT_MUTED)


def reload(color: str | None = None) -> QIcon:
    return _make_icon(_draw_reload, color or theme.TEXT_MUTED)


def trash(color: str | None = None) -> QIcon:
    return _make_icon(_draw_trash, color or theme.ERROR)


def edit(color: str | None = None) -> QIcon:
    return _make_icon(_draw_edit, color or theme.ACCENT)


def download(color: str | None = None) -> QIcon:
    return _make_icon(_draw_download, color or theme.ACCENT)


def mic(color: str | None = None) -> QIcon:
    return _make_icon(_draw_mic, color or theme.TEXT_MUTED)


def layers(color: str | None = None) -> QIcon:
    return _make_icon(_draw_layers, color or theme.TEXT_MUTED)


def gear(color: str | None = None) -> QIcon:
    return _make_icon(_draw_gear, color or theme.TEXT_MUTED)


def check(color: str | None = None) -> QIcon:
    return _make_icon(_draw_check, color or theme.SUCCESS)


def warning(color: str | None = None) -> QIcon:
    return _make_icon(_draw_warning, color or theme.WARNING)


def error(color: str | None = None) -> QIcon:
    return _make_icon(_draw_error, color or theme.ERROR)


def external(color: str | None = None) -> QIcon:
    return _make_icon(_draw_external, color or theme.TEXT_MUTED)


def _draw_home(p: QPainter, r: QRectF, c: QColor) -> None:
    """Ngôi nhà đơn giản."""
    w, h = r.width(), r.height()
    p.setPen(QPen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Mái nhà (tam giác)
    roof = QPainterPath()
    roof.moveTo(r.center().x(), r.top() + 2)
    roof.lineTo(r.right() - 2, r.top() + h * 0.45)
    roof.lineTo(r.left() + 2, r.top() + h * 0.45)
    roof.closeSubpath()
    p.drawPath(roof)
    # Thân nhà
    body = QRectF(r.left() + w * 0.18, r.top() + h * 0.42,
                  w * 0.64, h * 0.55)
    p.drawRect(body)
    # Cửa
    door_w = w * 0.18
    door_h = h * 0.28
    door_x = r.center().x() - door_w / 2
    door_y = r.bottom() - door_h - 1
    p.drawRect(QRectF(door_x, door_y, door_w, door_h))


def _draw_search(p: QPainter, r: QRectF, c: QColor) -> None:
    """Kính lúp."""
    p.setPen(QPen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    rad = r.width() * 0.28
    p.drawEllipse(QPointF(cx - 1, cy - 1), rad, rad)
    # Cán
    handle_x = cx + rad * 0.7
    handle_y = cy + rad * 0.7
    p.drawLine(QPointF(handle_x, handle_y),
               QPointF(handle_x + rad * 0.8, handle_y + rad * 0.8))


def home(color: str | None = None) -> QIcon:
    return _make_icon(_draw_home, color or theme.TEXT_MUTED)


def search(color: str | None = None) -> QIcon:
    return _make_icon(_draw_search, color or theme.TEXT_MUTED)


# ---- Bộ biểu tượng mở rộng (Giai đoạn 0) ----


def _outline(p: QPainter, c: QColor) -> None:
    """Đặt bút nét mảnh cho biểu tượng dạng viền."""
    p.setPen(QPen(c, _STROKE, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_file_plus(p: QPainter, r: QRectF, c: QColor) -> None:
    """Trang giấy có dấu cộng — tạo dự án mới."""
    w, h = r.width(), r.height()
    _outline(p, c)
    fold = w * 0.30
    path = QPainterPath()
    path.moveTo(r.left() + w * 0.18, r.top() + 1)
    path.lineTo(r.right() - fold, r.top() + 1)
    path.lineTo(r.right() - w * 0.12, r.top() + fold)
    path.lineTo(r.right() - w * 0.12, r.bottom() - 1)
    path.lineTo(r.left() + w * 0.18, r.bottom() - 1)
    path.closeSubpath()
    p.drawPath(path)
    cx = r.center().x() + w * 0.03
    cy = r.center().y() + h * 0.12
    arm = w * 0.16
    p.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
    p.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))


def _draw_help_circle(p: QPainter, r: QRectF, c: QColor) -> None:
    """Vòng tròn có dấu hỏi."""
    _outline(p, c)
    cx, cy = r.center().x(), r.center().y()
    rad = r.width() * 0.42
    p.drawEllipse(QPointF(cx, cy), rad, rad)
    arc = QRectF(cx - rad * 0.34, cy - rad * 0.58, rad * 0.68, rad * 0.62)
    p.drawArc(arc, 200 * 16, -240 * 16)
    p.drawLine(QPointF(cx, cy), QPointF(cx, cy + rad * 0.24))
    p.drawPoint(QPointF(cx, cy + rad * 0.58))


def _draw_bell(p: QPainter, r: QRectF, c: QColor) -> None:
    """Chuông thông báo."""
    w, h = r.width(), r.height()
    _outline(p, c)
    path = QPainterPath()
    path.moveTo(r.left() + w * 0.12, r.top() + h * 0.72)
    path.lineTo(r.left() + w * 0.22, r.top() + h * 0.60)
    path.lineTo(r.left() + w * 0.22, r.top() + h * 0.40)
    path.arcTo(QRectF(r.left() + w * 0.22, r.top() + h * 0.10,
                      w * 0.56, h * 0.56), 180, -180)
    path.lineTo(r.left() + w * 0.78, r.top() + h * 0.60)
    path.lineTo(r.left() + w * 0.88, r.top() + h * 0.72)
    path.closeSubpath()
    p.drawPath(path)
    clapper = QRectF(r.center().x() - w * 0.10, r.top() + h * 0.74,
                     w * 0.20, h * 0.16)
    p.drawArc(clapper, 0, -180 * 16)


def _draw_pause(p: QPainter, r: QRectF, c: QColor) -> None:
    """Hai vạch đứng — tạm dừng."""
    w, h = r.width(), r.height()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    bar_w = w * 0.18
    top, height = r.top() + h * 0.16, h * 0.68
    p.drawRoundedRect(QRectF(r.center().x() - w * 0.30, top, bar_w, height), 1.5, 1.5)
    p.drawRoundedRect(QRectF(r.center().x() + w * 0.12, top, bar_w, height), 1.5, 1.5)


def _draw_skip_back(p: QPainter, r: QRectF, c: QColor) -> None:
    """Tam giác lùi kèm vạch — về câu trước."""
    w, h = r.width(), r.height()
    p.setPen(QPen(c, _STROKE, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(r.left() + w * 0.20, r.top() + h * 0.18),
               QPointF(r.left() + w * 0.20, r.bottom() - h * 0.18))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    tri = QPainterPath()
    tri.moveTo(r.right() - w * 0.14, r.top() + h * 0.16)
    tri.lineTo(r.right() - w * 0.14, r.bottom() - h * 0.16)
    tri.lineTo(r.left() + w * 0.30, r.center().y())
    tri.closeSubpath()
    p.drawPath(tri)


def _draw_skip_forward(p: QPainter, r: QRectF, c: QColor) -> None:
    """Tam giác tiến kèm vạch — sang câu sau."""
    w, h = r.width(), r.height()
    p.setPen(QPen(c, _STROKE, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(r.right() - w * 0.20, r.top() + h * 0.18),
               QPointF(r.right() - w * 0.20, r.bottom() - h * 0.18))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    tri = QPainterPath()
    tri.moveTo(r.left() + w * 0.14, r.top() + h * 0.16)
    tri.lineTo(r.left() + w * 0.14, r.bottom() - h * 0.16)
    tri.lineTo(r.right() - w * 0.30, r.center().y())
    tri.closeSubpath()
    p.drawPath(tri)


def _speaker_path(r: QRectF) -> QPainterPath:
    """Thân loa dùng chung cho biểu tượng âm lượng và tắt tiếng."""
    w, h = r.width(), r.height()
    path = QPainterPath()
    path.moveTo(r.left() + w * 0.06, r.top() + h * 0.36)
    path.lineTo(r.left() + w * 0.24, r.top() + h * 0.36)
    path.lineTo(r.left() + w * 0.46, r.top() + h * 0.14)
    path.lineTo(r.left() + w * 0.46, r.bottom() - h * 0.14)
    path.lineTo(r.left() + w * 0.24, r.bottom() - h * 0.36)
    path.lineTo(r.left() + w * 0.06, r.bottom() - h * 0.36)
    path.closeSubpath()
    return path


def _draw_volume(p: QPainter, r: QRectF, c: QColor) -> None:
    """Loa có sóng âm."""
    w, h = r.width(), r.height()
    _outline(p, c)
    p.drawPath(_speaker_path(r))
    for i, scale in enumerate((0.22, 0.40)):
        box = QRectF(r.left() + w * 0.40, r.center().y() - h * scale,
                     w * (0.30 + i * 0.24), h * scale * 2)
        p.drawArc(box, -55 * 16, 110 * 16)


def _draw_fullscreen(p: QPainter, r: QRectF, c: QColor) -> None:
    """Bốn góc mở rộng — toàn màn hình."""
    w, h = r.width(), r.height()
    _outline(p, c)
    arm_x, arm_y = w * 0.26, h * 0.26
    corners = (
        (r.left() + 1, r.top() + 1, arm_x, arm_y),
        (r.right() - 1, r.top() + 1, -arm_x, arm_y),
        (r.left() + 1, r.bottom() - 1, arm_x, -arm_y),
        (r.right() - 1, r.bottom() - 1, -arm_x, -arm_y),
    )
    for x, y, dx, dy in corners:
        p.drawLine(QPointF(x, y), QPointF(x + dx, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy))


def _draw_pip(p: QPainter, r: QRectF, c: QColor) -> None:
    """Khung lớn kèm khung nhỏ ở góc dưới bên phải."""
    w, h = r.width(), r.height()
    _outline(p, c)
    p.drawRoundedRect(QRectF(r.left() + 1, r.top() + 1, w - 2, h - 2), 2.5, 2.5)
    inner = QRectF(r.left() + w * 0.46, r.top() + h * 0.48,
                   w * 0.44, h * 0.36)
    p.drawRoundedRect(inner, 2, 2)


def _draw_scissors(p: QPainter, r: QRectF, c: QColor) -> None:
    """Kéo cắt — tách câu thoại."""
    w, h = r.width(), r.height()
    _outline(p, c)
    rad = w * 0.13
    p.drawEllipse(QPointF(r.left() + w * 0.20, r.bottom() - rad - 1), rad, rad)
    p.drawEllipse(QPointF(r.right() - w * 0.20, r.bottom() - rad - 1), rad, rad)
    p.drawLine(QPointF(r.left() + w * 0.26, r.bottom() - rad * 2 - 1),
               QPointF(r.right() - w * 0.18, r.top() + 1))
    p.drawLine(QPointF(r.right() - w * 0.26, r.bottom() - rad * 2 - 1),
               QPointF(r.left() + w * 0.18, r.top() + 1))


def _draw_zoom(p: QPainter, r: QRectF, c: QColor, plus: bool) -> None:
    """Kính lúp có dấu cộng hoặc dấu trừ."""
    w = r.width()
    _outline(p, c)
    cx, cy = r.center().x() - w * 0.06, r.center().y() - w * 0.06
    rad = w * 0.30
    p.drawEllipse(QPointF(cx, cy), rad, rad)
    p.drawLine(QPointF(cx + rad * 0.72, cy + rad * 0.72),
               QPointF(r.right() - 1, r.bottom() - 1))
    arm = rad * 0.52
    p.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
    if plus:
        p.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))


def _draw_zoom_in(p: QPainter, r: QRectF, c: QColor) -> None:
    _draw_zoom(p, r, c, True)


def _draw_zoom_out(p: QPainter, r: QRectF, c: QColor) -> None:
    _draw_zoom(p, r, c, False)


def _draw_chevron_down(p: QPainter, r: QRectF, c: QColor) -> None:
    """Mũi nhọn hướng xuống."""
    w, h = r.width(), r.height()
    _outline(p, c)
    p.drawLine(QPointF(r.left() + w * 0.22, r.top() + h * 0.36),
               QPointF(r.center().x(), r.top() + h * 0.64))
    p.drawLine(QPointF(r.center().x(), r.top() + h * 0.64),
               QPointF(r.right() - w * 0.22, r.top() + h * 0.36))


def _draw_chevron_right(p: QPainter, r: QRectF, c: QColor) -> None:
    """Mũi nhọn hướng sang phải."""
    w, h = r.width(), r.height()
    _outline(p, c)
    p.drawLine(QPointF(r.left() + w * 0.36, r.top() + h * 0.22),
               QPointF(r.left() + w * 0.64, r.center().y()))
    p.drawLine(QPointF(r.left() + w * 0.64, r.center().y()),
               QPointF(r.left() + w * 0.36, r.bottom() - h * 0.22))


def _draw_chevron_left(p: QPainter, r: QRectF, c: QColor) -> None:
    """Mũi nhọn hướng sang trái."""
    w, h = r.width(), r.height()
    _outline(p, c)
    p.drawLine(QPointF(r.left() + w * 0.64, r.top() + h * 0.22),
               QPointF(r.left() + w * 0.36, r.center().y()))
    p.drawLine(QPointF(r.left() + w * 0.36, r.center().y()),
               QPointF(r.left() + w * 0.64, r.bottom() - h * 0.22))


def _draw_upload_cloud(p: QPainter, r: QRectF, c: QColor) -> None:
    """Đám mây có mũi tên hướng lên — vùng kéo thả tệp."""
    w, h = r.width(), r.height()
    _outline(p, c)
    cloud = QPainterPath()
    cloud.moveTo(r.left() + w * 0.22, r.top() + h * 0.68)
    cloud.arcTo(QRectF(r.left() + w * 0.06, r.top() + h * 0.40,
                       w * 0.32, h * 0.32), 270, -180)
    cloud.arcTo(QRectF(r.left() + w * 0.20, r.top() + h * 0.18,
                       w * 0.38, h * 0.38), 180, -170)
    cloud.arcTo(QRectF(r.left() + w * 0.54, r.top() + h * 0.36,
                       w * 0.38, h * 0.34), 120, -210)
    p.drawPath(cloud)
    cx = r.center().x()
    p.drawLine(QPointF(cx, r.bottom() - 1), QPointF(cx, r.center().y() - h * 0.02))
    p.drawLine(QPointF(cx - w * 0.13, r.center().y() + h * 0.11),
               QPointF(cx, r.center().y() - h * 0.02))
    p.drawLine(QPointF(cx, r.center().y() - h * 0.02),
               QPointF(cx + w * 0.13, r.center().y() + h * 0.11))


def _draw_merge(p: QPainter, r: QRectF, c: QColor) -> None:
    """Hai mũi tên chụm lại — gộp câu thoại."""
    w, h = r.width(), r.height()
    _outline(p, c)
    mid_x = r.center().x()
    p.drawLine(QPointF(r.left() + w * 0.10, r.top() + h * 0.16),
               QPointF(mid_x, r.center().y()))
    p.drawLine(QPointF(r.left() + w * 0.10, r.bottom() - h * 0.16),
               QPointF(mid_x, r.center().y()))
    p.drawLine(QPointF(mid_x, r.center().y()),
               QPointF(r.right() - w * 0.06, r.center().y()))
    p.drawLine(QPointF(r.right() - w * 0.24, r.center().y() - h * 0.13),
               QPointF(r.right() - w * 0.06, r.center().y()))
    p.drawLine(QPointF(r.right() - w * 0.24, r.center().y() + h * 0.13),
               QPointF(r.right() - w * 0.06, r.center().y()))


def _draw_waveform(p: QPainter, r: QRectF, c: QColor) -> None:
    """Năm vạch dọc cao dần rồi thấp dần — dạng sóng âm."""
    w, h = r.width(), r.height()
    p.setPen(QPen(c, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    ratios = (0.32, 0.62, 0.94, 0.62, 0.32)
    step = w / (len(ratios) + 1)
    for i, ratio in enumerate(ratios):
        x = r.left() + step * (i + 1)
        half = h * ratio / 2
        p.drawLine(QPointF(x, r.center().y() - half),
                   QPointF(x, r.center().y() + half))


def file_plus(color: str | None = None) -> QIcon:
    return _make_icon(_draw_file_plus, color or theme.TEXT_MUTED)


def help_circle(color: str | None = None) -> QIcon:
    return _make_icon(_draw_help_circle, color or theme.TEXT_MUTED)


def bell(color: str | None = None) -> QIcon:
    return _make_icon(_draw_bell, color or theme.TEXT_MUTED)


def pause(color: str | None = None) -> QIcon:
    return _make_icon(_draw_pause, color or theme.WARNING)


def skip_back(color: str | None = None) -> QIcon:
    return _make_icon(_draw_skip_back, color or theme.TEXT_MUTED)


def skip_forward(color: str | None = None) -> QIcon:
    return _make_icon(_draw_skip_forward, color or theme.TEXT_MUTED)


def volume(color: str | None = None) -> QIcon:
    return _make_icon(_draw_volume, color or theme.TEXT_MUTED)


def fullscreen(color: str | None = None) -> QIcon:
    return _make_icon(_draw_fullscreen, color or theme.TEXT_MUTED)


def pip(color: str | None = None) -> QIcon:
    return _make_icon(_draw_pip, color or theme.TEXT_MUTED)


def scissors(color: str | None = None) -> QIcon:
    return _make_icon(_draw_scissors, color or theme.TEXT_MUTED)


def zoom_in(color: str | None = None) -> QIcon:
    return _make_icon(_draw_zoom_in, color or theme.TEXT_MUTED)


def zoom_out(color: str | None = None) -> QIcon:
    return _make_icon(_draw_zoom_out, color or theme.TEXT_MUTED)


def chevron_down(color: str | None = None) -> QIcon:
    return _make_icon(_draw_chevron_down, color or theme.TEXT_MUTED)


def chevron_right(color: str | None = None) -> QIcon:
    return _make_icon(_draw_chevron_right, color or theme.TEXT_MUTED)


def chevron_left(color: str | None = None) -> QIcon:
    return _make_icon(_draw_chevron_left, color or theme.TEXT_MUTED)


def upload_cloud(color: str | None = None) -> QIcon:
    return _make_icon(_draw_upload_cloud, color or tokens.ACCENT_BLUE)


def merge(color: str | None = None) -> QIcon:
    return _make_icon(_draw_merge, color or theme.TEXT_MUTED)


def waveform(color: str | None = None) -> QIcon:
    return _make_icon(_draw_waveform, color or tokens.ACCENT_BLUE)


# ---- Bộ biểu tượng bổ sung (restyle indigo/violet) ----


def _draw_star(p: QPainter, r: QRectF, c: QColor) -> None:
    """Ngôi sao năm cánh — mục yêu thích / nổi bật."""
    import math
    _outline(p, c)
    cx, cy = r.center().x(), r.center().y()
    outer = r.width() * 0.44
    inner = outer * 0.44
    path = QPainterPath()
    for i in range(10):
        rad = outer if i % 2 == 0 else inner
        ang = math.radians(-90 + i * 36)
        x = cx + rad * math.cos(ang)
        y = cy + rad * math.sin(ang)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    p.drawPath(path)


def _draw_sliders(p: QPainter, r: QRectF, c: QColor) -> None:
    """Ba thanh trượt ngang — tinh chỉnh."""
    w, h = r.width(), r.height()
    _outline(p, c)
    rows = (0.25, 0.50, 0.75)
    knobs = (0.65, 0.35, 0.55)
    knob_r = w * 0.09
    for row, knob in zip(rows, knobs):
        y = r.top() + h * row
        p.drawLine(QPointF(r.left() + 1, y), QPointF(r.right() - 1, y))
        p.setBrush(c)
        p.drawEllipse(QPointF(r.left() + w * knob, y), knob_r, knob_r)
        p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_globe(p: QPainter, r: QRectF, c: QColor) -> None:
    """Quả địa cầu — dịch thuật / ngôn ngữ."""
    _outline(p, c)
    cx, cy = r.center().x(), r.center().y()
    rad = r.width() * 0.42
    p.drawEllipse(QPointF(cx, cy), rad, rad)
    # Kinh tuyến giữa (elip dọc) và xích đạo
    p.drawEllipse(QPointF(cx, cy), rad * 0.45, rad)
    p.drawLine(QPointF(cx - rad, cy), QPointF(cx + rad, cy))


def _draw_captions(p: QPainter, r: QRectF, c: QColor) -> None:
    """Khung phụ đề có hai dòng chữ."""
    w, h = r.width(), r.height()
    _outline(p, c)
    box = QRectF(r.left() + 1, r.top() + h * 0.14, w - 2, h * 0.72)
    p.drawRoundedRect(box, 3, 3)
    y1 = box.top() + box.height() * 0.40
    y2 = box.top() + box.height() * 0.68
    p.drawLine(QPointF(box.left() + w * 0.12, y1),
               QPointF(box.left() + w * 0.42, y1))
    p.drawLine(QPointF(box.left() + w * 0.52, y1),
               QPointF(box.right() - w * 0.12, y1))
    p.drawLine(QPointF(box.left() + w * 0.12, y2),
               QPointF(box.left() + w * 0.60, y2))


def _draw_user(p: QPainter, r: QRectF, c: QColor) -> None:
    """Người dùng: đầu tròn và vai."""
    w, h = r.width(), r.height()
    _outline(p, c)
    head_r = w * 0.20
    p.drawEllipse(QPointF(r.center().x(), r.top() + h * 0.30), head_r, head_r)
    shoulders = QRectF(r.left() + w * 0.16, r.top() + h * 0.56,
                       w * 0.68, h * 0.66)
    p.drawArc(shoulders, 0, 180 * 16)


def star(color: str | None = None) -> QIcon:
    return _make_icon(_draw_star, color or theme.TEXT_MUTED)


def sliders(color: str | None = None) -> QIcon:
    return _make_icon(_draw_sliders, color or theme.TEXT_MUTED)


def globe(color: str | None = None) -> QIcon:
    return _make_icon(_draw_globe, color or theme.TEXT_MUTED)


def captions(color: str | None = None) -> QIcon:
    return _make_icon(_draw_captions, color or theme.TEXT_MUTED)


def user(color: str | None = None) -> QIcon:
    return _make_icon(_draw_user, color or theme.TEXT_MUTED)


def _draw_chart_bar(p: QPainter, r: QRectF, c: QColor) -> None:
    """Biểu đồ cột — 3 cột cao thấp khác nhau."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    cw = r.width() * 0.22   # chiều rộng mỗi cột
    gap = r.width() * 0.07  # khoảng cách giữa cột
    # Cột 1 (50%)
    h1 = r.height() * 0.50
    p.drawRect(QRectF(r.left(), r.bottom() - h1, cw, h1))
    # Cột 2 (80%)
    h2 = r.height() * 0.80
    p.drawRect(QRectF(r.left() + cw + gap, r.bottom() - h2, cw, h2))
    # Cột 3 (60%)
    h3 = r.height() * 0.60
    p.drawRect(QRectF(r.left() + (cw + gap) * 2, r.bottom() - h3, cw, h3))


def chart_bar(color: str | None = None) -> QIcon:
    return _make_icon(_draw_chart_bar, color or theme.TEXT_MUTED)


def _draw_eye(p: QPainter, r: QRectF, c: QColor) -> None:
    """Icon mắt (eye) — hiện track."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    cx, cy = r.center().x(), r.center().y()
    # Hình ellipse mắt
    eye_path = QPainterPath()
    eye_path.moveTo(cx - 9, cy)
    eye_path.quadTo(cx - 9, cy - 5, cx, cy - 6)
    eye_path.quadTo(cx + 9, cy - 5, cx + 9, cy)
    eye_path.quadTo(cx + 9, cy + 5, cx, cy + 6)
    eye_path.quadTo(cx - 9, cy + 5, cx - 9, cy)
    p.drawPath(eye_path)
    # Con ngươi (pupil)
    p.drawEllipse(QPointF(cx, cy), 3, 3)


def _draw_eye_off(p: QPainter, r: QRectF, c: QColor) -> None:
    """Icon mắt có gạch chéo (eye-off) — ẩn track."""
    _draw_eye(p, r, c)
    # Gạch chéo qua mắt
    p.setPen(QPen(c, 1.8))
    cx, cy = r.center().x(), r.center().y()
    p.drawLine(QLineF(cx - 10, cy - 8, cx + 10, cy + 8))


def eye(color: str | None = None) -> QIcon:
    return _make_icon(_draw_eye, color or tokens.TEXT_SECONDARY)


def eye_off(color: str | None = None) -> QIcon:
    return _make_icon(_draw_eye_off, color or tokens.TEXT_SECONDARY)
    """Biểu trưng VoxDub: ô vuông bo góc và bốn vạch sóng âm."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    radius = size * 9 / 32
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(tokens.BRAND_LOGO_BG))
    p.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setPen(QPen(QColor(tokens.ACCENT_BLUE), max(1.6, size * 0.075),
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    ratios = (0.34, 0.66, 0.50, 0.26)
    step = size / (len(ratios) + 1)
    for i, ratio in enumerate(ratios):
        x = step * (i + 1)
        half = size * ratio / 2
        p.drawLine(QPointF(x, size / 2 - half), QPointF(x, size / 2 + half))
    p.end()
    return px
