import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("status_writer.py")


class StatusWriterTest(unittest.TestCase):
    def test_completed_status_clears_stale_failure_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            status_path = output / "job_status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "phase": "thumbnail",
                        "error_code": "ThumbnailFailed",
                        "error_message": "Google Flow thumbnail exit=1",
                        "reason": "old failure",
                        "retry_action": "resume",
                        "provider": "ai33",
                        "tts_cues_completed": 119,
                        "tts_cues_total": 121,
                        "failed_cue": 120,
                        "failed_stage": "tts",
                        "failed_code": "AI33SourceSampleRateLow",
                        "failed_attempts": 3,
                        "resume_from_cue": 120,
                        "phase_label_vi": "Loi TTS",
                        "last_log_line": "TTS failed",
                        "updated_at_epoch": 1,
                    }
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(output),
                    "completed",
                    "100",
                    "Hoan tat video",
                    "0",
                    "",
                    "",
                ],
                check=True,
            )

            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["phase"], "completed")
            self.assertEqual(status["progress_percent"], 100)
            self.assertGreater(status["updated_at_epoch"], 1)
            for key in (
                "error_code",
                "error_message",
                "reason",
                "retry_action",
                "provider",
                "tts_cues_completed",
                "tts_cues_total",
                "failed_cue",
                "failed_stage",
                "failed_code",
                "failed_attempts",
                "resume_from_cue",
                "phase_label_vi",
                "last_log_line",
            ):
                self.assertNotIn(key, status)


if __name__ == "__main__":
    unittest.main()
