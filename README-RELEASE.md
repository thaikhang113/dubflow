# DubFlow Release Notes

DubFlow is open-source desktop software for Windows and Linux. It processes
video locally: download, speech recognition, translation, Vietnamese speech
synthesis, subtitle generation, and video export.

## Supported release targets

- Windows 10/11 x64: PyInstaller onedir bundle (`DubFlow.exe`).
- Linux x86_64: PyInstaller onedir bundle in `tar.gz`.
- CPU mode is the baseline. NVIDIA acceleration is optional and depends on
  the installed driver and model runtime.

## Build locally

Windows:

```powershell
python -m pip install -e .
python -m pip install pyinstaller
python scripts/build_exe.py --no-test
```

Linux:

```bash
python3 -m pip install -e .
python3 -m pip install pyinstaller
python3 scripts/build_linux.py --version 0.1.0
```

Linux build needs system FFmpeg and Qt runtime libraries. The build does not
include ASR/TTS models, CUDA, or user credentials.

## Release rules

- Never commit `.env`, cookies, models, voices, or generated project data.
- Publish SHA256 checksums with each release artifact.
- Test each artifact on a clean machine before publishing.
- Keep model and third-party provider licenses in release notes.
