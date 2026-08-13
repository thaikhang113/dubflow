# DubFlow

**Lồng tiếng Việt cho video nước ngoài — tự động, chạy trên máy bạn, mã nguồn mở.**

DubFlow là ứng dụng desktop cho Windows và Linux. Dán link YouTube / TikTok /
Douyin / Bilibili hoặc chọn file trên máy, chọn giọng đọc, rồi xuất video
lồng tiếng Việt với nhạc nền, phụ đề và trình chỉnh sửa từng câu.

Nghe-chép, lồng tiếng, phụ đề và xuất video chạy cục bộ. Chỉ bước dịch cần
provider bên ngoài nếu bạn không dùng chế độ dịch tay.

```
Link / File video
   ├─► Tải về  ──►  Tách âm thanh  ──►  Tách nhạc nền (Demucs)
   │                       │
   │                       └──►  Nghe-chép lời gốc (Whisper / Paraformer)
   │                                     │
   │                                     └──►  Dịch sang tiếng Việt
   │                                                  │
   │                                                  └──►  Đọc thành giọng Việt (VieNeu)
   │                                                              │
   └───────────────────────────────────────────►  Khớp thời gian  ┘
                                                        │
                                    Trộn nhạc nền + phụ đề + che chữ gốc
                                                        │
                                                  dubbed_video.mp4
```

DubFlow được xây dựng lại từ mã nguồn [VoxDub](https://github.com/ttthanh2044/voxdub).
Tên dự án, giao diện, quy trình phát hành và phần mã được duy trì độc lập trong
repo này. Xem [LICENSE](LICENSE) và ghi công nguồn gốc trước khi phân phối lại.

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

### Cách nhanh nhất: dùng bản phát hành

Tải bản mới nhất tại [GitHub Releases](https://github.com/thaikhang113/dubflow/releases).

| Hệ điều hành | Gói |
|---|---|
| Windows 10/11 x64 | `DubFlow-vX.Y.Z-windows-x64.zip` |
| Linux x86_64 | `DubFlow-vX.Y.Z-linux-x86_64.tar.gz` |

Giải nén gói, đọc `HUONG_DAN_CAI_DAT.md`, rồi chạy `DubFlow.exe` trên Windows
hoặc `DubFlow/DubFlow` trên Linux.

Bản phát hành không kèm model AI, CUDA, FFmpeg hoặc thông tin đăng nhập.
Model được tải riêng khi cài tính năng tương ứng.

### Chạy từ mã nguồn

#### Windows

Cần:

- Python 3.10 trở lên
- FFmpeg bản đầy đủ
- khoảng 10 GB dung lượng trống nếu cài các model tùy chọn

Tải FFmpeg tại <https://www.gyan.dev/ffmpeg/builds/> rồi thêm thư mục `bin`
vào `PATH`.

Mở PowerShell trong thư mục dự án:

```powershell
.\cai_dat_all.bat
.\chay_app.bat
```

Script cài đặt có thể chạy lại an toàn. Thành phần đã cài sẽ được giữ lại.

#### Linux

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg libegl1 libgl1 libxkbcommon-x11-0
./cai_dat_all.sh
./chay_app.sh
```

Nếu file chưa có quyền chạy:

```bash
chmod +x cai_dat_all.sh chay_app.sh
```

#### Cài thủ công

```bash
python -m venv .venv
```

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m autodub_gui
```

Linux:

```bash
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/python -m autodub_gui
```

Model tùy chọn:

```bash
python scripts/setup_whisper.py
python scripts/setup_vieneu.py
python scripts/setup_paraformer.py
python scripts/setup_douyin.py
```

---

## 2. Chạy video đầu tiên

1. Mở DubFlow, chọn **Tạo dự án**.
2. Dán link video hoặc chọn file video trên máy.
3. Chọn ngôn ngữ gốc.
4. Chọn giọng đọc và nghe thử nếu cần.
5. Chọn phụ đề, nhạc nền và các tùy chọn chất lượng.
6. Bấm **Bắt đầu lồng tiếng**.

Khi hoàn tất, app cho phép mở video, mở thư mục kết quả hoặc chỉnh sửa từng
câu.

> Chạy dở bị tắt không làm mất tiến độ. Dữ liệu từng bước được lưu trong thư
> mục dự án; mở lại dự án để tiếp tục.

---

## 3. Bước dịch — hai cách

### Cách A — Dịch tay

Đây là chế độ không cần API key. Khi tới bước dịch, DubFlow tạo
`TRANSLATE_PENDING.txt` trong thư mục dự án.

1. Mở file hướng dẫn từ app.
2. Gửi transcript tới ChatGPT, Gemini hoặc công cụ dịch bạn chọn.
3. Lưu kết quả vào `data/transcript_vi.json`.
4. Quay lại app và chọn **Đã dịch xong, tiếp tục**.

### Cách B — Dịch tự động qua endpoint OpenAI-compatible

Điền các biến sau trong `.env` hoặc trang Cài đặt:

```dotenv
TRANSLATION_ENDPOINT=https://api.example.com/v1
TRANSLATION_API_KEY=your-api-key
TRANSLATION_MODEL=model-id
```

Endpoint cần hỗ trợ:

- `GET /models`
- `POST /chat/completions`

API key chỉ lưu cục bộ trong `.env`. Không commit `.env` hoặc cookie vào Git.

### Dịch sát ngữ cảnh hơn

Trang **Dịch thuật** cho phép nhập:

| Trường | Ví dụ |
|---|---|
| Chủ đề | `review công nghệ`, `phim cổ trang`, `vlog ẩm thực` |
| Xưng hô | `mình – các bạn`, `tôi – anh em`, `huynh – muội` |
| Thuật ngữ cố định | `内卷 = nội quyển`, mỗi dòng một cặp |
| Văn phong | `giọng trẻ trung, nhiều tiếng lóng` |

### Bilibili login

Xuất cookie trình duyệt ở định dạng Netscape rồi cấu hình:

```dotenv
BILIBILI_COOKIES_FILE=C:\path\to\bilibili-cookies.txt
```

Không commit file cookie.

---

## 4. Hướng dẫn từng trang

### Tạo dự án

- **Nhạc nền**: Demucs tách giọng khỏi nhạc; Duck giảm nhỏ tiếng gốc nhanh hơn.
- **Phụ đề**: không, file rời `.srt`, hoặc ghi thẳng vào video.
- **Che chữ**: khoanh vùng chữ trên video để làm mờ.
- **Tốc độ**: điều chỉnh tốc độ video và giọng đọc trong giới hạn an toàn.

### Xử lý hàng loạt

Mỗi dòng một video:

```text
https://youtu.be/abc123
https://youtu.be/def456 | nữ
https://www.douyin.com/video/789 | nam
# dòng bắt đầu bằng # là ghi chú
```

Tiến độ lưu vào `batch_state.json`; mở lại app để tiếp tục danh sách dở.

### Trình chỉnh sửa

- Xem bản gốc và bản dịch cạnh nhau.
- Nghe thử từng câu.
- Sửa câu rồi đọc lại riêng phần đã sửa.
- Xuất video, SRT, ASS hoặc MP3 lồng tiếng.

### Giọng đọc AI

VieNeu chạy trong môi trường riêng. Có thể:

- cài bộ giọng mẫu
- nghe thử từng giọng
- thêm giọng clone từ audio hoặc video ngắn
- xóa hồ sơ clone mà không xóa file nguồn

Chỉ dùng voice cloning khi có quyền sử dụng giọng nói đó.

### Phụ đề

Preset dựng sẵn gồm `clean`, `bold_yellow`, `box`, `tiktok`, `karaoke` và
`cinema`. Có thể chỉnh vị trí, font, cỡ chữ, viền, bóng, nền và số chữ mỗi
dòng.

### Tải xuống

Tải video về mà không chạy pipeline lồng tiếng. Hỗ trợ nhiều link và cookie
cho nội dung cần đăng nhập.

### Báo cáo chất lượng

`quality_report.json` và `timing_guide.json` cho biết câu bị lệch, bị nén hoặc
bị dồn thời gian để chỉnh lại trong editor.

### Cài đặt

`QUALITY_PRESET`:

- `fast`
- `balanced`
- `quality`

Các nhóm cài đặt chính: model, ngôn ngữ, thư mục output, số worker, tốc độ,
subtitle, dịch, branding và dọn file trung gian.

---

## 5. Kết quả nằm ở đâu

Mỗi lần chạy tạo một thư mục trong `output/`:

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

Pipeline cache theo file. Xóa file trung gian nào thì chỉ bước tương ứng chạy
lại.

> `AUTO_CLEAN_INTERMEDIATES=true` tiết kiệm ổ đĩa nhưng làm giảm khả năng sửa
> câu và xuất lại dự án.

---

## 6. Cài thêm

| Script | Chức năng |
|---|---|
| `scripts/setup_paraformer.py` | ASR tiếng Trung Paraformer |
| `scripts/setup_whisper.py` | ASR Whisper |
| `scripts/setup_vieneu.py` | TTS VieNeu |
| `scripts/setup_douyin.py` | Chromium cho Douyin |
| `scripts/setup_ocr.py` | OCR và xử lý vùng subtitle |
| `scripts/setup_voices.py` | Nạp thư viện giọng |

GPU NVIDIA không bắt buộc. CPU là chế độ nền; GPU chỉ tăng tốc một số model.

---

## 7. Câu hỏi thường gặp

**Lần đầu chạy lâu?**
Model AI cần được tải một lần. Thời gian phụ thuộc tốc độ mạng và model đã
chọn.

**Không có GPU có chạy được không?**
Có. Whisper, VieNeu và các bước media có fallback CPU.

**FFmpeg không nhận?**
Kiểm tra:

```bash
ffmpeg -version
ffprobe -version
```

Trên Windows có thể đặt `ffmpeg.exe` và `ffprobe.exe` cạnh `DubFlow.exe`.

**Dịch tự động không chạy?**
Kiểm tra `TRANSLATION_ENDPOINT`, `TRANSLATION_API_KEY` và
`TRANSLATION_MODEL`. Hoặc dùng `TRANSLATE_PENDING.txt` để dịch tay.

**Douyin không tải được?**
Chạy `scripts/setup_douyin.py`, rồi cài Chromium theo hướng dẫn hiện ra.

**Giọng clone thất bại?**
Đảm bảo VieNeu đã cài, audio rõ, dài từ 1 đến 8 giây và FFmpeg hoạt động.

**Có phải trả phí không?**
DubFlow không thu phí. Provider dịch hoặc model bên ngoài có thể có chính sách
chi phí riêng.

---

## 8. Dành cho lập trình viên

### Cấu trúc

```text
autodub/                 # lõi pipeline, không phụ thuộc GUI
├── pipeline.py          # pipeline chính, cache theo file
├── editor.py            # sửa câu và xuất lại
├── batch.py             # xử lý hàng loạt
├── config.py            # Settings từ .env
├── media/               # download, audio, video, subtitle
├── speech/              # ASR và TTS
├── text/                # SRT, ASS, dịch
└── content/             # metadata và prompt

autodub_gui/             # PySide6 desktop UI
├── app.py               # MainWindow
├── workers.py            # QThread cho tác vụ nặng
├── pages/               # các trang giao diện
├── ui/                  # widget dùng chung
└── video/               # player và timeline

scripts/                 # cài đặt và đóng gói
tests/                   # test suite
.github/workflows/       # CI và release Windows/Linux
```

### Cài dependency và chạy test

```bash
python -m pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Trên Windows PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
```

### Đóng gói

Windows:

```powershell
python -m pip install pyinstaller
python scripts/build_exe.py
```

Linux:

```bash
python -m pip install pyinstaller
python scripts/build_linux.py --version 0.1.0
```

Push tag semantic version như `v0.1.0` để GitHub Actions build và publish
artifact cho cả Windows và Linux. Chi tiết xem
[README-RELEASE.md](README-RELEASE.md).

### Đóng góp

Issue và pull request:

<https://github.com/thaikhang113/dubflow/issues>

---

## 9. Ghi công và đóng góp

DubFlow là bản fork/rework open-source dựa trên:

- [ttthanh2044/voxdub](https://github.com/ttthanh2044/voxdub)
- PySide6
- FFmpeg
- faster-whisper / Whisper
- VieNeu-TTS
- Paraformer và sherpa-onnx
- Demucs

Các model, voice mẫu và thư viện bên thứ ba có license riêng. Kiểm tra license
của từng dự án trước khi dùng thương mại.

Nếu DubFlow hữu ích, hãy star repo hoặc mở issue mô tả rõ môi trường và log lỗi:

<https://github.com/thaikhang113/dubflow>

## Giấy phép

Mã nguồn DubFlow theo giấy phép **MIT** — xem [LICENSE](LICENSE).

Không dùng voice cloning để giả mạo người khác. Không dùng app để phát hành
nội dung vi phạm bản quyền.
