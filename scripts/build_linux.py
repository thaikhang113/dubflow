"""Build a portable Linux onedir bundle and tar.gz artifact.

Run from project root:
    python3 scripts/build_linux.py
    python3 scripts/build_linux.py --no-test
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist", "DubFlow")


def run(command: list[str]) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def assemble() -> None:
    os.makedirs(os.path.join(DIST, "scripts"), exist_ok=True)
    for name in ("setup_support.py", "setup_vieneu.py",
                 "setup_paraformer.py", "setup_whisper.py",
                 "setup_douyin.py"):
        shutil.copy2(
            os.path.join(ROOT, "scripts", name),
            os.path.join(DIST, "scripts", name),
        )
    shutil.copy2(os.path.join(ROOT, ".env.example"),
                 os.path.join(DIST, ".env.example"))
    shutil.copy2(os.path.join(ROOT, "LICENSE"), os.path.join(DIST, "LICENSE"))
    os.makedirs(os.path.join(DIST, "models"), exist_ok=True)
    fonts = os.path.join(ROOT, "fonts")
    if os.path.isdir(fonts):
        shutil.copytree(fonts, os.path.join(DIST, "fonts"), dirs_exist_ok=True)


def smoke_test() -> None:
    env = dict(os.environ, AUTODUB_SMOKE="1", QT_QPA_PLATFORM="offscreen")
    run_env = [os.path.join(DIST, "DubFlow")]
    subprocess.run(run_env, cwd=DIST, env=env, check=True, timeout=180)


def archive(version: str) -> str:
    output = os.path.join(ROOT, "dist", f"DubFlow-v{version}-linux-x86_64.tar.gz")
    with tarfile.open(output, "w:gz") as archive_file:
        archive_file.add(DIST, arcname="DubFlow")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-test", action="store_true")
    parser.add_argument("--version", default="0.1.0")
    args = parser.parse_args()
    started = time.time()

    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        os.path.join(ROOT, "autodub-linux.spec"),
    ])
    if not os.path.isfile(os.path.join(DIST, "DubFlow")):
        raise SystemExit("PyInstaller finished without dist/DubFlow/DubFlow")
    assemble()
    if not args.no_test:
        smoke_test()
    output = archive(args.version)
    print(f"created {output} in {time.time() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
