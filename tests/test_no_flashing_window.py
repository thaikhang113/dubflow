"""Không widget nào được cho hiện khi còn chưa có cha.

Trên Windows, một widget chưa có cha mà bị gọi ``setVisible(True)`` hoặc
``show()`` sẽ được hệ điều hành dựng thành một CỬA SỔ RIÊNG. Nếu ngay sau đó
widget được đưa vào bố cục, cửa sổ ấy bị hủy — người dùng thấy màn hình nháy
một cái. Dựng liền mấy chục widget như vậy (trang Cài đặt, trang Trợ giúp) thì
màn hình nháy liên tục, trông rất mất chuyên nghiệp.

Lỗi gốc: ``ui/collapsible.py`` tạo ``QWidget()`` không cha rồi gọi
``setVisible(expanded)`` ngay, mãi mấy dòng sau mới đưa vào bố cục.

Cách tránh: truyền cha ngay lúc tạo — ``QWidget(self)`` — hoặc chỉ ẩn/hiện SAU
khi đã ``addWidget``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_THU_MUC = _ROOT / "autodub_gui"

# Widget dựng bằng dấu ngoặc rỗng nghĩa là chưa có cha.
_TAO_KHONG_CHA = re.compile(
    r"^\s*(?P<ten>(?:self\.)?[A-Za-z_][\w.]*)\s*=\s*"
    r"(?:QWidget|QFrame|QLabel|QScrollArea|QStackedWidget|QGroupBox|"
    r"QTabWidget|QToolBar|QSplitter)\(\)\s*$")

# Các cách hợp lệ để widget có cha.
_DA_CO_CHA = ("addWidget(", "insertWidget(", "addTab(", "setWidget(",
              "setParent(", "setCellWidget(", "setItemWidget(", "addItem(",
              "setTitleBarWidget(", "setCentralWidget(", "setMenuWidget(",
              "setCornerWidget(", "setViewport(", "setLayout(",
              "addPermanentWidget(", "layout.addRow(", "addRow(")

_CHO_HIEN = ("setVisible(True", ".show()", "setVisible(expanded",
             "setVisible(bool")


def _tep_nguon() -> list[Path]:
    return sorted(_THU_MUC.rglob("*.py"))


def _nhan(duong_dan: Path) -> str:
    """Tên tệp gọn để đưa vào thông báo lỗi."""
    try:
        return duong_dan.relative_to(_ROOT).as_posix()
    except ValueError:
        return duong_dan.name


def _quet(duong_dan: Path) -> list[str]:
    """Trả về mô tả các chỗ cho widget hiện lên khi chưa có cha."""
    dong = duong_dan.read_text(encoding="utf-8").splitlines()
    vi_pham: list[str] = []
    for i, line in enumerate(dong):
        khop = _TAO_KHONG_CHA.match(line)
        if not khop:
            continue
        ten = khop.group("ten")
        # Nhìn tối đa 40 dòng tiếp theo: chỉ tính vi phạm nếu widget bị cho
        # hiện TRƯỚC khi được gắn vào bố cục.
        for j in range(i + 1, min(i + 41, len(dong))):
            sau = dong[j]
            if ten not in sau:
                continue
            if any(k in sau for k in _DA_CO_CHA):
                break                      # đã có cha, an toàn
            if any(k in sau for k in _CHO_HIEN):
                vi_pham.append(
                    f"{_nhan(duong_dan)}:{j + 1}: "
                    f"«{ten}» được cho hiện khi chưa có cha "
                    f"(tạo ở dòng {i + 1}) -> {sau.strip()}")
                break
    return vi_pham


def test_khong_hien_widget_chua_co_cha() -> None:
    vi_pham: list[str] = []
    for path in _tep_nguon():
        vi_pham.extend(_quet(path))
    if vi_pham:
        pytest.fail(
            "Widget chưa có cha mà bị cho hiện sẽ nháy thành một cửa sổ "
            f"riêng trên màn hình. Có {len(vi_pham)} chỗ:\n"
            + "\n".join(vi_pham)
            + "\n\nCách sửa: truyền cha ngay lúc tạo, ví dụ QWidget(self), "
              "hoặc chỉ gọi setVisible/show SAU khi đã addWidget.")


def test_bo_quet_thuc_su_bat_duoc_loi(tmp_path) -> None:
    """Chính bộ quét phải bắt được đúng mẫu lỗi cũ, nếu không nó vô dụng."""
    mau = tmp_path / "vi_du.py"
    mau.write_text(
        "def build(self):\n"
        "    self._content = QWidget()\n"
        "    self._content.setVisible(True)\n"
        "    root.addWidget(self._content)\n",
        encoding="utf-8")
    assert _quet(mau), "bộ quét bỏ sót mẫu lỗi đã từng gây nháy cửa sổ"


def test_bo_quet_khong_bao_nham(tmp_path) -> None:
    """Gắn cha trước rồi mới ẩn/hiện là hợp lệ, không được báo lỗi."""
    mau = tmp_path / "vi_du_dung.py"
    mau.write_text(
        "def build(self):\n"
        "    self._content = QWidget()\n"
        "    root.addWidget(self._content)\n"
        "    self._content.setVisible(True)\n",
        encoding="utf-8")
    assert not _quet(mau)
