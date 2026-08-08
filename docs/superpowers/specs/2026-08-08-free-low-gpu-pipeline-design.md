# Free Low-GPU Pipeline Design

## Goal

Cho phép pipeline video chạy trên máy GPU yếu mà không cần AI33, Resona hoặc
9Router API key, dùng các backend đã có trong repo.

## Runtime Profile

`OPENCLAW_RUNTIME_PROFILE=free_low_gpu` đặt default sau khi người dùng chưa
override:

- Dịch bằng Ollama local.
- TTS bằng `vi-VN-HoaiMyNeural` qua Edge TTS.
- Whisper.cpp model `small` chạy CPU.
- OCR transcript dùng PaddleOCR; subtitle band dùng CV.
- `BGM_MODE=none` để không bắt buộc Demucs trên máy yếu.
- `SPEECH_ONLY_PREPROCESS=0` để không chạy Demucs ngầm trước Whisper.
- Một TTS worker; tắt TTS voice QA để tránh chạy Whisper lần hai.

Profile không thay đổi cấu hình explicit. AI33, Resona, 9Router, Demucs và
Kokoro vẫn dùng được khi user chọn.

## Dependency Rules

- AI33 key chỉ bắt buộc khi voice là `ai33:*`.
- Resona token chỉ bắt buộc khi voice là `resona:*`.
- `edge-tts` chỉ bắt buộc cho Edge voice.
- Ollama không cần API key.
- OCR local và CV không cần vision API key.
- TTS rewrite thiếu API key thì bỏ rewrite, đúng contract hiện có.

## Reliability Fixes

- AI33 HTTP lỗi phải trả `AI33Error`, đi qua circuit breaker và checkpoint.
- Series state JSON hỏng phải fail closed, không coi là state rỗng.
- Content monitor chỉ mark seen sau khi Telegram gửi thành công; JSON ghi atomic.
- Douyin stealth timeout chỉ kích hoạt ở 240 giây.

## Testing

- Static shell contract test cho profile và dependency selection.
- Unit test AI33 429 đi qua breaker.
- Unit test series state hỏng không bị ghi đè.
- Unit test content monitor không mark seen khi gửi thất bại.
- Syntax, compileall và toàn bộ test hiện có.

## Constraints

- Không thêm dependency.
- Không sao chép code GPL từ pyVideoTrans.
- Không đọc hoặc ghi secret.
- Không tuyên bố E2E thật nếu thiếu Linux runtime, Ollama, Edge TTS và media fixture.
