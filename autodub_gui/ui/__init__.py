"""Hệ thành phần giao diện dùng chung cho toàn bộ ứng dụng.

Mọi thành phần trong thư mục này đều tuân thủ ba điều:
  - lấy màu và khoảng cách từ `autodub_gui.tokens`, không viết cứng mã màu;
  - có đủ các trạng thái cần thiết (mặc định, di chuột qua, đang chọn,
    đang nhập, bị khóa, đang tải, lỗi, trống);
  - không đặt chiều rộng cố định cho phần chứa chữ, tránh cắt mất chữ.
"""
from __future__ import annotations
