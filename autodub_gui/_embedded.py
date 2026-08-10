"""Giá trị nhúng cứng vào bản đóng gói (exe).

File này trong repo LUÔN rỗng. Khi build exe, ``scripts/build_exe.py`` sinh
lại nó với VOXDUB_API_URL đọc từ .env của máy build, rồi khôi phục về rỗng
sau khi build xong — địa chỉ máy chủ nằm TRONG exe, không lộ ra .env của
người dùng và người dùng không chỉnh được.
"""

# Rỗng = không nhúng; saas_client rơi về địa chỉ cố định trong mã, rồi tới
# biến môi trường VOXDUB_API_URL (chỉ khi chạy từ mã nguồn).
VOXDUB_API_URL = ''
