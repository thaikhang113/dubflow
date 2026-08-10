"""Trạng thái hiển thị dạng chữ — không dùng biểu tượng cảm xúc.

Các hằng số này thay cho những biểu tượng cảm xúc trạng thái (dấu tích,
cảnh báo, lỗi, phát...) từng nằm rải rác trong toàn bộ giao diện.
"""
from __future__ import annotations

# Trạng thái (thay cho biểu tượng dấu tích, cảnh báo và lỗi)
STATUS_OK = "[OK]"
STATUS_WARN = "[!]"
STATUS_ERROR = "[X]"

# Nhãn cho nút phát và nút dừng
LABEL_PLAY = "Phát"
LABEL_STOP = "Dừng"
