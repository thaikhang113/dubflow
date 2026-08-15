"""Build a Debian package from an assembled ``dist/DubFlow`` bundle."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "DubFlow"


def _force_utf8_stdio() -> None:
    """Keep Vietnamese build output readable on Windows legacy consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def run(command: list[str]) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _bundle_data_dir(bundle: Path) -> Path:
    worker = Path("autodub") / "speech" / "asr_whisper_worker.py"
    candidates = [bundle / "data", bundle / "_internal", bundle]
    for path in candidates:
        if (path / worker).is_file():
            return path
    for path in candidates:
        if path.is_dir():
            return path
    return bundle


def _validate_bundle(bundle: Path, version: str) -> None:
    """Reject incomplete bundles before they become installable artifacts."""
    executable = bundle / "DubFlow"
    if not executable.is_file():
        raise SystemExit(f"bundle thiếu executable: {executable}")
    if os.name != "nt" and not os.access(executable, os.X_OK):
        raise SystemExit(f"bundle executable chưa có quyền chạy: {executable}")
    version_file = bundle / "VERSION"
    if not version_file.is_file() or version_file.read_text(
            encoding="utf-8").strip() != version:
        raise SystemExit(f"VERSION trong bundle không khớp {version!r}")
    for name in (
        "setup_support.py", "setup_vieneu.py", "setup_whisper.py",
        "setup_paraformer.py", "setup_ocr.py", "setup_douyin.py",
        "setup_demucs.py", "setup_voices.py", "setup_deepseek_ocr.py",
    ):
        if not (bundle / "scripts" / name).is_file():
            raise SystemExit(f"bundle thiếu script: {bundle / 'scripts' / name}")
    data_dir = _bundle_data_dir(bundle)
    for relative in (
        Path("autodub") / "speech" / "asr_whisper_worker.py",
        Path("autodub") / "speech" / "asr_paraformer_worker.py",
        Path("autodub") / "speech" / "tts" / "vieneu_worker.py",
        Path("autodub") / "media" / "demucs_worker.py",
        Path("autodub") / "media" / "ocr_worker.py",
        Path("autodub") / "media" / "deepseek_ocr_worker.py",
    ):
        if not (data_dir / relative).is_file():
            raise SystemExit(f"bundle thiếu worker: {data_dir / relative}")
    if (bundle / ".env").exists():
        raise SystemExit("bundle không được chứa .env")


def main() -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--check-only", action="store_true",
                        help="chỉ kiểm tra dist/DubFlow, không tạo .deb")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9][0-9A-Za-z.+~-]*", args.version):
        raise SystemExit(f"invalid Debian version: {args.version!r}")

    if not args.no_build:
        run([str(ROOT / "scripts" / "build_linux.py"),
             "--no-test", "--version", args.version])
    if not DIST.is_dir():
        raise SystemExit(f"missing bundle: {DIST}")
    _validate_bundle(DIST, args.version)
    if args.check_only:
        print(f"validated {DIST}", flush=True)
        return 0
    if shutil.which("dpkg-deb") is None:
        raise SystemExit("dpkg-deb is required to build .deb")

    package_root = Path(tempfile.mkdtemp(prefix="dubflow-deb-"))
    try:
        opt_dir = package_root / "opt" / "dubflow"
        shutil.copytree(DIST, opt_dir, symlinks=True)

        launcher = package_root / "usr" / "share" / "applications"
        launcher.mkdir(parents=True)
        (launcher / "dubflow.desktop").write_text(
            """[Desktop Entry]
Name=DubFlow
Comment=Local AI video dubbing
Exec=/opt/dubflow/DubFlow
Terminal=false
Type=Application
Categories=AudioVideo;Video;
""",
            encoding="utf-8",
        )

        control = package_root / "DEBIAN"
        control.mkdir()
        (control / "control").write_text(
            f"""Package: dubflow
Version: {args.version}
Section: video
Priority: optional
Architecture: amd64
Maintainer: DubFlow contributors
Depends: ffmpeg, libegl1, libgl1, libglib2.0-0, libpulse0,
  libgssapi-krb5-2, libfontconfig1, libdbus-1-3, libnss3,
  libx11-6, libx11-xcb1, libxkbcommon0, libxkbcommon-x11-0,
  libxcb1, libxcb-shm0, libxcb-randr0, libxcb-render0, libxcb-render-util0,
  libxcb-xfixes0, libxcb-sync1, libxcb-xkb1, libxcb-cursor0, libxcb-icccm4,
  libxcb-image0, libxcb-keysyms1, libxcb-shape0, libxcb-xinerama0
Description: Local AI video dubbing application
 DubFlow downloads local engines on first launch and creates Vietnamese
 dubbed video with subtitles and preserved background audio.
""",
            encoding="utf-8",
        )
        postinst = control / "postinst"
        postinst.write_text(
            "#!/bin/sh\nset -e\nchmod 755 /opt/dubflow/DubFlow\nexit 0\n",
            encoding="utf-8",
        )
        postinst.chmod(0o755)

        output = ROOT / "dist" / f"dubflow_{args.version}_amd64.deb"
        run(["dpkg-deb", "--build", "--root-owner-group",
             str(package_root), str(output)])
        print(f"created {output}", flush=True)
    finally:
        shutil.rmtree(package_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
