# Personal Docker Web Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first Docker web application that preserves the repository's complete video, monitor, series, trend, provider, login, resume, and artifact workflows on Windows Docker Desktop and Linux.

**Architecture:** Add one FastAPI application service with a SQLite-backed FIFO queue, one scheduler, and one subprocess worker. Existing skill wrappers remain the source of pipeline behavior; the web layer validates user input, stores secrets outside job output, maps structured status artifacts, and exposes a vanilla web UI. Optional Compose profiles provide Ollama and Trend Scout Postgres.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, SQLite stdlib, Playwright/Chromium CDP, vanilla HTML/CSS/JavaScript, Docker Compose, existing Bash/Python/FFmpeg/Whisper/Demucs pipeline.

## Global Constraints

- Work only on branch `tool`.
- Bind web to `127.0.0.1:18793` by default.
- Process one queued video job at a time; keep AI33 internal worker cap at three.
- Preserve existing pipeline quality gates and wrappers instead of reimplementing media logic.
- Store API keys, cookies, and browser profiles in Docker-managed volumes outside Git and job output.
- Never return stored secret values from an API.
- Validate every platform, URL, endpoint, action, voice, model, upload, and artifact path at a trust boundary.
- Do not accept shell commands or arbitrary host paths.
- Do not bypass login, captcha, OTP, or 2FA.
- Keep HyperFrames availability/dry-run only.
- Use TDD for every behavior change.
- Run GitNexus impact/detect tools when available; this Windows checkout currently has no `.gitnexus/run.cjs`, so record Git diff/test evidence as fallback.

---

## File Structure

Create:

```text
web_tool/
  __init__.py             Package marker
  app.py                  FastAPI app, routes, lifespan, static mount
  config.py               Fixed paths and validated environment settings
  store.py                SQLite schema, queue, providers, channels, dedupe
  secrets.py              Secret file persistence and redaction
  pipeline.py             Allowlisted wrapper command construction/status mapping
  worker.py               Single subprocess worker, cancel, recovery
  monitor.py              Channel scheduler using existing discovery code
  bilibili_login.py       Chromium/CDP QR login and cookie persistence
  integrations.py         Series and Trend allowlisted adapters
  static/
    index.html            Usable application shell
    app.js                API client, views, SSE updates, forms
    styles.css             Responsive operational UI
  tests/
    __init__.py
    test_config.py
    test_store.py
    test_secrets.py
    test_pipeline.py
    test_worker.py
    test_api.py
    test_static_ui.py
    test_monitor.py
    test_bilibili_login.py
    test_integrations.py
    test_docker_contract.py
    test_end_to_end.py
    fixtures/
      fake_pipeline.py
requirements-web.txt
Dockerfile
compose.yaml
.dockerignore
docker/
  entrypoint.sh
  healthcheck.py
```

Modify:

```text
README.md
.gitignore
```

---

### Task 1: Web Application and Runtime Configuration

**Files:**
- Create: `web_tool/__init__.py`
- Create: `web_tool/config.py`
- Create: `web_tool/app.py`
- Create: `web_tool/static/index.html`
- Create: `web_tool/static/app.js`
- Create: `web_tool/static/styles.css`
- Create: `web_tool/tests/__init__.py`
- Create: `web_tool/tests/test_config.py`
- Create: `requirements-web.txt`

**Interfaces:**
- Produces: `Settings.from_env() -> Settings`
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`
- Produces: `GET /api/health -> {"ok": true, "version": 1}`

- [ ] **Step 1: Write failing configuration and health tests**

```python
# web_tool/tests/test_config.py
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from web_tool.app import create_app
from web_tool.config import Settings


class ConfigTests(unittest.TestCase):
    def test_settings_create_private_runtime_directories(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"TOOL_ROOT": tmp, "TOOL_BIND_HOST": "127.0.0.1"}, clear=False
        ):
            settings = Settings.from_env()
            self.assertEqual(Path(tmp), settings.root)
            for path in (
                settings.data_dir,
                settings.secrets_dir,
                settings.jobs_dir,
                settings.output_dir,
                settings.models_dir,
                settings.browser_dir,
            ):
                self.assertTrue(path.is_dir())

    def test_health_endpoint_uses_local_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Settings.for_test(Path(tmp)))
            response = TestClient(app).get("/api/health")
            self.assertEqual(200, response.status_code)
            self.assertEqual({"ok": True, "version": 1}, response.json())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m unittest -v web_tool.tests.test_config
```

Expected: import failure because `web_tool.app` and `web_tool.config` do not exist.

- [ ] **Step 3: Implement validated settings and minimal app**

`Settings` must be a frozen dataclass with fields `root`, `data_dir`,
`secrets_dir`, `jobs_dir`, `output_dir`, `models_dir`, `browser_dir`,
`database_path`, `bind_host`, `bind_port`, and `repo_root`. It must implement
the exact public constructors `Settings.from_env() -> Settings` and
`Settings.for_test(root: Path) -> Settings`; both constructors create the six
runtime directories before returning.

Validation:

- `TOOL_BIND_HOST` defaults to `127.0.0.1`.
- `TOOL_BIND_PORT` defaults to `18793` and must be `1..65535`.
- Runtime directories are children of `TOOL_ROOT`.
- `repo_root` is the repository containing `skills/`.

`create_app()` must mount `web_tool/static`, return JSON health, and serve
`index.html` at `/`.

- [ ] **Step 4: Add exact web dependencies**

```text
fastapi==0.116.1
uvicorn[standard]==0.35.0
python-multipart==0.0.20
playwright==1.54.0
httpx==0.28.1
yt-dlp
edge-tts
```

- [ ] **Step 5: Run GREEN checks**

```powershell
python -m unittest -v web_tool.tests.test_config
python -m compileall -q web_tool
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add web_tool requirements-web.txt
git commit -m "feat: add local web tool application"
```

---

### Task 2: Durable SQLite Queue

**Files:**
- Create: `web_tool/store.py`
- Create: `web_tool/tests/test_store.py`
- Modify: `web_tool/app.py`

**Interfaces:**
- Produces: `Store(path: Path)`
- Produces: `Store.enqueue_job(request: dict) -> dict`
- Produces: `Store.claim_next_job() -> dict | None`
- Produces: `Store.update_job(job_id: str, **fields) -> dict`
- Produces: `Store.recover_running_jobs() -> int`
- Produces: `Store.set_queue_paused(paused: bool) -> None`

- [ ] **Step 1: Write failing FIFO, single-claim, and restart tests**

```python
# web_tool/tests/test_store.py
import tempfile
import unittest
from pathlib import Path

from web_tool.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "tool.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_fifo_claim_allows_one_running_job(self):
        first = self.store.enqueue_job({"platform": "bilibili", "source": "https://www.bilibili.com/video/BV1"})
        second = self.store.enqueue_job({"platform": "douyin", "source": "https://www.douyin.com/video/2"})
        claimed = self.store.claim_next_job()
        self.assertEqual(first["id"], claimed["id"])
        self.assertIsNone(self.store.claim_next_job())
        self.store.update_job(first["id"], state="completed")
        self.assertEqual(second["id"], self.store.claim_next_job()["id"])

    def test_restart_recovery_requires_resume(self):
        job = self.store.enqueue_job({"platform": "bilibili", "source": "https://www.bilibili.com/video/BV1"})
        self.store.claim_next_job()
        self.assertEqual(1, self.store.recover_running_jobs())
        recovered = self.store.get_job(job["id"])
        self.assertEqual("needs_attention", recovered["state"])
        self.assertEqual("resume", recovered["action"])

    def test_paused_queue_does_not_claim(self):
        self.store.enqueue_job({"platform": "bilibili", "source": "https://www.bilibili.com/video/BV1"})
        self.store.set_queue_paused(True)
        self.assertIsNone(self.store.claim_next_job())
```

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest -v web_tool.tests.test_store
```

Expected: `ModuleNotFoundError: web_tool.store`.

- [ ] **Step 3: Implement schema and atomic claim**

Use SQLite tables:

```sql
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  state TEXT NOT NULL,
  action TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL,
  source TEXT NOT NULL,
  request_json TEXT NOT NULL,
  job_dir TEXT NOT NULL DEFAULT '',
  pid INTEGER,
  error_code TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL DEFAULT '',
  progress INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

`claim_next_job()` must use `BEGIN IMMEDIATE`, refuse a second claim while any
job is `running`, and claim the oldest `queued` row by `created_at, id`.

- [ ] **Step 4: Run GREEN and concurrency checks**

```powershell
python -m unittest -v web_tool.tests.test_store
```

Expected: all tests pass and no two claims return jobs concurrently.

- [ ] **Step 5: Wire store lifecycle**

`create_app()` must create one `Store`, call `recover_running_jobs()` during
lifespan startup, and expose it as `app.state.store`.

- [ ] **Step 6: Commit**

```powershell
git add web_tool/store.py web_tool/tests/test_store.py web_tool/app.py
git commit -m "feat: add durable single-worker job queue"
```

---

### Task 3: Provider Profiles and Secret Persistence

**Files:**
- Create: `web_tool/secrets.py`
- Create: `web_tool/tests/test_secrets.py`
- Modify: `web_tool/store.py`
- Modify: `web_tool/app.py`

**Interfaces:**
- Produces: `SecretStore(root: Path)`
- Produces: `SecretStore.write(name: str, value: str) -> Path`
- Produces: `SecretStore.environment(profile_id: str) -> dict[str, str]`
- Produces: `sanitize(value: str) -> str`
- API: `GET/POST/DELETE /api/providers`
- API: `POST /api/providers/{id}/test`

- [ ] **Step 1: Write failing secret and provider tests**

Tests must prove:

```python
secret_store.write("provider-main", "super-secret")
assert secret_store.read_status("provider-main") == {"configured": True}
assert "super-secret" not in repr(secret_store.read_status("provider-main"))
assert sanitize("Authorization: Bearer super-secret") == "Authorization: Bearer <redacted>"
```

Provider validation cases:

- allow `http://host.docker.internal:11434`;
- allow `https://api.example.com/v1`;
- reject `file:///etc/passwd`;
- reject endpoint credentials such as `https://user:pass@example.com`;
- reject unknown kind;
- never include key in GET response.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest -v web_tool.tests.test_secrets
```

- [ ] **Step 3: Implement file secrets and provider metadata**

Use secret file names derived from UUID profile IDs, never user-supplied paths.
Write via temporary file plus `os.replace`; use mode `0o600` where supported.

Add SQLite table:

```sql
CREATE TABLE IF NOT EXISTS providers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  timeout_seconds INTEGER NOT NULL DEFAULT 90,
  has_secret INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Connection tests use stdlib `urllib.request`, bounded timeout, sanitized errors,
and provider-specific paths:

- Ollama: `GET /api/tags`
- OpenAI-compatible: `GET /models`
- AI33: endpoint connectivity only unless provider exposes a non-billable health path

- [ ] **Step 4: Run GREEN**

```powershell
python -m unittest -v web_tool.tests.test_secrets
```

- [ ] **Step 5: Commit**

```powershell
git add web_tool/secrets.py web_tool/store.py web_tool/app.py web_tool/tests/test_secrets.py
git commit -m "feat: add persistent provider profiles"
```

---

### Task 4: Pipeline Command Adapter and Single Worker

**Files:**
- Create: `web_tool/pipeline.py`
- Create: `web_tool/worker.py`
- Create: `web_tool/tests/test_pipeline.py`
- Create: `web_tool/tests/test_worker.py`
- Modify: `web_tool/app.py`

**Interfaces:**
- Produces: `build_job_command(job: dict, settings: Settings) -> list[str]`
- Produces: `build_job_environment(job: dict, providers: dict, settings: Settings) -> dict[str, str]`
- Produces: `read_job_status(job_dir: Path) -> dict`
- Produces: `Worker.start()`, `Worker.stop()`, `Worker.cancel(job_id: str) -> bool`

- [ ] **Step 1: Write failing command allowlist tests**

Expected commands:

```python
assert build_job_command(
    {"platform": "bilibili", "source": "https://www.bilibili.com/video/BV1"},
    settings,
) == ["bash", str(settings.repo_root / "skills/bilibili-vietnamese-dubber/run.sh"), "https://www.bilibili.com/video/BV1"]
```

Reject:

- unsupported platform;
- URL with username/password or invalid host;
- local path outside the server-created upload directory;
- source containing newline or NUL;
- resume directory outside `jobs_dir`.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest -v web_tool.tests.test_pipeline web_tool.tests.test_worker
```

- [ ] **Step 3: Implement adapter**

Environment mapping must include only validated values and secret data loaded
inside the worker process:

```text
OPENCLAW_AI_PROVIDER
OPENCLAW_AI_API_BASE
OPENCLAW_AI_MODEL
AI33_API_BASE
AI33_API_KEY
VOICE
AI33_TTS_WORKERS=3
BASE_ROOT
WHISPER_DIR
WHISPER_BIN
WHISPER_MODEL
CHROME_CDP_URL=http://127.0.0.1:9222
```

Never persist the expanded environment in SQLite or logs.

- [ ] **Step 4: Implement worker process lifecycle**

Requirements:

- poll queue with a condition/event, not a busy loop;
- create a process group/session;
- redirect stdout/stderr to job-local `log.txt`;
- discover published output directory from `LATEST_OUTPUT_DIR.txt`;
- refresh database status from `job_status.json`;
- success requires exit `0` and decodable non-empty `final_video_vi.mp4`;
- cancel terminates process group, waits, then kills after a bounded grace period;
- preserve job directory/checkpoint;
- shutdown leaves current job recoverable.

- [ ] **Step 5: Run GREEN**

Use a temporary fake wrapper that writes status and a small fixture file:

```powershell
python -m unittest -v web_tool.tests.test_pipeline web_tool.tests.test_worker
```

- [ ] **Step 6: Commit**

```powershell
git add web_tool/pipeline.py web_tool/worker.py web_tool/tests/test_pipeline.py web_tool/tests/test_worker.py web_tool/app.py
git commit -m "feat: run pipeline jobs through durable worker"
```

---

### Task 5: Job API, Status Streaming, Resume, Cancel, and Artifacts

**Files:**
- Create: `web_tool/tests/test_api.py`
- Modify: `web_tool/app.py`
- Modify: `web_tool/store.py`
- Modify: `web_tool/worker.py`

**Interfaces:**
- API: `GET/POST /api/jobs`
- API: `GET /api/jobs/{id}`
- API: `POST /api/jobs/{id}/cancel`
- API: `POST /api/jobs/{id}/resume`
- API: `POST /api/jobs/{id}/retry`
- API: `POST /api/queue/pause`
- API: `POST /api/queue/resume`
- API: `GET /api/events`
- API: `GET /api/jobs/{id}/artifacts/{name}`

- [ ] **Step 1: Write failing API contract tests**

Tests must verify:

- create returns `201` and sanitized job;
- invalid Bilibili/Douyin URL returns `422`;
- list order is newest first;
- resume uses same job directory and creates a queued resume execution;
- retry creates a new job linked by `retry_of`;
- artifact traversal `../../secret` returns `404`;
- cookies, `.env`, browser profile, provider state secrets, and arbitrary logs are not downloadable;
- SSE emits a job state event after update.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest -v web_tool.tests.test_api
```

- [ ] **Step 3: Implement API and event broker**

Use an in-process subscriber set of bounded `asyncio.Queue` objects. Publish only
sanitized job snapshots. Send a keepalive comment every 15 seconds.

Artifact allowlist:

```python
ARTIFACTS = {
    "final_video_vi.mp4",
    "vietnamese.srt",
    "dub.srt",
    "thumbnail.jpg",
    "voice_sync_quality_report.json",
    "final_mix_quality_report.json",
    "bilibili_branding_proof.json",
}
```

- [ ] **Step 4: Run GREEN**

```powershell
python -m unittest -v web_tool.tests.test_api
```

- [ ] **Step 5: Commit**

```powershell
git add web_tool/app.py web_tool/store.py web_tool/worker.py web_tool/tests/test_api.py
git commit -m "feat: expose queue and job control api"
```

---

### Task 6: End-User Jobs and Providers Interface

**Files:**
- Modify: `web_tool/static/index.html`
- Modify: `web_tool/static/app.js`
- Modify: `web_tool/static/styles.css`
- Create: `web_tool/tests/test_static_ui.py`

**Interfaces:**
- Consumes APIs from Tasks 3 and 5.
- Produces visible Jobs and Providers screens.

- [ ] **Step 1: Write failing static UI contract test**

Assert HTML/JS contains:

```text
data-view="jobs"
data-view="providers"
id="new-job-form"
id="provider-form"
id="queue-pause"
id="job-list"
new EventSource("/api/events")
```

Assert no landing-page hero, API-key value echo, raw log HTML injection, or
inline secret serialization.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest -v web_tool.tests.test_static_ui
```

- [ ] **Step 3: Implement operational UI**

Required behavior:

- sidebar navigation;
- create job form with URL/file, platform, provider, model, voice, preset;
- queue rows with status, progress, created time and contextual actions;
- job detail with structured error and artifact links;
- provider create/update/delete/test form;
- API key field clears after save and displays only `configured`;
- SSE refresh plus polling fallback;
- HTML escaping through DOM `textContent`, never untrusted `innerHTML`;
- responsive layout without nested cards or decorative landing content.

- [ ] **Step 4: Run GREEN**

```powershell
python -m unittest -v web_tool.tests.test_static_ui
```

- [ ] **Step 5: Commit**

```powershell
git add web_tool/static web_tool/tests/test_static_ui.py
git commit -m "feat: add jobs and provider web interface"
```

---

### Task 7: Bilibili QR Login and Cookie Import

**Files:**
- Create: `web_tool/bilibili_login.py`
- Create: `web_tool/tests/test_bilibili_login.py`
- Modify: `web_tool/app.py`
- Modify: `web_tool/static/index.html`
- Modify: `web_tool/static/app.js`
- Modify: `web_tool/static/styles.css`

**Interfaces:**
- Produces: `BilibiliLogin(settings, secret_store)`
- Produces: `login.start() -> dict`
- Produces: `login.qr_png() -> bytes`
- Produces: `login.status() -> dict`
- Produces: `login.import_netscape(text: str) -> dict`
- API: `/api/bilibili/login/start`, `/qr`, `/status`, `/cookies`

- [ ] **Step 1: Write failing cookie validation tests**

Validate:

- Netscape header required;
- every cookie domain is `bilibili.com` or subdomain;
- at least one of `SESSDATA`, `DedeUserID`, `bili_jct` marks login;
- cookie values never appear in status or exception text;
- malformed lines and files over 1 MiB fail.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest -v web_tool.tests.test_bilibili_login
```

- [ ] **Step 3: Implement QR login**

Use Playwright to connect to `http://127.0.0.1:9222`, open a dedicated Bilibili
login page, locate the visible QR element, and screenshot only that element.
Poll context cookies; write Netscape output atomically to
`settings.secrets_dir / "bilibili-cookies.txt"`.

No captcha solving. A captcha page returns:

```json
{"state":"needs_attention","error_code":"BilibiliCaptchaRequired"}
```

- [ ] **Step 4: Add UI**

The Bilibili Login view must show:

- start login button;
- QR image;
- login state and last check;
- upload/paste fallback;
- clear login button that deletes only container cookie/profile state after confirmation.

- [ ] **Step 5: Run GREEN**

```powershell
python -m unittest -v web_tool.tests.test_bilibili_login web_tool.tests.test_static_ui
```

- [ ] **Step 6: Commit**

```powershell
git add web_tool/bilibili_login.py web_tool/tests/test_bilibili_login.py web_tool/app.py web_tool/static
git commit -m "feat: add Bilibili QR login"
```

---

### Task 8: Channel Monitor Scheduler and Auto-Enqueue

**Files:**
- Create: `web_tool/monitor.py`
- Create: `web_tool/tests/test_monitor.py`
- Modify: `web_tool/store.py`
- Modify: `web_tool/app.py`
- Modify: `web_tool/static/index.html`
- Modify: `web_tool/static/app.js`

**Interfaces:**
- Produces: `MonitorScheduler(store, settings)`
- Produces: `run_channel_once(channel_id: str) -> dict`
- API: `GET/POST/DELETE /api/channels`
- API: `POST /api/channels/{id}/run`
- API: `POST /api/channels/{id}/enable`
- API: `POST /api/channels/{id}/disable`

- [ ] **Step 1: Write failing scheduler tests**

Tests must use a fake discovery function and prove:

- due channel is checked once;
- two discoveries of the same platform/video ID enqueue once;
- new video inherits provider, model, voice, series and preset;
- disabled channel does not run;
- login/captcha marks channel `needs_attention`;
- scheduler restart does not duplicate already seen videos.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest -v web_tool.tests.test_monitor
```

- [ ] **Step 3: Implement channel tables**

```sql
CREATE TABLE IF NOT EXISTS channels (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  platform TEXT NOT NULL,
  url TEXT NOT NULL,
  interval_minutes INTEGER NOT NULL,
  enabled INTEGER NOT NULL,
  provider_id TEXT,
  model TEXT NOT NULL DEFAULT '',
  voice TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '',
  preset_json TEXT NOT NULL DEFAULT '{}',
  next_check_at TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'ready',
  error_code TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS seen_videos (
  platform TEXT NOT NULL,
  video_id TEXT NOT NULL,
  source_url TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  PRIMARY KEY(platform, video_id)
);
```

- [ ] **Step 4: Reuse existing discovery**

Dynamically import `skills/content-monitor/content-monitor.py` and call
`fetch_latest_videos_for_channel(channel, count=10)`. Override its state/log/CDP
paths through environment before import. Do not launch its infinite daemon;
Docker scheduler owns timing.

- [ ] **Step 5: Add Channels UI**

Provide channel list, add/edit form, interval, provider/model/voice/series,
enable/disable, run now, last result and next check.

- [ ] **Step 6: Run GREEN**

```powershell
python -m unittest -v web_tool.tests.test_monitor web_tool.tests.test_static_ui
```

- [ ] **Step 7: Commit**

```powershell
git add web_tool/monitor.py web_tool/store.py web_tool/app.py web_tool/static web_tool/tests/test_monitor.py
git commit -m "feat: add channel monitoring queue"
```

---

### Task 9: Series, Trend, Telegram, and Runtime Settings

**Files:**
- Create: `web_tool/integrations.py`
- Create: `web_tool/tests/test_integrations.py`
- Modify: `web_tool/app.py`
- Modify: `web_tool/static/index.html`
- Modify: `web_tool/static/app.js`

**Interfaces:**
- Produces: `run_series_action(action: str, payload: dict, settings: Settings) -> dict`
- Produces: `run_trend_action(action: str, payload: dict, settings: Settings) -> dict`
- API: `/api/series/*`
- API: `/api/trend/*`
- API: `GET/PUT /api/settings`
- API: `GET /api/runtime/doctor`
- API: `POST /api/telegram/test`
- API: `GET /api/hyperframes/status`

- [ ] **Step 1: Write failing allowlist tests**

Series allowlist:

```text
list, show, add, remove, update, find-episodes, plan, status, resume, compile
```

Trend allowlist:

```text
scan, status, top-candidates, topic-details, video-risk, collection-tick
```

Reject arbitrary action, payload path, shell metacharacter, oversized query,
unsupported scan days, and compile path outside tool volumes.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest -v web_tool.tests.test_integrations
```

- [ ] **Step 3: Implement series adapter**

Invoke existing commands with fixed arguments, for example:

```text
python3 skills/series-tracker/series-tracker.py list
python3 skills/series-tracker/series-tracker.py refresh SERIES_ID --limit 500
python3 skills/series-compilation-orchestrator/scripts/series_compilation.py list --state /data/series/series.json --series-id SERIES_ID
python3 skills/series-compilation-orchestrator/scripts/series_compilation.py plan --state /data/series/series.json --series-id SERIES_ID --selector all
python3 skills/series-compilation-orchestrator/scripts/compilation_job.py status --payload /data/jobs/compilation/JOB/payload.json
```

Use fixed argument construction only. Parse JSON output; sanitize stderr.

- [ ] **Step 4: Implement trend adapter**

Trend tab reports `configured: false` until database endpoint and required
runtime are available. Once configured, invoke only fixed Trend Scout actions
and preserve scan mode/day validation from existing contracts.

- [ ] **Step 5: Add Series and Trend UI**

Series view: series list, episodes, missing items, plan/compile/resume.

Trend view: query, mode, days, scan status, candidates, details, risk.

- [ ] **Step 6: Add Settings and optional integration status**

Settings view must expose:

- queue interval and default provider/model/voice;
- AI33 worker display fixed at three;
- output export and runtime volume status;
- thumbnail/Google Flow availability and latest safe report status;
- Telegram bot token stored through `SecretStore`, chat ID stored as metadata, and
  a sanitized test-send result;
- HyperFrames availability/dry-run status only;
- doctor checks for FFmpeg, Chromium, yt-dlp, Whisper, Demucs, Ollama endpoint,
  writable volumes and configured providers.

The Telegram token must never appear in `GET /api/settings`, SQLite, status,
logs, or test response.

- [ ] **Step 7: Run GREEN**

```powershell
python -m unittest -v web_tool.tests.test_integrations web_tool.tests.test_static_ui
```

- [ ] **Step 8: Commit**

```powershell
git add web_tool/integrations.py web_tool/app.py web_tool/static web_tool/tests/test_integrations.py
git commit -m "feat: expose series trend and runtime settings"
```

---

### Task 10: Docker Image, Compose, Chromium, Doctor, and Volumes

**Files:**
- Create: `Dockerfile`
- Create: `compose.yaml`
- Create: `.dockerignore`
- Create: `docker/entrypoint.sh`
- Create: `docker/healthcheck.py`
- Create: `web_tool/tests/test_docker_contract.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `docker compose up -d tool`
- Produces: `GET http://127.0.0.1:18793/api/health`

- [ ] **Step 1: Write failing Docker contract test**

Test source must assert:

- service name `tool`;
- port mapping binds `127.0.0.1:18793`;
- six named volumes;
- `init: true`;
- healthcheck exists;
- Chromium remote debug remains container-local;
- no API key/cookie value in Compose;
- optional `ollama` and `trend-db` profiles;
- entrypoint uses `exec`, not background orphaning.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest -v web_tool.tests.test_docker_contract
```

- [ ] **Step 3: Implement image**

Base:

```dockerfile
FROM python:3.11-bookworm
```

Install apt packages:

```text
bash ca-certificates chromium cmake curl ffmpeg git libgl1 libglib2.0-0
procps tini
```

Install `requirements-web.txt`, `demucs`, and `inaSpeechSegmenter`. Build
whisper.cpp CLI in `/opt/whisper.cpp`; store downloaded model in
`/models/whisper` at runtime, not image layer.

Create non-root user and grant write access only to runtime volume mount points.

- [ ] **Step 4: Implement entrypoint**

Entrypoint:

1. validates writable volumes;
2. launches Chromium with profile `/data/browser` and CDP on `127.0.0.1:9222`;
3. runs a doctor report without printing secrets;
4. execs Uvicorn:

```bash
exec uvicorn web_tool.app:create_app --factory --host "${TOOL_BIND_HOST:-0.0.0.0}" --port "${TOOL_BIND_PORT:-18793}"
```

Compose maps host `127.0.0.1:18793` to container `18793`.

- [ ] **Step 5: Implement optional profiles**

`ollama` uses official Ollama image and `tool-models`-independent model volume.

`trend-db` uses PostgreSQL with password supplied through a local secret file,
not committed Compose defaults.

- [ ] **Step 6: Run Docker validation**

```powershell
python -m unittest -v web_tool.tests.test_docker_contract
docker compose config
docker build -t auto-vietsub-tool:test .
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add Dockerfile compose.yaml .dockerignore docker .gitignore web_tool/tests/test_docker_contract.py
git commit -m "feat: package web tool with Docker Compose"
```

---

### Task 11: Runtime Acceptance Fixtures, Browser Verification, and Documentation

**Files:**
- Create: `web_tool/tests/fixtures/fake_pipeline.py`
- Create: `web_tool/tests/test_end_to_end.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-08-docker-web-tool.md`

**Interfaces:**
- Proves the design success criteria except paid/external provider quality.

- [ ] **Step 1: Add fake pipeline integration fixture**

Fixture must:

- emit structured `job_status.json` phases;
- create a small decodable MP4 using FFmpeg;
- support a forced failure with `failed_cue` and `resume_from_cue`;
- resume from the same job directory;
- trap termination and preserve checkpoint.

- [ ] **Step 2: Write end-to-end API tests**

Cover:

1. create two jobs;
2. verify only one runs;
3. first completes with downloadable MP4;
4. second fails and exposes structured error;
5. resume second and complete;
6. restart app/store and retain history;
7. provider secret never appears in responses, DB, log, or artifacts;
8. channel discovery enqueues once;
9. series/trend disabled state is explicit when dependency absent.

- [ ] **Step 3: Run full portable suite**

```powershell
$env:PYTHONUTF8='1'
python -m unittest discover -s web_tool/tests -v
python -m compileall -q web_tool skills
python -m unittest -v skills.bilibili-vietnamese-dubber.test_url_normalization
docker compose config
git diff --check
```

Run existing script-style tests from their directories where module names with
hyphens prevent package import.

- [ ] **Step 4: Start local server and verify UI**

```powershell
python -m uvicorn web_tool.app:create_app --factory --host 127.0.0.1 --port 18793
```

Use browser automation at desktop `1440x900` and mobile `390x844`:

- Jobs screen visible without overlap;
- provider form saves and clears secret input;
- two queued jobs remain stable;
- job detail updates through SSE;
- cancel/resume buttons match state;
- Channels, Series, Trend, Login and Settings views open;
- longest Vietnamese labels fit their controls.

- [ ] **Step 5: Validate container runtime**

```powershell
docker compose up -d --build tool
docker compose ps
curl.exe http://127.0.0.1:18793/api/health
docker compose restart tool
curl.exe http://127.0.0.1:18793/api/health
```

Verify queue/provider/login metadata persists. Real API keys and cookies are not
required for this offline acceptance.

- [ ] **Step 6: Document end-user setup**

README must include:

- Windows Docker Desktop steps;
- Linux Docker/Compose steps;
- first-run wizard;
- host Ollama endpoint values;
- optional Compose Ollama/Trend profiles;
- QR login and cookie fallback;
- volume backup/export;
- CPU/GPU expectations;
- update/restart commands;
- exact limitations for HyperFrames, Google Flow, captcha and external quotas.

- [ ] **Step 7: Run security scan and final verification**

```powershell
git grep -n -E 'sk_[A-Za-z0-9]{20,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY'
python skills/douyin-vietnamese-dubber/test_no_credentials_in_job_output.py
git status --short --branch
```

Expected: no credential match, tests pass, only intended plan checkbox edits
remain.

- [ ] **Step 8: Commit and push**

```powershell
git add README.md web_tool/tests docs/superpowers/plans/2026-08-08-docker-web-tool.md
git commit -m "test: verify Docker web tool workflows"
git push origin tool
```

---

## Completion Audit

Before declaring complete, collect evidence for every spec success criterion:

| Requirement | Evidence |
|---|---|
| One Compose command and local web | successful `docker compose up`, health response, browser screenshot |
| Persistent provider endpoint/key/model | restart integration test and volume inspection without printing secret |
| QR login/manual cookies | mocked contract test plus real Chromium QR test when Bilibili is reachable |
| Video/channel/series without terminal | browser workflow tests for all three views |
| Monitor auto-enqueue with Ollama/provider preset | scheduler integration test |
| Structured errors and checkpoint resume | fake pipeline fail/resume E2E |
| Full existing pipeline preserved | wrapper command tests plus existing pipeline regression suite |
| Windows and Linux portability | Compose config/build on Windows; Linux CI/runtime required before broad portability claim |
| Final real video | Linux runtime E2E with decoded `final_video_vi.mp4`; do not claim until executed |
| No secret leakage | API/DB/log/artifact tests and credential scan |

Do not mark the goal complete while Linux container runtime or real final-video
acceptance remains unverified.
