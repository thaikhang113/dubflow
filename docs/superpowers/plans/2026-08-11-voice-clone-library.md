# Voice Clone Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable **Giọng clone** tab beside CapCut, with local VieNeu enrollment from audio or video and safe selection/deletion.

**Architecture:** Reuse the existing `voice_clone.py`, VieNeu worker, catalog, preview, and pipeline contracts. Add a thin UI management layer in `VoiceLibraryTab`; keep all embeddings in the existing custom voice JSON and keep source media outside the catalog. Video enrollment reuses pipeline separation/transcript selection rather than creating a second clone algorithm.

**Tech Stack:** Python 3.10+, PySide6, VieNeu standalone worker, FFmpeg, existing Demucs separation, pytest.

## Global Constraints

- Clone processing stays local; source audio/video is never uploaded.
- Reference duration must be between 1.0 and 8.0 seconds.
- Existing preset and CapCut voice flows must remain unchanged.
- Clone enrollment failure must leave existing voices usable.
- Do not add a new dependency for UI or JSON storage.
- Do not delete user source media when deleting a clone.

---

### Task 1: Lock Catalog Semantics

**Files:**
- Modify: `autodub/speech/tts/voices.py`
- Test: `tests/test_voices.py`

**Interfaces:**
- `source_group(voice: Voice) -> str` must return `"clone"` for `source == "custom"`, `"capcut"` for CapCut, and `"offline"` otherwise.
- Existing callers that expect offline grouping must be updated to treat `"clone"` as its own source tab only where source tabs are rendered.

- [ ] **Step 1: Write failing tests**

```python
def test_custom_voice_has_clone_source_group():
    voice = Voice("Clone", source="custom")
    assert source_group(voice) == "clone"
```

- [ ] **Step 2: Run the focused test**

Run:

```powershell
uv run --with pytest pytest -q tests/test_voices.py -k clone
```

Expected: FAIL because custom voices currently map to `"offline"`.

- [ ] **Step 3: Implement minimal grouping**

Update `source_group()` to return `"clone"` for `voice.custom`. Keep `Voice.label`, `Voice.custom`, and `Voice.is_capcut` behavior unchanged.

- [ ] **Step 4: Update affected source filters**

Ensure `voice_picker.py` and `voice_library.py` do not hide custom voices when clone source is selected. Existing offline behavior must still show non-CapCut, non-custom voices.

- [ ] **Step 5: Run tests**

```powershell
uv run --with pytest pytest -q tests/test_voices.py
```

- [ ] **Step 6: Commit**

```powershell
git add autodub/speech/tts/voices.py tests/test_voices.py autodub_gui/voice_picker.py
git commit -m "feat: classify custom voices as clone voices"
```

### Task 2: Add Custom Voice Store Operations

**Files:**
- Modify: `autodub/speech/tts/voice_clone.py`
- Test: `tests/test_voice_clone.py`

**Interfaces:**
- Add `delete_custom_voice(path: str, name: str) -> bool`.
- Add `custom_voice_names(path: str) -> set[str]`.
- Preserve atomic JSON writes through the existing worker-owned file format.

- [ ] **Step 1: Write failing tests**

```python
def test_delete_custom_voice_removes_only_requested_entry(tmp_path):
    path = tmp_path / "custom_voices.json"
    path.write_text(json.dumps({"presets": {
        "A": {"source": "custom"},
        "B": {"source": "custom"},
    }}), encoding="utf-8")

    assert delete_custom_voice(str(path), "A") is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["presets"]) == {"B"}
```

- [ ] **Step 2: Run and verify failure**

```powershell
uv run --with pytest pytest -q tests/test_voice_clone.py -k delete
```

Expected: FAIL because the operation is not defined.

- [ ] **Step 3: Implement atomic delete**

Load JSON defensively, remove only the requested preset, write to `path + ".tmp"`, replace the original, and return `False` for missing/corrupt entries without raising into the UI.

- [ ] **Step 4: Invalidate catalog cache**

Call `invalidate_catalog_cache()` after a successful delete so all pickers see the new list immediately.

- [ ] **Step 5: Run tests**

```powershell
uv run --with pytest pytest -q tests/test_voice_clone.py
```

- [ ] **Step 6: Commit**

```powershell
git add autodub/speech/tts/voice_clone.py tests/test_voice_clone.py
git commit -m "feat: add safe custom voice deletion"
```

### Task 3: Add Clone Enrollment Service Boundary

**Files:**
- Create: `autodub/speech/tts/voice_clone_service.py`
- Modify: `autodub/speech/tts/voice_clone.py`
- Test: `tests/test_voice_clone_service.py`

**Interfaces:**

```python
def enroll_from_audio(settings, source_audio: str, name: str) -> str:
    ...

def enroll_from_video(
    settings,
    video_path: str,
    name: str,
    *,
    source_lang: str = "zh-CN",
) -> str:
    ...
```

- [ ] **Step 1: Write failing tests**

Test that audio enrollment rejects missing files and delegates a valid normalized reference to `enroll_reference_audio`. Test video enrollment rejects missing video and uses the existing `select_reference_window` contract.

- [ ] **Step 2: Run focused tests**

```powershell
uv run --with pytest pytest -q tests/test_voice_clone_service.py
```

Expected: FAIL because the service module is absent.

- [ ] **Step 3: Implement audio enrollment**

Validate path, normalize using `prepare_reference_audio`, then call `enroll_reference_audio(settings, reference, name=name)`.

- [ ] **Step 4: Implement video enrollment**

Use existing audio extraction/separation helpers and transcript generation. Reuse `select_reference_window`; do not duplicate window-selection logic. Store temporary reference audio in a temporary directory and pass it to `enroll_reference_audio`.

- [ ] **Step 5: Define cleanup**

Use `TemporaryDirectory` for intermediate extraction. Never remove the original video.

- [ ] **Step 6: Run tests**

```powershell
uv run --with pytest pytest -q tests/test_voice_clone_service.py tests/test_voice_clone.py
```

- [ ] **Step 7: Commit**

```powershell
git add autodub/speech/tts/voice_clone_service.py autodub/speech/tts/voice_clone.py tests/test_voice_clone_service.py
git commit -m "feat: add audio and video clone enrollment service"
```

### Task 4: Add Clone Source Tab

**Files:**
- Modify: `autodub_gui/pages/voice_library.py`
- Modify: `autodub_gui/voice_picker.py` if shared source-tab logic requires it
- Test: `tests/test_voice_library_sources.py`

**Interfaces:**
- Add `_SRC_CLONE = 2`.
- Extend `_SRC_LABELS` to `("Giọng offline", "CapCut", "Giọng clone")`.
- `_src_voices()` must filter through `source_group()` and return only custom voices for clone tab.
- Clone tab should remain visible only when at least one custom voice exists, or when the create action is available.

- [ ] **Step 1: Write failing source-filter tests**

```python
def test_clone_source_filter_returns_only_custom_voices():
    voices = [
        Voice("Preset", source="library"),
        Voice("Clone", source="custom"),
        Voice("Cap", source="capcut"),
    ]
    assert [v.name for v in filter_source(voices, "clone")] == ["Clone"]
```

- [ ] **Step 2: Run test and confirm failure**

```powershell
uv run --with pytest pytest -q tests/test_voice_library_sources.py
```

- [ ] **Step 3: Implement source filtering**

Keep filtering as a small pure helper where possible; UI state should only select the group and call `_reset_page()`.

- [ ] **Step 4: Update counts and empty state**

Show clone count on the tab. Empty clone tab must explain that the user can create a clone from audio or video in the right panel.

- [ ] **Step 5: Run tests**

```powershell
uv run --with pytest pytest -q tests/test_voice_library_sources.py tests/test_voices.py
```

- [ ] **Step 6: Commit**

```powershell
git add autodub_gui/pages/voice_library.py autodub_gui/voice_picker.py tests/test_voice_library_sources.py
git commit -m "feat: add clone voice source tab"
```

### Task 5: Add Clone Creation Dialog

**Files:**
- Create: `autodub_gui/voice_clone_dialog.py`
- Modify: `autodub_gui/pages/voice_library.py`
- Test: `tests/test_voice_clone_dialog_values.py`

**Interfaces:**

```python
class VoiceCloneDialog(QDialog):
    def values(self) -> dict:
        # {"source": "audio"|"video", "path": str, "name": str}
        ...
```

- [ ] **Step 1: Write value-validation tests**

Cover missing name, missing path, unsupported extension, and valid audio/video values. Keep validation pure or expose a small `validate_clone_request(values)` helper.

- [ ] **Step 2: Run focused test**

```powershell
uv run --with pytest pytest -q tests/test_voice_clone_dialog_values.py
```

- [ ] **Step 3: Build the dialog**

Use existing `LabeledLineEdit`, `LabeledCombo`, `GhostButton`, `PrimaryButton`, and `QFileDialog`. Do not add a new UI framework or abstraction.

- [ ] **Step 4: Add progress/error state**

The dialog must disable controls while enrollment runs, show progress text, and re-enable controls after success/failure.

- [ ] **Step 5: Connect audio and video enrollment**

Use `voice_clone_service.enroll_from_audio` or `enroll_from_video` in a worker thread so the UI stays responsive.

- [ ] **Step 6: Refresh catalog on success**

Call `invalidate_catalog_cache()`, reload voices, select the new clone, and emit `changed`.

- [ ] **Step 7: Run tests**

```powershell
uv run --with pytest pytest -q tests/test_voice_clone_dialog_values.py
```

- [ ] **Step 8: Commit**

```powershell
git add autodub_gui/voice_clone_dialog.py autodub_gui/pages/voice_library.py tests/test_voice_clone_dialog_values.py
git commit -m "feat: add clone voice creation dialog"
```

### Task 6: Add Preview and Delete Actions

**Files:**
- Modify: `autodub_gui/pages/voice_library.py`
- Modify: `autodub_gui/voice_preview.py` only if custom voices need a separate preview path
- Test: `tests/test_voice_library_actions.py`

- [ ] **Step 1: Write tests**

Verify delete is enabled only for `Voice.custom`, preview uses the selected custom name, and deleting a clone refreshes the catalog without changing unrelated preset/CapCut entries.

- [ ] **Step 2: Run tests and confirm failure**

```powershell
uv run --with pytest pytest -q tests/test_voice_library_actions.py
```

- [ ] **Step 3: Implement delete confirmation**

Use existing `ConfirmDialog`. Delete only the JSON preset entry; preserve source media.

- [ ] **Step 4: Reuse preview**

Use the current `VoicePreview` path with the custom voice name. Do not add a second TTS renderer.

- [ ] **Step 5: Run tests**

```powershell
uv run --with pytest pytest -q tests/test_voice_library_actions.py
```

- [ ] **Step 6: Commit**

```powershell
git add autodub_gui/pages/voice_library.py autodub_gui/voice_preview.py tests/test_voice_library_actions.py
git commit -m "feat: manage and preview clone voices"
```

### Task 7: Wire Job Selection and Persistence

**Files:**
- Modify: `autodub_gui/voice_picker.py`
- Modify: `autodub_gui/pages/new_project_steps.py`
- Modify: `autodub_gui/pages/new_project_page.py`
- Modify: `autodub/pipeline.py` only if persisted state misses the selected clone
- Test: `tests/test_clone_job_selection.py`

- [ ] **Step 1: Write failing job-selection tests**

Verify a custom clone can be selected, serialized into `DubRequest.voice`, saved in draft state, and restored after reopening.

- [ ] **Step 2: Run focused tests**

```powershell
uv run --with pytest pytest -q tests/test_clone_job_selection.py
```

- [ ] **Step 3: Update picker source tabs**

Add clone source filtering beside offline and CapCut. Keep `VoicePicker.voice()` returning only the selected name, so pipeline contracts remain unchanged.

- [ ] **Step 4: Preserve existing per-job clone options**

Do not remove `clone_voice`, `clone_source`, or `clone_reference_audio` from `VoiceStep`; the reusable library voice and per-job enrollment flows must coexist.

- [ ] **Step 5: Run tests**

```powershell
uv run --with pytest pytest -q tests/test_clone_job_selection.py tests/test_voice_clone.py
```

- [ ] **Step 6: Commit**

```powershell
git add autodub_gui/voice_picker.py autodub_gui/pages/new_project_steps.py autodub_gui/pages/new_project_page.py autodub/pipeline.py tests/test_clone_job_selection.py
git commit -m "feat: use clone voices in project jobs"
```

### Task 8: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `docs/README.md` if present
- Test: full suite

- [ ] **Step 1: Document user flow**

Document audio/video clone creation, 1–8 second reference requirement, local storage path, deletion behavior, and fallback behavior.

- [ ] **Step 2: Document setup prerequisites**

State that VieNeu must be installed and FFmpeg/Demucs are required for video-source cloning.

- [ ] **Step 3: Run focused checks**

```powershell
python -m compileall -q autodub autodub_gui scripts
git diff --check
```

- [ ] **Step 4: Run full tests**

```powershell
uv run --with pytest pytest -q
```

Expected: all existing tests plus new clone-library tests pass.

- [ ] **Step 5: Manual smoke test**

1. Open the AI voice page.
2. Open **Giọng clone**.
3. Create a clone from a 1–8 second local WAV.
4. Confirm it appears in the catalog.
5. Preview it.
6. Select it in a new project.
7. Run a short local video job.
8. Delete the clone and confirm it disappears without deleting the source WAV.

- [ ] **Step 6: Commit**

```powershell
git add README.md .env.example docs
git commit -m "docs: document clone voice library"
```
