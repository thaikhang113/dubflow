# Runtime Doctor And Host Login Design

## Goal

Cho người dùng cuối biết chính xác workflow nào chạy được, thiếu API key/cookie/runtime nào, đồng thời mở Chrome trên máy để đăng nhập Bilibili và tự đồng bộ cookie vào web Docker.

## Doctor

`GET /api/runtime/doctor` trả:

- `ready`: runtime lõi có chạy được hay không;
- `workflows`: `local_video`, `bilibili`, `ollama_translation`, `ai33_voice`, `telegram`, `trend`;
- mỗi workflow có `status`, `required`, `missing`, `optional`;
- provider chỉ hiện ID, loại và `configured`; không trả key/token/cookie;
- Settings tự tải Doctor khi mở và vẫn có nút chạy lại.

Workflow local yêu cầu FFmpeg, Whisper, Demucs, volume ghi được và một provider dịch. Ollama không cần API key. AI33 yêu cầu provider AI33 có key. Bilibili báo cookie và host helper là mục tùy chọn nếu runtime tải video đã sẵn sàng. Telegram và Trend không chặn pipeline video.

## Host Login

Host helper dùng Python stdlib, bind `127.0.0.1:18794`, chỉ nhận:

- `GET /status`;
- `POST /open`.

`/open` chỉ được gọi từ web local, tìm Chrome/Chromium theo allowlist, mở profile riêng trong thư mục người dùng và load extension cục bộ. Extension chỉ có quyền cookie cho `bilibili.com` và quyền gửi tới `http://127.0.0.1:18793`. Khi thấy `SESSDATA`, `DedeUserID` hoặc `bili_jct`, extension chuyển cookie thành Netscape rồi gọi API import cookie hiện có.

Không đọc profile Chrome chính, không nhận path/command từ request, không mở CDP ra mạng. QR và import `cookies.txt` vẫn giữ làm fallback.

## Platform

- Windows: `start-bilibili-helper.ps1`.
- Linux: `start-bilibili-helper.sh`.
- Không thêm dependency host ngoài Python 3 và Chrome/Chromium.

## Verification

- Unit test Doctor không lộ secret và phân loại workflow đúng.
- Unit test helper CORS, allowlist command và endpoint.
- Static UI contract cho auto Doctor và nút mở Chrome.
- Browser QA desktop/mobile.
- Full regression, Docker build/health, credential scan.
