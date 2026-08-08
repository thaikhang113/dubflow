import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


source = sys.argv[1]
root = Path(os.environ["BILIBILI_OUTPUT_ROOT"])
output = root / "fake-output"
output.mkdir(parents=True, exist_ok=True)
(root / "LATEST_OUTPUT_DIR.txt").write_text(str(output.resolve()), encoding="utf-8")


def status(**values):
    (output / "job_status.json").write_text(
        json.dumps(values, ensure_ascii=False),
        encoding="utf-8",
    )


def interrupted(_signum, _frame):
    (output / "checkpoint.json").write_text(
        '{"resume_from_cue":2}\n',
        encoding="utf-8",
    )
    status(
        state="needs_attention",
        phase="interrupted",
        progress_percent=40,
        error_code="FakeInterrupted",
        error_message="Fake pipeline interrupted.",
        retry_action="resume",
        resume_from_cue=2,
    )
    raise SystemExit(8)


signal.signal(signal.SIGTERM, interrupted)
status(state="running", phase="download", progress_percent=10, label="Downloading")
time.sleep(0.3)
status(state="running", phase="translate", progress_percent=45, label="Translating")
time.sleep(0.3)

resuming = bool(os.environ.get("OPENCLAW_RESUME_JOB_DIR"))
if "BVFAIL" in source and not resuming:
    (output / "checkpoint.json").write_text(
        '{"resume_from_cue":2}\n',
        encoding="utf-8",
    )
    status(
        state="needs_attention",
        phase="tts",
        progress_percent=66,
        error_code="FakeCueFailed",
        error_message="Cue 2 failed.",
        retry_action="resume",
        failed_cue=2,
        resume_from_cue=2,
    )
    raise SystemExit(7)

status(
    state="running",
    phase="render",
    progress_percent=90,
    label="Rendering resumed job" if resuming else "Rendering",
)
subprocess.run(
    [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=64x64:rate=10",
        "-t",
        "0.5",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        str(output / "final_video_vi.mp4"),
    ],
    check=True,
)
status(state="completed", phase="done", progress_percent=100, label="Completed")
