import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from web_tool.config import Settings
from web_tool.secrets import SecretStore
from web_tool.store import Store
from web_tool.worker import Worker


def wait_for(store: Store, job_id: str, states: set[str], timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = store.get_job(job_id)
        if job["state"] in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job did not reach {states}: {store.get_job(job_id)}")


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = Settings.for_test(self.root)
        self.store = Store(self.settings.database_path)
        self.secrets = SecretStore(self.settings.secrets_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def write_script(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return path

    def enqueue(self) -> dict:
        return self.store.enqueue_job(
            {
                "platform": "douyin",
                "source": "https://www.douyin.com/video/1",
            }
        )

    def test_worker_completes_only_with_decodable_final_video(self):
        script = self.write_script(
            "success.py",
            """
import json
import os
from pathlib import Path
import subprocess

root = Path(os.environ["DOUYIN_VIDEOS_DIR"])
out = root / "fake-output"
out.mkdir(parents=True)
(root / "LATEST_OUTPUT_DIR.txt").write_text(str(out), encoding="utf-8")
(out / "job_status.json").write_text(json.dumps({
    "state": "running", "phase": "render", "progress_percent": 90
}), encoding="utf-8")
subprocess.run([
    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
    "-f", "lavfi", "-i", "color=c=black:s=32x32:d=0.2",
    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
    str(out / "final_video_vi.mp4"),
], check=True)
""",
        )
        job = self.enqueue()
        worker = Worker(self.store, self.settings, self.secrets)
        with patch(
            "web_tool.worker.build_job_command",
            return_value=[sys.executable, str(script)],
        ):
            worker.start()
            worker.notify()
            completed = wait_for(self.store, job["id"], {"completed", "failed"})
            worker.stop()
        self.assertEqual("completed", completed["state"])
        self.assertEqual(100, completed["progress"])
        self.assertTrue(
            (Path(completed["job_dir"]) / "final_video_vi.mp4").is_file()
        )

    def test_cancel_terminates_process_and_preserves_job_directory(self):
        script = self.write_script(
            "sleep.py",
            "import time\ntime.sleep(30)\n",
        )
        job = self.enqueue()
        worker = Worker(self.store, self.settings, self.secrets, cancel_grace=0.2)
        with patch(
            "web_tool.worker.build_job_command",
            return_value=[sys.executable, str(script)],
        ):
            worker.start()
            worker.notify()
            running = wait_for(self.store, job["id"], {"running"})
            self.assertTrue(worker.cancel(job["id"]))
            cancelled = wait_for(self.store, job["id"], {"cancelled"})
            worker.stop()
        self.assertEqual("cancelled", cancelled["state"])
        self.assertTrue(Path(running["job_dir"]).is_dir())

    def test_stop_leaves_running_job_recoverable(self):
        script = self.write_script(
            "sleep-for-stop.py",
            "import time\ntime.sleep(30)\n",
        )
        job = self.enqueue()
        worker = Worker(self.store, self.settings, self.secrets, cancel_grace=0.2)
        with patch(
            "web_tool.worker.build_job_command",
            return_value=[sys.executable, str(script)],
        ):
            worker.start()
            worker.notify()
            wait_for(self.store, job["id"], {"running"})
            worker.stop()
        self.assertEqual("running", self.store.get_job(job["id"])["state"])
        self.assertEqual(1, self.store.recover_running_jobs())
        self.assertEqual(
            "needs_attention",
            self.store.get_job(job["id"])["state"],
        )

    def test_bilibili_login_exit_has_structured_error(self):
        script = self.write_script(
            "bilibili-login-required.py",
            "raise SystemExit(20)\n",
        )
        job = self.store.enqueue_job(
            {
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1",
            }
        )
        worker = Worker(self.store, self.settings, self.secrets)
        with patch(
            "web_tool.worker.build_job_command",
            return_value=[sys.executable, str(script)],
        ):
            worker.start()
            worker.notify()
            failed = wait_for(
                self.store,
                job["id"],
                {"needs_attention", "failed"},
            )
            worker.stop()
        self.assertEqual("needs_attention", failed["state"])
        self.assertEqual("BilibiliLoginRequired", failed["error_code"])

    def test_refresh_finds_nested_status_before_output_pointer_exists(self):
        job = self.store.enqueue_job(
            {
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1",
            }
        )
        job_root = self.settings.jobs_dir / job["id"]
        output_dir = job_root / "Bilibili" / "input-20260809-133716"
        output_dir.mkdir(parents=True)
        (output_dir / "job_status.json").write_text(
            json.dumps(
                {
                    "state": "running",
                    "phase": "preprocess",
                    "progress_percent": 18,
                    "label": "Đang tách giọng/nhạc trước ASR",
                }
            ),
            encoding="utf-8",
        )

        Worker(self.store, self.settings, self.secrets)._refresh(job["id"], job_root)

        refreshed = self.store.get_job(job["id"])
        self.assertEqual(18, refreshed["progress"])
        self.assertEqual(str(output_dir), refreshed["job_dir"])


if __name__ == "__main__":
    unittest.main()
