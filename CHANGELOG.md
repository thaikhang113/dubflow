# Changelog

## 3.0.5 - 2026-08-14

### Added

- In-app installation controls for optional ASR, OCR, TTS, and voice features.
- Douyin cookie import, hybrid OCR support, and OpenClaw tool integration.

### Fixed

- Improved batch download and processing queue behavior.
- Fixed OCR and subtitle masking workflow compatibility.

## 3.0.4 - 2026-08-14

### Fixed

- OCR subtitle masking refreshes when the editor region changes and keeps
  original-logo detection separate from the subtitle region.
- Windows and Linux bundles include external ASR, TTS, OCR, and separator
  workers in current PyInstaller layouts.
- Linux uses system `ffmpeg`/`ffprobe` and declares `ffmpeg` as a Debian
  package dependency instead of downloading a static copy.
- Improve Vietnamese font loading, help text, download layout, and DubFlow
  branding in the app UI.

### Added

- In-app OCR subtitle masking defaults to the lower 30-35% of the frame.
- Release validation checks worker files, setup scripts, version, and secrets
  before packaging.

## 3.0.3 - 2026-08-14

### Fixed

- Bundle Whisper worker in Windows and Linux releases.
- Fail builds when a required external worker is missing.
- Stabilize settings default tests when `.env` has already been loaded.

### Added

- Manual `Kiểm tra cập nhật` button in the app header.
- In-app release download, SHA256 verification, and installer handoff.
