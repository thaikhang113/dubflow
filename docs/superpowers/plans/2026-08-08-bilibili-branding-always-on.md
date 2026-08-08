# Bilibili Branding Always-On Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bắt buộc mọi job Bilibili che logo gốc và chèn logo được duyệt trước hand-off.

**Architecture:** Wrapper Bilibili luôn giữ organize/Telegram của pipeline con, chạy `single_job_brand.py` trên video đã qua quality gate, rồi mới organize và gửi kết quả. Intro/outro vẫn là tùy chọn độc lập.

**Tech Stack:** Bash, Python stdlib `unittest`, ffmpeg.

## Global Constraints

- Không thêm dependency.
- Không làm hiệu ứng lật gương.
- Branding lỗi phải fail closed.
- Không đọc hoặc ghi secret.

---

### Task 1: Always-On Bilibili Branding

**Files:**
- Modify: `skills/bilibili-vietnamese-dubber/run.sh`
- Modify: `skills/bilibili-vietnamese-dubber/test_url_normalization.py`

**Interfaces:**
- Consumes: `single_job_brand.py`, `brand-assets.json`, `final_video_vi.mp4`.
- Produces: branded `final_video_vi.mp4` và `bilibili_branding_proof.json`.

- [x] Viết test static `test_wrapper_always_brands_before_final_handoff` yêu cầu không còn default `BILIBILI_BRANDING=0`, pipeline con luôn nhận `ORGANIZE_OUTPUT=0 AUTO_TELEGRAM_RESULT=0`, và branding script luôn chạy.
- [x] Chạy `python -m unittest -v test_url_normalization.py` và xác nhận test mới fail.
- [x] Xóa nhánh unbranded trong `run.sh`; luôn kiểm tra script/assets, chạy child không hand-off, brand, organize và gửi kết quả.
- [x] Giữ validation `BILIBILI_BRAND_INCLUDE_INTRO` và `BILIBILI_BRAND_INCLUDE_OUTRO` ở `0|1`.
- [x] Chạy test Bilibili và xác nhận pass.
- [x] Chạy `test_single_job_brand.py`, `bash -n`, `compileall` và `git diff --check`.
- [x] Commit và push `HEAD` lên `origin/khang`.
