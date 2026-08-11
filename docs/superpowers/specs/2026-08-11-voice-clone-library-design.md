# Voice Clone Library Design

**Status:** Approved by user

## Goal

Add a reusable **Giọng clone** source tab beside **CapCut** in the AI voice library. Users can create clones from either an audio file or a video, preview them, select them for future jobs, and delete them locally.

## Existing Context

- `autodub/speech/tts/voice_clone.py` already normalizes references, hashes them, and enrolls VieNeu embeddings.
- `autodub/speech/tts/vieneu_worker.py` already loads custom embeddings from `models/vieneu/custom_voices.json`.
- `autodub/speech/tts/voices.py` already exposes custom voices as `Voice(source="custom")`.
- `autodub/pipeline.py` already accepts clone fields and falls back to the preset voice if enrollment fails.
- `autodub_gui/pages/voice_library.py` currently has source tabs for offline voices and CapCut.

## User Flows

### Clone From Audio

1. Open **Giọng đọc AI**.
2. Select **Giọng clone**.
3. Click **Tạo giọng clone**.
4. Select WAV, MP3, M4A, or FLAC.
5. Enter a unique display name.
6. Normalize to mono 16 kHz.
7. Reject references shorter than 1 second or longer than 8 seconds.
8. Enroll locally through VieNeu.
9. Refresh catalog and select the new clone.

### Clone From Video

1. Select a local video or a downloaded project video.
2. Extract audio and run the existing vocal separation path.
3. Select the longest usable transcript window between 1 and 8 seconds.
4. Normalize the window and enroll locally.
5. Refresh catalog and select the new clone.

## UI

- Add source tab **Giọng clone** beside **CapCut**.
- Show only `Voice(source="custom")` entries in this tab.
- Add **Tạo giọng clone** action in the right management panel.
- Provide source selector: audio file or video.
- Provide file picker and name field.
- Show progress and actionable errors.
- Reuse existing preview, favorite, recent, and **Sử dụng giọng này** behavior.
- Add delete action for custom clones only.
- Do not expose embedding contents or source audio data.

## Storage

- Keep embeddings and metadata in the existing `models/vieneu/custom_voices.json`.
- Keep per-job extracted reference audio under the job `data/` directory.
- Use the existing hash-based name/cache behavior.
- Deleting a clone removes its JSON preset entry. It does not delete the user’s original source file.

## Error Handling

- Missing VieNeu installation: explain which installer to run.
- Missing/invalid source: block enrollment before starting worker.
- Invalid duration: show required 1–8 second range.
- Demucs failure: show that video cloning needs separable vocals; audio-file cloning remains available.
- Enrollment failure: preserve existing catalog and show worker error.
- Preview failure: keep clone selectable and show preview error.

## Security

- All cloning remains local.
- Never log audio contents, embeddings, API keys, or cookies.
- Do not upload source media.
- Only custom voices may be deleted from this UI.

## Verification

- Unit tests for custom voice filtering, deletion, duration validation, stable hash naming, and source selection.
- GUI-level tests for save/load values where Qt test support exists.
- Worker smoke test with a small WAV when VieNeu is installed.
- Full `pytest` suite and `python -m compileall -q autodub autodub_gui scripts`.
