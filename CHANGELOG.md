# Changelog

## 3.0.21 - 2026-09-08

### Fixed

- **Whisper GPU trên Windows không còn âm thầm rơi về CPU.** `ctranslate2` 4.x
  cần `cublas64_12.dll`, nhưng bộ nạp DLL chỉ tìm đại tệp `cublas64_*.dll` đầu
  tiên và có thể nạp bản CUDA 11 của venv khác: DLL nạp "thành công" mà GPU vẫn
  chết giữa chừng. Nay tìm trong `.venv-whisper` trước rồi mới tới venv GPU, và
  `setup_whisper.py` cài kèm `nvidia-cublas-cu12` để bản cài mới tự đủ tệp cần
  thiết.
- **Nút Dừng thật sự dừng được.** Mọi lời gọi ffmpeg và worker AI đều đã ghi
  danh với bộ hủy, trước đây chỉ riêng bước ghép video được ghi danh nên bấm
  Dừng vẫn phải chờ cả queue ffmpeg chạy xong. Đo lại: dừng giữa bước ghép âm
  thanh giảm từ 7.1 giây còn 0.1 giây, và không còn tệp ffmpeg nào sống sau khi
  dừng.
- `run_registered` truyền thẳng tham số `check` cho `Popen`, khiến mọi lời gọi
  có `check=False` vỡ với `TypeError`. Giờ `check` được bóc ra và xử lý đúng
  ngữ nghĩa `subprocess.run`.
- **Dự án đã xuất video không còn mở lại được bằng Trình chỉnh sửa khi bật tự
  dọn tệp trung gian.** Trước đây bước dọn xóa nguyên thư mục `data/`, mất luôn
  `transcript_vi.json` nên Editor báo "Run the dub first" và mất cache ASR/OCR.
  Nay dọn theo loại tệp: chỉ xóa media nặng, giữ metadata nhỏ. Vẫn giải phóng
  ~2.7 MB trên ~2.9 MB có thể dọn.
- Tự dọn tệp còn lấy mất `segments/.render_mode`, làm lần đọc lại kế tiếp bị
  Trình chỉnh sửa chặn xuất video với cáo buộc dùng "cơ chế gộp câu đời cũ",
  và chạy lại cũng không gỡ được. Marker giờ sống sót qua bước dọn.
- **Xử lý hàng loạt không còn đếm trùng một video.** Video vừa được tính
  success vừa bị tính failed khi việc ghi trạng thái lỗi; và bước kiểm chứng
  đòi cả tệp âm thanh trung gian — thứ mà tự dọn tệp có quyền xóa — ở chế độ có
  video.
- Bước tạo giọng đọc không bao giờ báo hiệu bắt đầu, nên ô "Đang tạo giọng đọc"
  không bao giờ sáng dù nó chiếm 30/100 thanh tiến trình. Mỗi bước giờ phải phát
  `start` kèm sự kiện kết thúc, có test giữ ràng buộc này.
- `video-subtitle-remover` được tải đúng theo bản phát hành 1.1.1 có khóa kiểm
  định, thay vì một commit dev không đánh dấu.
- Trình cài đặt DeepSeek-OCR không còn bị coi là thiếu gói dependency: traceback
  cũ đến từ bản cài đặt trước, không phải mã hiện tại; marker cài đặt giờ ghi rõ
  phiên bản thật đã tải.
- **Báo cáo tự kiểm (smoke) không còn luôn báo đạt.** Khi sửa cảnh báo "import
  không dùng", ba khối `try:` đã bị rỗng ruột thành `try: pass`, nên `except`
  không bao giờ chạy và `playwright_importable`, `multimedia_importable`,
  `new_modules_importable` in ra `True` dù bản đóng gói thiếu thư viện. Đây đúng
  là bộ kiểm CI dùng để chặn sản phẩm lỗi, nên nó không được phép luôn luôn đạt.
  Cùng lỗi này cũng làm `_check_multimedia()` trong trang Trợ giúp mất khả năng
  phát hiện trình phát video hỏng. Đã khôi phục cả bốn phép thử và thêm test giữ
  cho khối `try/except` không bị rỗng trở lại.
- Trang Trợ giúp không còn báo Python ngoài dải 3.10–3.12 là lỗi chặn, vì ràng
  buộc đó chỉ thuộc video-subtitle-remover và DeepSeek-OCR — hai engine cài vào
  venv riêng. App chạy bình thường trên Python 3.13.
- Bước cài đặt không còn bắt người dùng tải video-subtitle-remover (~700 MB) để
  được mở ứng dụng. Đây là tính năng tăng cường: thiếu nó thì pipeline tự rơi về
  che mờ.

### Performance

- Bỏ ~4.8 giây chết mỗi lượt xuất video trên máy không cài Ollama: việc giải mã
  ba khung hình để tìm logo nguồn giờ được chặn bằng một kiểm tra nhanh xem
  Ollama có đang chạy không.
- Nạp model giọng đọc sớm, phủ lên lúc đang nghe-chép. VieNeu chạy CPU nên không
  tranh card đồ họa với Whisper; trước đây nó chỉ bắt đầu **sau** khi nghe xong.
- Worker VieNeu thứ hai không còn chờ worker thứ nhất nạp xong mới nạp theo
  (khóa chỉ chặn khi RAM trống không đủ cho cả nhóm), và một worker lỗi giữa
  chừng không làm chậm đường tới câu đọc đầu tiên.
- Đo trên video 5 giây có lời thật: 45.1 giây còn 32.8 giây cho một lượt hoàn
  chỉnh không tái sử dụng.

### Added

- Pipeline ghi nhãn thời gian cho mọi bước, không chỉ hai bước tải và OCR, để
  log chỉ ra được chỗ chậm thay vì im lặng đúng chỗ lâu nhất.
- 17 test hồi quy cho hai chỗ trước đây không có lớp bảo vệ nào: bộ tải trước
  video kế tiếp trong hàng đợi (`_Prefetcher`, chưa từng có test) và nhánh xử lý
  hàng loạt của giao diện (`BatchWorker`, lớp người dùng thật bấm, cũng chưa từng
  có test).

### Verified

- Chuỗi đầy đủ với pipeline thật: video 5 giây, 10 phút và 30 phút có lời thật;
  hai video một lượt trong đó một video tải từ YouTube; dịch tay; dừng giữa
  chừng; chạy lại bỏ qua video đã xong; `retry_done`; mở lại dự án bằng Trình
  chỉnh sửa và xuất lại.
- 923 test pass.

## 3.0.20 - 2026-09-01

### Fixed

- Resolve all default Ruff checks without changing startup or setup behavior.

## 3.0.19 - 2026-09-01

### Fixed

- CapCut protocol MD5 checks are explicitly marked non-security hashes.

## 3.0.18 - 2026-09-01

### Fixed

- Manual translation hints now include saved video context.
- Remote worker cancel watchers stop after each job.
- OpenClaw binds to loopback by default and rolls back incomplete batches.
- Release workflows validate versions without shell interpolation and pin
  third-party actions.
- DeepSeek-OCR and VSR setup sources use immutable revisions and safer
  extraction.

## 3.0.17 - 2026-08-28

### Fixed

- DeepSeek-OCR is never part of mandatory first-run setup.
- DeepSeek-OCR installer includes dynamic model dependencies and detects
  partial installations before downloading the model.

## 3.0.16 - 2026-08-27

### Fixed

- DeepSeek-OCR is now opt-in and no longer blocks first-run setup.
- Linux package updates use APT so dependencies are resolved during install.
- OpenAI-compatible translation accepts full `/chat/completions` endpoints.

## 3.0.15 - 2026-08-26

### Fixed

- Make installed-package smoke checks reliable across Linux and Windows CI.

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
