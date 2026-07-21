---
name: google-flow-thumbnail
description: Tạo thumbnail YouTube bằng Google Flow trong Chrome thật qua CDP, dùng Gmail Google Pro đã đăng nhập thủ công. Dùng khi cần tạo thumbnail.jpg từ transcript/video output mà không gọi image API.
---

# Skill: google-flow-thumbnail

Dùng skill này để tạo thumbnail YouTube bằng **Google Flow trên Chrome thật**.

## Quy tắc vận hành

- Không dùng 9Router/chatgpt2api/OpenAI image API cho tạo ảnh.
- Không lưu mật khẩu Google, không bypass captcha/2FA/login/quota.
- Chrome CDP mặc định: `http://127.0.0.1:9222`, Docker relay: `http://172.21.0.1:9223` hoặc `http://host.docker.internal:9223`.
- Profile Chrome thật nằm ở `/home/haonguyen/.openclaw-chrome-handoff` do launcher `/home/haonguyen/.local/bin/start-douyin-cdp.sh` quản lý.
- Output video/thumbnail nằm trên HDD: `/mnt/hdd500/video douyin vietsub`.

## Lệnh thumbnail-only

```bash
bash ~/.openclaw/workspace/skills/google-flow-thumbnail/google-flow-thumbnail.sh "/mnt/hdd500/video douyin vietsub/OUTPUT_JOB_DIR"
```

## Output

Trong output dir của job:

- `thumbnail.jpg` — thumbnail final (ảnh Flow + chữ Việt local, hoặc fallback local)
- `thumbnail_story_analysis.json` — phân tích story (core_plot, main_character, main_conflict, strongest_emotion, mystery_or_secret, danger_or_threat, twist_or_reversal, clickable_angles)
- `thumbnail_hook_candidates.json` — 10-20 hook tiếng Việt (2-6 từ)
- `thumbnail_hook_scores.json` — chấm mỗi hook 0-10 theo content_accuracy, curiosity, clarity_in_1_second, specificity, spoiler_risk, ctr_potential
- `thumbnail_hook_selected.json` — hook cuối cùng (top-5, có reason + selected_angle)
- `thumbnail_character_candidates.json` — frame ứng viên + score_breakdown (CV + vision)
- `thumbnail_character_selected.json` — hero_reference + support_references + fallback_reason
- `thumbnail_character_refs/` — frame đã sample
- `reference_candidates.json` — toàn bộ candidate (frame video + cover/provided) + score + source
- `reference_selection_report.json` — winner_source/winner_path/winner_score/reason/top5 (cover/frame kịch tính)
- `reference_primary.jpg` / `reference_secondary.jpg` / `reference_collage.jpg` — hero + support + ghép cạnh nhau
- `thumbnail_image_plan.json` — selected_hook, selected_angle, main_subject, expression, background, composition, negative_space_for_text, style, negative_prompt, generation_mode
- `thumbnail_image_prompt.json` — prompt_text (variant đã dùng) + prompt_upload + prompt_text_only + negative_prompt + generation_mode
- `prompt_with_reference.json` — prompt_upload + prompt_text_only + prompt_used + selected_reference + upload_requested/used/required + upload_status + generation_mode
- `thumbnail_text_plan.json` — selected_hook, line_breaks, anchor, text_box, font_preset, fill, stroke, stroke_width, shadow, background_panel, emphasis_word, emphasis_scale
- `thumbnail_composer_report.json` — style, font_path, font_size, lines, text_box, fill_top/bottom, stroke, stroke_width, shadow, glow, extrude, background_panel, emphasis_word/scale
- `thumbnail_quality_report.json` — scores 0-10 + status (pass|warning|failed_fallback_used|needs_attention)
- `thumbnail_reference.jpg` — legacy reference (= hero_reference), giữ cho code cũ
- `thumbnail_reference_meta.json`
- `thumbnail_layout.json`
- `thumbnail_vision_analysis.json`
- `thumbnail_vision_prompt.txt`
- `thumbnail_prompt.txt` — giữ cho compat, sinh từ `thumbnail_image_prompt.json`
- `thumbnail_title.txt` — hook đã chọn
- `google_flow_thumbnail.log`
- `google_flow_debug/` nếu có lỗi cần debug

Ở thư mục gốc output:

- `LATEST_THUMBNAIL.txt`
- `LATEST_THUMBNAIL_PROMPT.txt`

## Cách tạo thumbnail tiếng Việt ổn định

Pipeline sáng tạo (chạy theo thứ tự):

1. **Creative** (`scripts/thumbnail_creative.py`): đọc `vietnamese.srt`, `dub.srt`, `original.srt`, `source_input.txt`, `final_metadata.json` → gọi Ollama local `/api/chat` để phân tích story, ideate 10-20 hook, chấm điểm, chọn hook top-5. Nếu Ollama lỗi/unavailable, fallback heuristic story summary + hook từ main_conflict (không quay lại keyword table cũ).
2. **Discover character references** (`scripts/thumbnail_reference.py --mode discover`): sample 16-48 frame từ `input.mp4`/`final_video_vi.mp4`, ưu tiên frame quanh cue subtitle khớp keyword hook/angle; chấm CV (subject size, face clarity, blur, clutter) + đúng 1 vision call cho top-3; xuất hero_reference + 2-3 support_references; copy hero → legacy `thumbnail_reference.jpg`. Cover/reference provided (`THUMBNAIL_REFERENCE_IMAGE`) giờ là CANDIDATE (được chấm điểm cùng frame), không còn thắng tuyệt đối.
3. **Build text plan** (`thumbnail_text_plan.json`): line_breaks, anchor, text_box, fill, stroke, shadow, emphasis_word chọn vùng chữ không đè mặt (dùng `thumbnail_layout.json` + vision `avoid_text_regions`). **Chạy trước image plan** để image prompt biết text layout thật và chừa đúng negative space.
4. **Build image plan + prompt**: `thumbnail_image_plan.json`/`thumbnail_image_prompt.json`/`thumbnail_prompt.txt` sinh **2 variant** — `prompt_upload` (nói rõ "use the attached reference image", chỉ dùng khi upload thành công) và `prompt_text_only` (mô tả reference bằng text, không giả vờ có ảnh đính kèm). Mặc định `thumbnail_prompt.txt` = text-only; sau khi biết `generation_mode` thật, cập nhật `thumbnail_prompt.txt`/`image_prompt.prompt_text` = variant đã dùng và ghi `prompt_with_reference.json`. Prompt cấm text/watermark/subtitle/Chinese title, yêu cầu negative space theo text plan.
5. **Flow generation**: mở Chrome CDP Google Flow, upload reference theo `FLOW_REFERENCE_UPLOAD`/`FLOW_REFERENCE_UPLOAD_REQUIRED` (xem dưới), điền **variant prompt đúng** (upload vs text-only), submit, tải ảnh.
6. **Compose Vietnamese text local** (`scripts/thumbnail_composer.py`): chèn chữ từ text plan, 1-2 dòng, emphasis word phóng to, tránh che đầu/mặt. Style `pro_youtube` (gradient fill + stroke đen + glow + extrude) mặc định, render stroke/glow/extrude riêng rồi gradient fill fill-only mask để stroke đen không bị gradient phủ mất.
7. **Quality gate**: chấm `thumbnail_quality_report.json` 0-10; nếu fail vì subject nhỏ/ảnh lộn hook/text đè mặt, retry Flow tối đa 1 lần. Gate không fail pipeline.

Ràng buộc an toàn giữ nguyên: thumbnail lỗi chỉ WARN/fallback local, không làm fail video pipeline; không lưu mật khẩu Google, không bypass captcha/2FA/quota; Chrome profile thật do launcher quản lý.

## Flow bridge an toàn

Workflow có tích hợp phần hữu ích theo kiểu FlowKit ở mức an toàn:

- Ghi request bridge vào `thumbnail_flow_bridge_request.json` gồm prompt, title, reference image, target output.
- Ghi heartbeat/status vào `thumbnail_flow_bridge_status.json` theo từng pha: prepare, connect CDP, open Flow, editor ready, prompt filled, submitted, waiting, compose text, done/fallback.
- Dùng Chrome thật/CDP và profile đã đăng nhập, không lưu mật khẩu Google.
- Phát hiện captcha/login/quota/UI block qua text, iframe, aria-label, class/id liên quan challenge.
- Nếu gặp captcha/reCAPTCHA/verification, workflow **không tự giải và không bypass**; ghi `THUMBNAIL_NEEDS_ATTENTION.txt`, tạo fallback local nếu được, rồi báo anh Hào xử lý tay trên Chrome thật.

Không tích hợp bất kỳ logic tự giải/bypass reCAPTCHA nào. Nếu repo/tool ngoài có phần đó thì chỉ được dùng ý tưởng queue/status/bridge, không dùng solver.

Config thumbnail reference/layout mặc định:

```bash
THUMBNAIL_USE_REFERENCE=1
THUMBNAIL_TEXT_SAFE_LAYOUT=1
THUMBNAIL_MAX_TEXT_LINES=2
THUMBNAIL_TOP_BANNER_MAX_HEIGHT=0.20
THUMBNAIL_AVOID_SUBJECT_CENTER=1
THUMBNAIL_VISION_ENABLED=1
THUMBNAIL_VISION_DEVICE=auto
THUMBNAIL_VISION_PREFER_GPU=1
THUMBNAIL_VISION_GPU_BACKEND=vulkan
THUMBNAIL_VISION_TIMEOUT_SECONDS=90
THUMBNAIL_VISION_IMAGE_MAX_SIZE=768
THUMBNAIL_VISION_FAIL_OPEN=1
THUMBNAIL_VISION_MODEL_DIR=/home/haonguyen/.local/share/openclaw-vision-models
GOOGLE_FLOW_BRIDGE_ENABLED=1
```

Config creative pipeline + reference discovery + dry-run:

```bash
# Creative (story analysis + hook ideation qua Ollama local)
THUMBNAIL_CREATIVE_ENABLED=1
THUMBNAIL_CREATIVE_API_BASE=http://127.0.0.1:11434
THUMBNAIL_CREATIVE_MODEL=minimax-m3:cloud   # hoặc qwen2.5:7b nếu đã cài; fallback OLLAMA_MODEL
THUMBNAIL_CREATIVE_TIMEOUT_SECONDS=90
THUMBNAIL_CREATIVE_ANALYSIS_TEMP=0.15
THUMBNAIL_CREATIVE_HOOK_TEMP=0.5
THUMBNAIL_CREATIVE_FAIL_OPEN=1

# Character reference discovery (multi-frame)
THUMBNAIL_REF_DISCOVER=1
THUMBNAIL_REF_MIN_FRAMES=16
THUMBNAIL_REF_MAX_FRAMES=48
THUMBNAIL_REF_SAMPLE_INTERVAL=6
THUMBNAIL_REF_VISION_SCORE=1   # bật 1 vision call cho top-3 hero candidates

# Quality gate + retry
THUMBNAIL_QUALITY_GATE_ENABLED=1
THUMBNAIL_FLOW_RETRY=1           # retry Flow tối đa 1 lần khi gate fail vì lý do sửa được

# Dry-run (sinh đủ artifacts nhưng KHÔNG mở Chrome/Flow)
THUMBNAIL_DRY_RUN=1
```

Config reference upload + prompt split + text style + refine (mới):

```bash
# Reference upload lên Google Flow
FLOW_REFERENCE_UPLOAD=1                  # 0 = luôn skip upload, dùng reference_prompt_only
FLOW_REFERENCE_UPLOAD_REQUIRED=0         # 1 = upload fail -> pipeline FAIL rõ (không fallback prompt-only âm thầm)
                                          # 0 = fail-open sang prompt-only (mặc định)

# Refine hook dựa trên visual analysis (sau khi có reference visual analysis)
THUMBNAIL_REFINE_HOOK=0                  # 1 = chạy thumbnail_creative.py --refine sau discover; 0 = giữ seed hook

# Text composer style
THUMBNAIL_TEXT_STYLE=pro_youtube         # pro_youtube (mặc định, v2: gradient+glow+extrude) | legacy (v1: fill đơn sắc)
```

**Rollback an toàn:**

- `THUMBNAIL_TEXT_STYLE=legacy` — quay lại composer v1 (fill đơn sắc `#FFDE46`, stroke 5, panel 165), bỏ gradient/glow/extrude. Dùng khi `pro_youtube` cho kết quả không tốt.
- `FLOW_REFERENCE_UPLOAD=0` — tắt hẳn upload reference, luôn prompt-only (không đụng UI upload Flow).
- `FLOW_REFERENCE_UPLOAD_REQUIRED=1` — bắt buộc upload; nếu Flow không có UI upload hoặc upload fail, pipeline **fail rõ** (exit nonzero + `needs_user_attention`) thay vì âm thầm fallback. Chỉ bật khi bạn chắc Flow có UI upload và muốn bắt buộc reference.
- `THUMBNAIL_REFINE_HOOK=0` — tắt refine hook visual, giữ hook seed từ creative ban đầu.

**Lưu ý hành vi mới:**

- Cover/reference provided (`THUMBNAIL_REFERENCE_IMAGE`) không còn thắng tuyệt đối — được đưa vào pool candidate và chấm điểm cùng frame video; chỉ thắng khi score cao nhất.
- Case chỉ có provided image, không có video: vẫn xuất `reference_candidates.json`/`reference_selection_report.json`/`reference_primary.jpg` (dùng provided làm hero).
- `discover_references()` parse JSON robust (JSONDecoder quét object cuối từ stdout) + fallback đọc `thumbnail_character_selected.json` — không còn `WARN: reference discovery failed` giả khi artifact thật đã tạo.
- `prompt_with_reference.json` phân biệt `prompt_upload` vs `prompt_text_only`; `thumbnail_prompt.txt`/`thumbnail_image_prompt.json` phản ánh **variant thật đã dùng** theo `generation_mode`.

Nếu chưa có local vision model/runtime, script vẫn tạo `thumbnail_vision_analysis.json` ở chế độ `heuristic_fallback` và không làm fail thumbnail. Nếu Ollama creative unavailable, script sinh `thumbnail_story_analysis.json`/`thumbnail_hook_selected.json` heuristic (có `fallback_reason`) và tiếp tục; không quay lại keyword table cũ trừ khi creative hoàn toàn không trả gì.

Nếu người dùng gửi ảnh mẫu/reference trong chat và file đó đã có trên máy, đặt:

```bash
THUMBNAIL_REFERENCE_IMAGE="/path/to/reference.jpg" bash ~/.openclaw/workspace/skills/google-flow-thumbnail/google-flow-thumbnail.sh "OUTPUT_DIR"
```

Không yêu cầu Google Flow vẽ chữ; chữ luôn chèn local sau cùng.

## Khi người dùng yêu cầu

Nếu người dùng nói “tạo thumbnail”, “tạo thumbnail YouTube”, “thumbnail tiếng Việt”, hoặc “chỉ tạo thumbnail cho video mới nhất”, hãy gọi thumbnail-only với output dir mới nhất. Nếu chưa biết output dir, đọc:

```bash
cat "/mnt/hdd500/video douyin vietsub/LATEST_OUTPUT_DIR.txt"
```

Sau đó chạy:

```bash
bash ~/.openclaw/workspace/skills/google-flow-thumbnail/google-flow-thumbnail.sh "OUTPUT_DIR"
```

Không cần tự viết prompt thủ công trong câu trả lời; script sẽ tự sinh prompt và title từ transcript/job metadata.
Khi báo kết quả, có thể gửi thêm `thumbnail_reference.jpg` để người dùng so sánh ảnh gốc/reference với thumbnail final.

## Khi cần người dùng can thiệp

Nếu Flow yêu cầu login/captcha/quota/limit hoặc UI đổi, script sẽ ghi rõ:

- `thumbnail_flow_status.json`
- `thumbnail_flow_bridge_status.json`
- `thumbnail_flow_bridge_request.json`
- `THUMBNAIL_NEEDS_ATTENTION.txt`
- dòng log `WARN_USER_ACTION_REQUIRED`

Trong trường hợp đó script sẽ cố tạo `thumbnail.jpg` fallback local từ `thumbnail_reference.jpg` hoặc `input.mp4` để pipeline video không bị kẹt. Khi báo kết quả cho người dùng, phải nói rõ thumbnail hiện tại là fallback local và cần mở Chrome CDP Google Flow để xử lý login/quota/captcha/limit nếu muốn tạo lại bằng Flow.
