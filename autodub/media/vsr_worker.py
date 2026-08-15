"""Bridge worker for the external video-subtitle-remover CLI."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--inpaint-mode", default="sttn-det")
    parser.add_argument("--subtitle-area-coords", nargs=4, type=float)
    return parser


def main() -> int:
    args = _parser().parse_args()
    source_root = os.environ.get("DUBFLOW_VSR_SOURCE", "")
    candidates = [
        os.path.join(source_root, "backend", "main.py"),
        os.path.join(source_root, "main.py"),
    ]
    entrypoint = next((path for path in candidates if os.path.isfile(path)), "")
    if not entrypoint:
        raise SystemExit("VSR source entrypoint not found")
    command = [
        sys.executable,
        entrypoint,
        "--input",
        args.input,
        "--output",
        args.output,
        "--inpaint-mode",
        args.inpaint_mode,
    ]
    if args.subtitle_area_coords:
        command += [
            "--subtitle-area-coords",
            *[str(value) for value in args.subtitle_area_coords],
        ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.run(command, env=env)
    print(json.dumps({"returncode": process.returncode}), flush=True)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
