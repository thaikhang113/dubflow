# OpenClaw trong DubFlow

Mở DubFlow, vào mục `OpenClaw` trong nhóm Công cụ rồi bật `Bật kết nối
OpenClaw`. Ứng dụng tự chạy API local và worker nền; người dùng không cần
mở terminal, cài Python hoặc tải source code.

Sao chép thông tin kết nối do DubFlow hiển thị vào cấu hình HTTP tool của
OpenClaw. API chỉ lắng nghe trên máy local và yêu cầu Bearer token.

Actions:

- `prepare`: extract links and return missing questions.
- `submit`: create one queue job per link and return `batch_id`.
- `status`: return aggregate and per-video progress.
- `cancel`: cancel non-terminal jobs in a batch.
- `retry_failed`: replace failed jobs with fresh queue jobs.

HTTP endpoints:

- `GET /health`
- `POST /v1/prepare`
- `POST /v1/submit`
- `GET /v1/batches/{batch_id}`
- `POST /v1/batches/{batch_id}/cancel`
- `POST /v1/batches/{batch_id}/retry-failed`

Submit body example:

```json
{
  "links": ["https://example.com/video"],
  "options": {
    "voice": "Truc Ly",
    "translate_style": "social",
    "subtitle_mode": "burn"
  }
}
```

DubFlow secrets remain in local `.env` and never enter the job payload.
