# Changelog

## 3.0.14 - 2026-08-26

### Fixed

- Make OpenClaw endpoint test independent of whether the default port is
  available on the CI runner.

## 3.0.13 - 2026-08-26

### Added

- Linux AMD ROCm detection for Whisper, Demucs, and DeepSeek-OCR.
- Linux AMD VAAPI video encoding with automatic CPU fallback.

### Fixed

- Batch processing now preserves completed items during automatic continuation.
- Long-video audio processing uses duration-scaled timeouts.
- GPU workers report their actual CUDA, ROCm, or CPU backend.

## 3.0.12 - 2026-08-15

### Fixed

- Hủy tải trước video dừng downloader thật, xóa file tạm và không phát kết quả
  cho URL cũ.
- Nút `Tiếp tục` giữ trạng thái `Đang tải…` trong lúc prefetch đang chạy.
- Chuẩn hóa fallback version giữa package, GUI, Linux build và Windows installer.

## 3.0.9 - 2026-08-15

### Fixed

- OCR bỏ qua text dọc hoặc box quá cao để không làm mờ toàn màn hình.
- VieNeu giới hạn thread OpenBLAS/ONNX, giảm lỗi thiếu bộ nhớ cuối job.
- Tự chuyển job nhiều voice/voice clone sang xử lý tuần tự, mỗi voice một
  worker, tránh nhân worker theo số voice.

### Changed

- Installer all-in-one cài thêm VSR worker.

## 3.0.7 - 2026-08-14

### Added

- Dynamic OpenClaw connection prompt with endpoint, token and workflow instructions.
- In-app `/health` connection test for the OpenClaw bridge.

## 3.0.6 - 2026-08-14

### Added

- OpenClaw integration managed entirely by DubFlow.
- Local HTTP bridge, token authentication, background queue worker and batch monitor.

### Changed

- OpenClaw setup no longer requires running Python commands or source files.

## 3.0.5 - 2026-08-14

### Added

- In-app installation controls for optional ASR, OCR, TTS, and voice features.
- Douyin cookie import, hybrid OCR support, and OpenClaw tool integration.

### Fixed

- Improved batch download and processing queue behavior.
- Fixed OCR and subtitle masking workflow compatibility.

## 3.0.4 - 2026-08-14

### Fixed

- OCR subtitle masking refreshes when the editor region changes and keeps
  original-logo detection separate from the subtitle region.
- Windows and Linux bundles include external ASR, TTS, OCR, and separator
  workers in current PyInstaller layouts.
- Linux uses system `ffmpeg`/`ffprobe` and declares `ffmpeg` as a Debian
  package dependency instead of downloading a static copy.
- Improve Vietnamese font loading, help text, download layout, and DubFlow
  branding in the app UI.

### Added

- In-app OCR subtitle masking defaults to the lower 30-35% of the frame.
- Release validation checks worker files, setup scripts, version, and secrets
  before packaging.

## 3.0.3 - 2026-08-14

### Fixed

- Bundle Whisper worker in Windows and Linux releases.
- Fail builds when a required external worker is missing.
- Stabilize settings default tests when `.env` has already been loaded.

### Added

- Manual `Kiểm tra cập nhật` button in the app header.
- In-app release download, SHA256 verification, and installer handoff.
## 3.0.8

- Thêm VSR làm engine chính để xóa phụ đề cứng sau khi OCR tìm vùng chữ.
- Tự quay về làm mờ nếu VSR chưa cài hoặc xử lý lỗi.
- Thêm setup, Doctor, cấu hình mode và worker VSR vào bundle Windows/Linux.
