---
name: series-compilation-orchestrator
description: Orchestrate deterministic, ordered compilation of a tracked video series through the OpenClaw host-runner, with explicit quality gates, branding confirmation, resumable jobs, and no credentials.
---

# Series compilation

Use this skill when a chat asks to list, download, compile, resume, inspect, or cancel
episodes of a tracked series. The detailed JSON schemas are in
[references/action-contracts.md](references/action-contracts.md).

## Natural-language workflow

1. Start with `series-list`; use `series-refresh` when the user wants the tracker
   refreshed before selecting episodes. Select with `all`, `range:N-M`, `list:N,M`,
   `latest:N` (and `latest` as the one-item shorthand), or `unprocessed`.
2. For selected episodes without a usable `final_video_vi.mp4`, queue each missing
   episode through the existing `series-download` action. Wait until download and
   localization quality gates pass; a non-empty subtitle or partial output is not
   sufficient. Do not compile failed or needs-attention episodes.
3. Always call `series-compilation-plan` and show its preview before
   `series-compilation-run`. Defaults are `max_seconds: 5400`, source order, and no
   splitting within an episode. Intro and outro are off by default, so a long
   compilation runs normally without branding. Only a queued or
   explicitly approved plan may run; `needs_attention` plans must be fixed and
   re-queued first.
4. Branding is opt-in: add the approved intro and outro only when the user
   explicitly requests personal branding. Each output part is exactly one intro,
   the selected episodes in source order, and one outro—never clips around each
   episode. For the known Bilibili uploader, the allowlisted
   `bilibili_top_left_block` profile covers the entire fixed top-left watermark
   block (Chinese uploader text plus Bilibili mark), scaled to the decoded video.
   Explicit pixel/time `overlay_regions` remain an API fallback, not the normal UI
   workflow. When branding is requested without them, the pipeline may run
   dependency-light local detection
   on each selected usable episode and proceeds only on high-confidence
   temporal/static evidence. Low confidence or missing title OCR returns
   `needs_attention` with preview frames and diagnostics; no blind blur is applied.
   Missing title OCR blocks the unknown/generic profile, but does not block the
   approved Bilibili fixed profile: its Chinese uploader watermark region is known
   and intentionally covered. Region times accept either `start`/`end` or `start_seconds`/`end_seconds`; labels
   are optional for blur-only or replacement-only regions.
5. Use `series-compilation-status` to report progress, `series-compilation-resume`
   to continue a paused/failed job after gates are fixed, and
   `series-compilation-cancel` to stop a job. Never claim completion until the
   final output exists and its quality gates pass.

Never ask for, print, persist, or put secrets in action payloads. Do not install
runtime packages. The basic FFmpeg pipeline is self-contained and must not depend on
HyperFrames. `scripts/hyperframes_adapter.py` is only a local availability check and
safe dry-run motion plan; it never executes shell commands.

For pure local state work, `scripts/series_compilation.py` supports `list` and `plan`.
The dashboard is monitoring-only: it reports job evidence and does not create
arbitrary overlay regions or profiles.
