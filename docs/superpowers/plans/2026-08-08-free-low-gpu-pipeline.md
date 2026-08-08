# Free Low-GPU Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm đường chạy miễn phí cho GPU yếu và sửa các blocker runtime đã xác nhận.

**Architecture:** Tái sử dụng Whisper.cpp, Ollama, Edge TTS, PaddleOCR và CV đã có. Profile chỉ cấp default; dependency và secret được kiểm tra theo provider thực sự chọn.

**Tech Stack:** Bash, Python stdlib, unittest, ffmpeg, whisper.cpp, Ollama, edge-tts.

## Global Constraints

- Không thêm dependency.
- Không sao chép code GPL.
- Không đọc, log hoặc commit secret.
- Cấu hình explicit luôn thắng profile.

---

### Task 1: Free Low-GPU Profile

**Files:**
- Modify: `skills/douyin-vietnamese-dubber/run.sh`
- Create: `skills/douyin-vietnamese-dubber/test_runtime_profile.py`

- [x] Viết test static yêu cầu profile đặt Ollama, Edge TTS, OCR local, CV, BGM none, một worker.
- [x] Chạy test và xác nhận fail.
- [x] Thêm default profile tối thiểu vào đầu `run.sh`.
- [x] Chạy test và xác nhận pass.

### Task 2: Conditional Dependencies

**Files:**
- Modify: `skills/douyin-vietnamese-dubber/run.sh`
- Modify: `skills/douyin-vietnamese-dubber/test_runtime_profile.py`

- [x] Viết test yêu cầu AI33/Resona/OCR/rewrite key không bị bắt buộc vô điều kiện.
- [x] Chạy test và xác nhận fail.
- [x] Dùng parameter expansion không-fatal; validate key ngay trước provider cần nó.
- [x] Chọn API key bằng `get_api_key`; Ollama dùng chuỗi rỗng.
- [x] Chạy test và toàn bộ test dubber.

### Task 3: AI33 Circuit Breaker

**Files:**
- Modify: `skills/douyin-vietnamese-dubber/ai33_tts_synthesize.py`
- Modify: `skills/douyin-vietnamese-dubber/test_ai33_tts_synthesize.py`

- [x] Đổi test 429 từ `SystemExit` sang `AI33Error`.
- [x] Chạy test và xác nhận fail.
- [x] Trả lỗi phân loại thay vì `sys.exit()` trong HTTP helper.
- [x] Chạy test và xác nhận pass.

### Task 4: Durable Series State

**Files:**
- Modify: `skills/series-tracker/series-tracker.py`
- Modify: `skills/series-tracker/test_series_tracker_state.py`

- [x] Viết test state JSON hỏng phải raise và giữ nguyên file.
- [x] Chạy test và xác nhận fail.
- [x] Fail closed trong `load_state`.
- [x] Chạy test và xác nhận pass.

### Task 5: Reliable Content Monitor

**Files:**
- Modify: `skills/content-monitor/content-monitor.py`
- Create: `skills/content-monitor/test_content_monitor.py`

- [x] Viết test gửi Telegram fail không mark seen.
- [x] Viết test save JSON atomic.
- [x] Chạy test và xác nhận fail.
- [x] Sửa flow và ghi JSON bằng temp + replace.
- [x] Chạy test và xác nhận pass.

### Task 6: Douyin Timeout

**Files:**
- Modify: `skills/douyin-stealth/scripts/fetch_douyin_v2.py`
- Create: `skills/douyin-stealth/scripts/test_progress_timeout.py`

- [x] Viết static regression test timeout chỉ kích hoạt sau 240 giây.
- [x] Chạy test và xác nhận fail.
- [x] Xóa nhánh 180 giây sai.
- [x] Chạy test và xác nhận pass.

### Task 7: Documentation and Verification

**Files:**
- Modify: `README.md`

- [x] Ghi lệnh doctor và chạy profile GPU yếu.
- [x] Chạy `bash -n` cho shell scripts.
- [x] Chạy `python -m compileall -q skills`.
- [x] Chạy toàn bộ unittest liên quan.
- [x] Kiểm tra `git diff --check`, secret patterns và `git status`.
