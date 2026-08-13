"""Run local OpenClaw file-queue worker."""
from __future__ import annotations

import argparse
import threading

from autodub.config import Settings
from autodub.remote_worker import run_worker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default="remote_queue")
    args = parser.parse_args()
    try:
        run_worker(args.queue, Settings.load(), threading.Event())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
