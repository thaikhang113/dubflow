# Revised implementation plan: Douyin trend intelligence and clean-media download

## 1. Mục tiêu và phạm vi

Mục tiêu gần nhất là bổ sung Douyin vào luồng nghiên cứu anime/trend của OpenClaw và nâng cấp đường tải Douyin để ưu tiên nguồn không logo/no-watermark có kiểm chứng. Không rewrite pipeline vietsub/lồng tiếng hiện tại và không gộp toàn bộ nội dung của `Master Implementation Plan - Douyin Integration.pdf` vào một lần triển khai.

Phạm vi này gồm:

1. Douyin Trend Scout chạy song song với Bilibili Trend Scout.
2. Thu thập Douyin từ hot/discovery, keyword và creator đã theo dõi.
3. Chuẩn hóa, deduplicate, lưu metric snapshot, xếp hạng và tạo digest chung hoặc tách theo platform.
4. Tách resolver media Douyin khỏi downloader, ưu tiên candidate clean và tải just-in-time.
5. Unit, contract, integration và live smoke test bằng URL Douyin thật do người dùng duyệt.

Ngoài phạm vi đợt này:

- Không thay pipeline subtitle/TTS đang hoạt động.
- Không tự động tải mọi candidate trend.
- Không triển khai CAPTCHA bypass.
- Không khẳng định một video “không logo” chỉ dựa trên tên URL.
- Không phụ thuộc runtime vào repository upstream đã lâu không cập nhật.

## 2. Baseline hiện tại

### 2.1 Bilibili trend research

`skills/ai-anime-trend-scout/` đã định nghĩa contract OpenClaw tương đối chặt:

- `trend-start-scan`, `trend-scan-status`, `trend-top-candidates` cho scan theo yêu cầu.
- `trend-collection-tick` cho collection cố định.
- `trend-report-prepare` và `trend-report-ack` cho digest có dedupe.
- `run_scheduled_report.sh` thực hiện prepare → gửi Telegram → ack, không đọc token trực tiếp.
- Host runner dùng allowlist và bridge riêng; OpenClaw không truy cập DB/service nội bộ trực tiếp.

Đây là mẫu nên mở rộng theo provider/platform, không nên tạo một workflow Douyin hoàn toàn khác.

### 2.2 Creator monitor

`skills/content-monitor/content-monitor.py` đã hỗ trợ `platform=douyin|bilibili`, kiểm tra video creator mới và gửi báo cáo. Đây là luồng “kênh có video mới”, không phải trend research:

- Không có hot-board discovery.
- Không có metric snapshot/velocity.
- Không có shortlist đa nguồn.
- Không phân biệt rõ API lỗi với kết quả rỗng ở mọi nhánh.
- Không nên nhét trend scoring vào daemon này.

Giữ creator monitor hiện tại làm nguồn tín hiệu creator; chỉ publish normalized candidates sang Trend Scout qua adapter hoặc collection job.

### 2.3 Douyin discovery và download

`skills/douyin-stealth/scripts/fetch_douyin_v2.py` đã có:

- Tái sử dụng Chrome/CDP.
- Search và normalize link/video ID ở mức hiện tại.
- Bắt network/DOM media candidates.
- Heuristic scoring, hạ điểm `playwm`/watermark và ưu tiên marker clean.
- Download bằng browser request context và mux audio khi cần.

`skills/douyin-vietnamese-dubber/run.sh` đã gọi browser downloader trước, sau đó fallback `yt-dlp`, rồi đưa `input.mp4` vào pipeline gốc.

Các điểm chưa đủ ổn định:

- Candidate clean hiện chủ yếu được suy ra từ chuỗi URL; đó không phải bằng chứng chắc chắn không logo.
- User-Agent đang hard-code ở request tải thay vì lấy đồng nhất từ browser session.
- Tải toàn body trước khi xác nhận candidate; chưa có Range validation độc lập.
- Resolver và downloader nằm chung một flow, khó unit test và khó quan sát fallback.
- Không có structured `media_resolution.json` ghi candidate, lý do chọn, validation và fallback.
- Fallback `yt-dlp` có thể tải bản watermark nhưng job không có policy rõ `allow_watermarked`.
- Chưa có quality gate riêng cho container, stream, duration và cleanliness confidence trước khi chuyển sang subtitle pipeline.

## 3. Điều chỉnh quan trọng so với PDF gốc

### 3.1 Không dựng cây `app/` mới ngay

Repository hiện tổ chức theo skill và host-runner. Tạo một cây ứng dụng mới sẽ nhân đôi scheduler, browser session và orchestration. Triển khai nên mở rộng các ranh giới đang có:

- `skills/ai-anime-trend-scout/`: contract và hướng dẫn OpenClaw đa platform.
- Trend Scout host service hiện tại: provider Douyin, storage, scoring và report package.
- `skills/douyin-stealth/`: browser/session adapter và Douyin extraction.
- `skills/douyin-vietnamese-dubber/`: chỉ nhận artifact download đã qua gate.
- Host runner: action allowlist cố định, không thêm shell/URL fetch tùy ý.

### 3.2 Repository cũ chỉ là nguồn tham khảo có pin

Không vendor hoặc import trực tiếp `douyin-downloader` vào runtime. Nếu cần nghiên cứu:

- Pin commit hash và ghi ngày audit.
- Chỉ port thuật toán nhỏ sau khi có test fixture và license notice.
- Mọi endpoint/field lấy từ upstream phải được xác minh lại bằng browser traffic hiện tại.
- Có adapter để thay extraction strategy mà không đổi downstream contract.
- Khi upstream và live behavior xung đột, live contract có fixture sanitized và test mới là nguồn sự thật.

MediaCrawler chỉ được dùng để hiểu behavior/shape; không copy production source. VideoLingo không thuộc milestone trend/clean-media này.

### 3.3 “Không logo” là confidence, không phải boolean suy đoán

Thay field `watermark_free: bool` đơn lẻ bằng:

- `cleanliness_status`: `verified_clean`, `likely_clean`, `watermarked`, `unknown`.
- `cleanliness_evidence`: player-state field, endpoint family, URL marker, visual/manual check, hoặc fallback provenance.
- `resolver_strategy` và `selected_candidate_id`.
- `allow_watermarked_fallback` là policy explicit, mặc định `false` cho job yêu cầu clean.

Chỉ `verified_clean` khi có bằng chứng upstream/player-state đáng tin hoặc golden live test đã xác nhận hình ảnh. URL không chứa `playwm` chỉ được xếp `likely_clean` hoặc `unknown`.

## 4. Kiến trúc đích tối thiểu

### 4.1 Provider contract cho Trend Scout

Trend engine dùng model chung và provider riêng:

```text
TrendProvider
  collect_hot(limit)
  search(query, window_days, cursor, limit)
  collect_creator(creator_id, cursor, limit)
  fetch_detail(content_id)
  fetch_comments(content_id, limit)   # optional, top candidates only
```

Provider trả `ProviderResult`, không trả list trần:

```text
status: success | empty_success | session_expired | blocked |
        rate_limited | invalid_response | network_error
items: normalized candidates
cursor / has_more
observed_at
error_code (sanitized)
```

Normalized candidate phải có `platform`, `platform_video_id`, `canonical_url`, title/description, creator ID, publish time, duration, metric values kèm `metric_availability`, source lane và observation timestamp. Unique key là `(platform, platform_video_id)`.

### 4.2 Douyin provider boundaries

Không cho Trend Scout đọc cookie/profile. Host-side Douyin provider gọi adapter CDP cục bộ và chỉ nhận dữ liệu sanitized:

```text
DouyinBrowserSessionAdapter
  health()
  acquire_page(purpose)
  session_metadata()        # không chứa cookie value

DouyinDiscoveryAdapter
  hot()
  search()
  creator_feed()
  detail()
```

Mỗi adapter phải phân biệt `empty_success` với session/challenge/response lỗi. Concurrency mặc định 1; bounded retry; gặp blocked/challenge thì dừng batch.

### 4.3 Media resolver contract

Tách ba bước:

```text
canonical Douyin URL
  -> collect candidates from current browser/player state
  -> validate and rank candidates
  -> download selected candidate immediately
```

Artifact resolver tối thiểu:

```json
{
  "schema_version": 1,
  "platform_video_id": "...",
  "canonical_url": "https://www.douyin.com/video/...",
  "status": "resolved",
  "cleanliness_status": "likely_clean",
  "selected_candidate_id": "sha256-of-redacted-metadata",
  "resolver_strategy": "player_state_or_network",
  "validation": {
    "http_ok": true,
    "content_type_ok": true,
    "media_signature_ok": true,
    "ffprobe_ok": true,
    "has_video": true
  },
  "fallback_used": false
}
```

Không lưu direct CDN URL vào DB/report lâu dài và không log query/token của URL. Candidate URL chỉ tồn tại trong memory hoặc file job private có TTL nếu thật sự cần resume.

Ranking dùng dữ liệu có cấu trúc theo thứ tự:

1. Player/detail field xác định play address clean.
2. Validation thành công trong chính browser request context.
3. Codec/container tương thích và có video stream.
4. Resolution/bitrate hợp lý, không mặc định “lớn nhất luôn tốt nhất”.
5. Marker URL chỉ là tín hiệu phụ.

Trước full download, dùng GET Range nhỏ khi server hỗ trợ; nếu không hỗ trợ Range thì stream vào file tạm với size/time limit, không giữ toàn body trong RAM. Sau download chạy `ffprobe`; mux audio chỉ khi stream audio thực sự tách rời.

## 5. Luồng OpenClaw đề xuất

### 5.1 Scan theo yêu cầu

Giữ contract hiện tại nhưng thêm platform rõ ràng, ưu tiên action mới không phá action Bilibili:

```text
trend-start-scan-v2 QUERY WINDOW MODE PLATFORM
trend-scan-status SCAN_ID
trend-top-candidates SCAN_ID LIMIT
trend-video-risk PLATFORM VIDEO_ID
```

`PLATFORM` chỉ nhận `bilibili`, `douyin`, `all`. Nếu muốn tránh action mới, bridge có thể thêm field platform nhưng host-runner vẫn phải validate allowlist và giới hạn độ dài/query/window.

### 5.2 Collection và báo cáo 4 giờ

`trend-collection-tick` chạy provider Bilibili và Douyin độc lập, mỗi provider có budget/circuit breaker riêng. Một platform lỗi không biến kết quả platform kia thành failed, nhưng digest phải hiển thị trạng thái từng nguồn.

Digest nên có:

- `Bilibili candidates`.
- `Douyin candidates`.
- `Cross-platform topics` chỉ khi clustering có đủ evidence.
- Metric thiếu hiển thị “không có dữ liệu”, không đổi thành 0.
- Candidate Douyin có canonical link, reason codes và cleanliness availability; không tự enqueue download.

Giữ prepare → Telegram → ack và dedupe hiện tại. Test không được gửi Telegram thật.

### 5.3 Từ shortlist sang tải clean

OpenClaw chỉ được enqueue khi người dùng yêu cầu hoặc policy đã duyệt:

```text
candidate selected
  -> resolve clean media (dry-run metadata first)
  -> require cleanliness threshold
  -> download to temp job
  -> media quality gate
  -> hand off input.mp4 to existing pipeline
```

Action host-runner nên tách:

- `douyin-resolve-media VIDEO_URL` trả artifact sanitized, không download full.
- `douyin-download-clean VIDEO_URL POLICY` với `POLICY=clean_only|allow_watermarked`.
- `run-douyin` giữ tương thích, nhưng về sau gọi downloader adapter mới trước pipeline.

Không cho caller truyền direct CDN URL.

## 6. Storage và scoring

Tái sử dụng storage Trend Scout hiện tại thay vì tạo SQLite thứ hai nếu service đang dùng Postgres. Schema cần thêm `platform`, external ID và metric availability; migration phải backward-compatible.

Metric snapshot lưu theo `(platform, video_id, observed_at)`. Scoring không dùng like tuyệt đối đơn thuần:

- freshness và age confidence;
- engagement velocity khi có ít nhất hai snapshot;
- share/comment/favorite intensity khi field có thật;
- relevance và source lane;
- creator diversity;
- duplicate/repost penalty;
- missing-metric confidence penalty.

Không so trực tiếp raw metric Bilibili với Douyin nếu semantics khác nhau. Normalize theo platform/window trước, rồi mới tạo cross-platform topic score.

## 7. Kế hoạch test bắt buộc

### 7.1 Unit tests, không network

- Response status mapping: empty khác blocked/session-expired.
- Normalization và canonical URL.
- Dedup key có platform.
- Pagination/cursor bounds.
- Metric snapshot và velocity.
- Scoring khi thiếu metric.
- Media candidate extraction từ sanitized fixtures.
- Ranking: clean evidence thắng URL heuristic; invalid media bị loại.
- Redaction: report/log không chứa cookie, authorization hay CDN query.
- Policy: `clean_only` không fallback watermark.
- Stream/container/audio validation.

### 7.2 Contract tests

- Host-runner chỉ nhận action/argument allowlist.
- Query length, platform, mode và limit bị giới hạn.
- Không nhận direct CDN URL ở download action.
- OpenClaw bridge chỉ trả payload sanitized.
- Report prepare/ack vẫn dedupe và không gửi lại.
- Bilibili action cũ không đổi behavior.

### 7.3 Integration tests cục bộ

- Fake CDP/browser context với fixture hot/search/detail/network responses.
- Fake server: Range 206, full 200, redirect, 403, HTML giả video, body rỗng, timeout.
- Candidate video-only + audio-only được mux đúng.
- `ffprobe` gate fail thì không hand off pipeline.
- Database migration, upsert và hai platform trùng numeric ID không xung đột.
- Provider Douyin lỗi nhưng digest Bilibili vẫn được tạo với trạng thái degraded.

### 7.4 Live smoke test thực tế

Live test là gate riêng, chạy thủ công trên host và cần URL/video Douyin công khai do người dùng duyệt. Không chạy trong unit suite, không gửi Telegram và không tự chạy subtitle/TTS.

Golden set ban đầu tối thiểu 6 URL:

- 2 video biết có logo/watermark.
- 2 video kỳ vọng có candidate clean.
- 1 video có audio tách rời hoặc encoding khác thường.
- 1 URL lỗi/đã xóa/đòi login để xác minh error classification.

Với mỗi URL:

1. Health check CDP và session, không in cookie/profile data.
2. Resolve canonical ID.
3. Thu candidate và ghi metadata đã redact.
4. Validate candidate bằng Range/stream giới hạn.
5. Download vào thư mục test tạm, không đưa vào thư viện output.
6. Chạy `ffprobe`: container, video/audio stream, duration, resolution.
7. Lấy frame ở đầu/giữa/cuối để người kiểm thử xác nhận logo ở vòng baseline; không tự tuyên bố clean khi chưa có evidence.
8. So sánh resolver mới với browser downloader hiện tại và `yt-dlp` fallback về success, kích thước, stream, duration và cleanliness status.
9. Xóa/giữ artifact theo lựa chọn người chạy; report không chứa signed CDN URL.

Pass criteria:

- 100% error case được phân loại đúng, không trả empty/success giả.
- 100% file accepted qua `ffprobe` và duration tolerance.
- `clean_only` không bao giờ âm thầm dùng candidate watermark/unknown.
- Các mẫu `verified_clean` được người kiểm thử xác nhận hình ảnh trong golden manifest.
- Không có secret/CDN token trong stdout, report hay committed fixture.
- Bilibili scheduled report contract vẫn pass.

Live trend smoke test riêng:

- Chạy một query anime Trung Quốc trên Douyin với limit nhỏ.
- Xác nhận canonical link thật, ID unique, publish time/metric availability trung thực.
- Chạy lại để kiểm tra dedupe.
- Chụp snapshot thứ hai sau khoảng thời gian đủ dài trước khi khẳng định velocity.
- Test session-expired/blocked bằng fixture hoặc controlled state; không cố tình kích CAPTCHA.

## 8. Milestone triển khai

### M0 — Baseline và contract

- Ghi current architecture audit ngắn cho trend/download.
- Chốt normalized models, error codes và cleanliness states.
- Chạy baseline test Bilibili, content monitor và downloader hiện tại.

### M1 — Resolver test-first

- Viết fixture/unit test candidate extraction, ranking, redaction và policy.
- Tách resolver thuần khỏi `fetch_douyin_v2.py` nhưng giữ CLI cũ.
- Thêm Range/stream validation và structured resolution artifact.
- Chưa thay `run-douyin` mặc định.

### M2 — Live clean-media proof

- Chạy golden live set.
- Hiệu chỉnh evidence/ranking theo traffic hiện tại, không theo assumption từ repo cũ.
- Chỉ bật feature flag `douyin_clean_media_resolver` sau khi pass.

### M3 — Douyin research provider

- Contract tests trước cho status/normalize/dedup.
- Implement hot/search/detail và creator adapter trên session hiện có.
- Lưu candidates/snapshots vào Trend Scout storage.
- Chưa lấy comments đại trà.

### M4 — Trend scoring và OpenClaw

- Platform-aware scoring.
- Host-runner allowlist và bridge v2.
- Scan theo yêu cầu, shortlist và report package có Douyin.
- Giữ Bilibili response tương thích.

### M5 — Scheduler/digest

- Collection 4 giờ với provider budgets độc lập.
- Digest theo platform, prepare/ack/dedupe hiện tại.
- Feature flag và rollback Douyin riêng.

### M6 — Handoff vào pipeline

- `run-douyin` gọi resolver mới theo flag.
- `clean_only` là lựa chọn rõ; fallback phải được ghi artifact.
- Chỉ hand off khi media gate pass.
- Chạy một E2E được người dùng phê duyệt đến `final_video_vi.mp4`; áp dụng đầy đủ subtitle/TTS quality gates hiện có.

## 9. Feature flags và rollback

```text
DOUYIN_TREND_PROVIDER=0
DOUYIN_TREND_SCHEDULED_COLLECTION=0
DOUYIN_CLEAN_MEDIA_RESOLVER=0
DOUYIN_CLEAN_ONLY_DEFAULT=1
DOUYIN_ALLOW_WATERMARKED_FALLBACK=0
DOUYIN_LIVE_TESTS=0
```

Rollback từng flag không ảnh hưởng:

- Bilibili Trend Scout.
- Creator monitor 1 giờ.
- Browser downloader hiện tại.
- Pipeline vietsub/lồng tiếng hiện tại.

## 10. Definition of done

Chỉ coi hạng mục hoàn thành khi:

- OpenClaw scan/digest hiển thị Douyin và Bilibili với trạng thái nguồn độc lập.
- Douyin candidate có canonical URL thật, dedupe đúng và metric availability trung thực.
- Có ít nhất hai snapshot trước khi gắn nhãn growth/velocity.
- Resolver không log/lưu lâu dài signed CDN URL hoặc session data.
- `clean_only` fail closed; không đổi sang watermark ngầm.
- Golden live test xác nhận các mẫu clean bằng evidence và kiểm tra hình ảnh.
- Download accepted qua `ffprobe`, stream và duration gate.
- Unit/contract/integration test pass; live smoke report pass.
- Bilibili Trend Scout và creator monitor regression tests pass.
- Feature flags rollback được từng phần.
- Chỉ sau E2E được duyệt mới báo pipeline video thành công, với `final_video_vi.mp4` và toàn bộ gate subtitle/TTS hiện tại đạt yêu cầu.

## 11. Quyết định cần chốt trước khi code

1. Digest Telegram: một tin chung Bilibili + Douyin hay hai tin/two threads.
2. Policy mặc định khi không chứng minh được clean: fail job hay cho phép hỏi người dùng để fallback watermark.
3. Golden live URLs và quyền giữ/xóa các file tải thử.
4. Douyin provider dùng chung Trend Scout Postgres hiện tại hay storage adapter khác; mặc định đề xuất dùng chung.
5. Sau shortlist, download luôn cần xác nhận người dùng hay có allowlist creator/topic được auto-enqueue.
