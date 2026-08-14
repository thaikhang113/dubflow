# DubFlow Release Notes

DubFlow is open-source desktop software for Windows and Linux. It processes
video locally: download, speech recognition, translation, Vietnamese speech
synthesis, subtitle generation, and video export.

## Supported release targets

- Windows 10/11 x64: Inno Setup installer (`DubFlow-...-setup.exe`).
- Linux x86_64: Debian package (`dubflow_<version>_amd64.deb`).
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
python3 scripts/build_linux.py --version 3.0.4
python3 scripts/build_deb.py --no-build --version 3.0.4
```

Linux build needs Qt runtime libraries and `dpkg-deb`. The `.deb` does not
require Python on the host: first-run setup downloads a verified portable
Python 3.12 runtime into the user data directory. FFmpeg is a Debian package
dependency and is never downloaded by the Linux wizard. ASR/TTS models, CUDA
support, and user credentials are not included in the package.

## Release workflow

Push a semantic-version tag such as `v3.0.4`. GitHub Actions builds both
platforms, writes SHA256 checksum files, and publishes one GitHub Release.
Do not publish artifacts from `main` manually.

Each release also includes a platform checksum file. DubFlow uses these files
for in-app update verification before launching the installer.

## Release rules

- Never commit `.env`, cookies, models, voices, or generated project data.
- Publish SHA256 checksums with each release artifact.
- Test each artifact on a clean machine before publishing.
- Keep model and third-party provider licenses in release notes.
