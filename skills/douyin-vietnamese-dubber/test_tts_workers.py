#!/usr/bin/env python3
import unittest
from pathlib import Path

RUN_SH = Path(__file__).with_name("run.sh")
SPEECH_PREPROCESS = Path(__file__).with_name("speech_only_preprocess.py")


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

    def test_prefetch_stops_submitting_batches_after_provider_failure(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn(
            'if any((result[0] or {}).get("ai33_failed") for result in batch_results.values()):',
            source,
        )
        self.assertIn('print("AI33 prefetch stopped after provider failure", flush=True)', source)

    def test_voice_qa_retry_forces_only_failed_cues(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("TTS_FORCE_CUE_IDS", source)
        self.assertIn("TTS_SPOKEN_TEXT_OVERRIDES_JSON", source)
        self.assertIn("if entry_index in forced_cue_ids:", source)
        self.assertIn('"$WHISPER_BIN" -m "$WHISPER_MODEL" -f "$VIETNAMESE_VOICE_WAV" -l vi -osrt', source)
        self.assertIn('retry-overrides --report "$TTS_VOICE_QUALITY_REPORT_JSON"', source)
        self.assertIn('TTS_FORCE_CUE_IDS="$tts_qa_failed_cues"', source)
        self.assertIn("tts_qa_ai33=$?", source)
        self.assertIn('"TTSPronunciationQualityFailed"', source)

    def test_auto_bgm_requires_real_demucs_no_vocals_stem(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn('BGM_MODE_FALLBACK="${BGM_MODE_FALLBACK:-none}"', source)
        self.assertIn('"BackgroundSeparationFailed"', source)
        self.assertIn('data.get("demucs", {}).get("used") is True', source)
        auto_case = source[source.index("select_bgm_source() {"):source.index("write_fit_adjustments_report() {")]
        self.assertNotIn('else SELECTED_BGM_MODE="duck"; SELECTED_BGM_SOURCE="$VIDEO"', auto_case)

    def test_demucs_keeps_music_bed_stereo_48k(self):
        source = SPEECH_PREPROCESS.read_text(encoding="utf-8")
        self.assertIn("def ffmpeg_extract_demucs_input", source)
        self.assertIn('"2", "-ar", "48000"', source)
        self.assertIn("convert_music_bed(found_no_vocals, no_vocals_wav)", source)
        self.assertIn("demucs_separate(demucs_input", source)

    def test_ai33_pronunciation_dictionary_reaches_wrapper_and_checkpoint(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("AI33_PRONUNCIATION_DICTIONARY_ID", source)
        self.assertIn("'pronunciation_dictionary_id': ai33_pronunciation_dictionary_id", source)
        self.assertIn("'--pronunciation-dictionary-id', ai33_pronunciation_dictionary_id", source)

    def test_ai33_low_source_sample_rate_retries_only_the_failed_cue_once(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("AI33SourceSampleRateLow", source)
        self.assertIn("AI33_SOURCE_QUALITY_RETRIES", source)
        self.assertIn("cmd.append('--force-regenerate')", source)
        wrapper = Path(__file__).with_name("ai33_tts_synthesize.py").read_text(encoding="utf-8")
        self.assertIn('if error.code != "AI33SourceSampleRateLow":', wrapper)


if __name__ == "__main__":
    unittest.main(verbosity=2)
