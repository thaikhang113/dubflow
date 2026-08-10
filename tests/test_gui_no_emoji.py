"""Kiểm tra không còn biểu tượng cảm xúc trong mã nguồn giao diện.

Quét mọi tệp .py trong autodub_gui/ để bảo đảm không sót biểu tượng nào.
Không nạp Qt, chỉ đọc chữ, nên chạy được trên mọi máy.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

# Regex tuong tu _EMOJI_RE trong autodub/content/generator.py
# Chi bat pictographs, dingbats, symbols thuc su -- khong bat mui ten hay dau cau.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # pictographs, emoticons, transport, symbols
    "\U00002700-\U000027BF"   # dingbats (check, sparkles...)
    "\U00002600-\U000026FF"   # misc symbols (sun, zap...)
    "\U0001F1E6-\U0001F1FF"   # flags
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U0001F3FB-\U0001F3FF"   # skin tones
    "\U0000200D"              # ZWJ
    "\U000020E3"              # combining keycap
    "\U00002B00-\U00002BFF"   # arrows/stars (star, arrow...)
    "]"
)

# File paths to scan
_SCAN_DIRS = [
    "autodub_gui",
    "autodub/content",
    "scripts",
]

_EXCLUDE_FILES = {
    # _EMOJI_RE là biểu thức chính quy hợp lệ, không phải biểu tượng hiển thị
}


def _scan_file(filepath: str) -> list[tuple[int, str]]:
    """Return list of (line_number, offending_line) for any emoji found."""
    findings = []
    try:
        with open(filepath, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                # Skip the _EMOJI_RE pattern itself (it defines what to strip)
                stripped = line.strip()
                if stripped.startswith('"') and any(
                    k in stripped for k in (
                        "U0001F000", "U00002700", "U00002600", "U0001F1E6",
                        "U0000FE00", "U0001F3FB", "U0000200D", "U000020E3",
                        "U00002B00", "U00002190",
                    )
                ):
                    continue
                if _EMOJI_RE.search(line):
                    findings.append((i, line.rstrip()))
    except Exception:
        pass
    return findings


def test_no_emoji_in_gui() -> None:
    """Kiểm tra không còn biểu tượng cảm xúc trong bất kỳ tệp giao diện nào."""
    root = Path(__file__).parent.parent
    all_findings: list[tuple[str, int, str]] = []

    for scan_dir in _SCAN_DIRS:
        dir_path = root / scan_dir
        if not dir_path.is_dir():
            continue
        for py_file in sorted(dir_path.rglob("*.py")):
            rel = str(py_file.relative_to(root))
            if rel in _EXCLUDE_FILES:
                continue
            findings = _scan_file(str(py_file))
            for lineno, line in findings:
                all_findings.append((rel, lineno, line))

    if all_findings:
        msg_parts = ["\nEmoji found in source files:"]
        for fname, lineno, line in all_findings:
            msg_parts.append(f"  {fname}:{lineno}: {line}")
        msg_parts.append(
            f"\nTotal: {len(all_findings)} emoji instances. "
            "Use status_text.py constants instead."
        )
        pytest.fail("\n".join(msg_parts))


if __name__ == "__main__":
    # Allow running directly: python tests/test_gui_no_emoji.py
    try:
        import pytest
        test_no_emoji_in_gui()
    except ImportError:
        # Manual run without pytest
        root = Path(__file__).parent.parent
        all_findings = []
        for scan_dir in _SCAN_DIRS:
            dir_path = root / scan_dir
            if not dir_path.is_dir():
                continue
            for py_file in sorted(dir_path.rglob("*.py")):
                rel = str(py_file.relative_to(root))
                findings = _scan_file(str(py_file))
                for lineno, line in findings:
                    all_findings.append((rel, lineno, line))
        if all_findings:
            print(f"FAIL: {len(all_findings)} emoji instances found:")
            for fname, lineno, line in all_findings:
                print(f"  {fname}:{lineno}: {line}")
            exit(1)
        else:
            print("OK: No emoji found in source files.")
