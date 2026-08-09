# Ollama On-Demand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-click local Ollama setup to the Providers screen without granting Docker access to the web container.

**Architecture:** Extend the existing localhost host helper with one fixed Ollama install action. Reuse current provider and settings APIs from the browser after installation succeeds.

**Tech Stack:** Python stdlib, Docker Compose, vanilla JavaScript, Python unittest.

## Global Constraints

- Work only on branch `tool`.
- Bind helper only to `127.0.0.1:18794`.
- Accept no command, model, service, endpoint or path input.
- Do not expose Docker output, API keys, tokens or cookies.
- Fixed model: `qwen2.5:3b`.
- Fixed provider endpoint: `http://ollama:11434`.

---

### Task 1: Host Helper Ollama Action

**Files:**
- Modify: `tools/bilibili-host-login/helper.py`
- Modify: `web_tool/tests/test_host_login_helper.py`

- [x] Add failing tests for exact Compose commands and redacted failure output.
- [x] Verify tests fail.
- [x] Add fixed `POST /ollama/install` action.
- [x] Verify helper tests pass.

### Task 2: Providers Install Flow

**Files:**
- Modify: `web_tool/static/index.html`
- Modify: `web_tool/static/app.js`
- Modify: `web_tool/static/styles.css`
- Modify: `web_tool/tests/test_static_ui.py`

- [x] Add failing UI contract test.
- [x] Verify test fails.
- [x] Add install button, busy state, provider creation and default selection.
- [x] Verify static and full web tests pass.

### Task 3: Delivery

- [x] Rebuild Docker tool.
- [x] Restart host helper.
- [x] Run the real Ollama install action.
- [x] Confirm model `qwen2.5:3b`, provider creation and Doctor readiness.
- [x] Commit and push `origin/tool`.
