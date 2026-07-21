## Host runner an toàn cho OpenClaw

Script host:

`/home/haonguyen/.local/bin/openclaw-host-douyin-runner.sh`

Mục tiêu:
- cho OpenClaw trong Docker gọi pipeline Douyin trên host
- chỉ cho phép tác vụ Douyin theo whitelist
- không cung cấp lệnh xóa file
- chỉ ghi kết quả vào `/mnt/hdd500/video douyin vietsub`

Các action được phép:
- `run-douyin <URL>`
- `run-douyin <URL> nam`
- `run-douyin <URL> nu`
- `latest-output`
- `latest-source`
- `send-latest-telegram`
- `doctor`

Preset giọng:
- `nam` dùng `vi-VN-NamMinhNeural`
- `nu` dùng `vi-VN-HoaiMyNeural`
- không truyền preset thì mặc định là `nu`

Không dùng script này cho:
- xóa file
- di chuyển dữ liệu nhạy cảm
- sửa database 9Router
- đụng Chrome profile ngoài nhu cầu đọc cookie/runtime gián tiếp của pipeline

File nhạy cảm cần tránh:
- `/home/haonguyen/.9router/db.json`
- `/home/haonguyen/.openclaw/openclaw.json`
- `/home/haonguyen/.config/google-chrome`
- `/home/haonguyen/.chrome-douyin-cdp`
- mọi Docker volume và file cấu hình ngoài phạm vi skill nếu không có yêu cầu rõ
