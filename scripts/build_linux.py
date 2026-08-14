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

def _bundle_data_dir() -> str:
    for name in ("_internal", "data"):
        path = os.path.join(DIST, name)
        if os.path.isdir(path):
            return path
    return os.path.join(DIST, "_internal")


def run(command: list[str]) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def assemble(version: str) -> None:
    clean_distribution_artifacts()
    with open(os.path.join(DIST, "VERSION"), "w", encoding="utf-8") as handle:
        handle.write(f"{version}\n")
    os.makedirs(os.path.join(DIST, "scripts"), exist_ok=True)
    for name in ("setup_support.py", "setup_vieneu.py",
                 "setup_paraformer.py", "setup_whisper.py", "setup_ocr.py",
                 "setup_douyin.py", "setup_demucs.py", "setup_voices.py",
                 "setup_deepseek_ocr.py"):
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
    voices = os.path.join(ROOT, "voices", "preset_voices_vn")
    if os.path.isdir(voices):
        shutil.copytree(
            voices,
            os.path.join(_bundle_data_dir(), "voices", "preset_voices_vn"),
            dirs_exist_ok=True,
        )


def clean_distribution_artifacts() -> None:
    for generated in (".env", "smoke_test_result.json", "smoke_startup_trace.txt"):
        path = os.path.join(DIST, generated)
        if os.path.isfile(path):
            os.remove(path)
    for generated_dir in ("bin", "logs", "output", "downloads", "VN"):
        path = os.path.join(DIST, generated_dir)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def smoke_test() -> None:
    env = dict(os.environ, AUTODUB_SMOKE="1", QT_QPA_PLATFORM="offscreen")
    run_env = [os.path.join(DIST, "DubFlow")]
    try:
        subprocess.run(run_env, cwd=DIST, env=env, check=True, timeout=180)
    finally:
        clean_distribution_artifacts()


def archive(version: str) -> str:
    output = os.path.join(ROOT, "dist", f"DubFlow-v{version}-linux-x86_64.tar.gz")
    with tarfile.open(output, "w:gz") as archive_file:
        archive_file.add(DIST, arcname="DubFlow")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-test", action="store_true")
    parser.add_argument("--version", default="3.0.7")
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
    for worker in (
            os.path.join("autodub", "speech", "asr_whisper_worker.py"),
            os.path.join("autodub", "speech", "asr_paraformer_worker.py"),
            os.path.join("autodub", "speech", "tts", "vieneu_worker.py"),
            os.path.join("autodub", "media", "demucs_worker.py"),
            os.path.join("autodub", "media", "ocr_worker.py"),
            os.path.join("autodub", "media", "deepseek_ocr_worker.py")):
        bundled = os.path.join(_bundle_data_dir(), worker)
        if not os.path.isfile(bundled):
            raise SystemExit(f"missing worker in bundle: {bundled}")
    assemble(args.version)
    if not args.no_test:
        smoke_test()
    output = archive(args.version)
    print(f"created {output} in {time.time() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
