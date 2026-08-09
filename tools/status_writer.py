#!/usr/bin/env python3
import json
import os
import sys
import time
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
        state="completed" if phase == "completed" else "running",
        phase=phase,
        progress=value,
        progress_percent=value,
        label=label,
        updated_at_epoch=time.time(),
        last_heartbeat_at=time.strftime("%F %T %z"),
    )
    if error_code:
        status["error_code"] = error_code
    if error_message:
        status["error_message"] = error_message
    if not error_code:
        status.pop("error_code", None)
        status.pop("error_message", None)
        status.pop("reason", None)
        status.pop("retry_action", None)
    if phase == "completed":
        for key in (
            "provider",
            "tts_cues_completed",
            "tts_cues_total",
            "tts_cues_reused",
            "failed_cue",
            "failed_stage",
            "failed_code",
            "failed_attempts",
            "resume_from_cue",
            "phase_label_vi",
            "last_log_line",
        ):
            status.pop(key, None)
    temporary = status_path.with_name(status_path.name + ".tmp")
    temporary.write_text(json.dumps(status, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, status_path)


if __name__ == "__main__":
    main()
