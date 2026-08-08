# Docker Web Tool Design

## Goal

Đóng gói repository thành công cụ web dùng cá nhân, chạy bằng Docker Compose trên
Windows Docker Desktop và Linux. Người dùng cuối thao tác hoàn toàn trên trình
duyệt: đăng nhập Bilibili, cấu hình provider, thêm video/kênh/series, theo dõi
queue, resume lỗi và tải kết quả.

Web là lớp điều phối cho logic hiện có. Không viết lại hoặc rút gọn pipeline
video, quality gate, TTS, subtitle, branding, monitor hay series.

## Product Scope

### Jobs

- Nhận URL Bilibili, Douyin/TikTok và file video local.
- Chọn provider dịch, model, voice và preset xử lý.
- Xếp job theo FIFO; một job active tại một thời điểm.
- Hiển thị phase, progress, heartbeat, lỗi có cấu trúc và artifact.
- Hỗ trợ pause/resume toàn queue, cancel job đang chạy, resume checkpoint và
  chạy lại từ đầu. Không dùng process suspension cho job đang chạy.
- Cho tải `final_video_vi.mp4`, `vietnamese.srt`, `dub.srt`, thumbnail và các
  quality report an toàn.

### Channels

- Thêm, xóa, bật/tắt kênh Bilibili hoặc Douyin/TikTok.
- Scheduler kiểm tra kênh theo chu kỳ cấu hình.
- Video mới được chống trùng và tự đưa vào queue.
- Mỗi channel chọn provider, model, voice, series và chính sách tự xử lý.
- Captcha hoặc login cần người dùng xử lý phải chuyển thành trạng thái
  `needs_attention`, không tự bypass.

### Series

- Giữ `series-tracker` và `series-compilation-orchestrator`.
- Theo dõi tập đã phát hiện, đã tải, đã dịch, đã render và đã compile.
- Cho tải tập thiếu, resume từng tập, quality gate trước compile và giữ đúng thứ
  tự nguồn.
- Branding Bilibili luôn chạy trước hand-off theo contract hiện tại.

### Trend

- Expose AI Anime Trend Scout khi Postgres và runtime tương ứng được cấu hình.
- Trend scan, archive research, candidate detail và risk check giữ contract hiện
  có.
- Tab bị disable với lý do rõ khi dependency chưa được cấu hình.

### Providers

- Profile `openai_compatible`: tên, endpoint, API key, model và timeout.
- Profile `ai33`: endpoint, API key, voice registry và connection test.
- Profile `ollama`: endpoint, model và connection test; API key là optional.
- Endpoint chỉ nhận `http` hoặc `https`; không nhận shell, file URL hay command.
- Connection test chỉ trả trạng thái và lỗi đã sanitize, không trả lại secret.
- Profile provider lưu bền sau restart Docker.

### Bilibili Login

- Nút đăng nhập mở Chromium trong container tới trang Bilibili.
- Web hiển thị QR đăng nhập; người dùng quét bằng app Bilibili.
- Sau đăng nhập, cookies được lấy qua CDP và lưu dạng Netscape trong secret
  volume.
- Web chỉ hiển thị trạng thái login, số cookie và thời điểm kiểm tra; không hiển
  thị giá trị cookie.
- Upload hoặc paste `cookies.txt` là fallback thủ công.
- Cookies hết hạn chuyển job/channel sang `needs_attention` và yêu cầu đăng nhập
  lại.

## Preserved Repository Behavior

Container phải tiếp tục dùng các module hiện có:

- `skills/bilibili-vietnamese-dubber`
- `skills/douyin-vietnamese-dubber`
- `skills/douyin-stealth`
- `skills/content-monitor`
- `skills/series-tracker`
- `skills/series-compilation-orchestrator`
- `skills/ai-anime-trend-scout`
- `skills/google-flow-thumbnail`
- `skills/telegram-openclaw-bot`

Các chức năng được giữ:

- yt-dlp, Chromium CDP và URL normalization;
- Demucs, speech segmentation, Whisper ASR và OCR;
- transcript selection và quality control;
- Ollama/9Router/OpenAI-compatible translation;
- AI33, Kokoro, Resona và Edge TTS;
- checkpoint, provider retry, circuit breaker và voice quality gate;
- voice sync, background stem, ducking và final mix;
- blur chữ Trung, burn-in Vietsub, logo và branding;
- thumbnail, organize output, Telegram và series compilation.

HyperFrames không được mô tả là hoàn chỉnh. Repository hiện chỉ có availability
check và dry-run; web chỉ expose đúng trạng thái đó.

## Architecture

### Required Service

Docker Compose có một service bắt buộc tên `tool`:

- FastAPI phục vụ JSON API, static UI và Server-Sent Events.
- SQLite lưu job queue, channel schedule, series references và provider metadata
  không bí mật.
- Một scheduler loop tạo monitor jobs.
- Một worker loop claim tối đa một job và gọi wrapper hiện có bằng subprocess.
- Chromium chạy với remote debugging trong cùng container để tái sử dụng
  `bilibili_cdp.py`.
- FFmpeg, ffprobe, yt-dlp, whisper.cpp runtime và Python pipeline nằm trong image
  hoặc model volume tương ứng.

Không thêm Redis/Celery cho bản dùng cá nhân. SQLite transaction và single worker
đủ đảm bảo queue không chạy trùng.

### Optional Profiles

- `ollama`: chạy Ollama trong Compose khi người dùng không dùng Ollama trên host.
- `trend-db`: Postgres cho Trend Scout nếu người dùng muốn dùng module trend.
- GPU không bắt buộc. NVIDIA GPU dùng Docker Desktop WSL2 trên Windows hoặc
  NVIDIA Container Toolkit trên Linux; CPU vẫn là đường chạy hợp lệ.

### Volumes

| Volume | Nội dung |
|---|---|
| `tool-data` | SQLite, cấu hình không bí mật, queue và scheduler state |
| `tool-secrets` | API keys, cookies và provider secret files |
| `tool-jobs` | Job directories, checkpoints, logs và reports |
| `tool-output` | Video/SRT/thumbnail hoàn chỉnh |
| `tool-models` | Whisper, Demucs và model cache |
| `tool-browser` | Chromium profile đăng nhập |

Volumes không bị xóa khi recreate hoặc update container.

## Queue Contract

- Trạng thái: `queued`, `running`, `paused`, `needs_attention`, `failed`,
  `cancelled`, `completed`.
- `paused` chỉ áp dụng cho job chưa chạy khi toàn queue bị pause; job `running`
  tiếp tục hoặc được cancel có kiểm soát.
- Thứ tự mặc định FIFO; người dùng có thể di chuyển job đang chờ.
- Chỉ một job `running`.
- Restart container:
  - `queued` giữ nguyên;
  - `completed`, `failed`, `cancelled` giữ nguyên;
  - job từng `running` chuyển thành `needs_attention` với action `resume`.
- Cancel gửi signal có kiểm soát tới process group và giữ checkpoint/artifact đã
  hoàn thành.
- Resume dùng job directory cũ và contract `OPENCLAW_RESUME_JOB_DIR`.
- Retry từ đầu tạo job mới; job cũ giữ làm lịch sử.
- AI33 vẫn dùng tối đa ba worker nội bộ theo pipeline hiện có.

## Data Flow

```text
Browser
  -> Web API validates request
  -> SQLite queue
  -> Single worker claims job
  -> Existing Bilibili/Douyin/series wrapper
  -> Existing core pipeline and quality gates
  -> job_status.json + reports + checkpoints
  -> SSE/status API
  -> final_video_vi.mp4 and downloadable artifacts
```

Channel monitor dùng cùng queue:

```text
Scheduler
  -> existing content monitor discovery
  -> dedupe source URL/video ID
  -> create queued job with channel preset
  -> normal worker flow
```

## Web Interface

Ứng dụng mở thẳng vào màn hình Jobs, không có landing page marketing.

- Sidebar: Jobs, Channels, Series, Trend, Providers, Bilibili Login, Settings.
- Jobs dùng bảng/panel gọn, ưu tiên quét trạng thái và thao tác lặp lại.
- Job detail có timeline phase, sanitized log tail, artifacts và action phù hợp
  trạng thái.
- Provider key dùng password input; sau lưu chỉ hiển thị `configured`.
- QR login hiển thị ảnh QR và trạng thái polling.
- Mọi control có label, keyboard focus và trạng thái disabled rõ.
- Desktop là chính; mobile vẫn xem queue, trạng thái và thao tác retry/download.

## Security

- Mặc định bind `127.0.0.1:18793`; không expose LAN/Internet.
- Không cần account/password trong local-only mode.
- Nếu sau này bind ngoài localhost, authentication và TLS là requirement riêng,
  không tự bật bằng cấu hình mơ hồ.
- API key và cookies nằm trong `tool-secrets`, file mode `0600` trên Linux.
- Windows dùng Docker-managed volume; secret không đặt trong bind mount repo.
- Secret không đi qua command line. Worker dùng environment/file descriptor hoặc
  secret file được allowlist.
- API không có endpoint đọc lại secret.
- Logs, provider errors, status và downloadable reports phải sanitize URL ký,
  cookie, token và key.
- Upload chỉ nhận loại file allowlist, giới hạn dung lượng và tên file do server
  tạo.
- URL, endpoint, voice, model, platform và action được validate bằng allowlist;
  không nhận shell command hoặc arbitrary host path.
- Chromium profile và cookie files không được đưa vào job output.

## Error Handling

- Wrapper exit code và `job_status.json` là nguồn trạng thái chính.
- Dashboard ưu tiên `error_code`, `message`, `failed_cue`, `failed_stage`,
  `resume_from_cue` và report path an toàn.
- Provider outage/rate limit chuyển sang `needs_attention` hoặc
  `waiting_provider`; không tạo silence rồi báo thành công.
- Thiếu model/runtime hiển thị doctor result và action cấu hình tương ứng.
- Login/captcha không bypass; yêu cầu người dùng mở màn hình login.
- Không báo completed nếu thiếu hoặc không decode được `final_video_vi.mp4`.

## Portability

### Windows

- Docker Desktop với WSL2 backend.
- Ollama host dùng `host.docker.internal`.
- Output mặc định nằm trong named volume; người dùng có thể chọn thư mục export
  bằng bind mount trong Compose override.
- GPU là optional profile; CPU path phải chạy được.

### Linux

- Docker Engine và Compose plugin.
- Host Ollama dùng `host-gateway` hoặc endpoint LAN được người dùng cấu hình.
- NVIDIA GPU dùng NVIDIA Container Toolkit khi có.
- File permissions được chuẩn hóa theo `PUID`/`PGID` để output host đọc được.

## First-Run Experience

1. Chạy `docker compose up -d`.
2. Mở `http://localhost:18793`.
3. Setup wizard chạy doctor cho FFmpeg, Chromium, Whisper model, Demucs và output
   volume.
4. Thêm provider endpoint/key/model hoặc chọn Ollama local.
5. Đăng nhập Bilibili bằng QR nếu cần.
6. Tạo job đầu tiên hoặc thêm channel monitor.

Wizard không bắt người dùng dùng terminal ngoài lệnh Docker Compose ban đầu.

## Testing

### Unit and Contract

- Provider endpoint/key validation và secret redaction.
- SQLite queue claim chỉ có một active job.
- Restart recovery chuyển running job thành resumable.
- Channel discovery dedupe và auto-enqueue.
- Job status/error mapping từ artifact hiện có.
- Cookie import, login-state detection và không lộ cookie.
- Path, upload và action allowlist.

### Integration

- Fake wrapper tạo progress/report/final video để test web, SSE, cancel và resume.
- Existing pipeline tests tiếp tục chạy không đổi.
- Docker image build và Compose config validation trên CI.
- Browser test cho setup, provider, QR state, create job, queue, retry và download.

### Runtime Acceptance

Trên Windows và Linux:

- container restart không mất provider profile, login, queue hoặc completed job;
- hai job chỉ có một job chạy;
- monitor phát hiện video mới và enqueue đúng một lần;
- Ollama host endpoint dịch được một fixture;
- Bilibili login QR tạo cookie secret nhưng không lộ trong UI/log;
- một video test tạo được `final_video_vi.mp4` decode được;
- resume job TTS lỗi tiếp tục từ checkpoint;
- output cuối giữ audio 48 kHz stereo và subtitle/branding gate.

## Deliverables

- `Dockerfile`
- `compose.yaml`
- `.dockerignore`
- backend web/API/queue/scheduler trong một thư mục ứng dụng mới
- static frontend
- migrations/schema bootstrap SQLite
- Docker entrypoint và runtime doctor
- tests cho queue, secrets, API và browser workflow
- README cài đặt Windows/Linux và troubleshooting

## Explicit Non-Goals

- Multi-user, billing, cloud SaaS hoặc public Internet deployment.
- Redis/Celery/Kubernetes.
- Tự giải captcha hoặc bypass login.
- Tự hoàn thiện HyperFrames ngoài khả năng hiện có của repository.
- Thay đổi thuật toán pipeline video nếu không cần cho Docker boundary.

## Success Criteria

Thiết kế hoàn thành khi người dùng trên Windows hoặc Linux có thể:

1. Chạy một lệnh Docker Compose và mở web local.
2. Lưu endpoint/API key/model và giữ qua restart.
3. Đăng nhập Bilibili bằng QR hoặc import cookie thủ công.
4. Thêm video, channel hoặc series mà không dùng terminal.
5. Để monitor tự enqueue video mới và dịch bằng Ollama/provider đã chọn.
6. Xem lỗi thật, resume checkpoint và tải video hoàn chỉnh.
7. Dùng toàn bộ pipeline hiện có mà không làm lộ secrets.
