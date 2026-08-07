#!/usr/bin/env python3
import unittest
from pathlib import Path

RUN_SH = Path(__file__).with_name("run.sh")


class TTSWorkerTests(unittest.TestCase):
    def test_ai33_prefetch_uses_three_worker_cap_and_keeps_ordered_results(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn('AI33_TTS_WORKERS="${AI33_TTS_WORKERS:-3}"', source)
        self.assertIn("ThreadPoolExecutor(max_workers=ai33_tts_workers)", source)
        self.assertIn("prefetched_tts_results.update(batch_results)", source)
        self.assertIn("for entry_index in range(1, total_entries + 1)", source)
        checkpoint = Path(__file__).with_name("tts_checkpoint.py").read_text(encoding="utf-8")
        self.assertIn("def _manifest_lock", checkpoint)
        self.assertIn("with _manifest_lock(manifest_path)", checkpoint)
        ai33 = Path(__file__).with_name("ai33_tts_synthesize.py").read_text(encoding="utf-8")
        self.assertIn("with tts_checkpoint._manifest_lock(target)", ai33)
        self.assertIn("with tts_checkpoint._manifest_lock(report_path)", ai33)

    def test_prefetch_skips_reusable_checkpoint_cues_without_ramping_above_three(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("reusable_checkpoint_cues", source)
        self.assertIn("if entry_index not in reusable_checkpoint_cues", source)
        self.assertIn('ai33_tts_workers = max(1, min(3, int(os.environ.get("AI33_TTS_WORKERS", "3") or "3")))', source)
        self.assertNotIn("ai33_tts_workers += 1", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
