# VoxDub Studio

**Lồng tiếng Việt cho video nước ngoài — tự động, chạy trên máy bạn, miễn phí.**

Ứng dụng desktop cho Windows. Dán link YouTube / TikTok / Douyin / Bilibili (hoặc chọn file trên máy), chọn giọng đọc, bấm chạy — nhận về video đã lồng tiếng Việt, **giữ nguyên nhạc nền và hiệu ứng âm thanh gốc**, kèm phụ đề và trình chỉnh sửa từng câu.

Nghe-chép, lồng tiếng, phụ đề, xuất video đều **chạy offline trên máy bạn**, không cần API key, không gửi video đi đâu.

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

---

## Mục lục

1. [Cài đặt trong 5 phút](#1-cài-đặt-trong-5-phút)
2. [Chạy video đầu tiên](#2-chạy-video-đầu-tiên)
3. [Bước dịch — hai cách](#3-bước-dịch--hai-cách)
4. [Hướng dẫn từng trang](#4-hướng-dẫn-từng-trang)
5. [Kết quả nằm ở đâu](#5-kết-quả-nằm-ở-đâu)
6. [Cài thêm (không bắt buộc)](#6-cài-thêm-không-bắt-buộc)
7. [Câu hỏi thường gặp](#7-câu-hỏi-thường-gặp)
8. [Dành cho lập trình viên](#8-dành-cho-lập-trình-viên)
9. [Ủng hộ tác giả](#9-ủng-hộ-tác-giả)

---

## 1. Cài đặt trong 5 phút

### Bạn cần chuẩn bị 2 thứ

| Cần gì | Tải ở đâu | Lưu ý |
|---|---|---|
| **Python 3.10 trở lên** | <https://www.python.org/downloads/> | Khi cài **NHỚ TÍCH ô "Add Python to PATH"** — quên bước này là mọi thứ sau đó không chạy |
| **ffmpeg (bản full)** | <https://www.gyan.dev/ffmpeg/builds/> — file `ffmpeg-release-full.7z` | Giải nén ra ví dụ `C:\ffmpeg`, rồi thêm `C:\ffmpeg\bin` vào **PATH** của Windows |

<details>
<summary><b>Cách thêm ffmpeg vào PATH (bấm để xem)</b></summary>

1. Giải nén file `.7z` vừa tải (dùng [7-Zip](https://www.7-zip.org/) nếu Windows không mở được)
2. Đổi tên thư mục vừa giải nén thành `ffmpeg`, chép vào ổ `C:\` → được `C:\ffmpeg\bin\ffmpeg.exe`
3. Bấm phím Windows, gõ **"environment variables"** → mở **"Edit the system environment variables"**
4. Bấm **Environment Variables…** → ở khung dưới chọn dòng **Path** → **Edit** → **New** → dán `C:\ffmpeg\bin` → **OK** hết
5. **Mở lại** Command Prompt, gõ `ffmpeg -version`. Hiện ra một đống chữ = xong.

</details>

### Rồi chạy 1 file

Tải mã nguồn về (bấm **Code → Download ZIP** ở trang GitHub, hoặc `git clone`), giải nén, rồi:

> **Đúp chuột vào `cai_dat.bat`**

File này tự làm hết:

| Bước | Nội dung |
|---|---|
| 1 | Kiểm tra Python |
| 2 | Kiểm tra ffmpeg |
| 3 | Cài thư viện Python (`requirements.txt`) |
| 4 | Tạo file cấu hình `.env` |
| 5 | Cài bộ nghe-chép **Whisper** và bộ giọng đọc **VieNeu** |

Lần đầu tải về khoảng **1–2 GB** (model AI) nên hơi lâu. **Chạy lại `cai_dat.bat` lúc nào cũng an toàn** — phần nào đã xong sẽ được bỏ qua, không tải lại.

### Mở ứng dụng

> **Đúp chuột vào `chay_app.bat`**

<details>
<summary><b>Nếu bạn thích gõ lệnh hơn</b></summary>

```bash
pip install -r requirements.txt
copy .env.example .env
py scripts/setup_whisper.py      # bộ nghe-chép, ~1 GB
py scripts/setup_vieneu.py       # bộ giọng đọc, ~300 MB
py -m autodub_gui                # mở app
```

</details>

---

## 2. Chạy video đầu tiên

1. Mở app → thanh bên trái chọn **Tạo dự án**
2. **Dán link video** (hoặc bấm chọn file `.mp4` trên máy)
3. Chọn **ngôn ngữ gốc** của video — tiếng Trung, tiếng Anh, tiếng Hàn…
4. Chọn **giọng đọc** — bấm nghe thử trước cũng được
5. Bấm **Bắt đầu lồng tiếng** rồi ngồi chờ

Xong, app cho bạn 3 nút: **mở video**, **mở thư mục**, **chỉnh sửa từng câu**.

> **Chạy dở bị tắt giữa chừng?** Không mất gì. Mọi bước đều lưu ra file — vào trang **Dự án**, mở lại dự án đó, app chạy tiếp từ đúng chỗ đã dừng.

---

## 3. Bước dịch — hai cách

Cả pipeline chạy offline, **trừ bước dịch**. Bạn chọn một trong hai:

### Cách A — Dịch tay (mặc định, không cần cấu hình gì)

Chạy tới bước dịch, app dừng lại và ghi sẵn file `TRANSLATE_PENDING.txt` ngay trong thư mục dự án. File đó là hướng dẫn từng bước, có kèm sẵn lời nhắn viết hoàn chỉnh để gửi cho AI:

1. Bấm nút **Mở hướng dẫn** trong app (mở `TRANSLATE_PENDING.txt` bằng Notepad)
2. Làm theo 3 bước ghi trong đó: copy `data/transcript_original.json` → dán vào **ChatGPT / Gemini** cùng lời nhắn có sẵn → lưu kết quả thành `data/transcript_vi.json`
3. Quay lại app bấm **Đã dịch xong, tiếp tục**

Miễn phí, không giới hạn, chất lượng tuỳ AI bạn dùng.

### Cách B — Dịch tự động qua endpoint OpenAI-compatible

VoxDub gửi transcript tới endpoint API bạn chọn bằng API key của bạn.

```dotenv
TRANSLATION_ENDPOINT=https://api.example.com/v1
TRANSLATION_API_KEY=your-api-key
TRANSLATION_MODEL=model-id
```

Endpoint cần có:

- `GET /models`
- `POST /chat/completions`

Prompt giữ ngữ cảnh video, xưng hô, glossary, style notes, câu liền trước,
ID và giới hạn độ dài từng cue. API key chỉ lưu trong `.env`, không ghi log.

### Bilibili login

Xuất cookies từ trình duyệt đang đăng nhập thành Netscape `cookies.txt`, rồi
đặt đường dẫn:

```dotenv
BILIBILI_COOKIES_FILE=C:\path\to\bilibili-cookies.txt
```

Pipeline tự bỏ query tracking như `vd_source` và dùng cookie khi tải Bilibili.
Không commit file cookie.

### ASR mặc định

Video tiếng Trung dùng Paraformer nếu đã cài `.venv-asr`; nếu thiếu model hoặc
worker lỗi, pipeline tự quay về Whisper.

ba mục trên, pipeline dừng và báo cấu hình thiếu thay vì tự chuyển provider.

### Dịch chuẩn hơn — điền ngữ cảnh video

Trang **Dịch thuật** trên thanh bên có mấy ô giúp bản dịch bám sát video hơn (áp dụng cho cả hai cách):

| Ô | Ví dụ |
|---|---|
| Chủ đề | `review công nghệ`, `phim cổ trang`, `vlog ẩm thực` |
| Xưng hô | `mình – các bạn`, `tôi – anh em`, `huynh – muội` |
| Thuật ngữ cố định | `内卷 = nội quyển`, mỗi dòng một cặp |
| Ghi chú văn phong | `giọng trẻ trung, nhiều tiếng lóng` |

---

## 4. Hướng dẫn từng trang

### Tạo dự án — làm 1 video

Ngoài link và giọng đọc, các tuỳ chọn đáng chú ý:

- **Nhạc nền**: `Demucs` tách hẳn giọng khỏi nhạc (chất lượng cao nhất, mặc định) — hoặc `Duck` giảm nhỏ tiếng gốc khi có giọng đọc (nhanh hơn nhiều)
- **Phụ đề**: không / **rời** (file `.srt`, bật tắt được trong trình phát) / **ghi thẳng vào hình** (luôn hiện, hợp đăng TikTok)
- **Phụ đề & che chữ…**: mở khung xem trước ngay trên khung hình video — **kéo thả** dòng phụ đề để đặt vị trí, chỉnh font/cỡ/màu/viền thấy ngay, và **khoanh vùng bằng chuột** để che mờ chữ Trung trên hình

### Xử lý hàng loạt — nhiều video một lượt

Dán link vào ô, **mỗi dòng một video**:

```
https://youtu.be/abc123
https://youtu.be/def456 | nữ
https://www.douyin.com/video/789 | nam
# dòng bắt đầu bằng # là ghi chú, bỏ qua
```

- Giọng đọc và ngôn ngữ chọn một lần cho cả loạt; muốn video nào khác giọng thì thêm `| nam` hoặc `| nữ` ở cuối dòng
- **Tiến độ tự lưu** vào `batch_state.json` — tắt app mở lại, dán lại danh sách cũ, video đã xong tự bỏ qua

### Trình chỉnh sửa — sửa từng câu

- Bảng liệt kê từng câu, bản gốc và bản dịch cạnh nhau
- Bấm **▶** nghe thử câu đó; **nhấp đôi** vào ô bản dịch để sửa
- Sửa bao nhiêu câu tuỳ thích rồi bấm **Lưu tất cả và đọc lại** một lần — app chỉ đọc lại đúng những câu đã sửa
- Bấm **Xuất video** khi ưng. Cạnh đó có sẵn nút tải riêng file `.SRT`, `.ASS` hoặc MP3 lồng tiếng.

### Giọng đọc AI

Thư viện giọng có bộ lọc theo **giới tính / vùng miền / phong cách**, nút **nghe thử** từng giọng. Repo đi kèm sẵn **120 giọng mẫu** trong `voices/preset_voices_vn/`.

**Thêm giọng của riêng bạn:** chọn một file WAV dài 5–10 giây (nói rõ, không nhạc nền), nhập đúng nội dung câu nói trong đó — app tự học và thêm vào thư viện.

> Không dùng tính năng này để giả mạo giọng người khác.

### Phụ đề

Các bộ kiểu dựng sẵn: `clean`, `bold_yellow`, `box`, `tiktok`, `karaoke`, `cinema`. Chỉnh được vị trí, font, cỡ chữ, viền, bóng, nền mờ kiểu CapCut, số chữ mỗi dòng.

Chế độ **karaoke** làm chữ nhảy theo giọng đọc; bật *Khớp mốc chữ thật* để app nghe lại chính giọng vừa tạo và căn chuẩn từng cụm (thêm khoảng 30–60 giây mỗi video).

### Tải xuống

Chỉ tải video về, không lồng tiếng. Dán nhiều link một lượt. Hỗ trợ cookies trình duyệt cho video cần đăng nhập.

### Báo cáo chất lượng

Đọc `quality_report.json` của một dự án: bao nhiêu câu khớp đẹp, câu nào bị nén hoặc dồn trễ, câu nào chồng tiếng. Xem trang này để biết cần sửa tay câu nào.

### Cài đặt

Có một **nút vặn tổng** là `QUALITY_PRESET`: `fast` / `balanced` (khuyên dùng) / `quality`. Chỉnh mục chi tiết nào thì mục đó ghi đè preset.

| Thẻ | Nội dung chính |
|---|---|
| Cơ bản | Model Whisper, bộ nhận dạng, thư mục xuất, ngôn ngữ mặc định, tên hiển thị |
| Hiệu suất | Số việc chạy song song, số luồng giọng đọc |
| Nâng cao | Tốc độ video/giọng, ngân sách ký tự mỗi giây, chống chồng tiếng, âm lượng, dọn file trung gian |

---

## 5. Kết quả nằm ở đâu

Mỗi lần chạy tạo một thư mục trong `output/`:

```
output/VN/20260809103000_vi/
├── dubbed_video.mp4            ← VIDEO HOÀN CHỈNH (thứ bạn cần)
├── transcript_vi.srt           ← phụ đề tiếng Việt rời
├── youtube/                    ← tiêu đề, mô tả, hashtag, prompt thumbnail
└── data/                       ← file kỹ thuật, dùng để chạy tiếp & sửa câu
    ├── transcript_original.json/.srt   ← lời gốc app nghe được
    ├── transcript_vi.json              ← bản dịch tiếng Việt
    ├── original_audio.wav, vocals.wav, no_vocals.wav
    ├── audio_vi_full.wav               ← toàn bộ giọng đọc đã ghép
    ├── segments/                       ← giọng đọc từng câu (cache)
    ├── quality_report.json             ← chấm điểm khớp thời gian
    └── timing_guide.json               ← liệt kê câu bị lệch, cần sửa tay
```

Mọi bước đều **cache theo file**: xoá file nào thì riêng bước đó chạy lại, phần còn lại giữ nguyên.

> Muốn tiết kiệm ổ cứng, bật `AUTO_CLEAN_INTERMEDIATES=true` — nhưng dự án đã dọn thì **không sửa từng câu hay xuất lại được nữa**.

---

## 6. Cài thêm (không bắt buộc)

Mỗi mục là một file `.bat`, đúp chuột là chạy:

| File | Làm gì | Dung lượng |
|---|---|---|
| `cai_them_paraformer.bat` | Bộ nghe tiếng Trung **Paraformer** — chính xác hơn Whisper và nhanh hơn trên CPU. Cài xong app tự dùng cho video tiếng Trung. | ~520 MB |
| `cai_them_douyin.bat` | Trình duyệt Chromium để tải video **Douyin** thẳng từ link | ~170 MB |
| `nap_giong_doc.bat` | Nạp 120 giọng mẫu trong `voices/` vào app. Thả thêm file `.wav` vào `voices/custom/` rồi chạy lại để thêm giọng riêng. | — |

Cần GPU NVIDIA để Whisper và Demucs chạy nhanh hơn? App tự phát hiện và dùng, không cần cấu hình gì.

---

## 7. Câu hỏi thường gặp

**Lần đầu chạy rất lâu?**
Whisper và Demucs phải tải model về (vài GB, **một lần duy nhất**). Từ lần thứ hai trở đi nhanh hơn hẳn.

**Máy không có card đồ hoạ có chạy được không?**
Được hết. Whisper chạy CPU tốt (chọn model `medium`), giọng đọc VieNeu vốn được thiết kế cho CPU (~1 giây/câu). Có GPU thì tự nhanh hơn.

**Lỗi `No such filter: subtitles` khi ghi phụ đề vào hình?**
ffmpeg của bạn thiếu libass. Cài lại bản **full** từ gyan.dev, hoặc tạm chuyển phụ đề sang chế độ **rời**.

**Giọng đọc bị chồng lên nhau / nhanh quá?**
Tiếng Việt thường dài hơn tiếng gốc khoảng 20%. Ba cách xử lý, thử theo thứ tự:
1. Vào **Trình chỉnh sửa**, viết lại những câu dài cho ngắn gọn hơn
2. Giảm `TRANSLATE_CPS_BUDGET` (mặc định `12.5`) để bản dịch tự ngắn lại
3. Đặt `VIDEO_SPEED=0.9` — làm chậm cả video một chút để có thêm chỗ trống

Câu nào bị lệch đều được liệt kê trong `data/timing_guide.json` và trang **Báo cáo chất lượng**.

**Không tải được video Douyin?**
Chạy `cai_them_douyin.bat`. Một số video vẫn cần cookies đăng nhập — trang **Tải xuống** có hỗ trợ.

**Chạy `cai_dat.bat` bị lỗi giữa chừng?**
Cứ chạy lại. Script được viết để chạy lại nhiều lần vô hại — phần đã xong sẽ bỏ qua.

**App báo thiếu bộ giọng đọc?**
Chạy lại `cai_dat.bat` (bước 5), hoặc gõ `py scripts/setup_vieneu.py`.

**Tôi có phải trả tiền gì không?**
Không. Toàn bộ pipeline chạy trên máy bạn. Chỉ khi bạn tự dựng máy chủ dịch ở [Cách B](#cách-b--dịch-tự-động-cần-tự-dựng-máy-chủ) thì mới phát sinh chi phí API của chính bạn.

---

## 8. Dành cho lập trình viên

### Cấu trúc

```
autodub/                 # lõi pipeline, không phụ thuộc GUI
├── pipeline.py          # DubPipeline — chạy đủ các bước, cache theo file
├── editor.py            # sửa câu / đọc lại / xuất lại
├── batch.py             # chạy hàng loạt, state crash-safe
├── config.py            # Settings đọc từ .env, validate lười
├── workdir.py           # bố cục thư mục dự án (data/, youtube/)
├── progress.py          # ProgressEvent callback + cancel
├── media/               # download, audio, video, phụ đề, che chữ, Demucs
├── speech/              # ASR (Whisper, Paraformer) + TTS (VieNeu, CapCut)
├── text/                # SRT, karaoke ASS, dịch, TRANSLATE_PENDING.txt
├── content/             # tiêu đề/mô tả/hashtag + prompt thumbnail

autodub_gui/             # giao diện PySide6, dark theme
├── app.py               # MainWindow — thanh bên + các trang
├── workers.py           # QThread cho từng việc nặng
├── pages/               # mỗi trang một file
├── ui/                  # widget dùng chung
├── video/               # trình phát + timeline
├── theme.py             # QSS
└── tokens.py            # design tokens — file DUY NHẤT chứa mã màu

scripts/                 # cài đặt & đóng gói (mỗi script chạy lại được)
voices/preset_voices_vn/ # 120 giọng mẫu, đi kèm repo
tests/                   # 584 test
```

### Nguyên tắc thiết kế

- **Mỗi thành phần nặng một virtualenv riêng** — `.venv-vieneu` (ONNX, không torch), `.venv-whisper`, `.venv-asr`. Môi trường chính nhẹ, không xung đột phiên bản.
- **Cache theo file, không theo bộ nhớ** — mọi bước ghi kết quả ra đĩa, nên chạy tiếp sau khi tắt máy là chuyện bình thường.
- **`tokens.py` là nơi duy nhất có mã màu** — không hardcode màu ở chỗ khác.

### Chạy test

```bash
py -m pytest -q
```

### Đóng gói `.exe`

```bash
py scripts/build_exe.py
```

Góp ý và báo lỗi: <https://github.com/ttthanh2044/voxdub/issues>

---

## 9. Ủng hộ tác giả

Dự án này miễn phí và mã nguồn mở. Nếu nó giúp ích cho bạn, có thể mời tác giả một ly cà phê:

| | |
|---|---|
| **Ngân hàng** | MB Bank |
| **Số tài khoản** | `0983832373` |
| **Chủ tài khoản** | TRAN TAN THANH |

Cảm ơn bạn rất nhiều. Một ngôi sao ⭐ trên GitHub cũng đã là động lực lớn.

---

## Giấy phép

Mã nguồn theo giấy phép **MIT** — xem [LICENSE](LICENSE).

Các model AI mà app tải về (VieNeu, Whisper, Paraformer, Demucs) có giấy phép riêng của từng dự án; kiểm tra trước khi dùng cho mục đích thương mại.

**Xin đừng dùng để giả mạo giọng người khác, hoặc lồng tiếng nội dung vi phạm bản quyền.**
## Giọng clone VieNeu

Mở trang **Giọng đọc AI**, bấm **Thêm giọng clone** rồi chọn:

- **Đoạn audio**: WAV/MP3/M4A/FLAC/OGG/AAC có 1 đến 8 giây thoại rõ.
- **Video**: MP4/MKV/WEBM/MOV/AVI có đoạn thoại rõ trong 1 đến 8 giây đầu.

Ứng dụng xử lý cục bộ bằng VieNeu. File nguồn không bị tải lên và không bị xóa.
Hồ sơ đã học lưu tại `models/vieneu/custom_voices.json`; dữ liệu này được nạp
lại tự động sau khi mở app.

Sau khi tạo, giọng xuất hiện trong tab **Giọng clone**, có thể nghe thử, chọn
cho dự án mới, hoặc xóa hồ sơ. Xóa hồ sơ không xóa audio/video nguồn.

Yêu cầu: VieNeu đã cài, FFmpeg có trong `PATH`; video clone cần thêm audio đọc
được từ video. Nếu học giọng thất bại, các giọng cũ vẫn giữ nguyên.
