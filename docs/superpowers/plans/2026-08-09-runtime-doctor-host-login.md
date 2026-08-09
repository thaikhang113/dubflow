# Runtime Doctor And Host Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add workflow-based runtime diagnostics and one-click host Chrome Bilibili login to the existing local Docker web tool.

**Architecture:** Extend the current Doctor response instead of creating another diagnostics service. Add a stdlib host helper and a minimal Chrome extension that posts Bilibili cookies to the existing validated cookie import API.

**Tech Stack:** Python 3 stdlib, FastAPI, vanilla JavaScript/CSS, Chrome Manifest V3, existing Docker Compose.

## Global Constraints

- Work only on branch `tool`.
- Never return or log API key, Telegram token, cookie value or browser profile data.
- Bind helper to `127.0.0.1:18794`.
- Use a dedicated browser profile.
- Accept no arbitrary command, executable path, callback URL or filesystem path.
- Keep QR and manual Netscape cookie import.
- Use TDD.

---

### Task 1: Workflow Doctor

**Files:**
- Modify: `web_tool/integrations.py`
- Modify: `web_tool/app.py`
- Modify: `web_tool/tests/test_integrations.py`

- [x] Add failing tests for workflow status, missing key names and secret isolation.
- [x] Run `python -m unittest -v web_tool.tests.test_integrations` and verify RED.
- [x] Extend `runtime_doctor()` and pass current settings/login/Telegram state from the API.
- [x] Run the integration tests and verify GREEN.

### Task 2: Host Login Helper

**Files:**
- Create: `tools/bilibili-host-login/helper.py`
- Create: `tools/bilibili-host-login/start-bilibili-helper.ps1`
- Create: `tools/bilibili-host-login/start-bilibili-helper.sh`
- Create: `tools/bilibili-host-login/extension/manifest.json`
- Create: `tools/bilibili-host-login/extension/background.js`
- Create: `web_tool/tests/test_host_login_helper.py`

- [x] Add failing tests for local bind, CORS allowlist, fixed Chrome command and unsupported method.
- [x] Verify RED.
- [x] Implement the stdlib helper, scripts and extension.
- [x] Verify GREEN.

### Task 3: Web UI

**Files:**
- Modify: `web_tool/static/index.html`
- Modify: `web_tool/static/app.js`
- Modify: `web_tool/static/styles.css`
- Modify: `web_tool/tests/test_static_ui.py`

- [x] Add failing UI contract tests for Doctor workflow output, automatic load and host login button.
- [x] Verify RED.
- [x] Add structured checklist rendering and host-helper open flow.
- [x] Verify GREEN and run desktop/mobile browser QA.

### Task 4: Documentation And Delivery

**Files:**
- Modify: `README.md`
- Modify: this plan

- [x] Document Windows/Linux helper startup and security boundary.
- [x] Run full web/pipeline/Docker/security verification.
- [ ] Commit and push `origin/tool`.
