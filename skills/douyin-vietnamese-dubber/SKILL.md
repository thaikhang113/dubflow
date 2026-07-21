---
name: douyin-vietnamese-dubber
description: Nhận video local hoặc link Douyin/TikTok, tạo phụ đề gốc original.srt bằng whisper.cpp, dịch sang vietnamese.srt, tạo lồng tiếng Việt vietnamese_voice.wav bằng edge-tts, và ghép thành final_video_vi.mp4. Dùng khi người dùng muốn tạo phụ đề tiếng Việt, lồng tiếng Việt, hoặc xử lý video Douyin/TikTok Trung Quốc sang tiếng Việt.
---

# Skill: douyin-vietnamese-dubber

Skill này ưu tiên xử lý **video local**. Douyin/TikTok link được hỗ trợ ở mức tải an toàn; nếu gặp login/captcha/block thì dừng rõ ràng, không crash.

## Khi nào dùng

Dùng khi người dùng nói:
- `tạo phụ đề tiếng Việt cho video này`
- `lồng tiếng Việt video này`
- `dịch video Douyin sang tiếng Việt`
- `tìm video Douyin về [chủ đề], tải về và lồng tiếng Việt`
- `tạo phụ đề tiếng Việt cho video tôi vừa gửi`
- `tải video này và tạo thumbnail YouTube`
- `tải video thứ 3, giọng nam/nữ, tạo thumbnail`

## Input

- Video local: `/path/to/video.mp4`
- Link Douyin/TikTok: `https://www.douyin.com/video/...`
- Chủ đề Douyin cho wrapper: `mèo con`, `đồ ăn đường phố`, ...

## Output

Mỗi lần chạy tạo một thư mục con trong `${DOUYIN_VIDEOS_DIR:-$HOME/douyin-videos}`:

| File | Mục đích |
|---|---|
| `original.srt` | Phụ đề gốc từ Whisper |
| `original.raw.srt` | Bản Whisper trước lọc hậu xử lý nếu speech-only bật |
| `vietnamese.srt` | Phụ đề tiếng Việt đầy đủ hơn để hiển thị |
| `dub.srt` | Bản tiếng Việt ngắn hơn để tạo TTS khi optimizer bật |
| `asr_speech.wav` | Audio đưa vào Whisper, đã silence vùng music/non-speech |
| `vocals.wav` | Vocal stem từ Demucs hoặc fallback audio gốc |
| `no_vocals.wav` | Music bed/no-vocals stem để trộn nhỏ vào video cuối |
| `speech_regions.json` | Vùng được nhận diện là speech/dialogue |
| `speech_preprocess_report.json` | Report tách vocals/music và segmentation |
| `asr_postprocess_report.json` | Report lọc segment ASR ngoài vùng speech/lặp/vô nghĩa |
| `dubbing_report.json` | Báo cáo timing/rewrite/subtitle-only của optimizer |
| `dubbing_segments.json` | Chi tiết từng segment sau tối ưu |
| `speed_report.csv` | Báo cáo tốc độ từng câu/segment TTS |
| `tts_alignment_report.json` | Báo cáo fit audio, overhang, action/quality flag từng câu |
| `vietnamese_voice.wav` | Audio lồng tiếng Việt từ `edge-tts` |
| `final_video_audio_only.mp4` | Video đã ghép audio tiếng Việt trước khi burn-in sub |
| `final_video_vi.mp4` | Video final đã ghép audio, làm mờ dải sub Trung gốc và chèn sub Việt |
| `thumbnail.jpg` | Thumbnail YouTube do AI tạo qua Google Flow trên Chrome thật (hoặc fallback local) |
| `thumbnail_reference.jpg` | Ảnh hero reference (frame nhân vật rõ nhất), cũng là legacy reference |
| `thumbnail_story_analysis.json` | Phân tích story (core_plot, main_character, main_conflict, clickable_angles) |
| `thumbnail_hook_selected.json` | Hook tiếng Việt đã chọn (top-5, có reason + selected_angle) |
| `thumbnail_character_selected.json` | Hero + support references + fallback_reason |
| `thumbnail_image_plan.json` / `thumbnail_image_prompt.json` | Plan + prompt ảnh cho Flow (cấm chữ, yêu cầu negative space) |
| `thumbnail_text_plan.json` | Plan chèn chữ Việt local (line_breaks, text_box, emphasis_word) |
| `thumbnail_quality_report.json` | Quality gate 0-10 + status (pass/warning/failed_fallback_used/needs_attention) |
| `thumbnail_layout.json` | Layout vùng chữ an toàn, tránh che chủ thể |
| `thumbnail_vision_analysis.json` | Phân tích vision/reference nếu local vision runtime sẵn sàng |
| `final_metadata.json` | Metadata tên phim/tập và đường dẫn thư viện gọn |
| `log.txt` | Nhật ký chạy pipeline, không chứa secret |
| `audio.wav` | Audio WAV 16kHz mono tách từ video |
| `input.mp4` | Video đầu vào đã copy/tải về |

## Preflight / Doctor

Luôn chạy doctor trước khi debug môi trường:

```bash
bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/run.sh --doctor
```

Doctor check và in rõ `OK`/`FAIL` cho:
- `ffmpeg`
- `python3`
- `curl`
- `yt-dlp`
- `edge-tts`
- `WHISPER_BIN`
- `WHISPER_MODEL`
- `NINEROUTER_API_BASE`
- API key 9Router, giá trị luôn bị ẩn
- output dir writable

## Cấu hình runtime

## Vietnamese Dub Timing Optimizer

- Mặc định bật `VIET_DUB_TIMING_OPTIMIZER=1` để tránh giọng Việt bị ép quá nhanh.
- Optimizer chạy sau `original.srt` và trước `edge-tts`; không can thiệp Douyin/CDP/cookie/link die/downloader.
- Khi bật, pipeline tạo `vietnamese.srt` để làm phụ đề đầy đủ hơn và `dub.srt` để TTS đọc ngắn, tự nhiên hơn.
- Giới hạn tốc độ theo brief: `TARGET_MAX_SPEED=1.25`, `SOFT_MAX_SPEED=1.35`, `HARD_MAX_SPEED=1.50`, `HARD_MAX_DURATION=3.0`.
- Không tăng tốc global toàn file; fit theo từng nhóm câu. Nếu câu quá dài, ưu tiên rewrite/rút gọn/merge timing thay vì cắt ngang audio.
- Optimizer giữ nhóm câu liền mạch thành một timing group khi các segment gốc quá vụn để tránh lỗi đang nói dở bị cắt sang câu khác.
- Video gốc là master timeline: không kéo/chậm/freeze video final để chờ TTS; audio Việt phải được đặt theo timestamp SRT, pad/trim audio theo duration video gốc, rồi kiểm tra duration bằng `timeline_duration_report.json`.
- `ALLOW_AUDIO_OVERHANG` mặc định là `0.6` giây. TTS không clip ngang câu sau khi speed-fit; segment quá dài sẽ được ghi vào `tts_alignment_report.json`/`speed_report.csv` để vòng sau rewrite tốt hơn.
- Nếu model/API hụt hơi ở batch dịch lớn (`502`, timeout, JSON cụt, thiếu item), optimizer tự retry batch nhỏ hơn trước khi fallback từng câu/flow cũ; lỗi vẫn được ghi vào `dubbing_report.json`/`log.txt`.

Tắt optimizer khi cần so sánh flow cũ:

```bash
VIET_DUB_TIMING_OPTIMIZER=0 bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/run.sh "https://www.douyin.com/video/..."
```

Các biến chỉnh nhanh:

```bash
MAX_TTS_SPEED=1.2
TARGET_MAX_SPEED=1.25
SOFT_MAX_SPEED=1.35
HARD_MAX_SPEED=1.50
HARD_MAX_DURATION=3.0
REWRITE_IF_RATIO_ABOVE=1.2
SUBTITLE_ONLY_IF_RATIO_ABOVE=1.45
MAX_REWRITE_ATTEMPTS=3
MIN_SEGMENT_DURATION=1.2
MERGE_GAP_UNDER=0.45
ALLOW_AUDIO_OVERHANG=0.6
OPTIMIZER_TRANSLATE_BATCH_SIZE=20
OPTIMIZER_TRANSLATE_MIN_BATCH_SIZE=1
```

## Burn-in phụ đề Việt và che sub Trung

- Mặc định bật `BURN_VIET_SUBTITLE=1` và `MASK_ORIGINAL_SUBTITLE=1`.
- Sau khi ghép audio, pipeline tạo `final_video_audio_only.mp4`, rồi render `final_video_vi.mp4` bằng `subtitle_mask_render.py`.
- Mặc định `SUBTITLE_MASK_STYLE=blur_band`: sample thưa vài frame, dùng CV/OCR để tìm vị trí hàng sub Trung phổ biến, rồi blur một dải ngang cố định toàn khung hình. Không track từng chữ/từng frame trong đường mặc định.
- OCR transcript vẫn chạy riêng để cứu transcript khi ASR lỗi; thay đổi này chỉ áp dụng ở bước render final.
- `subtitle_mask_render.py` ghi debug report `final_video_vi.subtitle_band.json` gồm vị trí `y`, `height`, số mẫu detect được và trạng thái fallback.
- Phụ đề Việt mặc định màu vàng, căn giữa trong dải blur. Nếu detect không đủ mẫu, fallback về một dải ngang gần đáy, không kéo đen từ đáy lên.
- Rollback flow cũ bằng `SUBTITLE_MASK_STYLE=legacy_box`; bỏ che sub gốc bằng `SUBTITLE_MASK_STYLE=none` hoặc `MASK_ORIGINAL_SUBTITLE=0`.
- Config chính:

```bash
BURN_VIET_SUBTITLE=1
MASK_ORIGINAL_SUBTITLE=1
SUBTITLE_MASK_STYLE=blur_band
SUBTITLE_BAND_SAMPLE_COUNT=16
SUBTITLE_BAND_REGION_TOP_RATIO=0.55
SUBTITLE_BAND_REGION_BOTTOM_RATIO=0.96
SUBTITLE_BAND_HEIGHT_RATIO=0.10
SUBTITLE_BAND_MIN_HEIGHT=44
SUBTITLE_BAND_BLUR=18
SUBTITLE_BAND_TINT_OPACITY=0.12
SUBTITLE_TEXT_COLOR=yellow
SUBTITLE_TEXT_ALIGN=band_center
SUBTITLE_FONT=/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf
SUBTITLE_FONT_SIZE_RATIO=0.045
SUBTITLE_OUTLINE=3
```

- Nếu render subtitle lỗi, script giữ `final_video_audio_only.mp4` làm `final_video_vi.mp4` và ghi WARN, không làm mất video.

## Speech-only preprocess chống dịch nhầm nhạc/lời bài hát

- Mặc định bật `SPEECH_ONLY_PREPROCESS=1`; tắt bằng `SPEECH_ONLY_PREPROCESS=0` để quay về flow cũ.
- Pipeline không đưa trực tiếp audio gốc vào Whisper nữa khi preprocess OK.
- Trước ASR, script extract `audio.wav`, chạy Demucs `--two-stems=vocals` để tạo `vocals.wav` và `no_vocals.wav` nếu máy có Demucs.
- Sau đó dùng `inaSpeechSegmenter` nếu có; nếu thiếu thì fallback energy VAD để tìm vùng speech/dialogue.
- `asr_speech.wav` giữ timeline gốc nhưng silence vùng music/noise/singing/non-speech để Whisper không dịch nhầm nhạc nền hoặc lời bài hát.
- Sau Whisper, `postprocess_asr_srt.py` lọc segment nằm ngoài vùng speech, lặp chữ nhiều, quá ngắn/vô nghĩa.
- Video cuối giữ music bed/no_vocals nhỏ nếu `KEEP_ORIGINAL_MUSIC_BED=true`, volume mặc định `MUSIC_BED_VOLUME=0.18`.

Config mặc định:

```bash
SUBTITLE_MODE=dialogue_only
IGNORE_BACKGROUND_MUSIC=true
IGNORE_SONG_LYRICS=true
KEEP_ORIGINAL_MUSIC_BED=true
SPEECH_ONLY_PREPROCESS=1
SPEECH_ONLY_DEMUCS=1
SPEECH_SEGMENTATION_BACKEND=auto
SPEECH_ONLY_TIMEOUT_SECONDS=1800
MUSIC_BED_VOLUME=0.18
```

Nếu sau này đổi sang `faster-whisper`, phải bật `vad_filter=True`, `condition_on_previous_text=False` và lưu `confidence`/`no_speech_prob`/`avg_logprob` từng segment để hậu xử lý lọc thêm theo xác suất.

## Sắp xếp output gọn như thư viện phim

- Mặc định bật `ORGANIZE_OUTPUT=1` sau khi video/thumbnail hoàn tất.
- Job gốc `video-YYYY...` vẫn giữ nguyên để debug; không xóa `audio.wav`, `dub.srt`, report, log.
- File dễ mở cho người dùng được copy sang:

```bash
/mnt/hdd500/video douyin vietsub/Phim đã xử lý/<Tên Phim>/<Tên Phim - Tập 01>.mp4
```

- File đi kèm trong cùng thư mục gồm thumbnail, vietsub, dub subtitle, log, metadata.
- Root output có pointer dễ tìm:
  - `VIDEO_MOI_NHAT.mp4`
  - `THUMBNAIL_MOI_NHAT.jpg`
- Khi báo kết quả cho user, ưu tiên `organized_video` trong `final_metadata.json` hoặc dòng log `organized_video:` thay vì bắt user tự mở thư mục `video-YYYY...`.
- Có thể truyền tên/tập từ môi trường nếu user nói rõ:

```bash
FINAL_VIDEO_TITLE="Viễn Cổ Thú Thần" FINAL_EPISODE_RANGE="01-04" bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/run.sh "URL"
```

- Nếu không chắc tên phim/tập, script fallback tên `Video Douyin - YYYY-MM-DD HH-MM` và `Tập 01`.

## Thumbnail YouTube tự động

- Mặc định sau khi tạo xong `final_video_vi.mp4`, pipeline tự gọi skill `google-flow-thumbnail` để tạo `thumbnail.jpg`.
- Thumbnail skill chạy pipeline sáng tạo: phân tích story + ideate hook (qua Ollama local) → chọn hero reference từ nhiều frame (CV + vision) → sinh image plan/prompt cấm chữ → Flow tạo ảnh nền → chèn chữ Việt local theo text plan → quality gate.
- OpenClaw không cần tự viết prompt ảnh hay hook: thumbnail script tự đọc `vietnamese.srt`, `original.srt`, `source_input.txt`, `final_metadata.json` để sinh `thumbnail_story_analysis.json`, `thumbnail_hook_selected.json`, `thumbnail_image_plan.json`, `thumbnail_text_plan.json` và `thumbnail_prompt.txt`/`thumbnail_title.txt`.
- Thumbnail script sẽ tạo `thumbnail_reference.jpg` (hero frame rõ nhân vật nhất) và `thumbnail_layout.json` để bám bố cục gốc, chọn vùng chữ an toàn.
- Nếu local vision runtime/model có sẵn, thumbnail script tạo thêm `thumbnail_vision_analysis.json` để mô tả nhân vật/bố cục/vùng cần tránh; nếu thiếu model thì fallback heuristic, không fail pipeline. Nếu Ollama creative unavailable, script fallback heuristic story/hook (có `fallback_reason`), không quay lại keyword table cũ.
- Google Flow chỉ tạo ảnh nền/nhân vật; chữ tiếng Việt được chèn local bằng renderer an toàn, nên không bị đổi sang tiếng Anh và giảm che đầu/mặt nhân vật.
- Có thể tắt bằng `AUTO_THUMBNAIL=0` nếu người dùng yêu cầu chỉ làm video.
- Nếu Google Flow lỗi/login/captcha/quota/UI đổi, video vẫn hoàn tất; lỗi được ghi vào `google_flow_thumbnail.log` và `google_flow_debug/`.

Khi người dùng nhắc “tạo thumbnail”, “thumbnail YouTube”, hoặc không nói rõ nhưng đang làm video đăng YouTube, giữ mặc định `AUTO_THUMBNAIL=1`.

## Cấu hình runtime

Nếu runtime còn thiếu dependency, có thể dùng helper setup:

```bash
bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/setup-runtime.sh
```

Script này cài `ffmpeg`, `edge-tts`, và dựng `whisper.cpp` + model `small` khi runtime cho phép.


Không hard-code secret. Dùng env khi runtime khác nhau:

```bash
export WHISPER_DIR="$HOME/whisper.cpp"
export WHISPER_BIN="$WHISPER_DIR/build/bin/whisper-cli"
export WHISPER_MODEL="$WHISPER_DIR/models/ggml-small.bin"
export NINEROUTER_API_BASE="http://127.0.0.1:20128/v1"
export NINEROUTER_API_KEY="..."        # ưu tiên, không ghi vào log
# hoặc:
export NINEROUTER_DB_PATH="$HOME/.9router/db.json"
```

Default API base:
- host Linux: `http://127.0.0.1:20128/v1`
- container Docker: `http://172.19.0.1:20128/v1`

Nếu Docker network khác, đặt `NINEROUTER_API_BASE` thủ công.

## Local video flow ưu tiên

```bash
bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/run.sh "/path/to/video.mp4"
```

Pipeline:
1. Copy video local vào output dir.
2. FFmpeg tách audio WAV 16kHz mono.
3. Speech-only preprocess tách vocals/music và tạo `asr_speech.wav` chỉ còn dialogue/speech trên timeline gốc.
4. `whisper-cli` tạo `original.srt` từ `asr_speech.wav`, rồi lọc hậu xử lý theo `speech_regions.json`.
5. Chạy Vietnamese Dub Timing Optimizer qua 9Router để tạo `vietnamese.srt`, `dub.srt`, `dubbing_report.json`.
6. `edge-tts` đọc `dub.srt`, giới hạn speed tối đa `MAX_TTS_SPEED`, rồi ghép thành `vietnamese_voice.wav`.
7. FFmpeg ghép audio Việt + music bed/no_vocals nhỏ vào `final_video_audio_only.mp4`.
8. Detect vị trí hàng sub Trung, render dải blur ngang + burn-in sub Việt thành `final_video_vi.mp4`.
9. Tạo `thumbnail.jpg` bằng `google-flow-thumbnail` qua Chrome thật/CDP + Google Flow; lỗi thumbnail chỉ ghi WARN, không làm fail video.
10. Sắp xếp bản final vào `Phim đã xử lý` với tên tiếng Việt dễ đọc và tạo `VIDEO_MOI_NHAT.mp4`.

## Thumbnail YouTube tự động

Sau khi video hoàn tất, skill mặc định tự tạo một thumbnail duy nhất:

```bash
thumbnail.jpg
```

Cơ chế:
- đọc `vietnamese.srt`, `original.srt`, `source_input.txt`, `final_metadata.json`
- phân tích story + ideate/chọn hook tiếng Việt qua Ollama local (`thumbnail_story_analysis.json`, `thumbnail_hook_selected.json`); Ollama lỗi → fallback heuristic
- lấy `thumbnail_reference.jpg` (hero frame) từ nhiều frame sample trong `input.mp4`/`final_video_vi.mp4`, chấm CV + 1 vision call (`thumbnail_character_selected.json`)
- sinh `thumbnail_image_plan.json`/`thumbnail_prompt.txt` cấm chữ, yêu cầu negative space theo text plan
- sinh `thumbnail_text_plan.json` và phân tích `thumbnail_layout.json` để chèn chữ ở vùng an toàn
- gọi Chrome thật qua CDP và thao tác Google Flow bằng Gmail Google Pro đã đăng nhập thủ công; best-effort upload reference (nếu có UI), không thì `reference_prompt_only`
- quality gate `thumbnail_quality_report.json`; nếu fail vì lý do sửa được, retry Flow tối đa 1 lần
- không dùng 9Router, chatgpt2api, hay OpenAI image API cho bước tạo ảnh này
- lưu `thumbnail.jpg` trong output dir
- cập nhật `LATEST_THUMBNAIL.txt` ở thư mục gốc output

Tắt tự tạo thumbnail nếu cần:

```bash
AUTO_THUMBNAIL=0 bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/run.sh "https://www.douyin.com/video/..."
```

Tạo thumbnail riêng cho job đã có:

```bash
bash ~/.openclaw/workspace/skills/google-flow-thumbnail/google-flow-thumbnail.sh "/mnt/hdd500/video douyin vietsub/OUTPUT_JOB_DIR"
```

## Douyin flow

### Chạy qua host runner khi ở OpenClaw/Docker

Nếu đang ở trong container OpenClaw, ưu tiên gọi host runner thay vì chạy pipeline multimedia trực tiếp trong container:

```bash
/home/node/host-bin/openclaw-host-douyin-runner.sh run-douyin "https://www.douyin.com/video/..."
```

Nếu người dùng yêu cầu giọng nói:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh run-douyin "https://www.douyin.com/video/..." nam
/home/node/host-bin/openclaw-call-host-runner.sh run-douyin "https://www.douyin.com/video/..." nu
```

Lưu ý quan trọng khi chạy từ OpenClaw/container:

- `run-douyin` chạy trên **host**, không chạy trong container; không được kết luận lỗi chỉ vì `ps` trong container không thấy `ffmpeg`, `whisper`, `edge-tts`.
- Host runner trả `queued: true`, `job_id`, `request`, `log`; phải đọc log host trong `/mnt/hdd500/video douyin vietsub/host-runner-queue/logs/` hoặc pointer `LATEST_OUTPUT_DIR.txt` để theo dõi.
- Queue chạy tuần tự; nếu có job đang chạy, job sau sẽ chờ lock thay vì fail ngay.
- Không queue lại cùng URL nhiều lần nếu job đang chạy/chờ, trừ khi người dùng yêu cầu rõ ràng.
- Chỉ báo hoàn tất khi `final_video_vi.mp4` thật sự tồn tại trong output dir và log có `HOÀN TẤT`.

Preset giọng:
- `nam` / `giọng nam` → `vi-VN-NamMinhNeural`
- `nu` / `nữ` / `giọng nữ` → `vi-VN-HoaiMyNeural`

Nếu người dùng không nói giọng nào, mặc định dùng `nu`.

Host runner tương ứng trên máy chủ:

```bash
/home/haonguyen/.local/bin/openclaw-host-douyin-runner.sh
```

Quy tắc an toàn:
- Chỉ dùng action whitelist: `run-douyin`, `latest-output`, `latest-source`, `send-latest-telegram`, `doctor`.
- Không tạo lệnh xóa file qua runner.
- Không sửa/xóa file nhạy cảm như `.9router/db.json`, Chrome profile, Docker volume, OpenClaw config nếu người dùng không yêu cầu rõ ràng.
- Nếu cần dọn file cũ, phải hỏi lại người dùng bằng tên file/thư mục cụ thể trước.

Với link trực tiếp:

```bash
bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/run.sh "https://www.douyin.com/video/..."
```

Chọn giọng trực tiếp trên host:

```bash
EDGE_TTS_VOICE_PRESET="nam" bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/run.sh "https://www.douyin.com/video/..."
EDGE_TTS_VOICE_PRESET="nu" bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/run.sh "https://www.douyin.com/video/..."
```

Với chủ đề tìm kiếm qua `douyin-stealth`:

```bash
bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/douyin-to-vietsub.sh "CHU_DE"
```

`douyin-to-vietsub.sh`:
- tự dò container gateway OpenClaw hoặc dùng `OPENCLAW_CONTAINER`
- gọi `douyin-stealth` để tìm link
- nếu gặp `CAPTCHA_WAIT`, `QR_LOGIN`, `NOT_LOGGED_IN`, `CDP_OFFLINE`, `EXTRACTOR_*`, `SEARCH_TIMEOUT` thì dừng an toàn và báo lỗi rõ
- không cố vượt captcha/login/block

### Quy tắc bắt buộc khi người dùng nói “video thứ N”

- Phải nhắc lại **đúng URL cụ thể** của video thứ N trước khi chạy.
- Phải truyền **URL đó trực tiếp** vào `run.sh`; không được chỉ nói chung chung “video thứ 3”.
- Chỉ được báo “đã tải/đã việt sub xong” sau khi `final_video_vi.mp4` thật sự tồn tại.
- Khi báo hoàn tất, phải kèm:
  - URL nguồn đã xử lý
  - thư mục output
  - đường dẫn file `final_video_vi.mp4`

Mỗi lần chạy, `run.sh` sẽ tự ghi:
- `source_input.txt` trong thư mục output của job
- `LATEST_SOURCE_URL.txt` ở thư mục gốc output
- `LATEST_OUTPUT_DIR.txt` ở thư mục gốc output

Nhờ vậy có thể đối chiếu ngay video mới nhất có đúng link người dùng yêu cầu hay không.

## Telegram result sender

Nếu cần gửi lại kết quả qua Telegram:

```bash
TELEGRAM_CHAT_ID="CHAT_ID" \
TELEGRAM_BOT_TOKEN="TOKEN_OR_CONFIGURED_ENV" \
bash ~/.openclaw/workspace/skills/douyin-vietnamese-dubber/telegram-send-result.sh "OUTPUT_DIR"
```

`telegram-send-result.sh` không echo token. Nếu giữ raw Telegram Bot API bằng `curl`, không bật `set -x` và không log URL/token.

## Xử lý lỗi

- Chạy `bash run.sh --doctor` trước.
- Nếu thiếu Whisper trong container, chạy `setup-runtime.sh`, hoặc mount/cài `whisper.cpp` vào container, hoặc chạy skill trên host có đủ dependency.
- Nếu API không connect được, đặt `NINEROUTER_API_BASE` đúng theo runtime.
- Nếu Douyin bị login/captcha/block, dừng và báo rõ; không crash, không retry vô hạn.
