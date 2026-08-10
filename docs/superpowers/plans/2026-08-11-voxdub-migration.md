# VoxDub Migration Implementation Plan

> **For agentic workers:** Implement incrementally with tests before production code.

**Goal:** Replace old pipeline with VoxDub while preserving Bilibili login and adding a local OpenAI-compatible translation endpoint.

**Architecture:** VoxDub remains the desktop PySide pipeline. Translation uses authenticated `/models` discovery and `/chat/completions`; Bilibili cookies stay in a local Netscape cookie file and are injected into yt-dlp. Paraformer is preferred for Chinese, with existing Whisper fallback.

**Tech Stack:** Python 3.10+, requests, yt-dlp, PySide6, pytest, existing VoxDub components.

## Global Constraints

- Never log or commit API keys or cookie values.
- Keep MIT attribution from VoxDub.
- Keep existing cache, resume, TTS, subtitle, mix, and export behavior.
- Use smallest compatible change; no Docker/web rewrite.

### Task 1: Provider

- Add endpoint normalization, model discovery, chat completion, prompt builder, JSON parsing, retries.
- Add settings fields and tests.

### Task 2: Pipeline

- Route automatic translation through provider when configured.
- Keep analysis/review behavior using same provider.

### Task 3: Bilibili

- Add URL canonicalization and Netscape cookie validation.
- Inject configured cookie file into pipeline downloads.

### Task 4: GUI and defaults

- Expose provider endpoint/key/model and cookie file in settings.
- Make Paraformer default for Chinese while retaining fallback.

### Task 5: Verification

- Run focused tests, full pytest, compile smoke test, inspect staged diff for secrets.
