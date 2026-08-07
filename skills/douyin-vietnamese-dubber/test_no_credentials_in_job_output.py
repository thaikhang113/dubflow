#!/usr/bin/env python3
"""Regression: job output must never contain cookie/session credentials.

Covers:
  1. bilibili run.sh must not copy COOKIES_TXT into OUT_DIR.
  2. bilibili run.sh must scrub residual bilibili_cookies.txt from OUT_DIR.
  3. organize_output scrub removes known credential basenames from job_dir.
  4. organize_output allowlist copy never places bilibili_cookies into library.

No network, no real cookies content required (fixture markers only).
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BILI_RUN = ROOT.parent / "bilibili-vietnamese-dubber" / "run.sh"
ORGANIZE = ROOT / "organize_output.py"
COOKIE_MARKER = "# Netscape HTTP Cookie File\nFAKE_SESSION=do-not-ship\n"


def load_organize():
    spec = importlib.util.spec_from_file_location("organize_output", ORGANIZE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_bilibili_run_sh_no_cookie_copy_to_out_dir():
    text = BILI_RUN.read_text(encoding="utf-8", errors="replace")
    # Forbidden: copy cookies into job output
    forbidden = [
        r'cp\s+"\$COOKIES_TXT"\s+"\$OUT_DIR/',
        r'cp\s+\$COOKIES_TXT\s+\$OUT_DIR/',
        r'cp\s+".*bilibili_cookies\.txt"\s+"\$OUT_DIR/',
    ]
    for pat in forbidden:
        assert re.search(pat, text) is None, f"bilibili run.sh still copies cookies to OUT_DIR: {pat}"
    # Required: residual scrub
    assert 'rm -f "$OUT_DIR/bilibili_cookies.txt"' in text, (
        "bilibili run.sh must scrub residual bilibili_cookies.txt from OUT_DIR"
    )
    # Cookies still allowed in JOB_CACHE for yt-dlp
    assert 'COOKIES_TXT="$JOB_CACHE/bilibili_cookies.txt"' in text
    assert 'yt-dlp --cookies "$COOKIES_TXT"' in text
    assert "trap cleanup_bilibili_cookie EXIT" in text
    assert 'rm -f "${COOKIES_TXT:-}"' in text


def test_scrub_forbidden_credentials_removes_cookie_file():
    mod = load_organize()
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp)
        cookie = job / "bilibili_cookies.txt"
        cookie.write_text(COOKIE_MARKER, encoding="utf-8")
        (job / "vietnamese.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n", encoding="utf-8")
        removed = mod.scrub_forbidden_credentials(job)
        assert "bilibili_cookies.txt" in removed
        assert not cookie.exists(), "credential file must be deleted from job_dir"
        assert (job / "vietnamese.srt").exists(), "non-credential files must remain"


def test_organize_output_never_copies_cookies_to_library():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        job = tmp / "job"
        base = tmp / "base"
        job.mkdir()
        base.mkdir()
        # Minimal final video + planted credential residual
        (job / "final_video_vi.mp4").write_bytes(b"\x00\x00fake-mp4")
        (job / "vietnamese.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chao\n", encoding="utf-8")
        (job / "bilibili_cookies.txt").write_text(COOKIE_MARKER, encoding="utf-8")
        (job / "source_input.txt").write_text("https://www.bilibili.com/video/BV1xx411c7mD\n", encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(ORGANIZE), "--job-dir", str(job), "--base-dir", str(base)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"organize failed: {proc.stderr}\n{proc.stdout}"

        # Cookie scrubbed from job
        assert not (job / "bilibili_cookies.txt").exists()

        # No cookie anywhere under library / base
        leaked = [p for p in base.rglob("*") if p.is_file() and "cookie" in p.name.lower()]
        assert leaked == [], f"cookie files leaked into library: {leaked}"

        meta = json.loads((job / "final_metadata.json").read_text(encoding="utf-8"))
        assert "bilibili_cookies.txt" in meta.get("scrubbed_credentials", [])
        # outputs must not reference cookies
        for key, val in (meta.get("outputs") or {}).items():
            if val:
                assert "cookie" not in str(val).lower()


def main():
    test_bilibili_run_sh_no_cookie_copy_to_out_dir()
    print("PASS test_bilibili_run_sh_no_cookie_copy_to_out_dir")
    test_scrub_forbidden_credentials_removes_cookie_file()
    print("PASS test_scrub_forbidden_credentials_removes_cookie_file")
    test_organize_output_never_copies_cookies_to_library()
    print("PASS test_organize_output_never_copies_cookies_to_library")
    print("ALL PASS")


if __name__ == "__main__":
    main()
