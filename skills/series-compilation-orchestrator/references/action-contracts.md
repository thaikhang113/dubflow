# Host-runner action contracts

Invoke `/home/node/host-bin/openclaw-call-host-runner.sh ACTION JSON` and parse the
JSON object in the returned `stdout`. Treat non-JSON stdout, non-zero exit, or an
`ok:false` response as failure. Payloads contain paths and identifiers only—never
tokens, cookies, API keys, or environment secrets.

All responses use this envelope (action-specific fields are additional):

```json
{"ok":true,"action":"series-list","request_id":"...","status":"ok"}
```

The exact action payloads are:

```json
{"action":"series-list","series_id":"optional-id"}
{"action":"series-refresh","series_id":"optional-id","limit":500}
{"action":"series-download","series_id":"series-id","episode_numbers":[1,2],"selector":"optional-selector","wait_for_quality_gates":true}
{"action":"series-compilation-plan","compilation_id":"safe-id","series_id":"series-id","selector":"all","max_seconds":5400,"order":"source","split_episodes":false,"include_intro":false,"include_outro":false,"branding":{},"overlay_regions":[]}
{"action":"series-compilation-run","compilation_id":"safe-id"}
{"action":"series-compilation-status","compilation_id":"safe-id"}
{"action":"series-compilation-resume","compilation_id":"safe-id"}
{"action":"series-compilation-cancel","compilation_id":"safe-id"}
```

## Single Bilibili processing

For one known Bilibili video, OpenClaw must show a plan and receive confirmation
before queuing the potentially long-running job. Then it may invoke only this
strict payload (no unknown keys):

```json
{"action":"bilibili-process","url":"https://www.bilibili.com/video/BV...","voice":"Ngọc Huyền","branding":{"enabled":true,"profile":"bilibili_top_left_block","blur_uploader_block":true,"replace_logo":true,"include_intro":true,"include_outro":true}}
```

Top-level keys are exactly `action`, `url`, `voice`, and optional `branding`.
`branding` allows exactly `enabled`, `profile`, `blur_uploader_block`,
`replace_logo`, `include_intro`, and `include_outro`. It defaults to disabled and
every child flag defaults to false. Child flags or `profile` with disabled
branding are rejected. Enabled branding must use the approved
`bilibili_top_left_block` profile with both blur and replacement enabled; it is the
fixed top-left Chinese uploader text plus Bilibili mark and the approved brand
logo—no caller supplied overlay coordinates, asset paths, environment values, or
translation model are accepted. Intro/outro are explicit opt-ins. Vietnamese
voice spellings `Ngọc Huyền`, `Ngoc Huyen`, and `ngoc huyen` normalize to
`ai33:vbee_hn_female_ngochuyen_full_48k-fhg`; this does not change the global
default voice. Translation model selection remains host-owned and keeps the
existing Ollama route.

`series-list` accepts a JSON object and may filter by `series_id`; `series-refresh`
accepts `{series_id, limit}`. `series-download` accepts episode selection through
`episode_numbers` or `selector`, resolves episode URLs only from tracker state, and
does not accept arbitrary filesystem paths. It may retain the legacy explicit URL
form where that runner already supports it. `series-list` and `series-refresh` return `series` with episode records. A record
should include `episode_number`, `status`, `download_status`,
`localization_status`, and any output path. Download responses must expose gate
results; queue missing episodes, then poll status/list until every selected episode
has a verified final output.

Plans accept and persist `order`, `split_episodes`, `include_intro`, and
`include_outro`. Intro/outro branding is opt-in and defaults to off: OpenClaw adds
them only when explicitly requested, otherwise it compiles selected episodes
normally. When enabled, each output part contains one intro, the selected episodes
in source order, and one outro. Currently only `order:"source"` and `split_episodes:false` are
supported; other values are rejected. Plan responses include `compilation_id`, `state`, `plan_preview`, `parts`,
`missing_episodes`, and `warnings`. Run/resume/status include `state` and per-part
states (`queued`, `processing`, `completed`, `needs_attention`, `error`, or
`canceled`); cancel returns the resulting `canceled` state. A plan with missing
episodes, failed gates, invalid explicit regions, or unconfirmed low-confidence
regions must be `needs_attention` and must not be run. If branding requests
`blur_logo`, `blur_title`, or `replace_logo` without `overlay_regions`, the plan
may use dependency-light local detection to sample every selected usable episode and
  persists `overlay_detections` keyed by episode number with preview paths and
  diagnostics. It proceeds only when the requested branding has high-confidence
  evidence; low confidence or missing title OCR blocks unknown/generic profiles
  and remains `needs_attention` with preview frames and must not be run. Missing
  title OCR does not block the approved Bilibili fixed profile because its Chinese
  uploader watermark region is known and intentionally covered. Explicit regions
  remain supported, and no blind blur is applied.

For the known Bilibili uploader, `branding.profile:"bilibili_top_left_block"` (or
a selected series whose `platform` is `bilibili`) uses the approved normalized
top-left block for both the Chinese uploader text and Bilibili mark. It is persisted
as profile evidence and can blur the full block and place a circular replacement in
its center. The dashboard is monitoring-only. `overlay_regions` is the API fallback,
not a normal dashboard/UI input, and uses explicit pixel/time records, for example:

```json
{"x":20,"y":20,"width":300,"height":80,"start_seconds":0,"end_seconds":8,"confidence":0.72,"confirmed":true,"blur":true}
```

`start_seconds`/`end_seconds` are accepted aliases for `start`/`end` and are
normalized before branding. `label` is optional: blur-only and replacement-only
regions receive safe default labels. Low-confidence regions remain fail-closed
unless every such region is explicitly `confirmed:true`.
