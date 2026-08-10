"""Bảng màu và bảng kiểu Qt duy nhất cho toàn ứng dụng.

Nguồn sự thật về màu và khoảng cách nằm ở `autodub_gui/tokens.py`.
Tệp này chỉ làm hai việc:
  1. Xuất lại các tên cũ để những tệp chưa chuyển sang token không bị vỡ.
  2. Dựng chuỗi `STYLESHEET` từ token.

Cấm viết mã màu hex trực tiếp ở đây (`tests/test_ui_tokens.py` sẽ báo lỗi).
"""
from __future__ import annotations

import os as _os

from autodub_gui import tokens as _t

# -- Tên cũ giữ cho tương thích ngược (gỡ dần ở Giai đoạn 8) ----------
BG = _t.BG_APP
BG_SIDEBAR = _t.BG_SIDEBAR
BG_PANEL = _t.BG_PANEL
BG_INPUT = _t.BG_INPUT
BG_HOVER = _t.BG_PANEL_HOVER

BORDER = _t.BORDER_SUBTLE
BORDER_CARD = _t.BORDER_SUBTLE
BORDER_FOCUS = _t.BORDER_ACTIVE

TEXT = _t.TEXT_PRIMARY
TEXT_MUTED = _t.TEXT_SECONDARY
TEXT_DIM = _t.TEXT_MUTED

ACCENT = _t.PRIMARY
ACCENT_HOVER = _t.PRIMARY_HOVER
ACCENT_PRESSED = _t.PRIMARY_DARK
ACCENT_PURPLE = _t.ACCENT_PURPLE
ACCENT_PURPLE_HOVER = _t.ACCENT_PURPLE_HOVER

SUCCESS = _t.SUCCESS
SUCCESS_BG = _t.SUCCESS_BG
WARNING = _t.WARNING
WARNING_BG = _t.WARNING_BG
ERROR = _t.DANGER
ERROR_BG = _t.DANGER_BG
RUNNING = _t.PROCESSING


def _grad_h(start: str, end: str) -> str:
    """Dải chuyển sắc ngang từ trái sang phải, dùng trong QSS."""
    return (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {start}, stop:1 {end})")


def _triangle_asset(name: str, w: int, h: int, color: str, *,
                    up: bool = False) -> str:
    """Vẽ một tam giác nhỏ ra tệp PNG rồi trả về đường dẫn dùng trong QSS.

    Qt Style Sheets KHÔNG hỗ trợ mẹo «tam giác bằng viền» của CSS web —
    viền luôn được vẽ thành khối chữ nhật, chính là ô vuông lạ từng hiện
    cạnh các ô chọn. Cách đúng là đưa cho Qt một ảnh mũi tên thật.
    Dùng QImage nên vẽ được ngay khi nạp mô-đun, trước cả QApplication.
    """
    from PySide6.QtCore import QPointF, Qt as _Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF

    folder = _os.path.join(_os.path.expanduser("~"), ".voxdub_cache", "ui")
    _os.makedirs(folder, exist_ok=True)
    path = _os.path.join(folder, f"{name}.png")
    image = QImage(w, h, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(_Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    if up:
        points = [QPointF(0, h), QPointF(w, h), QPointF(w / 2, 0)]
    else:
        points = [QPointF(0, 0), QPointF(w, 0), QPointF(w / 2, h)]
    painter.drawPolygon(QPolygonF(points))
    painter.end()
    image.save(path)
    return path.replace("\\", "/")


_ARROW_DOWN = _triangle_asset("arrow_down", 10, 6, _t.TEXT_SECONDARY)
_ARROW_UP_S = _triangle_asset("arrow_up_s", 8, 5, _t.TEXT_SECONDARY, up=True)
_ARROW_DOWN_S = _triangle_asset("arrow_down_s", 8, 5, _t.TEXT_SECONDARY)


STYLESHEET = f"""
/* ---- Nền chung ---- */
QWidget {{
    background: {_t.BG_APP};
    color: {_t.TEXT_PRIMARY};
    font-family: {_t.FONT_STACK};
    font-size: {_t.FS_BODY}px;
}}
QMainWindow {{ background: {_t.BG_APP}; }}
QDialog {{ background: {_t.BG_PANEL}; }}

/* ---- Thanh điều hướng bên trái ---- */
QListWidget#nav, QListWidget#nav2 {{
    background: {_t.BG_SIDEBAR};
    border: none;
    outline: none;
    padding: 0px;
}}
QListWidget#nav::item, QListWidget#nav2::item {{
    height: {_t.NAV_ITEM_H}px;
    padding: 0px 14px;
    border: none;
    border-radius: {_t.RADIUS_MD}px;
    margin: 2px 10px;
    color: {_t.TEXT_SECONDARY};
    font-size: {_t.FS_BODY}px;
    font-weight: 500;
}}
QListWidget#nav::item:hover, QListWidget#nav2::item:hover {{
    background: {_t.NAV_HOVER_BG};
    color: {_t.TEXT_PRIMARY};
}}
QListWidget#nav::item:selected, QListWidget#nav2::item:selected {{
    background: {_t.BG_SELECTED};
    color: {_t.PRIMARY};
    font-weight: 600;
}}
QListWidget#nav::item:selected:hover, QListWidget#nav2::item:selected:hover {{
    background: {_t.BG_SELECTED};
    color: {_t.PRIMARY};
}}

/* ---- Thẻ nội dung ---- */
QFrame#card {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 10px;
}}
QFrame#card:hover {{
    border-color: {_t.BORDER_DEFAULT};
}}
QFrame#cardFlat {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 10px;
}}
QFrame#sidebarCard {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 10px;
}}
QFrame#banner {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 10px;
}}
QFrame#divider {{
    border: none;
    background: {_t.BORDER_SUBTLE};
    max-height: 1px;
}}

QGroupBox {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: {_t.RADIUS_LG}px;
    margin-top: 22px;
    padding: 18px 16px 16px 16px;
    font-weight: normal;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 2px 10px;
    color: {_t.TEXT_PRIMARY};
    font-size: {_t.FS_BODY}px;
    font-weight: 600;
}}

/* ---- Ô nhập liệu ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {_t.BG_INPUT};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 8px;
    padding: 8px 12px;
    min-height: 22px;
    color: {_t.TEXT_PRIMARY};
    selection-background-color: {_t.PRIMARY};
    selection-color: {_t.TEXT_ON_ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {_t.BORDER_ACTIVE};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{
    color: {_t.TEXT_DISABLED};
    background: {_t.BG_INPUT_DISABLED};
}}
QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled {{
    color: {_t.TEXT_DISABLED};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    image: url("{_ARROW_DOWN}");
    width: 10px;
    height: 6px;
    margin-right: 8px;
}}
/* Bảng thả xuống: từng dòng cao thoáng, bo góc, có trạng thái rê chuột.
   Các dòng ::item chỉ có tác dụng khi combo được gắn QStyledItemDelegate —
   xem polish_combo() trong ui/inputs.py. */
QComboBox QAbstractItemView {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_DEFAULT};
    border-radius: 10px;
    selection-background-color: {_t.BG_SELECTED};
    selection-color: {_t.PRIMARY};
    outline: none;
    padding: 5px;
}}
QComboBox QAbstractItemView::item {{
    min-height: 30px;
    padding: 4px 10px;
    border: none;
    border-radius: 6px;
    color: {_t.TEXT_PRIMARY};
}}
QComboBox QAbstractItemView::item:hover {{
    background: {_t.BG_PANEL_HOVER};
}}
QComboBox QAbstractItemView::item:selected {{
    background: {_t.BG_SELECTED};
    color: {_t.PRIMARY};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: transparent; border: none; width: 18px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{_ARROW_UP_S}");
    width: 8px;
    height: 5px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{_ARROW_DOWN_S}");
    width: 8px;
    height: 5px;
}}

/* ---- Nút bấm ---- */
QPushButton {{
    background: {_t.BG_BUTTON};
    border: 1px solid {_t.BORDER_BUTTON};
    border-radius: 8px;
    padding: 9px 18px;
    min-height: 22px;
    color: {_t.TEXT_PRIMARY};
}}
QPushButton:hover {{
    background: {_t.BG_PANEL_HOVER};
    border-color: {_t.BORDER_DEFAULT};
}}
QPushButton:pressed {{ background: {_t.BG_BUTTON_PRESSED}; }}
QPushButton:focus {{ border-color: {_t.BORDER_ACTIVE}; }}
QPushButton:disabled {{
    color: {_t.TEXT_DISABLED};
    background: {_t.BG_PANEL};
    border-color: {_t.BORDER_SUBTLE};
}}

QPushButton#primary {{
    background: {_t.PRIMARY};
    border: none;
    color: {_t.TEXT_ON_ACCENT};
    font-weight: 600;
    padding: 10px 22px;
    border-radius: {_t.RADIUS_MD}px;
}}
QPushButton#primary:hover {{
    background: {_t.PRIMARY_HOVER};
    color: {_t.TEXT_ON_ACCENT};
}}
QPushButton#primary:pressed {{ background: {_t.PRIMARY_DARK}; color: {_t.TEXT_ON_ACCENT}; }}
QPushButton#primary:focus {{
    background: {_t.PRIMARY_HOVER};
    border: 2px solid {_t.PRIMARY_DARK};
    color: {_t.TEXT_ON_ACCENT};
}}
QPushButton#primary:disabled {{
    background: {_t.PRIMARY_DISABLED_BG};
    color: {_t.TEXT_DISABLED};
}}

QPushButton#danger {{
    color: {_t.DANGER};
    border-color: {_t.BORDER_DANGER};
    background: transparent;
    font-weight: 600;
}}
QPushButton#danger:hover {{
    background: {_t.DANGER_BG};
    border-color: {_t.DANGER};
}}
QPushButton#danger:disabled {{
    color: {_t.TEXT_DISABLED};
    border-color: {_t.BORDER_SUBTLE};
    background: transparent;
}}

QPushButton#ghost {{
    background: {_t.BG_BUTTON};
    border: 1px solid {_t.BORDER_DEFAULT};
    color: {_t.TEXT_SECONDARY};
    font-weight: 500;
}}
QPushButton#ghost:hover {{
    background: {_t.BG_SELECTED_SOFT};
    color: {_t.TEXT_PRIMARY};
    border-color: {_t.PRIMARY};
}}
QPushButton#ghost:pressed {{
    background: {_t.BG_SELECTED};
    color: {_t.TEXT_PRIMARY};
    border-color: {_t.PRIMARY};
}}
QPushButton#ghost:focus {{
    border-color: {_t.BORDER_ACTIVE};
    color: {_t.TEXT_PRIMARY};
}}
QPushButton#ghost:disabled {{ color: {_t.TEXT_DISABLED}; background: transparent; }}

QPushButton#iconbtn {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 0px;
    min-height: 0px;
}}
QPushButton#iconbtn:hover {{ background: {_t.BG_PANEL_HOVER}; }}
QPushButton#iconbtn:pressed {{ background: {_t.BG_BUTTON_PRESSED}; }}
QPushButton#iconbtn:checked {{ background: {_t.BG_SELECTED}; }}
QPushButton#iconbtn:focus {{ background: {_t.BG_PANEL_HOVER}; }}

QPushButton#segment {{
    background: transparent;
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 0px;
    padding: 8px 12px;
    font-size: {_t.FS_BODY}px;
    font-weight: 500;
    color: {_t.TEXT_SECONDARY};
}}
QPushButton#segment[position="first"] {{
    border-top-left-radius: {_t.RADIUS_MD}px;
    border-bottom-left-radius: {_t.RADIUS_MD}px;
}}
QPushButton#segment[position="last"] {{
    border-top-right-radius: {_t.RADIUS_MD}px;
    border-bottom-right-radius: {_t.RADIUS_MD}px;
}}
QPushButton#segment:hover:!checked {{
    background: {_t.BG_PANEL_HOVER};
    color: {_t.TEXT_PRIMARY};
}}
QPushButton#segment:checked {{
    background: {_t.PRIMARY};
    border-color: {_t.PRIMARY};
    color: {_t.TEXT_ON_ACCENT};
    font-weight: 600;
}}
QPushButton#segment:disabled {{ color: {_t.TEXT_DISABLED}; }}

/* Nút kiểu cũ — giữ lại để các trang chưa chuyển đổi không bị vỡ */
QPushButton#stop {{
    color: {_t.DANGER}; font-weight: 600;
    border-color: {_t.BORDER_DANGER}; background: transparent;
}}
QPushButton#stop:hover {{ background: {_t.DANGER_BG}; border-color: {_t.DANGER}; }}
QPushButton#stop:disabled {{ color: {_t.TEXT_DISABLED}; border-color: {_t.BORDER_SUBTLE}; }}
QPushButton#purple {{
    background: {_t.ACCENT_PURPLE}; border: none;
    color: {_t.TEXT_ON_ACCENT}; font-weight: 600;
    padding: 9px 18px; border-radius: 8px;
}}
QPushButton#purple:hover {{ background: {_t.ACCENT_PURPLE_HOVER}; }}
QPushButton#purple:disabled {{ background: {_t.BG_PANEL}; color: {_t.TEXT_DISABLED}; }}
QPushButton#pill {{
    background: transparent; border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 0px; padding: 8px 20px; font-size: {_t.FS_BODY}px;
    font-weight: 500; color: {_t.TEXT_SECONDARY};
}}
QPushButton#pill:checked {{
    background: {_t.PRIMARY}; color: {_t.TEXT_ON_ACCENT};
    border-color: {_t.PRIMARY}; font-weight: 600;
}}
QPushButton#pill:hover:!checked {{
    background: {_t.BG_PANEL_HOVER}; color: {_t.TEXT_PRIMARY};
}}

/* ---- Thanh tab dạng viên thuốc (trang Cài đặt) ---- */
QWidget#pillTabBar {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 20px;
}}
QPushButton#pillTab {{
    background: transparent;
    border: none;
    color: {_t.TEXT_SECONDARY};
    border-radius: 17px;
    padding: 7px 16px;
    font-size: {_t.FS_BODY}px;
    font-weight: 600;
    min-height: 20px;
}}
QPushButton#pillTab:hover:!checked {{
    background: {_t.NAV_HOVER_BG};
    color: {_t.TEXT_PRIMARY};
}}
QPushButton#pillTab:checked {{
    background: {_t.PRIMARY};
    color: {_t.TEXT_ON_ACCENT};
}}

/* ---- Chip lọc (thư viện giọng đọc) ---- */
QPushButton#chip {{
    background: {_t.CHIP_BG};
    border: 1px solid {_t.BORDER_BUTTON};
    color: {_t.TEXT_SECONDARY};
    border-radius: 14px;
    padding: 4px 14px;
    font-size: {_t.FS_LABEL}px;
    font-weight: 500;
    min-height: 18px;
}}
QPushButton#chip:hover:!checked {{
    border-color: {_t.BORDER_DEFAULT};
    color: {_t.TEXT_PRIMARY};
}}
QPushButton#chip:checked {{
    background: {_t.CHIP_BG_ACTIVE};
    border-color: {_t.CHIP_BORDER_ACTIVE};
    color: {_t.TEXT_PRIMARY};
    font-weight: 600;
}}

/* ---- Thẻ giọng đọc ---- */
QFrame#voiceCard {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: {_t.RADIUS_LG}px;
}}
QFrame#voiceCard:hover {{
    background: {_t.BG_PANEL_HOVER};
    border-color: {_t.BORDER_DEFAULT};
}}
QFrame#voiceCard[selected="true"] {{
    background: {_t.VOICE_SELECTED_BG};
    border: 1px solid {_t.BORDER_ACTIVE};
}}

/* ---- Nhãn nhóm trong thanh bên (CÔNG CỤ / HỆ THỐNG) ---- */
QLabel#sectionLabel {{
    color: {_t.SECTION_LABEL};
    font-size: {_t.FS_BADGE}px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 2px 16px;
    background: transparent;
}}

/* ---- Ô đánh dấu ---- */
QCheckBox, QRadioButton {{ spacing: 9px; background: transparent; padding: 3px 0; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {_t.BORDER_DEFAULT};
    background: {_t.BG_INPUT};
    border-radius: 4px;
}}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {_t.PRIMARY};
    border-color: {_t.PRIMARY};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {_t.BORDER_ACTIVE};
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background: {_t.BG_INPUT_DISABLED};
    border-color: {_t.BORDER_SUBTLE};
}}

/* ---- Thanh tiến trình ---- */
QProgressBar {{
    background: {_t.TRACK_BG};
    border: none;
    border-radius: 3px;
    height: 5px;
    text-align: center;
    color: {_t.TEXT_SECONDARY};
    font-size: {_t.FS_META}px;
}}
QProgressBar::chunk {{
    background: {_grad_h(_t.PRIMARY, _t.ACCENT_BLUE)};
    border-radius: 3px;
}}

/* ---- Bảng dữ liệu ---- */
QTableWidget, QTableView {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: {_t.BG_SELECTED};
    selection-color: {_t.TEXT_PRIMARY};
    outline: none;
}}
QTableWidget::item {{ padding: 6px 12px; border: none; }}
QTableWidget::item:selected {{
    background: {_t.BG_SELECTED};
    color: {_t.TEXT_PRIMARY};
}}
QHeaderView::section {{
    background: {_t.BG_PANEL};
    color: {_t.TEXT_MUTED};
    padding: 12px;
    border: none;
    border-bottom: 1px solid {_t.BORDER_SUBTLE};
    font-size: {_t.FS_LABEL}px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background: {_t.BG_PANEL}; border: none; }}

/* ---- Danh sách ---- */
QListWidget {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 10px;
    outline: none;
}}
QListWidget::item {{ border: none; color: {_t.TEXT_PRIMARY}; }}
QListWidget::item:selected {{ background: {_t.BG_SELECTED}; }}

/* ---- Thẻ tab ---- */
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {_t.TEXT_SECONDARY};
    padding: 9px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
    font-size: {_t.FS_BODY}px;
    font-weight: 500;
}}
QTabBar::tab:hover {{ color: {_t.TEXT_PRIMARY}; }}
QTabBar::tab:selected {{
    color: {_t.TEXT_PRIMARY};
    border-bottom: 2px solid {_t.PRIMARY};
    font-weight: 600;
}}
QTabBar::tab:disabled {{ color: {_t.TEXT_DISABLED}; }}

/* ---- Thanh cuộn ---- */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {_t.BORDER_DEFAULT}; border-radius: 4px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {_t.SCROLL_HANDLE_HOVER}; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {_t.BORDER_DEFAULT}; border-radius: 4px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {_t.SCROLL_HANDLE_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- Thanh trượt ---- */
QSlider::groove:horizontal {{
    height: 4px; background: {_t.TRACK_BG}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {_t.PRIMARY}; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -5px 0;
    border-radius: 7px; background: {_t.TEXT_ON_ACCENT};
    border: 1px solid {_t.BORDER_DEFAULT};
}}
QSlider::handle:horizontal:disabled {{ background: {_t.TEXT_DISABLED}; }}
QSlider::sub-page:horizontal:disabled {{ background: {_t.BORDER_DEFAULT}; }}

/* ---- Thành phần khác ---- */
QScrollArea {{ border: none; background: transparent; }}
QLabel {{ background: transparent; }}
QLabel#pageTitle {{
    font-size: {_t.FS_PAGE_TITLE}px; font-weight: 700; color: {_t.TEXT_PRIMARY};
}}
QLabel#sectionTitle {{
    font-size: {_t.FS_SECTION}px; font-weight: 700; color: {_t.TEXT_PRIMARY};
}}
QLabel#cardTitle {{
    font-size: {_t.FS_CARD_TITLE}px; font-weight: 600; color: {_t.TEXT_PRIMARY};
}}
QLabel#hint {{ color: {_t.TEXT_MUTED}; font-size: {_t.FS_LABEL}px; }}
QLabel#meta {{ color: {_t.TEXT_MUTED}; font-size: {_t.FS_META}px; }}
QLabel#sectionNote {{ color: {_t.TEXT_SECONDARY}; font-size: {_t.FS_LABEL}px; }}
QLabel#sectionHeader {{
    color: {_t.TEXT_MUTED}; font-size: {_t.FS_META}px; font-weight: 700;
    padding-bottom: 4px;
}}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical {{ height: 4px; }}
QStatusBar {{
    background: {_t.BG_SIDEBAR};
    color: {_t.TEXT_SECONDARY};
    border-top: 1px solid {_t.BORDER_SUBTLE};
    font-size: {_t.FS_LABEL}px;
}}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {_t.BG_INPUT};
    color: {_t.TEXT_PRIMARY};
    border: 1px solid {_t.BORDER_DEFAULT};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: {_t.FS_LABEL}px;
}}
QMenu {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_DEFAULT};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 7px 16px; border-radius: 6px; color: {_t.TEXT_PRIMARY};
}}
QMenu::item:selected {{ background: {_t.BG_SELECTED}; }}
QMenu::separator {{
    height: 1px; background: {_t.BORDER_SUBTLE}; margin: 4px 8px;
}}

/* ---- Thẻ video (giữ cho trang cũ) ---- */
QFrame#videoCard {{
    background: {_t.BG_PANEL};
    border: 1px solid {_t.BORDER_SUBTLE};
    border-radius: 10px;
}}
QFrame#videoCard:hover {{
    border-color: {_t.BORDER_DEFAULT};
    background: {_t.BG_PANEL_HOVER};
}}
"""
