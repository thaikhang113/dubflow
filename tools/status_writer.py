#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path


def main():
    out_dir, phase, progress, label, api_expected, error_code, error_message = sys.argv[1:8]
    status_path = Path(out_dir) / "job_status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        status = {}
    value = max(0, min(100, int(float(progress))))
    status.update(
        state="running",
        phase=phase,
        progress=value,
        progress_percent=value,
        label=label,
    )
    if error_code:
        status["error_code"] = error_code
    if error_message:
        status["error_message"] = error_message
    temporary = status_path.with_name(status_path.name + ".tmp")
    temporary.write_text(json.dumps(status, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, status_path)


if __name__ == "__main__":
    main()
