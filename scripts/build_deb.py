"""Build a Debian package from an assembled ``dist/DubFlow`` bundle."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "DubFlow"


def run(command: list[str]) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()

    if not args.no_build:
        run([str(ROOT / "scripts" / "build_linux.py"),
             "--no-test", "--version", args.version])
    if not DIST.is_dir():
        raise SystemExit(f"missing bundle: {DIST}")
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
Depends: libegl1, libgl1, libxkbcommon-x11-0
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
