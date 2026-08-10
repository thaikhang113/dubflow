"""Đặt kiểu dáng cho riêng một widget, không để lây sang widget con.

Đây là một cái bẫy rất dễ mắc của Qt: gọi `widget.setStyleSheet("background: X")`
sẽ áp nền đó cho CẢ widget con bên trong, và mức ưu tiên còn cao hơn bảng kiểu
chung của ứng dụng. Hậu quả thấy được là nút chính mất hẳn nền chuyển sắc khi
nó nằm trong một khung đã đặt nền.

Cách chữa là luôn viết bộ chọn theo tên riêng của widget. Các hàm dưới đây tự
đặt tên nếu widget chưa có, rồi mới gắn bảng kiểu.
"""
from __future__ import annotations

from itertools import count

from PySide6.QtWidgets import QWidget

_AUTO_NAME = count()


def _ensure_name(widget: QWidget, prefix: str) -> str:
    """Bảo đảm widget có tên riêng để viết bộ chọn."""
    name = widget.objectName()
    if not name:
        name = f"{prefix}{next(_AUTO_NAME)}"
        widget.setObjectName(name)
    return name


def scoped_style(widget: QWidget, body: str, *,
                 selector: str = "") -> None:
    """Gắn bảng kiểu chỉ áp cho riêng widget này.

    `body` là phần bên trong dấu ngoặc nhọn, ví dụ "background: {tokens.BG_PANEL};".
    """
    name = _ensure_name(widget, "scoped")
    prefix = selector or type(widget).__name__
    widget.setStyleSheet(f"{prefix}#{name} {{ {body} }}")


def clear_background(widget: QWidget) -> None:
    """Nền trong suốt cho riêng widget này."""
    scoped_style(widget, "background: transparent;")


def panel_background(widget: QWidget, color: str, *,
                     border: str = "", radius: int = 0) -> None:
    """Nền đặc cho riêng một khung chứa, kèm viền và bo góc nếu cần."""
    parts = [f"background: {color};"]
    parts.append(f"border: {border};" if border else "border: none;")
    if radius:
        parts.append(f"border-radius: {radius}px;")
    scoped_style(widget, " ".join(parts))
