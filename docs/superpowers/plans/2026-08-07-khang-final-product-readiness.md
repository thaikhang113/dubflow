# Khang Final Product Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn branch `khang` into a user-testable Vietnamese video processing product with natural-language input, clear failures, protected runtime secrets, verified AI33 TTS, series compilation, and a completed HyperFrames book-video path.

**Architecture:** Keep current skill/host-runner boundaries. Fix shared URL, status, voice, and environment contracts in their existing modules. Add only a thin test-service wrapper and acceptance artifacts; do not create a second application tree or rewrite the media pipeline.

**Tech Stack:** Bash, Python 3, FFmpeg, systemd, AI33, Ollama/9Router, Chrome CDP, existing host-runner, existing series-compilation scripts, optional HyperFrames runtime.

## Global Constraints

- Never reuse or print the API key pasted in chat. Revoke it before testing.
- Secrets stay outside Git and outside job output.
- `EnvironmentFile` may load secrets into test services; source code must reference variable names only.
- Bilibili tracking query and fragment must be stripped before queueing.
- Transcript, OCR, translation, TTS, audio, subtitle, and final-video gates remain fail-closed.
- Natural-language input remains the user-facing API; internal actions stay allowlisted.
- No production service restart during test work.
- No HyperFrames dependency installation inside this repository.

## Current Readiness Matrix

| Requirement | Current state | Evidence | Action |
|---|---|---|---|
| Bilibili URL with `?vd_source=...` | Implemented on `khang` | `skills/bilibili-vietnamese-dubber/scripts/bilibili_cdp.py`, `test_url_normalization.py` | Run contract test on Linux host |
| ASR at roughly 98.6% coverage not rejected | Implemented | `choose_transcript_source.py`, transcript quality tests | Run regression with UTF-8 and host dependencies |
| OCR zero-result fallback | Implemented | `ocr_subtitle_transcript.py`, `test_ocr_diagnostic_retry.py` | Verify on real sample |
| Actionable dashboard/job failure | Partly implemented | `job_status.json`, `OPENCLAW_JOB_STATUS_JSON`, error codes | Verify dashboard consumes fields; add adapter only if missing |
| AI33 secret via machine environment | Pipeline supports env | `run.sh`, `ai33_tts_synthesize.py` | Add isolated test service and systemd `EnvironmentFile` |
| Ngọc Huyền voice | Alias contract exists, ID currently `vbee_hn_female_ngochuyen_full_48k-fhg` | Bilibili contracts/docs | Verify ID against AI33 response; do not assume `24k` ID |
| Natural-language series workflow | Skill contract exists | `series-compilation-orchestrator/SKILL.md` | Run full queue → gate → plan → compile acceptance test |
| HyperFrames book-video generation | Not implemented; only availability/dry-run adapter | `hyperframes_adapter.py` | Define smallest real book-video job and implement after pipeline gates |
| Final user test | Not done | No real AI33/Ollama/Chrome E2E evidence | Execute final acceptance run |

---

### Task 1: Revoke Exposed Credential and Freeze Secret Boundary

**Files:**
- Modify only external secret storage, not repository files.
- Inspect: `skills/douyin-vietnamese-dubber/run.sh`
- Inspect: `skills/douyin-vietnamese-dubber/ai33_tts_synthesize.py`

- [ ] Revoke the API key pasted in the chat provider console.
- [ ] Create a replacement secret outside the repository, for example `/home/haonguyen/.openclaw/config/khang-ai33.env`, with mode `0600`:

```dotenv
AI33_API_KEY=REPLACED_VALUE
```

- [ ] Confirm Git does not track the file:

```bash
git check-ignore -v /home/haonguyen/.openclaw/config/khang-ai33.env
git grep -n "sk_" -- ':!*.lock'
```

- [ ] Confirm logs do not contain the value:

```bash
grep -RIl --exclude-dir=.git --exclude='*.mp4' --exclude='*.wav' "REPLACED_VALUE" /home/haonguyen/.openclaw 2>/dev/null
```

**Acceptance:** Old key revoked; replacement exists only outside Git; no key value appears in source, logs, dashboard, or job artifacts.

### Task 2: Add Isolated Khang Test Service

**Files:**
- Create: `deploy/khang-test.service`
- Create: `deploy/khang-test.env.example`
- Create: `deploy/README.md`

- [ ] Define a service that loads `EnvironmentFile=/home/haonguyen/.openclaw/config/khang-ai33.env`.
- [ ] Point service to the checked-out `khang` runner and a dedicated test queue/output directory.
- [ ] Do not bind to the production queue or restart production services.
- [ ] Add a health command that reports only `ok`, provider availability, configured voice ID, and dependency status; never report secret values.
- [ ] Add a systemd verification sequence:

```bash
systemctl --user daemon-reload
systemctl --user restart khang-test.service
systemctl --user is-active khang-test.service
systemctl --user status khang-test.service --no-pager
```

**Acceptance:** Service starts with secret loaded, `systemctl status` shows no key, and production service state is unchanged.

### Task 3: Make Runtime Paths Portable and Testable

**Files:**
- Modify: `skills/douyin-vietnamese-dubber/voice_registry.py`
- Modify: `skills/series-tracker/series-tracker.py`
- Modify: test subprocess invocations that assume `bash` is directly on `PATH`
- Test: `skills/douyin-vietnamese-dubber/test_voice_registry.py`
- Test: `skills/series-tracker/test_series_tracker_state.py`

- [ ] Preserve Linux defaults while allowing explicit environment overrides.
- [ ] Ensure an empty `OPENCLAW_VOICE_REGISTRY_JSON` uses the Linux default path, not the current directory and not a Windows-normalized path.
- [ ] Run Python subprocess tests with `sys.executable` and explicit shell discovery where the test requires Bash.
- [ ] Keep production Bash behavior unchanged.

**Acceptance:** Python tests pass on Linux host; Windows static checks do not fail from `cp1252` output; no path default is written into repository state.

### Task 4: Verify and Harden Dashboard Error Mapping

**Files:**
- Inspect/modify host-runner dashboard bridge outside repository if that is the actual owner.
- Inspect: `skills/douyin-vietnamese-dubber/run.sh`
- Inspect: `skills/bilibili-vietnamese-dubber/run.sh`
- Test: `skills/bilibili-vietnamese-dubber/test_url_normalization.py`
- Test: `skills/douyin-vietnamese-dubber/test_transcript_quality.py`

- [ ] Trace `job_status.json` from pipeline failure to dashboard response.
- [ ] Preserve these fields end to end:

```json
{
  "state": "needs_attention",
  "phase": "transcript",
  "progress_percent": 58,
  "error_code": "TranscriptSourcesFailedQC",
  "error_message": "sanitized explanation",
  "reason": "retry or manual action",
  "retry_action": "retry_transcript",
  "artifacts": ["transcript_decision.json"]
}
```

- [ ] Reject generic `runner_failed` when a structured child error exists.
- [ ] Ensure dashboard displays the sanitized message and retry action without exposing paths, tokens, cookies, or raw provider response.

**Acceptance:** Forced transcript, OCR, translation, and AI33 failures each show a distinct actionable error, not only exit code 7.

### Task 5: Verify Ngọc Huyền AI33 Voice

**Files:**
- Modify: runtime voice registry outside Git, if needed.
- Inspect: `skills/douyin-vietnamese-dubber/voice_registry.py`
- Inspect: `skills/bilibili-vietnamese-dubber/run.sh`
- Test: `skills/bilibili-vietnamese-dubber/test_host_runner_bilibili_contract.py`

- [ ] Add the candidate voice ID to the runtime registry only after AI33 accepts it.
- [ ] Test both aliases:

```bash
python3 skills/douyin-vietnamese-dubber/voice_registry.py normalize-ai33 "Ngọc Huyền"
python3 skills/douyin-vietnamese-dubber/voice_registry.py normalize-ai33 "vbee_hn_female_ngochuyen_full_48k-fhg"
```

- [ ] Run one short AI33 synthesis using the replacement environment file.
- [ ] Verify WAV exists, duration is non-zero, sample rate is canonicalized to 48 kHz downstream, and no credential appears in stdout/stderr.
- [ ] Treat the `24k-st` ID from chat as unverified input; do not add it unless AI33 confirms it.

**Acceptance:** One real Vietnamese WAV from Ngọc Huyền passes provider, audio, and credential-redaction gates.

### Task 6: Run Real Transcript and Translation Regression

**Files:**
- No production code change unless a regression is found.
- Test: `skills/douyin-vietnamese-dubber/test_transcript_quality.py`
- Test: `skills/douyin-vietnamese-dubber/test_ocr_diagnostic_retry.py`
- Test: `skills/douyin-vietnamese-dubber/test_translation_cjk_gate.py`
- Test: `skills/douyin-vietnamese-dubber/test_transcript_source_separation.py`

- [ ] Run offline tests with UTF-8 output.
- [ ] Run one real sample through ASR and OCR only.
- [ ] Confirm transcript decision records separate:
  - `speech_timing_source`
  - `display_subtitle_timing`
  - `dub_tts_timing`
- [ ] Confirm empty OCR is classified as no visible subtitles or subsystem failure, not silently treated as success.
- [ ] Confirm 98.6% ASR coverage relaxation still records warning evidence.

**Acceptance:** No manual `transcript_vi.json` required for a sample with usable ASR and no usable OCR.

### Task 7: Run Real Ollama/9Router Translation

**Files:**
- Inspect: `skills/douyin-vietnamese-dubber/viet_dub_timing_optimizer.py`
- Inspect: `skills/douyin-vietnamese-dubber/run.sh`
- Test: existing optimizer and translation tests

- [ ] Run one short transcript through the configured translation route.
- [ ] Verify Vietnamese output is not CJK/source-identical.
- [ ] Verify retry/fallback yields `pending/manual_translate` with actionable status instead of fake Chinese output.
- [ ] Verify translation memory only uses sanitized text and configured series/genre IDs.

**Acceptance:** `vietnamese.srt` and `dub.srt` contain valid Vietnamese cues; translation failures stop before TTS with structured status.

### Task 8: Run Real TTS, Mix, Subtitle, and Final Video E2E

**Files:**
- No production code change unless a gate fails.
- Test: `skills/douyin-vietnamese-dubber/test_exact_sync_policy.py`
- Test: `skills/douyin-vietnamese-dubber/test_final_mix_quality.py`
- Test: `skills/douyin-vietnamese-dubber/test_voice_sync_overhang.py`
- Test: `skills/douyin-vietnamese-dubber/test_no_credentials_in_job_output.py`

- [ ] Process one short approved Bilibili URL with a tracking query.
- [ ] Use `Ngọc Huyền` voice.
- [ ] Verify canonical URL before download.
- [ ] Verify TTS coverage, 48 kHz canonical audio, final duration, subtitle render, and no CJK leakage.
- [ ] Verify final output exists:

```text
final_video_vi.mp4
voice_sync_quality_report.json
final_mix_quality_report.json
job_status.json
```

- [ ] Inspect final video manually for audio sync, subtitle readability, and Chinese subtitle masking.

**Acceptance:** One real job reaches `HOÀN TẤT` with all gates passing and no secret in output.

### Task 9: Validate Natural-Language Series Workflow

**Files:**
- Inspect: `skills/series-tracker/series-tracker.py`
- Inspect: `skills/series-compilation-orchestrator/SKILL.md`
- Inspect: `skills/series-compilation-orchestrator/scripts/compilation_job.py`
- Test: `skills/series-tracker/test_series_tracker_state.py`
- Test: `skills/series-compilation-orchestrator/scripts/test_compilation_job.py`

- [ ] Start with a natural-language request: identify series, refresh, select episodes.
- [ ] Queue only episodes without verified `final_video_vi.mp4`.
- [ ] Poll until every selected episode has passed localization gates.
- [ ] Generate and show compilation plan before run.
- [ ] Compile in source order with intro/outro disabled by default.
- [ ] Verify resume/cancel/status behavior.

**Acceptance:** User can say “tải series này, xử lý tiếng Việt, tổng hợp tập 1 đến 5” and receive a plan, progress, and verified final output without manually composing internal JSON.

### Task 10: Define Minimal HyperFrames Book-Video Deliverable

**Files:**
- Modify: `skills/series-compilation-orchestrator/scripts/hyperframes_adapter.py` only if runtime contract is available.
- Create: `skills/series-compilation-orchestrator/scripts/book_video_job.py`
- Test: `skills/series-compilation-orchestrator/scripts/test_book_video_job.py`
- Modify: `skills/series-compilation-orchestrator/SKILL.md`

- [ ] First confirm the actual HyperFrames runtime API and input/output contract on host.
- [ ] Implement only one deterministic path: source video + book assets + explicit motion regions → output video.
- [ ] Keep dry-run available when HyperFrames is absent.
- [ ] Fail closed on missing input/assets; do not fake HyperFrames success.
- [ ] Add a small fixture test for plan generation and artifact validation.

**Acceptance:** With HyperFrames installed, one book-video job creates a verified output; without it, status clearly says unavailable and does not claim completion.

### Task 11: Final Acceptance Checklist and Release Gate

**Files:**
- Create: `docs/acceptance/khang-final-product-checklist.md`
- Modify: `README_VI.md` only if user-facing commands changed.

- [ ] Record environment, commit SHA, service status, test URL hash, selected voice ID, and artifact paths.
- [ ] Do not record API key, cookies, signed CDN URLs, or raw browser profile paths.
- [ ] Run:

```bash
git status --short --branch
python3 -m compileall -q skills
find skills -name '*.sh' -print0 | xargs -0 bash -n
```

- [ ] Run all offline tests.
- [ ] Run one manual AI33 test.
- [ ] Run one manual Bilibili E2E.
- [ ] Run one manual series compilation.
- [ ] Run HyperFrames acceptance only when runtime exists.

**Acceptance:** Release is marked complete only when final video exists, all required gates pass, and every skipped item has an explicit reason.

## Execution Order

1. Task 1: revoke credential.
2. Task 2: isolated service.
3. Task 3: portability.
4. Task 4: dashboard mapping.
5. Tasks 5–8: single-video E2E.
6. Task 9: series workflow.
7. Task 10: HyperFrames book-video.
8. Task 11: final acceptance.

## Known Gaps

- Current repository has no `18793/test/manual` dashboard implementation.
- Current repository has no AI33 systemd test service.
- Current HyperFrames code is only an availability/dry-run adapter.
- Real AI33, Ollama/9Router, Chrome CDP, and production host-runner behavior cannot be proven from this Windows checkout.
- The first pasted AI33 key is compromised and must not be used.
