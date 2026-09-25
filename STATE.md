# DubFlow Project State

## Mission
Build and maintain DubFlow: local Vietnamese video dubbing desktop app.

## Current Architecture
- `autodub/`: core pipeline, media, speech, TTS, translation, editor, batch.
- `autodub_gui/`: PySide6 desktop UI and background workers.
- `tests/`: unit and regression coverage.
- GitNexus: code graph, impact analysis, execution flows.
- TencentDB Agent Memory: long-term project memory through local Memory Proxy.

## Working Rules
- Run GitNexus `impact` before editing any function, class, or method.
- Run focused tests before broad tests.
- Run `detect_changes()` before committing.
- Keep TencentDB credentials outside repository files.
- Keep DubFlow runtime independent from TencentDB and Loop Engineer.

## Active Priorities
- Preserve resumable pipeline artifacts and legacy work-directory compatibility.
- Keep GUI responsive by moving heavy work to workers.
- Keep CPU fallback working when optional GPU/model runtimes are absent.
- Record architecture decisions, regressions, and release notes in TencentDB memory.

## Verification Baseline
- `python -m pytest -q`
- `python -m ruff check .` (cấu hình trong `pyproject.toml`)
- `python -m compileall -q autodub autodub_gui scripts`
- `tests/test_no_mojibake.py` chặn tiếng Việt bị encode hai lượt quay lại
- `qa/gui_walkthrough.py` và `qa/commit_safety_check.py` trước mỗi commit

## Latest Verification
- 2026-09-24: Nâng cấp phiên bản v3.0.25 (Sửa lỗi và tăng tốc tải video Bilibili / Douyin).
  + Tự động nạp cookies Netscape Bilibili (`default_bilibili_cookies_file`) tránh bị CDN bóp băng thông 90KB/s hoặc từ chối kết nối.
  + Bổ sung cookies, douyin_cookies và fragment_workers vào `PrefetchWorker` ở Bước 1 GUI.
  + Tự động cấu hình `ffmpeg_location` trong `yt-dlp` (`build_ydl_opts` và `download_video`), ngăn lỗi thiếu ffmpeg khi ghép luồng video/audio.
  + Tối ưu hóa chuỗi định dạng tải `bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]...` ngăn tải luồng 4K khổng lồ làm treo và chậm tiến trình.
  + 986/986 tests passed, linter sạch 100%.
- 2026-09-24: Kiểm tra toàn diện thực tế mọi chức năng (Real-World E2E & Component Validation).
  + Toàn bộ 986 unit/integration tests qua 100% trong 65s.
  + Bộ rà soát GUI Walkthrough: 13/13 trang dựng và điều hướng hoàn hảo, 0 lỗi.
  + Bộ rà soát tính năng Features Review: Quét 33 dự án thật, Báo cáo chất lượng nạp 8 dự án, vòng đọc/ghi Cài đặt, 174 giọng đọc VieNeu, OpenClaw API (port 50762, auth tokens, /v1/prepare), 17 mục Doctor.
  + Bộ rà soát Trình chỉnh sửa Editor Review: Sửa câu, tách phụ đề khỏi lời đọc, VieNeu đọc lại từng câu, dựng lại video và xuất video gắn phụ đề thành công (0 phát hiện).
  + Bộ rà soát Dừng khẩn cấp Cancel Review: Dừng ngay sau 0.0s - 0.1s, 0 tiến trình FFmpeg bị treo hoặc mồ côi.
  + Bộ rà soát Xử lý hàng loạt Batch Flows Review: Dừng giữa chừng, chế độ chạy lại video đã xong (retry_done=True), và tạm dừng chờ bản dịch tay rồi tiếp tục đều hoạt động chuẩn xác (0 phát hiện).
  + Bộ rà soát Đầu-Cuối E2E Review (S1-S7): 7/7 kịch bản chạy video thật và tải YouTube thật, hoàn tất không lỗi (findings_e2e = 0).
  + Kiểm thử tải video thực tế: Tải URL YouTube thật, nhận 19 sự kiện tiến độ, định dạng chi tiết [download] ...% of ~... at ... ETA ..., cập nhật ghi đè tại chỗ trên LogPanel và thanh tiến trình.
  + Đo lường hiệu năng thực tế: Lượt chạy sạch hoàn tất trong 33.4s (`timing_single.py`), lượt tái sử dụng hoàn tất trong 15.6s (`timing_review.py`).
  + Kiểm tra chống lỗi âm thầm (`probe_guard_check.py`): Test guard phát hiện lỗi tiêm probe chuẩn xác và khôi phục 100%.
  + Smoke Test chính thức (`AUTODUB_SMOKE=1`): 17/17 tiêu chí hệ thống đạt `ok: true`.
- 2026-09-23: Nâng cấp phiên bản v3.0.24.
  + Hiển thị tiến độ tải video thời gian thực chuẩn xác: `[download] 35.4% of ~2.80GiB at 14.5MiB/s ETA 02:08`.
  + Tích hợp StepTracker, LogPanel (ghi đè tại chỗ) và DownloadPage.
  + 100% tests passed, 13/13 trang GUI walkthrough sạch sẽ.
- 2026-09-23: Nâng cấp phiên bản v3.0.23.
  + Tự động quét và nạp thư mục binary FFmpeg/FFprobe (`candidate_bin_dirs` & `ensure_bin_in_path`) trong `autodub/utils.py`.
  + Phân lập phạm vi hủy tiến trình con (Scope-Aware Process Cancellation) qua `cancel_scope` và `contextvars` trong `autodub/cancel.py`.
  + Full test suite: 984 passed, 0 failures; `ruff check` sạch 100%.
- 2026-09-13: `autodub/batch.py` + `.env.example` + một toast ở trang Dự án
  được sửa lỗi mã hóa hai lượt (UTF-8 -> CP1252 -> UTF-8) bằng ftfy, có rào
  chắn giữ nguyên bộ dấu câu toàn góc trong `batch.py`. Lưới chặn hồi quy:
  `tests/test_no_mojibake.py`.
- 2026-09-13: full suite `946 passed`; `ruff check .` sạch; `compileall` sạch.
- 2026-09-13: GitNexus index dựng lại tại `945d68b` (534 tệp, 623 luồng). MCP
  server vẫn giữ bản LadybugDB cũ nên resource `clusters` báo lỗi version, và
  FTS thiếu thư viện runtime - dùng CLI `.gitnexus/run.cjs` cho impact/detect.
- 2026-09-13: điểm còn dở của `qa/REVIEW.md` mục A đã xong -
  `select_backends()` đọc `VSR_ENABLED`, kế hoạch phần cứng viết lại khi bật/tắt.
- 2026-09-13: dọn hết lời hứa "Vox/tín dụng/mã hóa dữ liệu" còn sót từ máy chủ
  VoxDub trong nhãn GUI, `TRANSLATE_PENDING.txt`, chú thích lõi và bảng lỗi;
  trạng thái dự án "Lỗi" giờ đọc từ `pipeline_state.json` thay vì tệp ma.
- 2026-08-25: full suite `832 passed`.
- 2026-08-25: `python -m compileall -q autodub autodub_gui scripts` passed.
- 2026-08-25: `git diff --check` passed; only line-ending warnings remain.
- 2026-08-25: Windows bundle built with PyInstaller; smoke report `ok: true`.
- 2026-08-25: release ZIP `dist/DubFlow-v3.0.12-windows-x64.zip` contains 1410 entries,
  executable, license, and ASR worker; no `.env` or smoke/runtime artifacts.
- 2026-08-25: TencentDB Memory Proxy health returned HTTP 200.
- 2026-08-25: GitNexus `detect_changes(scope="all")` returned HIGH risk because
  current uncommitted changes touch `DubPipeline` and `EditorPage`; review required
  before commit.
- 2026-08-25: GitNexus FTS repair was unavailable because LadybugDB FTS extension
  is not installed on this machine; index remains usable for symbol impact/context.
- 2026-08-25: focused batch/timeline/checkpoint tests `44 passed`.
- 2026-08-25: CI and release workflows now run Linux and Windows smoke tests
  before packaging; Windows smoke uses `QT_QPA_PLATFORM=offscreen`.
- 2026-08-25: isolated Windows bundle smoke with empty `DUBFLOW_DATA_DIR`
  returned `ok: true`; runtime config/logs stayed outside `dist/DubFlow`.
- 2026-08-25: 5-hour duration invariant verified:
  FFmpeg timeout `72000s`, ASR timeout `216000s`.
- 2026-08-25: Linux bundle built in Docker Python 3.11/bookworm with smoke
  passing; tar artifact: `dist/DubFlow-v3.0.12-linux-x86_64.tar.gz`.
- 2026-08-25: Debian package validated in Docker:
  package `dubflow`, version `3.0.12`, architecture `amd64`, executable and
  desktop entry present.
- 2026-08-25: Windows bundle directory rebuilt after Linux build and direct
  smoke returned `ok: true`; Linux build did not leave its layout in
  `dist/DubFlow`.
- 2026-08-25: release workflow now runs Python 3.11/3.12 tests before either
  platform build; both build jobs depend on the test matrix.
- 2026-08-25: Debian bundle validation now requires `setup_vsr.py` and
  `autodub/media/vsr_worker.py`; installer tests `26 passed`.
- 2026-08-25: fresh Linux bundle rebuilt in Docker with smoke passing and
  Debian package rebuilt after VSR validation.
- 2026-08-25: full suite rerun `832 passed`; compileall passed.
- 2026-08-25: current artifact hashes:
  Linux tar `F23CC8238E50850471F05437EF405CDCCAE65634430AE0DE7739BB59D9038F14`;
  Debian `0B9D80492E6BB3E5DFB935159699B7E0F1670A814B271F4C506E5E73E8B9F7CC`;
  Windows ZIP `E66AD4B351C6FB8F2551D42371F59D7786607B48A7E70343EC3DBF44F267EAEB`.
- 2026-08-25: clean Debian container installed `dubflow_3.0.12_amd64.deb`
  and ran `/opt/dubflow/DubFlow` smoke with `ok: true`.
- 2026-08-25: CI and release workflows now smoke-test installed Debian
  packages and installed Windows Inno Setup apps, not only build directories.
- 2026-08-25: Real local E2E passed with Whisper + VieNeu on a generated
  4.7-second video: first run returned `translate_pending`, resume reused ASR
  artifacts and completed TTS, soft subtitles, and video merge.
- 2026-08-25: Real E2E final artifact passed ffprobe validation:
  `dubbed_video.mp4` contains H.264 video, AAC audio, and mov_text subtitles;
  duration `5.44s`, size `60341` bytes.
- 2026-08-25: Full regression suite rerun with project venv: `833 passed in
  28.29s`; compileall passed; installer tests `27 passed`; CI/release YAML
  parsing passed.
- 2026-08-25: Release artifact hashes rechecked:
  Linux tar `F23CC8238E50850471F05437EF405CDCCAE65634430AE0DE7739BB59D9038F14`;
  Debian `0B9D80492E6BB3E5DFB935159699B7E0F1670A814B271F4C506E5E73E8B9F7CC`;
  Windows ZIP `E66AD4B351C6FB8F2551D42371F59D7786607B48A7E70343EC3DBF44F267EAEB`.
- 2026-08-26: User-like audit found and fixed two workflow bugs:
  batch auto-continuation now keeps completed items in `batch_state.json`;
  OpenClaw uses an ephemeral fallback port when configured port is occupied.
  Full suite after fixes: `852 passed`; compileall passed.
- 2026-08-26: MainWindow constructed and switched through all 14 registered
  pages without exception. Real local batch artifacts passed ffprobe checks.
  Real machine has NVIDIA CUDA; AMD ROCm/DirectML paths verified by simulated
  hardware plans only because this machine has no AMD GPU.

## Session Protocol
1. Read this file and relevant TencentDB memory.
2. Read GitNexus context before changing unfamiliar code.
3. Analyze impact before editing symbols.
4. Implement smallest change.
5. Run focused tests, then regression checks.
6. Store durable decision or bug knowledge in TencentDB.
