# Auto Hardware Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tu dong chon Ollama GPU hoac CPU theo GPU Docker that, hien ket qua tren web, va fallback CPU an toan.

**Architecture:** Host helper localhost phat hien NVIDIA/VRAM, chay Docker GPU smoke test, va recreate rieng service Ollama bang compose override co dinh. Backend luu mode, Doctor doc hardware status; web cho chon Auto/CPU/GPU va ap dung.

**Tech Stack:** Python stdlib, FastAPI, SQLite settings, Docker Compose, vanilla HTML/CSS/JS.

## Global Constraints

- CPU la fallback mac dinh; GPU loi khong lam job fail.
- Chi chap nhan `auto`, `cpu`, `gpu`.
- Khong chay command do request nguoi dung cung cap.
- Khong dua secret, cookie, token hoac output command vao API.
- Image hien tai giu Whisper, Demucs va render tren CPU.

---

### Task 1: Host hardware detector

**Files:**
- Modify: `tools/bilibili-host-login/helper.py`
- Modify: `web_tool/tests/test_host_login_helper.py`
- Create: `compose.gpu.yaml`

**Interfaces:**
- Produces: `detect_hardware(run=subprocess.run, docker=None) -> dict`
- Produces: `apply_hardware_mode(mode, run=subprocess.run, docker=None) -> dict`
- Produces: `GET /hardware`, `POST /hardware/apply`

- [ ] Add failing tests for no GPU, NVIDIA 4 GiB -> hybrid, NVIDIA 8 GiB -> gpu, Docker smoke failure -> cpu fallback, and fixed compose commands.
- [ ] Run `python -m unittest web_tool.tests.test_host_login_helper` and confirm failures.
- [ ] Implement parsing of fixed `nvidia-smi` CSV output, fixed Docker smoke command, persisted `~/.auto-vietsub/hardware.json`, and fixed compose CPU/GPU commands.
- [ ] Add `compose.gpu.yaml` with NVIDIA reservation only for `ollama`.
- [ ] Run focused tests and commit `feat: add automatic Ollama hardware profile`.

### Task 2: Backend settings and Doctor

**Files:**
- Modify: `web_tool/app.py`
- Modify: `web_tool/integrations.py`
- Modify: `web_tool/tests/test_api.py`
- Modify: `web_tool/tests/test_integrations.py`

**Interfaces:**
- Consumes: host helper `GET /hardware`
- Produces: settings fields `hardware_mode`, `hardware_profile`
- Produces: Doctor `checks.hardware` and hardware workflow

- [ ] Add failing API tests for allowlist and persistence.
- [ ] Add failing Doctor tests for selected profile, stage assignments, and fallback reason.
- [ ] Implement settings validation and a one-second host helper hardware read.
- [ ] Render hardware as a Doctor workflow without exposing raw command output.
- [ ] Run focused tests and commit `feat: expose hardware profile in Doctor`.

### Task 3: End-user web control

**Files:**
- Modify: `web_tool/static/index.html`
- Modify: `web_tool/static/app.js`
- Modify: `web_tool/static/styles.css`
- Modify: `web_tool/tests/test_static_ui.py`

**Interfaces:**
- Consumes: `/api/settings`, `/api/runtime/doctor`, host helper `/hardware/apply`
- Produces: select `settings-hardware-mode`, status `settings-hardware-status`, action `settings-hardware-detect`

- [ ] Add failing static UI contract tests.
- [ ] Add accessible select and detect/apply button in Settings.
- [ ] Apply through host helper, save returned profile through `/api/settings`, refresh Doctor, and show Vietnamese fallback reason.
- [ ] Verify keyboard layout and mobile wrapping with browser screenshot.
- [ ] Run focused tests and commit `feat: add automatic hardware controls`.

### Task 4: Verification and real Bilibili E2E

**Files:**
- Modify: `README.md`
- Modify: `web_tool/tests/test_docker_contract.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified Docker runtime and `final_video_vi.mp4`.

- [ ] Add Docker contract tests for GPU override and CPU-safe base compose.
- [ ] Document Auto/CPU/GPU and fallback.
- [ ] Run all web and pipeline tests, Bash syntax, compileall, secret scan, and `git diff --check`.
- [ ] Rebuild tool, start helper, apply Auto, verify RTX 3050 Ti resolves hybrid and Ollama reports GPU after model load.
- [ ] Submit `https://www.bilibili.com/video/BV1ATDoYAENJ?vd_source=24f7e90f90cc65d5c1f427f207ee3730&spm_id_from=333.788.videopod.sections`.
- [ ] Require completed state, decodable `final_video_vi.mp4`, AAC 48 kHz, translation/TTS/voice-sync/subtitle reports passing.
- [ ] Commit docs/tests and push `origin/tool`.

