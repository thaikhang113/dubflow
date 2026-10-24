# Round 34 pipeline audit

Scope: autodub/pipeline.py, autodub_gui/workers.py, autodub/batch.py, autodub/cancel.py,
autodub/pipeline_state.py, autodub/workdir.py, autodub/async_subprocess.py (+ the
media/audio.py, media/timing.py, speech/align.py helpers those files call).
Interpreter used for every probe:
`D:\dubflow\.venv\Scripts\python.exe` (Python 3.13.13).
No model download, no network, no real video: heavy children are stubbed.

## REPRODUCED

### P-1 GUI "Stop" cannot stop the parallel ffmpeg passes — the children are registered with scope `None`
- Evidence: `autodub/media/audio.py:231` (ThreadPoolExecutor for `slow_segments`), `autodub/media/audio.py:212-217` (`run_registered(...)` with **no** `scope=` argument), `autodub/media/audio.py:349-350` (`postprocess_voice_clips` pool) -> `autodub/media/audio.py:291-296` (same missing `scope=`), `autodub/media/timing.py:186-187` (atempo pool) -> `autodub/media/timing.py:181`; root cause in `autodub/cancel.py:20-22` (scope is a `contextvars.ContextVar`) and `autodub/cancel.py:101` / `:119-121` (a child is registered under `CURRENT_CANCEL_SCOPE.get()`, i.e. `None` in a pool thread), with the scoped kill filter at `autodub/cancel.py:77`. The GUI Stop side is `autodub_gui/workers.py:86-87` (and its nine identical siblings at `:176-177`, `:233-234`, `:289-290`, `:342-343`, `:396-397`, `:444-445`, `:699-700`, `:847-848`, `:910-911`).
- Symptom: with VOICE_SPEED != 1.0 (or on any run reaching the post-process / atempo passes) the user presses "Stop" and the app keeps spawning ffmpeg for **the whole pass** — hundreds of `atempo` invocations on a 900-segment video — then stops. "Stop" looks ignored, the fans keep spinning, and the work directory keeps growing.
- Repro: `qa/work/probe_p34_scope_threadpool.py` -> `D:\dubflow\.venv\Scripts\python.exe -X utf8 qa\work\probe_p34_scope_threadpool.py` -> `stop requested at t=1.0s, pass ended at t=5.9s` / `children STILL ALIVE after the Stop kill loop: 1` / `ffmpeg invocations: 8 total, 6 started AFTER Stop` / `segments rendered: 8/8` / `stop surfaced as: no (returned normally)`. The probe's control (PART 3) uses the global `cancel_processes()` instead of the GUI scope and behaves correctly: `stop surfaced as: PipelineCancelled: Pipeline cancelled by user`, `outputs 1/8`.
- Root cause: `ThreadPoolExecutor` does not carry `contextvars` into its worker threads, so every `run_registered` call made from a pool thread registers its child with `scope=None`, and `cancel_processes(scope="gui")` (what the GUI Stop button does) filters by scope, so those children are never killed and the pass never sees the cancel.
- Minimal fix: the repo already has the pattern — `autodub/pipeline.py:816-825` hand-copies the scope into the background thread for exactly this reason ("Thiếu nó, Demucs ... ghi danh với scope None và nút Dừng (scope \"gui\") không giết được worker"). Apply the same two lines to the three ffmpeg pools, e.g. in `slow_segments`:
  ```python
  scope = CURRENT_CANCEL_SCOPE.get()          # captured in the CALLING thread
  def _slow_one(seg): ...                     # unchanged
  def _scoped(seg):                           # pool task
      with cancel_scope(scope):
          _slow_one(seg)
  ```
  and submit `_scoped` instead of `_slow_one` (`autodub/media/audio.py:232`); same for `autodub/media/audio.py:350` and `autodub/media/timing.py:187`. Safe because `cancel_scope` only sets the child's registration scope and `run_registered` already raises `PipelineCancelled` when the pass is cancelled mid-flight, which is the behaviour the caller (`autodub/pipeline.py:1202`, `autodub/pipeline.py:1211`) is written for.
- Severity: high

### P-2 A clip left half-written by an interrupted pass is reused forever (the pass writes its output non-atomically)
- Evidence: `autodub/media/audio.py:208-210` (reuse predicate is only `exists && size > 0 && mtime >= src`) and `autodub/media/audio.py:214-215` (ffmpeg is given `dst` **directly**, no temp file) — contrast the sibling function `autodub/media/audio.py:289` / `:311`, which writes `dst + ".post.tmp.wav"` and only then `os.replace(tmp, dst)`. `wav_duration_s` (`autodub/media/audio.py:354-358`) reads the length out of the WAV header and its own comment says it is the cheap length source for "the many places that only need the length (timeline fit on 900+ segments)", so it cannot see a truncated PCM body.
- Symptom: after a Stop/kill that lands inside the VOICE_SPEED slow-down pass, one sentence is dubbed as a clipped, clicky fragment (or its subtitle ends long after the voice stops) on **every** later run of that project — including runs started after a "clean" resume. Re-running the pipeline does not repair it; only clearing the work directory does.
- Repro: `qa/work/probe_p34_scope_threadpool.py` (PART 4) -> `D:\dubflow\.venv\Scripts\python.exe -X utf8 qa\work\probe_p34_scope_threadpool.py` -> `half-written clip      : 26504 bytes (30% of the source)` / `after a fresh run      : 26504 bytes, ffmpeg invoked 0 time(s) for this clip` / `header duration reported: 1.0 s`. The probe plants the truncated clip the way a killed ffmpeg leaves it (created by the pass, newer mtime than the source) and calls the real `slow_segments`; ffmpeg is never invoked and the truncated file is kept.
- Root cause: `slow_segments` is the one per-segment pass that lets ffmpeg write straight into the cached output path, so an interrupted run leaves a non-empty, newer-than-source file that the resume predicate (`autodub/media/audio.py:208-210`) accepts as finished; because `wav_duration_s` reads the header, even a duration check cannot tell it apart from a complete clip.
- Minimal fix: mirror the known-good write in the same module — in `autodub/media/audio.py:213-215` render to `tmp = dst + ".tmp.wav"` and `os.replace(tmp, dst)` after the existing size check at `:218-219`. Then a killed pass can never leave a file at the reusable name. (Same reason `postprocess_voice_clip` at `:289`, `:311` is immune.)
- Severity: medium

## UNVERIFIED HYPOTHESIS

### P-3 Truncated speaker-reference clips are reused for voice cloning
- Evidence: `autodub/pipeline.py:2063-2078` (ffmpeg writes `clip_path` directly; on cancel/`returncode != 0` the loop just `continue`s and leaves the partial file) and `autodub/pipeline.py:2064` (`if not os.path.isfile(clip_path)` — existence only, no size/duration check), then `autodub/pipeline.py:2083-2085` builds `embed_batch.json` from those paths and `:2086+` runs the embedding.
- Why unverified: the failure needs a real cancel/kill during this step plus the real speaker-embedding step to show the cloned voice is degraded; both are model calls I did not run. Mechanism is the same one I reproduced in P-2 (partial artifact at a cache path accepted by an existence/size predicate).
- Severity: low

### P-4 A truncated `original_audio.wav` survives a cancelled Step 2 and is reused by ASR
- Evidence: `autodub/pipeline.py:770-771` (reuse predicate = `exists && size > 0`), `autodub/pipeline.py:791-794` (the single-output fallback `extract_audio` writes straight to `audio_path`, and nothing removes it on failure); the dual-output path is safe (`autodub/media/audio.py:174-177` deletes a partial `asr_path`/`hq_path` and raises).
- Why unverified: needs a real kill during that one ffmpeg call plus a real ASR run to observe the truncated transcript; P-2 already demonstrates the general pattern.
- Severity: medium (the visible effect would be "the last part of the video has no dub", silent — worth a size/duration check even if rare)

### P-5 The optional subtitle-alignment pass never observes a GUI Stop
- Evidence: `autodub/speech/align.py:199` (the pool task `_one`), `:219` (`ThreadPoolExecutor(max_workers=n_workers)`), and the two handlers `:205` / `:223` (`except PipelineCancelled: raise`). Nothing in the file reads the cancel flag (a grep for `cancel_event` in `autodub/speech/align.py` returns no match), so the handler at `:205` is unreachable from the GUI, and its own comment states the consequence ("nuốt nó ở đây là pipeline tiếp tục nghe hàng trăm clip nữa rồi mới xuất video"). The per-segment TTS pool does it correctly (`autodub/pipeline.py:2435` calls `rep.check_cancelled()` inside every task) — the align pool is the outlier.
- Why unverified: reproducing needs the real ASR/alignment model (`_asr_words` at `autodub/speech/align.py:73` runs in-process, no child process). Static reading only; I did not run the pass.
- Severity: medium

## CLEAN (checked and found sound)

- **Broad-`except` sweep (category A).** `qa/work/probe_p34_cancel_swallow.py` walks the AST of the files in scope, finds every `except Exception`/`except BaseException`, keeps those whose body swallows, and marks whether the handler itself reacts to the cancel flag. Output: `qa/work/p34_scan_all.txt` (42 handlers). Every handler that encloses a cancel-sensitive call is either (a) paired with a `except PipelineCancelled` re-raise — `autodub/pipeline.py:360-362`, `autodub/pipeline.py:390-392`, `autodub/batch.py:353`, `autodub/editor.py:684`, `autodub/speech/transcriber.py:264`, `:280`, `:292`, `autodub/speech/align.py:205`, `:223`; or (b) unguarded *by design* with an explanatory comment — `autodub/pipeline.py:643-647` ("ffmpeg lạ — không đáng làm hỏng lượt chạy"); or (c) in `autodub_gui/workers.py`, guarded by `_cancel_event` before reporting a failure — `:415-417`, `:889-891`, `:956-958`, `:1000-1005`, `:1050-1055`. No remaining DF-01/DF-02 site. (Note: `autodub/pipeline.py:518` and `:1034` swallow without re-raising, but both sit in front of the TTS work and are followed by `rep.check_cancelled()`, so the outcome is the same.)
- **Non-atomic state files (category B).** `autodub/utils.py:195-211` (`save_json_atomic`: `mkstemp` + `os.replace`), used for the speaker map (`autodub/pipeline.py:222`), the voice map (`autodub/utils.py:288`), the transcript (`autodub/speech/transcriber.py:711-713`), the batch state (`autodub/batch.py:386-388`, called at `:481`), the editor's segment/opts files (`autodub/editor.py:84`, `:193`, `:266-267`, `:304`) and the alignment cache (`autodub/speech/align.py:259`). The expensive translation checkpoint is discarded only *after* the transcript is safely on disk.
- **Per-clip post-processing.** `autodub/media/audio.py:289-311`: temp file + `os.replace`, and on failure the temp is removed and the raw clip is copied — no half-written clip ever lands at the reusable name.
- **Clear-cancel hygiene in the GUI workers.** Every worker that registers children under the GUI scope calls `clear_cancel_request()` at the start of the run (`autodub_gui/workers.py:93`, `:185`, `:243`, `:297`, `:350`, `:403`, `:452`, `:856`, `:922`), so a stale Stop flag cannot make the *next* run commit suicide.
- **`cancel_processes` itself.** `autodub/cancel.py:83-94`: the kill loop is inside `try/except OSError` and bounded by a 1 s deadline, so Stop cannot hang the GUI thread even with a stuck child.
- **Duration-validated reuse in the timeline pass.** `autodub/media/timing.py:172-179` compares the cached clip's duration with the expected post-atempo duration before reusing (weaker than it looks — see P-2 — but strictly better than the size-only checks elsewhere).
- **`PipelineCancelled` swallowed by `except Exception` at `autodub/pipeline.py:788`.** Harmless: the very next statement (`:791-794`) calls `extract_audio`, which re-raises the same cancellation, so the run still aborts.
- **Batch state.** `autodub/batch.py` writes its state through `_save_json_atomic` (`:386-388`, `:481`); the interrupted-run behaviour was reviewed and no data-loss path was found beyond the JSON atomicity already covered above.

## Probe inventory (all under D:\dubflow\qa\work\)
- `probe_p34_scope_threadpool.py` — PART 1 contextvar-vs-pool thread; PART 2 GUI-scope Stop during `slow_segments`; PART 3 global-cancel control; PART 4 reuse of a half-written clip. ffmpeg stubbed by a shim that still goes through the real `run_registered` bookkeeping.
- `probe_p34_cancel_swallow.py` — AST sweep of broad exception handlers; writes `p34_scan_all.txt`.