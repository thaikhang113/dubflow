import os
from pydub import AudioSegment
from pydub.generators import Sine
from autodub.media.audio import merge_segments


def _make_segment_file(path: str, duration_ms: int = 1000):
    tone = Sine(440).to_audio_segment(duration=duration_ms)
    tone.export(path, format="wav")


def test_merge_segments_basic(tmp_path):
    seg_dir = str(tmp_path / "segments")
    os.makedirs(seg_dir)

    _make_segment_file(os.path.join(seg_dir, "seg_001.wav"), 500)
    _make_segment_file(os.path.join(seg_dir, "seg_002.wav"), 800)

    segments = [
        {"id": 1, "start": 0.0, "end": 1.0, "duration": 1.0},
        {"id": 2, "start": 2.0, "end": 3.5, "duration": 1.5},
    ]
    total_duration = 5.0
    output_path = str(tmp_path / "merged.wav")

    result = merge_segments(segments, seg_dir, output_path, total_duration)
    assert os.path.exists(result)

    audio = AudioSegment.from_wav(result)
    assert abs(len(audio) / 1000.0 - total_duration) < 0.1


def test_merge_segments_empty(tmp_path):
    seg_dir = str(tmp_path / "segments")
    os.makedirs(seg_dir)
    output_path = str(tmp_path / "merged.wav")

    result = merge_segments([], seg_dir, output_path, total_duration=3.0)
    assert os.path.exists(result)
    audio = AudioSegment.from_wav(result)
    assert abs(len(audio) / 1000.0 - 3.0) < 0.1


def _save_tone(path: str, freq: int, duration_ms: int):
    Sine(freq).to_audio_segment(duration=duration_ms).export(path, format="wav")


def test_merge_segments_uses_background(tmp_path):
    seg_dir = str(tmp_path / "segments")
    os.makedirs(seg_dir)
    _save_tone(os.path.join(seg_dir, "seg_001.wav"), freq=440, duration_ms=500)

    bg_path = str(tmp_path / "no_vocals.wav")
    _save_tone(bg_path, freq=110, duration_ms=4000)

    output_path = str(tmp_path / "merged.wav")
    segments = [{"id": 1, "start": 1.0, "end": 1.5, "duration": 0.5}]

    merge_segments(segments, seg_dir, output_path, total_duration=4.0,
                   background_path=bg_path)

    merged = AudioSegment.from_wav(output_path)
    assert abs(len(merged) / 1000.0 - 4.0) < 0.1

    # The background tone should still be audible at t=0 (no segment overlay there)
    head = merged[:300]
    silent = AudioSegment.silent(duration=300, frame_rate=merged.frame_rate)
    assert head.dBFS > silent.dBFS + 10  # at least 10 dB louder than silence


def test_merge_segments_pads_short_background(tmp_path):
    seg_dir = str(tmp_path / "segments")
    os.makedirs(seg_dir)

    bg_path = str(tmp_path / "no_vocals.wav")
    _save_tone(bg_path, freq=110, duration_ms=1000)  # shorter than total_duration

    output_path = str(tmp_path / "merged.wav")
    merge_segments([], seg_dir, output_path, total_duration=3.0,
                   background_path=bg_path)

    merged = AudioSegment.from_wav(output_path)
    assert abs(len(merged) / 1000.0 - 3.0) < 0.1


def test_merge_segments_missing_background_falls_back(tmp_path):
    seg_dir = str(tmp_path / "segments")
    os.makedirs(seg_dir)
    output_path = str(tmp_path / "merged.wav")

    merge_segments([], seg_dir, output_path, total_duration=2.0,
                   background_path=str(tmp_path / "does_not_exist.wav"))

    merged = AudioSegment.from_wav(output_path)
    assert abs(len(merged) / 1000.0 - 2.0) < 0.1


def test_merge_segments_applies_background_gain(tmp_path):
    """In duck mode the original audio is reduced by N dB before overlay."""
    seg_dir = str(tmp_path / "segments")
    os.makedirs(seg_dir)
    bg_path = str(tmp_path / "original_audio.wav")
    _save_tone(bg_path, freq=440, duration_ms=3000)

    full_output = str(tmp_path / "full.wav")
    quiet_output = str(tmp_path / "quiet.wav")

    merge_segments([], seg_dir, full_output, total_duration=3.0,
                   background_path=bg_path)
    merge_segments([], seg_dir, quiet_output, total_duration=3.0,
                   background_path=bg_path, background_gain_db=-12.0)

    full = AudioSegment.from_wav(full_output)
    quiet = AudioSegment.from_wav(quiet_output)
    # -12 dB should drop loudness noticeably; allow a 1 dB tolerance for the
    # round-trip through pydub + 16-bit PCM export
    assert quiet.dBFS < full.dBFS - 10
    assert abs(len(quiet) / 1000.0 - 3.0) < 0.1
