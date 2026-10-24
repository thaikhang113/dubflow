# Round 34 GUI / OpenClaw audit

Scope: `autodub_gui/`, `autodub/openclaw_runtime.py`, `autodub/openclaw_tool.py`,
`autodub/openclaw_tools_registry.py`, `mcp_server.py`, `autodub/config.py`, `autodub/updates.py`.
All probes run with `D:\dubflow\.venv\Scripts\python.exe`, `QT_QPA_PLATFORM=offscreen`,
own data dir under `qa/work/rd34_*`. Interpreter probe preamble used throughout:
`cd D:\dubflow; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`.

## REPRODUCED

### G-1 Free-text .env values written by the GUI are silently mangled for the dubbing pipeline
- Evidence: `autodub_gui/env_store.py:51` and `autodub_gui/env_store.py:57` (value written raw, `f"{key}={val}"`, no quoting/escaping) versus the reader `autodub/config.py:339` (`load_dotenv`) → `autodub/config.py:367` / `autodub/config.py:473-476`.
- Symptom: the Settings / Translate pages show the user's text correctly (they re-read the file with `read_env`), but the pipeline receives a *different* string. Three manifestations, all in user-facing free text (`TRANSLATE_GLOSSARY`, `TRANSLATE_CONTEXT`, `TRANSLATE_STYLE_NOTES`, `TRANSLATE_DOMAIN`):
  1. everything from the first ` #` to the end of the value is dropped — a glossary line `AI = trí tuệ nhân tạo # giữ nguyên tiếng Anh` plus the following `GPU = …` line vanish, so the translation prompt silently loses terms;
  2. a value that *starts* with a quote makes python-dotenv fail to parse the statement, so the whole setting is lost (empty) and a `python-dotenv could not parse statement starting at line N` warning is written to stderr;
  3. `$NAME` / `${NAME}` in the value are expanded from the process environment, so prices/placeholders come out as unrelated environment text.
- Repro: `qa/work/probe_p34_cfg_roundtrip.py` → `& .\.venv\Scripts\python.exe qa\work\probe_p34_cfg_roundtrip.py`, observed:
  `RESULT G2-hash TRANSLATE_GLOSSARY settings_matches_typed=False file_matches_typed=True` / `in file ='AI = trí tuệ nhân tạo # giữ nguyên tiếng Anh\nGPU = card đồ họa'` / `pipeline='AI = trí tuệ nhân tạo'` / `widget  ='AI = trí tuệ nhân tạo # giữ nguyên tiếng Anh\nGPU = card đồ họa'`
  `RESULT C1-context TRANSLATE_CONTEXT settings_matches_typed=False` / `pipeline='Kênh review'` (typed `'Kênh review #shorts về linh kiện máy tính'`)
  `RESULT Q1-quotes TRANSLATE_STYLE_NOTES settings_matches_typed=False` / `pipeline=''` (typed `'"giữ nguyên" tên nhân vật'`)
  Control cases that do round-trip: `G1-control` (plain glossary) and `M1-semicolon` both `settings_matches_typed=True`.
  Mechanism isolated without Qt by `qa/work/probe_p34_dotenv_parse.py` → `TYPE T_HASH_TAIL … read_env='Kênh review #shorts về linh kiện' dotenv='Kênh review'`, `T_LEAD_QUOTE … dotenv=None` (whole statement rejected), `T_DOLLAR … dotenv='giá $HOME và ${PATH expanded from the real PATH}'`.
- Root cause: `write_env` stores the value unquoted while the reader is python-dotenv, which strips a whitespace-preceded `#` (`.venv/Lib/site-packages/dotenv/parser.py:125`), un-quotes / rejects a value starting with a quote (`.venv/Lib/site-packages/dotenv/parser.py:133-135` plus the `read_regex(_comment)` at `.venv/Lib/site-packages/dotenv/parser.py:161`) and expands `$VAR` (`.venv/Lib/site-packages/dotenv/variables.py:5,73`).
- Minimal fix: in `autodub_gui/env_store.py` write non-plain values already-quoted and escape the two characters that matter, e.g. in `write_env`
  `val = '"' + val.replace("\\", "\\\\").replace('"', '\\"') + '"' if _NEEDS_QUOTE.search(val) else val`
  with `_NEEDS_QUOTE = re.compile(r'^["\']|\s#|\$|\\')`, and unquote symmetrically in `read_env`. Safe because quoting is exactly the form `dotenv.set_key` already produces on the OpenClaw settings path (`autodub/openclaw_tools_registry.py:165-211`), so both writers agree, and plain values (`0`, `true`, `balanced`, absolute paths) stay byte-identical.
- Severity: high

### G-2 Deleting a project runs `shutil.rmtree` on the Qt main thread
- Evidence: `autodub_gui/pages/projects_page.py:273`
- Symptom: after confirming "Xóa dự án" on the Projects page the entire window freezes — no repaint, no cursor change — for as long as the recursive delete takes; project folders hold the dubbed video plus intermediate wavs, so it scales with project size.
- Repro: `qa/work/probe_p34_gui_rmtree.py` (builds a synthetic project of `P34_NBIG` files, patches `ConfirmDialog.ask` to confirm and the page's settings provider, counts Qt timer ticks serviced while `_delete` runs):
  `files=1209 mb=139 delete_call_ms=204 gui_thread_unserviced_ms=205`
  `files=5017 mb=569 delete_call_ms=893 gui_thread_unserviced_ms=893`
  (baseline in the same probe: 60 timer ticks per 300 ms when idle; the folder was really deleted afterwards.) Command:
  `$env:P34_NBIG='5000'; $env:P34_BIGMB='120'; & .\.venv\Scripts\python.exe qa\work\probe_p34_gui_rmtree.py`
- Root cause: the delete handler calls `shutil.rmtree` inline instead of using the QThread worker pattern this page already uses for scanning.
- Minimal fix: hand the path to a worker (mirror `ProjectScanWorker`, `autodub_gui/workers.py:499`) and refresh the list from its `finished` signal; safe because nothing after `shutil.rmtree` in the handler depends on completion except the toast and re-render, and the OSError→toast handling moves into the worker's error signal unchanged.
- Severity: medium (measured ≈1.6 ms per MB, i.e. ~8 s on a 5 GB project)

### G-3 The batch-id containment guard can be bypassed with backslashes
- Evidence: `autodub/openclaw_runtime.py:92` (`if "/" in batch_id or not batch_id: raise ValueError`) combined with the path join at `autodub/openclaw_tool.py:247-248`
- Symptom: an authenticated caller can read — and act on — any `*.json` file outside `<data>/openclaw_queue/batches/`, including `openclaw.json`, which stores the API token itself. The guard exists specifically to prevent this and does not hold on the shipping platform.
- Repro: `qa/work/probe_p34_http_traversal.py` (server bound to an ephemeral loopback port, own data dir) →
  `RESULT 'E encoded-slash traversal' status=404 body={"ok": false, "error": "Không tìm thấy batch: ..%2F..%2Foutside_marker"}`
  `RESULT 'F backslash traversal -> outside file' status=200 body={"ok": true, "batch_id": "..\\..\\outside_marker", "status": "running", "percent": 0, "counts": {}, "jobs": []}`
  `RESULT 'G traversal -> openclaw.json' status=500 body={"ok": false, "error": "KeyError: 'job_ids'"}` (the file was read and parsed; only the missing key turned it into a 500)
  `RESULT 'J POST cancel via traversal' status=200 body={"ok": true, "batch_id": "OUTSIDE", "cancelled": [], "signalled": [], "still_running": []}`
- Root cause: the id is validated as a *string* for `/` only, then passed to `pathlib`/`os` where `\` is a separator on Windows, so a backslash escapes the `batches` directory.
- Minimal fix: validate the resolved target, not the raw string — in `autodub/openclaw_tool.py:_manifest_path` (or once in the handler) do `try: target.resolve().relative_to((Path(queue_root) / "batches").resolve()) except ValueError: raise BatchNotFound(...)`, reusing the `is_within_directory` pattern already in `autodub_gui/projects.py`. Safe: legitimate ids are always `batch-<12 hex>` (created at `autodub/openclaw_tool.py:333`), so no valid request changes behaviour.
- Severity: high — note the token is required and the default bind is loopback, but this install's `openclaw.json` currently has `bind_host=0.0.0.0`, so the endpoint is reachable from the LAN when a user enables that mode.

### G-4 A batch manifest without `job_ids` answers 500 instead of a clean 4xx
- Evidence: `autodub/openclaw_tool.py:285` (status), `autodub/openclaw_tool.py:370` (cancel), `autodub/openclaw_tool.py:400` and `:438` (retry) index `manifest["job_ids"]` / `manifest["jobs"]` directly, while the HTTP mapping at `autodub/openclaw_runtime.py:130-135` only converts `(TypeError, ValueError, FileNotFoundError)` to 400 — `KeyError` falls through to the catch-all 500.
- Symptom: a truncated, hand-edited or foreign JSON file in `batches/` (or a manifest written by an older build) makes `GET /v1/batches/<id>`, `POST /v1/batches/<id>/cancel` and `.../retry-failed` return `500 `{"ok": false, "error": "KeyError: 'job_ids'"}` instead of a 4xx with a usable message; MCP clients that treat 5xx as retryable loop on it.
- Repro: same probe, exact observed lines:
  `RESULT 'H manifest w/o job_ids' status=500 body={"ok": false, "error": "KeyError: 'job_ids'"}`
  `RESULT 'I POST cancel w/o job_ids' status=500 body={"ok": false, "error": "KeyError: 'job_ids'"}`
- Root cause: the manifest is treated as trusted as soon as it parses as JSON.
- Minimal fix: validate the shape once in `_read_manifest` (`autodub/openclaw_tool.py:265-270`), e.g. `if not isinstance(data.get("job_ids"), list): raise BatchNotFound("…")`; safe because both writers of that file set `job_ids` (`autodub/openclaw_tool.py:331-362` on submit, `:438` on retry), so no legitimate file is rejected.
- Severity: medium

### G-5 `mcp_server.py` reads a hardcoded developer-machine config path
- Evidence: `mcp_server.py:7` and `mcp_server.py:10` (`Path("D:/dubflow/openclaw.json")`), consumed at `mcp_server.py:20-28`.
- Symptom: the MCP bridge that drives DubFlow's tools uses a stale config, posts to the wrong port and sends the wrong bearer token, so every tool call comes back `{"ok": false, "error": "HTTP Error 401: Unauthorized"}` (or a connection error) and the tools look broken. On a packaged install neither hardcoded path exists, `_get_api_config()` returns `{}`, and the token is empty.
- Repro: measured on this machine (no secret values printed): `D:\dubflow\openclaw.json` exists with `enabled=False port=38643`, the live config `%LOCALAPPDATA%\DubFlow\openclaw.json` has `enabled=True port=52558`, and the two tokens differ (`tokens_match: False`). The runtime's real config path is `data_dir()/"openclaw.json"` (`autodub/openclaw_runtime.py:150`).
- Root cause: an absolute path from the development machine instead of `data_root()`.
- Minimal fix: `config_path = Path(data_root()) / "openclaw.json"` (import `from autodub.utils import data_root`) — the same file the runtime writes; safe because it is exactly the location `autodub/openclaw_runtime.py:150-176` persists.
- Severity: medium

## UNVERIFIED HYPOTHESIS

### G-6 An import failure inside the request thread drops the connection with no HTTP reply
`autodub/openclaw_runtime.py:77` (`from autodub.openclaw_tool import BatchNotFound`) sits *above* the `try:` at line 78, so any `ImportError` in `autodub.openclaw_tool`'s import chain escapes the handler before a reply exists and the client sees a dropped connection (empty reply) instead of a 5xx. Not reproduced: I could not make that import fail without breaking the whole app. One-line fix: move the import inside the `try` (it maps to 500) or to module level, where startup fails loudly.

### G-7 `retry-failed` could be steered into writing outside `batches/`
`autodub/openclaw_tool.py:439` writes the rewritten manifest to `_manifest_path(queue_root, manifest["batch_id"])` — the destination is taken from the *file's own* `batch_id`, and G-3 lets a file outside `batches/` be used as the manifest. Reaching it needs an outside JSON file that already carries `batch_id`, `jobs` and `job_ids`; I did not construct one, so this is a plausible follow-on of G-3 rather than a demonstrated write. The G-3 fix closes it.



## CLEAN (checked and found sound)

- **GUI construction with default/empty state (category D)**: `qa/work/probe_p34_gui_empty.py` builds `MainWindow` against a pristine data dir and walks all 14 rows (`win._page_widgets`, `win.switch_page`) plus the OpenClaw page and the empty project filters → `failures=0`; every registered page constructed and refreshed (row 7 = editor is `None` by design until a project is opened).
- **OpenClaw authorization**: no token / wrong token / non-ASCII `Authorization` → `401 {"ok": false, "error": "Token không hợp lệ"}` with no dropped connection (`autodub/openclaw_runtime.py:51-59`) — probe cases A, B; the bytes-based comparison fix holds.
- **Malformed request bodies**: `_json_body` (`autodub/openclaw_runtime.py:61-72`) maps missing/non-numeric `Content-Length` and empty/oversize bodies to 400 and non-dict JSON to 400; the sizes passed to `self.rfile.read` are bounded by `_MAX_BODY=1_000_000`.
- **Tool registry**: `dispatch_tool` (`autodub/openclaw_tools_registry.py:594-603`) wraps every tool invocation in `try/except Exception`, so hostile argument shapes (`arguments=null`, a list, wrong types) yield `{"ok": false, …}` via the 400 mapper or the registry's own catch — no exception escapes into the request thread. The per-tool coercers (`_as_bool/_as_int/_as_choice/_as_text`) raise `ValueError`, which is in the 400 tuple.
- **Settings worker-count blanking**: `PARALLEL_WORKERS` (`autodub_gui/pages/settings_fields.py:239`) and `VIENEU_MAX_WORKERS` (`:274`) are both `NUMBER` with `decimals=0`, so the `f"{v:.0f}"` rendering can only produce `"0"`/`"0.0"`/`""` — the blanking test in `autodub_gui/pages/settings_page.py:390-408` matches; no value slips through.
- **Settings save scope**: `_own_fields()` (`autodub_gui/pages/settings_page.py:339-345`) writes only its own tab's keys, so pressing Save on Settings does not reset the Voice/Subtitle/Translate tool pages' keys.
- **Other heavy work is already off-thread**: `projects.ensure_thumbnail` (`autodub_gui/projects.py:373`) has exactly one caller, `autodub_gui/workers.py:536-539` inside a worker; `style_dialog.extract_frame` (`autodub_gui/style_dialog.py:84,88`) is only reached from `_FrameWorker` (`autodub_gui/style_dialog.py:109`); the cache `os.walk` at `autodub_gui/pages/settings_panels.py:480` runs only inside `_CacheCleaner` (`:442-464`); `autodub_gui/system_open.py:43-70` uses non-blocking `subprocess.Popen`; the Windows setup/download paths (`autodub_gui/workers_setup.py`) are all QThread subclasses. Every `.wait(N)` call found (`autodub_gui/app.py:668`, `pages/editor_page.py:557/1233/1241/1254/1257`, `pages/batch_page.py:875`, `pages/download_page.py:585`, `pages/editor_launcher_page.py:229`, `pages/home_page.py:320`, `pages/new_project_page.py:297/1277/1280`, `pages/projects_page.py:294`, `pages/settings_panels.py:371/469/699/816`, `pages/translate_tool_page.py:161`, `voice_clone_dialog.py:131`) is on a teardown/idempotent-cleanup path, not a normal user action.
- **Project scan reporting** (`autodub_gui/projects.py`): status precedence (`:197-213`), cache validity (`:291-311`, keyed on mtime+size of every file whose presence changes the status) and the `data/report.json` vs `dub_report.json` fallback (`autodub_gui/projects.py:97-103`) all read consistent with what the pages display; no misreported state found.
- **Update download/install** (`autodub/updates.py`): `download_verified` verifies the release SHA-256 and deletes a mismatching file (`autodub/updates.py:146-151`), the checksum parser requires exactly 64 hex characters (`:109-116`), and every network call has a timeout (`:61`, `:126`, `:134`). I suspected the UTF-8 (no-BOM) `.cmd` written at `autodub/updates.py:181-192` would be mis-decoded by `cmd.exe` (console code page 437 here) when the user profile path contains Vietnamese diacritics; it did **not** reproduce — a `.cmd` written the same way inside `qa/work/rd34_upd/Nguyễn Văn A/` and run via `cmd /c` resolved the non-ASCII path correctly (`marker-ok`, `exit=0`).
- **Version comparison** (`autodub/updates.py:31-47`): `parse_version` strips a `v`/`V` prefix and non-digit tails, `is_newer` zero-pads both sides before comparing, so `3.0.34` vs `v3.0.34` is correctly not-newer and `3.0.4` vs `3.0.34` orders numerically.
- **Loopback bind warning**: `bind_host` is user-configurable and the runtime warns when it is not loopback (`autodub/openclaw_runtime.py:150-176`); the `0.0.0.0` value observed in this install is a user setting, not a default.

Probe files (write targets of this round):
`qa/work/probe_p34_http_traversal.py`, `qa/work/probe_p34_gui_empty.py`,
`qa/work/probe_p34_gui_rmtree.py`, `qa/work/probe_p34_cfg_roundtrip.py`,
`qa/work/probe_p34_dotenv_parse.py`; raw logs `qa/work/_p34_trav.log`,
`qa/work/_p34_empty.log`, `qa/work/_p34_rmtree.log`, `qa/work/_p34_cfg.log`.