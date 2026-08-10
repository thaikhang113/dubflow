"""Chặn tiếng Việt không dấu trong toàn bộ mã nguồn.

Chủ dự án yêu cầu: hễ xuất hiện tiếng Việt thì phải có dấu đầy đủ — chuỗi
hiển thị, comment và docstring đều vậy. Bài kiểm thử này quét từng dòng, tìm
các cụm từ tiếng Việt viết không dấu nằm trong danh sách đen.

Cách nhận biết: một dòng bị coi là vi phạm khi chứa ít nhất một cụm trong
`_BLACKLIST` mà cụm đó không phải là mã định danh trong code (tên hàm, tên
biến, khóa cấu hình). Vì vậy danh sách đen chỉ gồm những cụm nhiều chữ, đặc
trưng cho tiếng Việt viết tay, không trùng với từ tiếng Anh.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent

_SCAN_DIRS = ("autodub_gui", "autodub", "scripts", "tests")

# Những cụm tiếng Việt không dấu hay gặp nhất. Mỗi cụm gồm từ hai chữ trở lên
# để không đụng nhầm vào từ tiếng Anh hoặc tên hàm.
_BLACKLIST = (
    "bat dau", "tuy chon", "cai dat", "long tieng", "nghe thu", "chinh sua",
    "xuat video", "tai xuong", "phu de", "giong doc", "nhac nen", "tong quan",
    "thu muc", "video goc", "danh sach", "nguoi dung", "du an", "cau hinh",
    "thong bao", "trang thai", "hoan thanh", "dang xu ly", "khong the",
    "vui long", "mac dinh", "hien thi", "kiem tra", "thoi gian", "ket qua",
    "tep tin", "duong dan", "khoi tao", "thanh cong", "that bai", "tien trinh",
    "cua so", "man hinh", "gia tri", "so luong", "ban dich", "cau thoai",
    "tach nhac", "am thanh", "dinh dang", "chat luong", "toc do", "kich thuoc",
)

_BLACKLIST_RE = re.compile(
    r"(?<![0-9a-zA-Z_])(" + "|".join(_BLACKLIST) + r")(?![0-9a-zA-Z_])",
    re.IGNORECASE)

# Tệp được miễn trừ kèm lý do rõ ràng.
_EXEMPT: dict[str, str] = {
    # Chính bài kiểm thử này chứa danh sách đen nên đương nhiên khớp.
    "tests/test_vi_diacritics.py": "chứa danh sách đen dùng để đối chiếu",
    # Tệp này sinh ra các tệp .bat cài đặt cho Windows. Chữ mà .bat in ra cửa
    # sổ dòng lệnh phải giữ không dấu, vì cmd.exe dùng bảng mã cũ nên chữ có
    # dấu sẽ hiện thành ký tự rác. Chủ dự án đã chốt giữ nguyên phần này.
    "scripts/build_exe.py": "sinh tệp .bat cho cmd.exe, chữ console phải là ASCII",
}

# Tên ba tệp cài đặt đóng gói kèm ứng dụng. Đây là tên tệp có thật trên đĩa,
# đóng vai trò như mã định danh: đổi tên sẽ làm hỏng bản cài của người dùng
# hiện tại. Chủ dự án đã chốt giữ nguyên, nên mọi dòng nhắc tới chúng được
# bỏ qua khi quét.
_INSTALLER_FILES = (
    "Cai dat giong VieNeu",
    "Cai dat ASR tieng",        # tên bị ngắt dòng ở vài chỗ nên khớp phần đầu
    "Cai dat tinh nang Douyin",
)


def _is_installer_reference(line: str) -> bool:
    """Dòng này có đang nhắc tới tên một tệp .bat cài đặt không."""
    return any(name in line for name in _INSTALLER_FILES)


def _scan(path: Path) -> list[tuple[int, str]]:
    """Trả về danh sách (số dòng, nội dung) của những dòng vi phạm."""
    findings: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings
    for lineno, line in enumerate(text.splitlines(), 1):
        if _is_installer_reference(line):
            continue
        if _BLACKLIST_RE.search(line):
            findings.append((lineno, line.strip()))
    return findings


def _all_sources() -> list[Path]:
    files: list[Path] = []
    for name in _SCAN_DIRS:
        directory = _ROOT / name
        if not directory.is_dir():
            continue
        files.extend(p for p in directory.rglob("*.py")
                     if "__pycache__" not in p.parts)
    return sorted(files)


def test_no_unaccented_vietnamese() -> None:
    """Không dòng nào được chứa tiếng Việt viết thiếu dấu."""
    offenders: list[str] = []
    for path in _all_sources():
        rel = path.relative_to(_ROOT).as_posix()
        if rel in _EXEMPT:
            continue
        for lineno, line in _scan(path):
            offenders.append(f"{rel}:{lineno}: {line}")
    if offenders:
        pytest.fail(
            "Tiếng Việt phải có dấu đầy đủ, kể cả trong comment và docstring. "
            f"Có {len(offenders)} dòng vi phạm:\n" + "\n".join(offenders[:60]))


def test_exemption_list_stays_accurate() -> None:
    """Mọi tệp được miễn trừ phải còn tồn tại và phải kèm lý do."""
    for rel, reason in _EXEMPT.items():
        assert (_ROOT / rel).is_file(), f"Tệp miễn trừ không còn: {rel}"
        assert reason.strip(), f"Thiếu lý do miễn trừ cho {rel}"


def test_display_strings_are_accented() -> None:
    """Chuỗi hiển thị trong giao diện không được viết tiếng Việt thiếu dấu."""
    call_re = re.compile(
        r"(?:setText|setPlaceholderText|setToolTip|addItem|setWindowTitle|"
        r"QLabel|QPushButton|QCheckBox|showMessage)\s*\(\s*[\"']([^\"']{4,})")
    offenders: list[str] = []
    gui = _ROOT / "autodub_gui"
    for path in sorted(gui.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if _is_installer_reference(line):
                continue
            match = call_re.search(line)
            if match and _BLACKLIST_RE.search(match.group(1)):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    if offenders:
        pytest.fail("Chuỗi hiển thị thiếu dấu tiếng Việt:\n" +
                    "\n".join(offenders))
