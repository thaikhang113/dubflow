# CapCap Integration

DubFlow uses CapCap's layer-oriented editor concepts without importing CapCap
runtime modules or duplicating DubFlow ASR, OCR, translation, TTS, or FFmpeg
backends.

## Boundary

- `autodub/` remains pipeline and export source of truth.
- `autodub_gui/video/layer_model.py` stores serializable tracks and layers.
- `autodub_gui/video/layer_bridge.py` converts existing segments, blur regions,
  audio sources, and branding options.
- `autodub_gui/video/timeline_state.py` persists `data/timeline.json`.
- `autodub_gui/video/layer_panel.py` exposes visibility and lock state.

Legacy work directories need no migration. Missing or invalid `timeline.json`
is rebuilt from existing DubFlow artifacts.

Layer visibility currently affects visual blur and logo export. Subtitle timing,
text edits, and audio remain controlled by existing DubFlow editor commands and
render options.

TencentDB Agent Memory and Loop Engineer stay development-time tooling. DubFlow
runtime has no dependency on either service.
