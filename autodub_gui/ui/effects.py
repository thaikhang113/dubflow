"""Hiệu ứng đổ bóng mềm.

Bảng kiểu QSS của Qt không hỗ trợ `box-shadow`, nên phải dùng
`QGraphicsDropShadowEffect`.

Cảnh báo hiệu năng: chỉ đặt cho tối đa khoảng 12 widget cùng lúc (thẻ lớn,
hộp thoại, cửa sổ nổi). Đặt lên mọi thẻ trong lưới sẽ làm tụt khung hình.
Tuyệt đối không đặt lên widget có `QGraphicsView` hay video bên trong, vì
Qt sẽ vô hiệu hóa bề mặt vẽ gốc của hệ điều hành.
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from autodub_gui import tokens


def soft_shadow(widget: QWidget, blur: int = tokens.SHADOW_BLUR,
                dy: int = tokens.SHADOW_Y,
                alpha: int = tokens.SHADOW_ALPHA) -> QGraphicsDropShadowEffect:
    """Gắn bóng mềm cho widget và trả về hiệu ứng vừa gắn."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setXOffset(0)
    eff.setYOffset(dy)
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)
    return eff
