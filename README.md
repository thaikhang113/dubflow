# DubFlow

Lồng tiếng Việt cho video nước ngoài — tự động, chạy trên máy bạn, mã nguồn mở.

DubFlow là ứng dụng desktop cho Windows và Linux. Dán link YouTube, TikTok,
Douyin hoặc Bilibili, hoặc chọn file video trên máy, chọn giọng đọc rồi xuất
video lồng tiếng Việt với nhạc nền, phụ đề và trình chỉnh sửa từng câu.

Nghe-chép, tách giọng, tạo giọng đọc, phụ đề và xuất video chạy cục bộ. Chỉ
bước dịch tự động cần endpoint bên ngoài; bạn cũng có thể dịch thủ công.

```text
Link / File video
   ├─► Tải về ──► Tách âm thanh ──► Tách nhạc nền (Demucs)
   │                    │
   │                    └─► Nghe-chép lời gốc (Whisper / Paraformer)
   │                                  │
   │                                  └─► Dịch sang tiếng Việt
   │                                               │
   │                                               └─► Đọc thành giọng Việt (VieNeu)
   │
   └────────────────────────────────────────► Khớp thời gian
                                                   │
                              Trộn nhạc nền + phụ đề + che chữ gốc
                                                   │
                                             dubbed_video.mp4
```

DubFlow được xây dựng lại từ mã nguồn [VoxDub](https://github.com/ttthanh2044/voxdub).
Repo gốc là nền tảng ban đầu của dự án; DubFlow giữ credit nguồn gốc và phát
triển độc lập phần giao diện, đóng gói, bootstrap và phát hành.

---

## Mục lục

1. [Cài đặt trong 5 phút](#1-cài-đặt-trong-5-phút)
2. [Chạy video đầu tiên](#2-chạy-video-đầu-tiên)
3. [Bước dịch — hai cách](#3-bước-dịch--hai-cách)
4. [Hướng dẫn từng trang](#4-hướng-dẫn-từng-trang)
5. [Kết quả nằm ở đâu](#5-kết-quả-nằm-ở-đâu)
6. [Cài thêm](#6-cài-thêm)
7. [Câu hỏi thường gặp](#7-câu-hỏi-thường-gặp)
8. [Dành cho lập trình viên](#8-dành-cho-lập-trình-viên)
9. [Ghi công và đóng góp](#9-ghi-công-và-đóng-góp)

---

## 1. Cài đặt trong 5 phút

### Dùng bản phát hành

Tải bản mới nhất tại [GitHub Releases](https://github.com/thaikhang113/dubflow/releases).

| Hệ điều hành | Gói |
| --- | --- |
| Windows 10/11 x64 | `DubFlow-vX.Y.Z-windows-x64-setup.exe` |
| Linux x86_64 | `dubflow_X.Y.Z_amd64.deb` |

Windows: chạy installer `.exe`.

Debian/Ubuntu:

```bash
sudo apt install ./dubflow_X.Y.Z_amd64.deb
```

Mở DubFlow sau khi cài. Lần đầu chạy, wizard tự tải và cài các thành phần:

1. Python runtime
2. FFmpeg và ffprobe
3. VieNeu TTS
4. Whisper ASR
5. Paraformer ASR tiếng Trung
6. OCR
7. Chromium cho Douyin
8. Demucs và model `htdemucs`
9. Thư viện voice

Wizard có progress, log, retry và resume. Đóng app rồi mở lại sẽ tiếp tục từ
bước chưa hoàn tất. App chính chỉ mở sau khi bootstrap hoàn tất.

Model, credential, cookie và dữ liệu dự án không nằm trong installer. Dữ liệu
người dùng được lưu tại:

- Windows: `%LOCALAPPDATA%\DubFlow`
- Linux: `$XDG_DATA_HOME/dubflow` hoặc `~/.local/share/dubflow`

### Chạy từ mã nguồn

Yêu cầu Python 3.10–3.12.

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m autodub_gui
```

Hoặc:

```powershell
.\cai_dat_all.bat
.\chay_app.bat
```

Linux:

```bash
sudo apt-get update
sudo apt-get install -y libegl1 libgl1 libxkbcommon-x11-0
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/python -m autodub_gui
```

Gói Linux phát hành tự tải Python portable khi chạy lần đầu. CPU luôn là
fallback; GPU NVIDIA/AMD tăng tốc các pipeline có runtime tương thích. FFmpeg
đã tự chọn encoder phần cứng khả dụng.

---

## 2. Chạy video đầu tiên

1. Mở DubFlow, chọn **Tạo dự án**.
2. Dán link video hoặc chọn file video trên máy.
3. Chọn ngôn ngữ gốc.
4. Chọn giọng đọc và nghe thử nếu cần.
5. Chọn phụ đề, nhạc nền, che chữ và chất lượng xuất.
6. Bấm **Bắt đầu lồng tiếng**.

Khi hoàn tất, app cho phép mở video, mở thư mục kết quả hoặc chỉnh sửa từng
câu.

> Pipeline lưu kết quả từng bước ra file. Nếu app bị đóng giữa chừng, mở lại
> dự án để tiếp tục từ bước đã dừng.

---

## 3. Bước dịch — hai cách

### Cách A — Dịch thủ công

Khi tới bước dịch, app tạo `TRANSLATE_PENDING.txt` trong thư mục dự án.

1. Mở file hướng dẫn từ app.
2. Gửi transcript tới ChatGPT, Gemini hoặc công cụ khác.
3. Lưu kết quả vào `data/transcript_vi.json`.
4. Quay lại app và chọn **Đã dịch xong, tiếp tục**.

Cách này không cần API key.

### Cách B — Endpoint OpenAI-compatible

Cấu hình trong trang Cài đặt hoặc file `.env`:

```dotenv
TRANSLATION_ENDPOINT=https://api.example.com/v1
TRANSLATION_API_KEY=your-api-key
TRANSLATION_MODEL=model-id
```

Endpoint cần hỗ trợ:

- `GET /models`
- `POST /chat/completions`

API key chỉ lưu cục bộ. Không commit `.env`, API key hoặc cookie vào Git.

### Dịch sát ngữ cảnh hơn

Trang **Dịch thuật** hỗ trợ thêm:

| Trường | Ví dụ |
| --- | --- |
| Chủ đề | `review công nghệ`, `phim cổ trang`, `vlog ẩm thực` |
| Xưng hô | `mình – các bạn`, `tôi – anh em`, `huynh – muội` |
| Thuật ngữ cố định | `内卷 = nội quyển`, mỗi dòng một cặp |
| Văn phong | `giọng trẻ trung, nhiều tiếng lóng` |

---

## 4. Hướng dẫn từng trang

### Tạo dự án

- **Nhạc nền**: Demucs tách giọng khỏi nhạc với chất lượng cao; Duck giảm
  tiếng gốc nhanh hơn.
- **Phụ đề**: xuất file rời hoặc ghi thẳng vào video.
- **Che chữ**: xem trước video và khoanh vùng chữ gốc để che.
- **Chất lượng**: chọn tốc độ, chất lượng xuất và tùy chọn xử lý.

### Xử lý hàng loạt

Mỗi dòng một video:

```text
https://youtu.be/abc123
https://youtu.be/def456 | nữ
https://www.douyin.com/video/789 | nam
# dòng bắt đầu bằng # là ghi chú
```

Tiến độ được lưu trong `batch_state.json`. Mở lại app để tiếp tục.

### Trình chỉnh sửa

- Xem bản gốc và bản dịch cạnh nhau.
- Nghe thử từng câu.
- Nhấp đúp để sửa bản dịch.
- Lưu và đọc lại những câu đã sửa.
- Xuất video, `.srt`, `.ass` hoặc MP3 lồng tiếng.

### Giọng đọc AI

VieNeu hỗ trợ voice preset và voice clone từ audio/video ngắn. Voice preset
nằm trong `voices/preset_voices_vn/`.

Chỉ clone hoặc phân phối giọng khi có quyền sử dụng. Không dùng voice cloning
để giả mạo người khác.

### Phụ đề

Preset gồm `clean`, `bold_yellow`, `box`, `tiktok`, `karaoke` và `cinema`.
Có thể chỉnh vị trí, font, cỡ chữ, màu, viền, bóng, nền mờ và số chữ mỗi dòng.

### Tải xuống

Tải video về mà không chạy pipeline lồng tiếng. Hỗ trợ nhiều link và browser
cookies cho nội dung yêu cầu đăng nhập.

### Cài đặt

Trang Cài đặt quản lý model, ngôn ngữ, thư mục output, số worker, tốc độ,
phụ đề, dịch, branding và dọn file trung gian.

---

## 5. Kết quả nằm ở đâu

Mỗi dự án nằm trong `output/`:

```text
output/VN/<project>/
├── dubbed_video.mp4
├── transcript_vi.srt
├── data/
│   ├── transcript_original.json
│   ├── transcript_vi.json
│   ├── original_audio.wav
│   ├── vocals.wav
│   ├── no_vocals.wav
│   ├── audio_vi_full.wav
│   ├── quality_report.json
│   └── timing_guide.json
└── segments/
```

Pipeline cache theo file. Xóa file nào thì chỉ bước tương ứng chạy lại.

Updater tải release mới, kiểm tra SHA256 rồi mới chạy installer. Project, model
và voice nằm ngoài thư mục cài đặt nên không bị ghi đè.

---

## 6. Cài thêm

Các script setup có thể chạy lại nhiều lần:

| Script | Chức năng |
| --- | --- |
| `scripts/setup_whisper.py` | Cài Whisper ASR |
| `scripts/setup_paraformer.py` | Cài Paraformer ASR tiếng Trung |
| `scripts/setup_vieneu.py` | Cài VieNeu TTS |
| `scripts/setup_voices.py` | Nạp thư viện voice |
| `scripts/setup_ocr.py` | Cài OCR |
| `scripts/setup_douyin.py` | Cài Chromium và hỗ trợ Douyin |
| `scripts/setup_demucs.py` | Cài Demucs và model `htdemucs` |

---

## 7. Câu hỏi thường gặp

**Lần đầu chạy lâu không?**
Có. Model và thành phần hỗ trợ có thể chiếm vài GB nhưng chỉ tải một lần.

**Không có GPU có chạy được không?**
Được. Pipeline có fallback CPU nhưng tốc độ thấp hơn.

**Không tải được Douyin?**
Chạy `scripts/setup_douyin.py`, cài Chromium rồi thử lại. Một số video cần
browser cookies đăng nhập.

**Cập nhật app có mất project không?**
Không. Project, model và voice nằm ngoài thư mục cài đặt.

**Có phải trả phí không?**
DubFlow không thu phí. Provider dịch, model hoặc dịch vụ bên ngoài có thể có
chi phí riêng.

---

## 8. Dành cho lập trình viên

### Cấu trúc

```text
autodub/                 # lõi pipeline, không phụ thuộc GUI
├── pipeline.py          # pipeline chính, cache theo file
├── editor.py            # sửa câu và xuất lại
├── batch.py             # xử lý hàng loạt
├── config.py            # cấu hình
├── media/               # download, audio, video, subtitle, OCR, Demucs
├── speech/              # ASR và TTS
└── text/                # SRT, ASS và dịch

autodub_gui/             # PySide6 desktop UI
├── app.py               # MainWindow và bootstrap
├── workers.py           # QThread cho tác vụ nặng
├── pages/               # các trang giao diện
├── ui/                  # widget dùng chung
└── video/               # player và timeline

scripts/                 # setup và đóng gói
tests/                   # test suite
.github/workflows/       # CI và release
```

### Chạy test

```bash
python -m pytest -q
python -m compileall -q autodub autodub_gui scripts
```

Windows PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
```

### Đóng gói

Windows:

```powershell
python scripts/build_exe.py --no-test
```

Linux:

```bash
python3 scripts/build_linux.py --version X.Y.Z
python3 scripts/build_deb.py --no-build --version X.Y.Z
```

Build `.deb` cần môi trường Linux có `dpkg-deb`. Push tag semantic version như
`vX.Y.Z` để GitHub Actions build installer Windows, package Linux và checksum
SHA256. Xem [README-RELEASE.md](README-RELEASE.md).

---

## 9. Ghi công và đóng góp

DubFlow là bản fork/rework open-source dựa trên:

- **Nguồn gốc chính:** [ttthanh2044/voxdub](https://github.com/ttthanh2044/voxdub)
- [PySide6](https://doc.qt.io/qtforpython/)
- [FFmpeg](https://ffmpeg.org/)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [VieNeu-TTS](https://github.com/pnnbao-ump/VieNeu-TTS)
- [Demucs](https://github.com/facebookresearch/demucs)

Báo lỗi, đề xuất tính năng và gửi pull request tại
[repository DubFlow](https://github.com/thaikhang113/dubflow).

Không commit model, voice, cookie, API key hoặc dữ liệu dự án. Không dùng app
để phát hành nội dung vi phạm bản quyền.

## Giấy phép

Mã nguồn DubFlow theo giấy phép **MIT** — xem [LICENSE](LICENSE).

Model, voice và thư viện bên thứ ba có license riêng. Kiểm tra license trước
khi phân phối hoặc sử dụng thương mại.
