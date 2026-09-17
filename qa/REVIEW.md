# Rà soát tính năng DubFlow theo góc nhìn người dùng

Ngày rà soát: 2026-09-08. Máy: RTX 3050 Ti Laptop 4 GB, 16 nhân, 15 GB RAM,
Windows. Model/venv cài thật tại `%LOCALAPPDATA%\DubFlow`.

Lượt 2 bổ sung: ba phàn nàn của Haonguyen ngày 07/09 — không có nút dừng khẩn
cấp khi làm video, bấm dừng vẫn chạy hết tiến trình, và "lâu kinh". Đã đo, đã
sửa, số liệu ở mục **Dừng khẩn cấp** và **Hiệu năng**.

## Cách tiến hành

Bốn bộ rà soát độc lập, chạy bằng hạ tầng trong `qa/`:

| Bộ | Phạm vi | Kết quả |
| --- | --- | --- |
| `gui_walkthrough.py` | 13 trang + editor + launcher, dựng/điều hướng/chụp ảnh | 13/13 OK, **0 phát hiện** |
| `e2e_review.py` | 7 kịch bản pipeline thật (S1–S7) | **0 phát hiện** |
| `features_review.py` | Dự án, Báo cáo chất lượng, vòng ghi/đọc `.env`, Giọng đọc, Phụ đề, OpenClaw, Doctor | 1 (VSR chưa cài — giờ là tùy chọn) |
| `editor_review.py` | Sửa câu, phụ đề riêng, đọc lại giọng, dựng lại video, xuất chỉ phụ đề | **0 phát hiện** |
| `cancel_review.py` | Bấm Dừng giữa merge_audio / TTS / xuất video | **0 phát hiện** |
| `timing_single.py` | Một lượt chạy hoàn chỉnh, không cache, đo từng bước | — |
| `long_video_review.py` | Video 10 phút rồi 30 phút có lời thật, chạy hết chuỗi | **0 lỗi** |
| `batch_flows_review.py` | Ba nhánh batch chưa từng chạy với pipeline thật | **0 phát hiện** |

Bằng chứng: `qa/shots/*.png` (27 ảnh), `qa/logs/*.log`, `qa/runs/<kịch bản>/`,
`qa/findings_*.json`. Unit test: **906 passed**. Smoke `AUTODUB_SMOKE=1`:
`ok: true`.

## Phát hiện đã sửa trong lượt này

Ba lỗi dưới đây chặn đứng luồng người dùng và khiến các bước rà soát sau không
chạy được, nên đã vá ngay để hoàn tất việc kiểm tra.

### 1. Auto-clean làm dự án không mở lại được bằng Editor — S1

`AUTO_CLEAN_INTERMEDIATES=true` xóa **toàn bộ** thư mục `data/`, gồm cả
`transcript_vi.json`. Hệ quả trên dự án đã xuất video thành công:

```
EditorError: No translation found (transcript_vi.json). Run the dub first.
```

Người dùng lồng tiếng xong, bấm mở Trình chỉnh sửa, và được bảo chạy lại từ đầu.
Kèm theo đó là mất cache ASR/OCR (`transcript_original.json`,
`ocr_regions.json`) nên mọi lần chạy sau phải nghe lại và chạy OCR lại (~28 s
cho video 5 giây), và batch không validate được vì mất `report.json`.

Sửa trong [autodub/diskspace.py](../autodub/diskspace.py): dọn theo **loại tệp**
chứ không theo danh sách tên — chỉ xóa media nặng (`.wav/.mp4/.mkv/.webm/.mov`)
và clip trong `segments*/`. Mọi metadata nhỏ (transcript, report, quality,
timing, render_opts, state) được giữ. `measure_project()` dùng chung lối đếm với
`clean_project()` để chữ "dọn được" trên giao diện khớp số byte thực giải phóng.

Hiệu quả đo trên dự án thật: giữ lại ~17 KB metadata, vẫn giải phóng ~2.7 MB.

### 2. Auto-clean xóa marker `segments/.render_mode` → chặn xuất video vĩnh viễn — S1

`_clean_data_dir` xóa nguyên thư mục `segments/`, mất luôn marker ẩn
`.render_mode`. Lần đọc lại giọng kế tiếp tạo `segments/` mới không marker, và
`editor._check_render_mode()` suy ra "giọng đọc tạo theo cơ chế gộp câu đời cũ"
rồi **từ chối xuất video**:

```
EditorError: Thư mục này chứa giọng đọc tạo theo cơ chế gộp câu đời cũ.
```

Dự án kẹt: không xuất lại được, và thông báo gợi ý "chạy tiếp dự án" cũng không
giải quyết vì marker vẫn thiếu. Sửa bằng `_clean_segment_dir()`: xóa clip
`.wav`, giữ tệp ẩn bắt đầu bằng dấu chấm, chỉ xóa thư mục khi không còn gì.

### 3. Batch đếm hai lần một video, và validate nhầm tệp trung gian — S1/S2

Sửa trong [autodub/batch.py](../autodub/batch.py):

* `summary.success += 1` chạy **trước** `on_result()`; nếu `on_result` ném lỗi
  thì cùng một video vừa được tính success vừa bị tính failed. Đã dời xuống sau.
* `validate_batch_report()` yêu cầu cả `dub_audio` (`data/audio_vi_full.wav`) ở
  chế độ có video — đúng ra chỉ `dubbed_video.mp4` là sản phẩm người dùng cần;
  tệp WAV là trung gian mà auto-clean hợp lệ sẽ xóa.

## Phát hiện còn lại

### A. VSR là bước bắt buộc của wizard — S2 — **đã sửa**

`hardware.select_backends()` chọn backend VSR chỉ theo RAM ≥ 8 GB và đĩa ≥ 4 GB,
**không đọc** `settings.vsr_enabled`. `bootstrap.steps()` biến lựa chọn đó thành
bước bắt buộc, và `app.main()` đóng cửa sổ nếu `bootstrap.is_complete()` sai:

```
steps: [..., 'vsr']   missing: ['vsr']   is_complete(): False
```

Hệ quả: trên máy đủ RAM/đĩa, người dùng phải tải ~700 MB video-subtitle-remover
(yêu cầu Python 3.10–3.12) mới mở được app, kể cả khi đã tắt "AI xóa phụ đề"
trong Cài đặt. Tính năng tăng cường bị nâng cấp thành điều kiện khởi động.

Sửa: `BootstrapStep` thêm cờ `optional`; bước `vsr` được đánh dấu tùy chọn;
`is_complete()` bỏ qua bước tùy chọn; `BootstrapDialog` coi bước tùy chọn đã fail
là "skipped" rồi đi tiếp thay vì kẹt ở Retry/Close. Wizard vẫn chào cài VSR.

Kiểm chứng trên máy này: `is_complete()` `False` → `True`, và
`first_run.is_first_run()` `False` → app mở cửa sổ thay vì thoát.

Chưa làm một phần: `select_backends()` vẫn không đọc `settings.vsr_enabled`, nên
người dùng đã tắt "AI xóa phụ đề" vẫn được chào cài VSR. Giờ đó chỉ còn là thừa
một lựa chọn, không còn chặn khởi động.

### B. Doctor báo `fail` cho Python ngoài dải 3.10–3.12 — S2 — **đã sửa, kèm đính chính**

Sai ở hai chỗ trong kết luận ban đầu:

* `requires-python = ">=3.10"` **đã có** marker `python_version >= '3.13'` cho
  `audioop-lts`, tức dự án có chủ đích hỗ trợ 3.13. Đề xuất chặn `<3.13` là
  **không đúng**, sẽ làm hỏng môi trường dev đang chạy tốt.
* Chú thích "3.13+ chưa có wheel cho onnxruntime/ctranslate2" trong
  `workers_setup.py` không còn đúng cho interpreter của app: trên 3.13.13 ở máy
  này, ctranslate2 4.8.1, onnxruntime 1.28.0, faster-whisper 1.2.1 đều import
  được và toàn bộ E2E chạy trên đó.

Điểm đúng: dải 3.10–3.12 chỉ ràng buộc VSR và DeepSeek-OCR, và hai engine đó cài
vào venv riêng do `workers_setup` chọn interpreter — nên `doctor._check_python()`
trả `fail` là buộc người dùng cài lại Python vì lý do không đúng. Sửa thành
`warn` với hướng dẫn nêu rõ ràng buộc thật.

Cả dự án đều giới hạn 3.10–3.12 (`doctor.py`, `setup_vsr.py`, `build_exe.py`,
`workers_setup.py` với chú thích "3.13+ chưa có wheel cho onnxruntime/
ctranslate2 nên KHÔNG được chọn"), nhưng `requires-python = ">=3.10"` không có
chặn trên. `pip install -e .` trên Python 3.13 vẫn thành công, để app chạy trên
interpreter mà chính Doctor báo lỗi:

```
Python runtime: Python 3.13 không nằm trong dải hỗ trợ 3.10–3.12.
```

Ghi chú: đoạn vừa rồi giữ nguyên để lưu diễn biến; hai gạch đầu ở mục B là kết
luận sau khi kiểm tra kỹ hơn.

### C. ~~DeepSeek-OCR thiếu dependency~~ — đã loại, báo cáo sai

Lúc đầu tôi kết luận `setup_deepseek_ocr.py` thiếu `addict, matplotlib, requests`
vì `bootstrap-state.json` còn giữ nguyên traceback ImportError đó. Kiểm tra lại
nguồn hiện tại thì **ba gói đã được khai báo** trong `DEEPSEEK_PYTHON_PACKAGES`
(dòng 27–34), kèm cả bước smoke import đúng bộ đó.

Traceback cũ đến từ bản app đã cài đặt
(`%LOCALAPPDATA%\Programs\DubFlow\scripts\setup_deepseek_ocr.py`), tức là **xác
rác của một build trước**, không phải lỗi của mã trong repo. Không có gì để sửa;
người dùng chỉ cần chạy lại bước cài DeepSeek-OCR bằng bản hiện tại.

### D. Giới hạn môi trường, không phải lỗi ứng dụng

* Endpoint dịch trong `.env` (`13.220.34.185:20128`) không truy cập được từ máy
  này. Đã kiểm code path dịch bằng mock OpenAI-compatible local
  (`qa/mock_translate.py`): gộp lô, checkpoint, gọi `/v1/models`,
  `check_model` đều chạy đúng. Dịch thật qua mạng công khai **chưa** kiểm.
* Video YouTube lớn (679 MB) bị `HTTP Error 403`; video ngắn tải bình thường.
  Bilibili/Douyin/TikTok chưa kiểm (cần cookies).
* RAM trống thấp có lúc xuống 0.7 GB, governor hạ TTS về 1 luồng — hành vi đúng
  thiết kế. Khi RAM ~4 GB, hai worker VieNeu cùng khởi động bình thường.

## Dừng khẩn cấp: nguyên nhân và số liệu

Người dùng nói "làm video không có nút dừng", "bấm dừng vẫn chạy hết tiến trình".
Nút Dừng **có tồn tại** và sáng trong lúc chạy — vấn đề là nó không giết được
việc. Lý do: chỉ `merge_video` đi qua `cancel.run_registered()`. Mọi lời gọi
ffmpeg/AI khác dùng `subprocess.run`/`Popen` trần nên không nằm trong danh sách
mà `cancel_processes()` duyệt khi bấm Dừng.

Đã ghi danh: `audio.py` (7 lời gọi), `retime.py` (2), `ocr.py`, `vsr.py`,
`video2x.py`, `vision.py`, worker Whisper và Paraformer (`register_process` /
`unregister_process` quanh vòng đời `Popen`), và worker VieNeu.

Sửa luôn một lỗi thật trong `run_registered`: nó truyền thẳng `**kwargs` cho
`Popen`, nên mọi lời gọi có `check=False` vỡ với
`Popen.__init__() got an unexpected keyword argument 'check'`. Giờ `check` được
bóc ra và tự xử lý theo đúng ngữ nghĩa `subprocess.run`.

Đo lại bằng `qa/cancel_review.py` (bấm Dừng đúng lúc bước bắt đầu, đếm ffmpeg còn
sống):

| Điểm bấm Dừng | Trước | Sau |
| --- | --- | --- |
| giữa `merge_audio` | 7.1 s | **0.1 s** |
| giữa xuất video | 0.1 s | 0.1 s |
| giữa bước TTS | không dừng được (bước không phát `start`, worker không ghi danh) | **10.1 s** |

Còn ~10 s ở TTS là một lần nạp model đang chạy dở — pipeline chỉ kiểm tra hủy
giữa các câu. Chấp nhận được, đã ghi nhận chứ không đào thêm.

## Video lớn: đã đo thật

Trước đây mọi thử nghiệm chỉ ở video 5 giây. Đã dựng hai video dài có lời thật
(do TTS sinh) rồi chạy hết chuỗi bằng `qa/long_video_review.py`:

| Độ dài | Tổng thời gian | Số câu | Video ra | Thư mục dự án |
| --- | --- | --- | --- | --- |
| 10 phút | 9.8 phút | 89 | 600 s, h264 + aac | 204 MB |
| 30 phút | 22.6 phút | 294 | 1800 s, h264 + aac | 727 MB |

Cả hai đều `completed`, không timeout, không sập. Kiểm chất lượng đầu ra:

* `volumedetect` trên video 30 phút: mean −17.9 dB, max −1.3 dB — có tiếng thật,
  không phải khe im lặng.
* Phủ hết băng thời gian: `total_original_duration` 1713.9 s / 1800 s (95 %,
  phần còn lại là khe im trong file nguồn), cue phụ đề cuối ở 00:29:33.
* Không có hiện tượng cắt ngắn hay dồn clip.

Đường cong tuyến tính: ~24 MB mỗi phút cho thư mục dự án, phần lớn là WAV trung
gian (`audio_vi_full.wav` 162.9 MB cho 30 phút). Ngoại suy: 1 giờ ~1.4 GB,
2 giờ ~2.8 GB, 5 giờ ~7.1 GB — chưa tính video tải về.

Trần timeout tỷ lệ theo thời lượng nên không phải nút thắt: ffmpeg = 4× media
(30 phút → chờ 120 phút), ASR = 12× media (30 phút → chờ 6 giờ). Con số "5-hour
invariant" trong `STATE.md` chỉ là kiểm tra phép tính đó, chưa ai chạy thật 5 giờ.

Cần lưu ý, chưa phải lỗi:

* `preflight` chỉ warn dưới 10 GB trống, fail dưới 2 GB. Ở mốc 5 giờ (~7 GB chưa
  tính video nguồn) người dùng ổ chặt vẫn được đi tiếp.
* Chậm nhất là ASR: 30 phút audio mất ~21 phút nghe trên GPU 4 GB — chi phí
  Whisper medium, không phải lỗi quản lý.
* `merge_video` lượt 30 phút chiếm 108.9 s ở `subtitle_mode=none` (stream-copy),
  siêu tuyến tính so với 21.6 s của lượt 10 phút. Chưa giải thích được, nên xem
  lại trước khi làm video 2 giờ.

Chưa kiểm: video ≥ 1 giờ, và video lớn tải từ mạng (YouTube 679 MB từng trả 403).

## Hiệu năng: "lâu kinh" đi đâu

`_tick()` chỉ được gọi ở `acquire` và `ocr`, nên log quảng bá đo từng bước nhưng
im lặng đúng chỗ chậm nhất. Đã thêm mốc cho `extract / asr / translate / tts /
merge_audio / merge_video`.

Đo một lượt hoàn chỉnh, video 5 giây, không cache (`qa/timing_single.py`):

| Bước | Trước | Sau |
| --- | --- | --- |
| TTS | 16.6 s | **8.8 s** |
| xuất video | 6.8 s | **2.0 s** |
| **tổng** | **45.1 s** | **32.8 s** (−27%) |

Ba nguyên nhân, đã sửa cả ba:

1. **Thăm dò logo nguồn gọi Ollama vô ích.** `branding_vision_enabled` mặc định
   `True`, và `detect_logo_region_video` giải mã 3 khung hình **trước khi** biết
   có Ollama hay không — 6.5 s chết mỗi lượt xuất trên máy không cài Ollama. Thêm
   `ollama_available()` (trần 1.5 s) chặn trước.
2. **Nạp model giọng đọc không nằm chờ ai.** VieNeu mất ~14 s nạp model và trước
   đây chỉ bắt đầu **sau** lúc nghe xong. VieNeu chạy CPU, không tranh VRAM với
   Whisper, nên đã gọi `_warm_tts_early()` ngay trước bước ASR để hai việc chồng
   lên nhau; Bước 5 dùng lại đúng pool đã nóng.
3. **Worker thứ hai nạp model theo kiểu xếp hàng.** `warm_up_async` vẫn giữ
   `_start_lock` tuyệt đối, nên "song song" trên giấy: N worker là N × 13 s. Giờ
   khóa chỉ chặn khi RAM trống không đủ cho cả nhóm (`_ram_allows_parallel`, giữ
   nguyên hành vi tuần tự trên máy thiếu RAM).

## Những gì đã xác minh dùng được

### Xử lý hàng loạt

Đã chạy thật, không chỉ unit test (29 test batch cũ thì 21 cái dùng pipeline giả):

* Hai video một lượt (1 tệp trên máy + 1 URL YouTube) đều `success`.
* Tải trước video kế tiếp chạy thật: `_prefetch/1/jNQXAC9IVRw.mp4` xuống xong
  trong lúc video đầu đang xử lý.
* Chạy lại: `skipped=2` — không làm lại video đã xong.
* `retry_done=True`: làm lại đúng video đã xong (`success=1 skipped=0`).
* Một video chờ dịch tay: lượt đầu `pending=1 failed=0` (không bị tính là lỗi),
  điền `transcript_vi.json` xong thì lượt sau `success=1`.
* Bấm Dừng giữa batch: video đang chạy ghi `'processing'`, video chưa chạy không
  bị tính `failed`. Chạy lại thì tự hồi: `skipped=1 success=1`, trạng thái cuối
  đều `success`.
* `AUTO_CLEAN_INTERMEDIATES=true` + batch: `success=1`.

Đã bổ sung 17 test hồi quy cho hai chỗ trước đây không có guard nào:

* `_Prefetcher` (10 test) — chưa từng có test nào dù vừa đụng mạng vừa đụng dọn
  tệp: tải lỗi phải suy về `None` chứ không phá cả batch, `adopt` chuyển được
  `video_meta.json` vào `data/` và không đè bản đã có, `cleanup` không để sót
  tệp, executor vẫn giữ đúng trần số luồng tải song song.
* `BatchWorker` nhánh GUI (7 test) — lớp người dùng thật bấm, trước đây **không
  có test nào**: nối đúng SynthCache / DemucsCache / WhisperCache theo số video
  và theo `reuse_tts`, đóng cache ở `finally`, `PipelineCancelled` phát
  `cancelled` chứ không phải `failed`, lỗi một video chỉ là một dòng "Lỗi" trên
  bảng, giọng theo từng dòng thắng template.

Còn để trống: batch nhiều video qua GUI thật trên máy chủ, và batch có Bilibili /
TikTok cần cookie.

**Pipeline thật, đủ chuỗi** (tải/nhận video → OCR → tách tiếng → ASR → dịch →
TTS → hậu kỳ → trộn → xuất → metadata):

* Whisper chạy GPU thật: `large-v3`/`medium` trên CUDA, `float16` rồi
  `int8_float16` khi thiếu VRAM — nhờ bản vá cublas64_12 trước đó.
* Xuất video NVENC, có cả stream `video` + `audio` + `subtitle` (mov_text).
* Resume không nghe lại ASR (47 s so với 102 s chạy đầu).
* Dịch tay: tắt dịch tự động → `translate_pending` + `TRANSLATE_PENDING.txt` →
  điền `transcript_vi.json` → resume hoàn tất.
* Batch 2 mục (1 tệp + 1 URL YouTube) đều success; chạy lại skip đúng 2 mục.
* Editor: sửa câu, phụ đề riêng không đụng lời đọc, đọc lại 1 câu, dựng lại video
  (7 s), xuất chỉ phụ đề (9 s) — phụ đề ra đúng bản sửa riêng.
* OpenClaw: mọi endpoint trả 401 khi thiếu Bearer token; `/health`,
  `/v1/prepare` hoạt động với token; nút kiểm tra kết nối trong app báo thành công.
* Cài đặt: vòng ghi/đọc `.env` giữ nguyên khóa khác và dòng chú thích.
* 7 preset phụ đề normalize hợp lệ, 174 giọng đọc trong danh mục, giọng mặc định
  nằm trong danh mục.

## Cách chạy lại

```powershell
.venv\Scripts\python.exe qa\gui_walkthrough.py
.venv\Scripts\python.exe qa\e2e_review.py        # ~7 phút, cần model đã cài
.venv\Scripts\python.exe qa\features_review.py   # cần qa/runs có dự án
.venv\Scripts\python.exe qa\editor_review.py
.venv\Scripts\python.exe -m pytest tests -q
```

`qa/` **không** có trong `.gitignore`, nên nó hiện là untracked trong
`git status`. Muốn giữ lâu dài thì thêm `qa/` vào `.gitignore`; muốn dọn thì
xóa thư mục là hết, vì không có tệp tracked nào thuộc phạm vi rà soát nằm ở đây.
