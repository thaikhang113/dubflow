#!/usr/bin/env python3
"""Offline Phase-4 exact per-cue resume contract; no upstream hooks/provider network."""

import importlib.util
import struct
import tempfile
import unittest
import wave
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("tts_resume", SKILL_DIR / "tts_resume.py")
resume = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resume)


def write_wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
        out.writeframes(struct.pack("<" + "h" * 2400, *([500] * 2400)))


class ResumeIntegrationTests(unittest.TestCase):
    def test_122_cues_reuse_1_to_86_then_only_generate_87_to_122_and_edit_50(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); provider_calls = []; upstream_calls = []
            cues = [(f"cue {i}", i * 100, i * 100 + 100) for i in range(1, 123)]
            settings = {"speed": 1.0, "context_chaining": "false", "sample_rate": 24000, "channels": 1, "provider": "ai33"}
            config = resume.make_config(cues, "ai33:voice", settings, 24000, 1)
            def provider(index, _text, output):
                provider_calls.append(index); write_wav(output); return 1
            first = resume.run_cues(root, cues[:86], config, provider, upstream_hook=lambda: upstream_calls.append("bad"), require_complete=False)
            self.assertEqual(list(range(1, 87)), provider_calls)
            provider_calls.clear()
            result = resume.run_cues(root, cues, config, provider, upstream_hook=lambda: upstream_calls.append("bad"))
            self.assertEqual(list(range(87, 123)), provider_calls)
            self.assertEqual((122, 86, 122), (result["completed"], result["reused"], len(result["master_inputs"])))
            self.assertEqual([], upstream_calls)
            self.assertTrue(all(path.exists() for path in result["master_inputs"]))
            provider_calls.clear()
            changed = list(cues); changed[49] = ("changed cue 50", 5000, 5100)
            changed_config = resume.make_config(changed, "ai33:voice", settings, 24000, 1)
            result = resume.run_cues(root, changed, changed_config, provider, upstream_hook=lambda: upstream_calls.append("bad"))
            self.assertEqual([50], provider_calls)
            self.assertEqual((122, 121), (result["completed"], result["reused"]))
            self.assertEqual([], upstream_calls)


if __name__ == "__main__": unittest.main()
