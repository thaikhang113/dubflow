---
name: bilibili-vietnamese-dubber
description: Xác định video/tập Bilibili cụ thể bằng Chrome CDP đã đăng nhập, rồi tạo phụ đề tiếng Việt, lồng tiếng Việt, burn-in sub, thumbnail Google Flow. Dùng khi người dùng muốn xử lý video Bilibili sang tiếng Việt hoặc đã có tên/tập/BVID/URL cụ thể.
---

# Skill: bilibili-vietnamese-dubber

Dùng skill này khi người dùng đã nêu video/tập cụ thể hoặc muốn xử lý video Bilibili, ví dụ:
- `tìm đúng tập 1 của <tên phim> để vietsub`
- `tải video Bilibili này và vietsub tiếng Việt`
- `video thứ 3 Bilibili giọng nam tạo thumbnail`
- `lồng tiếng Việt video Bilibili`

## Phân luồng bắt buộc

- Với yêu cầu khám phá/gợi ý chung như “tìm anime AI Bilibili”, “tìm series có cốt truyện dài”, “video đang hot” hoặc “cho tôi link để xem”, phải dùng `ai-anime-trend-scout` trước. Không dùng `bilibili-find` như fallback discovery.
- Chỉ dùng `bilibili-find` để xác định video có tên/tập đã biết khi người dùng có ý định tải, vietsub hoặc xử lý video đó.
- `bilibili-find-episodes` vẫn là đường đúng khi người dùng nêu rõ số tập của một series/tên đã biết.

## Nguyên tắc

- Dùng Chrome thật qua CDP tại `127.0.0.1:9222`; user phải đăng nhập Bilibili thủ công trước.
- Không bypass captcha/OTP/login. Nếu Bilibili yêu cầu xác minh, báo user xử lý trên Chrome thật.
- Không dùng/thay đổi downloader Douyin.
- Output lưu trên HDD trong `/mnt/hdd500/video douyin vietsub/Bilibili`.
- Pipeline vietsub/lồng tiếng/thumbnail tái dùng `douyin-vietnamese-dubber` sau khi đã tải `input.mp4`.

## Lệnh từ container/OpenClaw: xác định video để tải/vietsub

Tìm video/tập đã biết để xử lý:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh bilibili-find "từ khóa" 10
```

Chạy video:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh run-bilibili "https://www.bilibili.com/video/BV..." nam
/home/node/host-bin/openclaw-call-host-runner.sh run-bilibili "https://www.bilibili.com/video/BV..." nu
```

## Opt-in Cáo Một Phim branding

The normal `run-bilibili` path remains unbranded.  For a single branded job, set
`BILIBILI_BRANDING=1` explicitly; the optional approved clips are independently
validated with `BILIBILI_BRAND_INCLUDE_INTRO=1` and/or
`BILIBILI_BRAND_INCLUDE_OUTRO=1`.  The stage blurs the full fixed top-left Chinese
uploader text plus bilibili mark, overlays the approved circular logo, and runs
before organize/Telegram delivery.  Intro/outro are added once around the job
video, never per scene.  Clip flags without `BILIBILI_BRANDING=1` fail closed.

```bash
BILIBILI_BRANDING=1 BILIBILI_BRAND_INCLUDE_INTRO=1 BILIBILI_BRAND_INCLUDE_OUTRO=1 \
  bash ~/.openclaw/workspace/skills/bilibili-vietnamese-dubber/run.sh "https://www.bilibili.com/video/BV..." nam
```

## Natural-language action: one Bilibili job

For a request such as “Xử lý link này bằng giọng Ngọc Huyền, che block uploader
và logo Bilibili góc trái trên, thay logo thương hiệu, có intro/outro”, first
present the job plan (URL, normalized voice, branding choices, and that it is a
large queued job). Only queue after the user confirms the plan.

Use the fixed JSON-only host action below. Do not turn user text into shell,
environment, path, model, or overlay-coordinate arguments. `branding` defaults to
off; all child flags default to `false`, and child flags are invalid unless
`enabled:true`. The only enabled profile is the approved fixed uploader block, so
the actual blur and approved logo replacement cannot be redirected by a chat.

```json
{
  "action": "bilibili-process",
  "url": "https://www.bilibili.com/video/BV...",
  "voice": "Ngọc Huyền",
  "branding": {
    "enabled": true,
    "profile": "bilibili_top_left_block",
    "blur_uploader_block": true,
    "replace_logo": true,
    "include_intro": true,
    "include_outro": true
  }
}
```

`Ngọc Huyền`, `Ngoc Huyen`, and `ngoc huyen` normalize to
`ai33:vbee_hn_female_ngochuyen_full_48k-fhg`. This action does not alter the
existing default voice. Its translation route/model is host-owned and retains the
existing Ollama route; the payload cannot choose it.

Xem output mới nhất:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh bilibili-latest-output
```

## Lệnh trên host

```bash
bash ~/.openclaw/workspace/skills/bilibili-vietnamese-dubber/run.sh --find "từ khóa" 10
bash ~/.openclaw/workspace/skills/bilibili-vietnamese-dubber/run.sh "https://www.bilibili.com/video/BV..." nam
bash ~/.openclaw/workspace/skills/bilibili-vietnamese-dubber/run.sh --doctor
```

## Output chính

- `input.mp4` trong job pipeline.
- `final_video_vi.mp4` video final có lồng tiếng Việt + che sub gốc + sub Việt burn-in.
- `thumbnail.jpg` thumbnail tạo qua Google Flow/fallback local.
- `source_platform.txt` = `bilibili`.
- `source_title.txt`, `bilibili_meta.json` để debug (meta non-secret).
- Cookie/session chỉ nằm trong cache download (`JOB_CACHE/bilibili_cookies.txt`), **không** copy vào job output.

Khi báo kết quả cho user, ưu tiên đường dẫn `organized_video` trong log hoặc `final_metadata.json`.

## Quan trọng khi chạy trong Telegram/container

Bot Telegram/OpenClaw chạy trong container có thể không có Python/Chrome CDP host. Vì vậy:

- Không chạy trực tiếp `run.sh` hoặc `scripts/bilibili_cdp.py` trong container.
- Luôn gọi host runner:
  - `/home/node/host-bin/openclaw-call-host-runner.sh bilibili-find "KEYWORD" 10` (chỉ để resolve video/tập đã biết cho job xử lý, không phải tìm trend/gợi ý)
  - `/home/node/host-bin/openclaw-call-host-runner.sh run-bilibili "VIDEO_URL" nam`
  - `/home/node/host-bin/openclaw-call-host-runner.sh monitor-add-bilibili "CHANNEL_OR_VIDEO_URL" "TEN_KENH"`
  - `/home/node/host-bin/openclaw-call-host-runner.sh monitor-remove-bilibili "TEN_KENH_OR_URL"`
- CDP `127.0.0.1:9222` chỉ cần reachable trên host; container không cần tự connect CDP.

## Tìm đúng theo số tập Bilibili

Khi người dùng nói số tập như `tập 0 đến 3`, `tập 1`, `video số 0-2`, hoặc `邪神墨然 0-3`, không dùng `bilibili-find` thường và không dùng web search làm nguồn chính.

Luôn dùng host runner đọc playlist/合集 đang mở trong Chrome CDP thật:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh bilibili-find-episodes "邪神墨然" "0-3"
/home/node/host-bin/openclaw-call-host-runner.sh bilibili-find-episodes "邪神墨然" "1,2,3"
/home/node/host-bin/openclaw-call-host-runner.sh bilibili-find-episodes "邪神墨然" "1"
```

Kết quả trả JSON có:

- `episode` / `requested_episode`
- `title`
- `url`
- `duration`
- `source=cdp_playlist`
- `confidence`
- `missing_episodes` nếu không thấy tập yêu cầu

Quy tắc bắt buộc:

- Nếu user yêu cầu tập đơn/đầu như `0-3`, hạ ưu tiên hoặc bỏ qua video có chữ `合集`, `尊享版`, `一口气`, `185-187`.
- Chỉ chọn compilation khi user có nói rõ `合集`, `hợp tập`, `một hơi`, `一口气`, hoặc `全集`.
- Nếu playlist CDP đọc được thì không tự thay bằng kết quả web/latest như tập 177 hoặc 185-187.
- Nếu không thấy tập trong playlist, báo rõ tập nào thiếu; không tự bịa link khác.
