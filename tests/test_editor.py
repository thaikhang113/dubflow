"""Tests for the segment-editor core (autodub.editor).

TTS and ffmpeg are stubbed — no synthesis, no encoding.
"""
import json
import os

import pytest

from autodub import editor
from autodub.config import Settings
from autodub.editor import (
    EditorError,
    load_render_opts,
    load_work_dir,
    resolve_existing_background,
    resynth_segment,
    save_render_opts,
    update_segment_text,
)


def make_segments():
    return [
        {"id": 1, "text": "原文1", "start": 0.0, "end": 2.0, "duration": 2.0, "text_vi": "câu 1"},
        {"id": 2, "text": "原文2", "start": 2.0, "end": 4.0, "duration": 2.0, "text_vi": "câu 2"},
    ]


@pytest.fixture
def work_dir(tmp_path):
    """A minimal finished work dir: transcript + source video + cached wavs."""
    d = tmp_path / "20260101000000_vi"
    d.mkdir()
    (d / "transcript_vi.json").write_text(
        json.dumps(make_segments(), ensure_ascii=False), encoding="utf-8")
    (d / "source.mp4").write_bytes(b"x")
    (d / "dubbed_video.mp4").write_bytes(b"x")
    (d / "audio_vi_full.wav").write_bytes(b"x")
    (d / "no_vocals.wav").write_bytes(b"x")
    (d / "original_audio.wav").write_bytes(b"x")
    segs = d / "segments"
    segs.mkdir()
    for i in (1, 2):
        (segs / f"seg_{i:03d}.wav").write_bytes(b"x")
    # Wavs rendered under the current 1:1 scheme (pre-1:1 dirs are rejected).
    from autodub.pipeline import DubPipeline
    (segs / ".render_mode").write_text(DubPipeline.RENDER_MODE, encoding="utf-8")
    fit = d / "segments_fit"
    fit.mkdir()
    for i in (1, 2):
        (fit / f"seg_{i:03d}.wav").write_bytes(b"x")
    return str(d)


# --------------------------- load --------------------------- #

def test_load_work_dir(work_dir):
    state = load_work_dir(work_dir)
    assert len(state.segments) == 2
    assert state.target.text_field == "text_vi"
    assert state.video_path.endswith("source.mp4")     # not dubbed_video.mp4


def test_load_missing_dir():
    with pytest.raises(EditorError, match="not found"):
        load_work_dir("/nope/does/not/exist")


def test_load_without_translation(tmp_path):
    (tmp_path / "x").mkdir()
    with pytest.raises(EditorError, match="No translation"):
        load_work_dir(str(tmp_path / "x"))


# --------------------------- edit --------------------------- #

def test_update_segment_text_persists(work_dir):
    update_segment_text(work_dir, 1, "câu một mới")
    data = json.loads((open(os.path.join(work_dir, "transcript_vi.json"), encoding="utf-8")).read())
    assert data[0]["text_vi"] == "câu một mới"
    assert data[1]["text_vi"] == "câu 2"                # untouched


def test_update_rejects_empty(work_dir):
    with pytest.raises(EditorError, match="trống"):
        update_segment_text(work_dir, 1, "   ")


def test_update_unknown_id(work_dir):
    with pytest.raises(EditorError, match="Không tìm thấy câu"):
        update_segment_text(work_dir, 99, "x")


# --------------------------- resynth --------------------------- #

def test_resynth_invalidates_stale_artifacts(work_dir, monkeypatch):
    calls = {}

    class FakeResult:
        def to_dict(self):
            return {"actual_duration": 1.9, "speed_adjusted": False, "rate_applied": "1.0"}

    class FakeSynth:
        def synthesize(self, text, output_path, target_duration):
            calls["text"] = text
            with open(output_path, "wb") as f:
                f.write(b"new-audio")
            return FakeResult()

    monkeypatch.setattr(editor, "get_synthesizer", lambda *a, **k: FakeSynth(),
                        raising=False)
    # get_synthesizer is imported inside the function; patch the source too.
    import autodub.speech.tts as tts
    monkeypatch.setattr(tts, "get_synthesizer", lambda *a, **k: FakeSynth())

    update_segment_text(work_dir, 1, "câu mới cho segment một")
    resynth_segment(work_dir, 1, Settings())

    # Strict 1:1 — only segment 1's own text is re-rendered (with terminal
    # punctuation enforced), keyed by its own id.
    assert calls["text"] == "câu mới cho segment một."
    assert open(os.path.join(work_dir, "segments", "seg_001.wav"), "rb").read() == b"new-audio"
    # stale derived outputs for the segment removed
    assert not os.path.exists(os.path.join(work_dir, "segments_fit", "seg_001.wav"))
    assert not os.path.exists(os.path.join(work_dir, "audio_vi_full.wav"))
    assert not os.path.exists(os.path.join(work_dir, "dubbed_video.mp4"))


def test_resynth_is_one_to_one(work_dir, monkeypatch):
    """Editing one segment re-renders only that segment — never a group."""
    calls = {}

    class FakeResult:
        def to_dict(self):
            return {"actual_duration": 1.9, "speed_adjusted": False, "rate_applied": "1.0"}

    class FakeSynth:
        def synthesize(self, text, output_path, target_duration):
            calls["text"] = text
            calls["target_duration"] = target_duration
            with open(output_path, "wb") as f:
                f.write(b"new-audio")
            return FakeResult()

    import autodub.speech.tts as tts
    monkeypatch.setattr(tts, "get_synthesizer", lambda *a, **k: FakeSynth())

    resynth_segment(work_dir, 2, Settings())
    assert calls["text"] == "câu 2."
    # Last segment: slot = duration + tail_slack (2.0 + 2.0)
    assert calls["target_duration"] == 4.0
    # seg 1's fitted wav left alone
    assert os.path.exists(os.path.join(work_dir, "segments_fit", "seg_001.wav"))


# --------------------------- background resolution --------------------------- #

def test_background_demucs_reuses_no_vocals(work_dir):
    path, gain = resolve_existing_background(work_dir, "demucs", -12.0)
    assert path.endswith("no_vocals.wav") and gain == 0.0


def test_background_duck_uses_original_with_gain(work_dir):
    path, gain = resolve_existing_background(work_dir, "duck", -15.0)
    assert path.endswith("original_audio.wav") and gain == -15.0


def test_background_none_is_silent(work_dir):
    assert resolve_existing_background(work_dir, "none", 0.0) == (None, 0.0)


def test_background_demucs_missing_falls_back(tmp_path):
    (tmp_path / "e").mkdir()
    assert resolve_existing_background(str(tmp_path / "e"), "demucs", 0.0) == (None, 0.0)


# --------------------------- rebuild --------------------------- #

def test_rebuild_reuses_cached_wavs(work_dir, monkeypatch):
    """Rebuild must not re-run TTS; it only mixes and muxes."""
    seen = {}
    import autodub.media.audio as audio_mod
    import autodub.media.video as video_mod
    import autodub.text.srt as srt_mod

    monkeypatch.setattr(audio_mod, "merge_segments",
                        lambda *a, **k: seen.setdefault("merged", a[2]))
    monkeypatch.setattr(video_mod, "merge_video",
                        lambda *a, **k: seen.setdefault("video", a[2]) or a[2])
    monkeypatch.setattr(srt_mod, "generate_srt",
                        lambda *a, **k: seen.setdefault("srt", True))

    out = editor.rebuild_output(work_dir, Settings(), subtitle_mode="burn", blur_regions=[])
    assert out.endswith("dubbed_video.mp4")
    assert seen["merged"].endswith("audio_vi_full.wav")
    assert seen["srt"] is True
    # render opts persisted for next time
    assert load_render_opts(work_dir)["subtitle_mode"] == "burn"


def test_rebuild_defaults_to_persisted_render_opts(work_dir, monkeypatch):
    save_render_opts(work_dir, {"subtitle_mode": "soft", "blur_regions": [{"x": 0}]})
    captured = {}
    import autodub.media.audio as audio_mod
    import autodub.media.video as video_mod
    import autodub.text.srt as srt_mod
    monkeypatch.setattr(audio_mod, "merge_segments", lambda *a, **k: None)
    monkeypatch.setattr(srt_mod, "generate_srt", lambda *a, **k: None)

    def fake_merge_video(*a, **k):
        captured["mode"] = k.get("subtitle_mode")
        captured["blur"] = k.get("blur_regions")
        return a[2]

    monkeypatch.setattr(video_mod, "merge_video", fake_merge_video)
    editor.rebuild_output(work_dir, Settings())      # no explicit opts
    assert captured["mode"] == "soft"
    assert captured["blur"] == [{"x": 0}]


def test_rebuild_passes_subtitle_style(work_dir, monkeypatch):
    captured = {}
    import autodub.media.audio as audio_mod
    import autodub.media.video as video_mod
    import autodub.text.srt as srt_mod
    monkeypatch.setattr(audio_mod, "merge_segments", lambda *a, **k: None)
    monkeypatch.setattr(srt_mod, "generate_srt", lambda *a, **k: None)
    monkeypatch.setattr(video_mod, "merge_video",
                        lambda *a, **k: captured.setdefault("style", k.get("subtitle_style")) or a[2])

    style = {"font_size": 30, "position": "top", "margin_v": 60}
    editor.rebuild_output(work_dir, Settings(), subtitle_mode="burn",
                          subtitle_style=style)

    # Kiểu được điền đủ mọi khóa trước khi dùng, nhưng ba mục người dùng chốt
    # phải đi thẳng tới ffmpeg và được lưu lại y nguyên cho lần xuất sau.
    for key, value in style.items():
        assert captured["style"][key] == value
        assert load_render_opts(work_dir)["subtitle_style"][key] == value


# --------------------------- batch save --------------------------- #

def read_transcript(work_dir):
    with open(os.path.join(work_dir, "transcript_vi.json"), encoding="utf-8") as f:
        return json.load(f)


def test_save_segment_texts_returns_only_changed(work_dir):
    changed = editor.save_segment_texts(work_dir, {1: "câu 1 mới", 2: "câu 2"})
    assert changed == [1]                      # seg 2 text identical → not re-synth
    assert read_transcript(work_dir)[0]["text_vi"] == "câu 1 mới"


def test_save_segment_texts_saves_all_at_once(work_dir):
    changed = editor.save_segment_texts(work_dir, {1: "một", 2: "hai"})
    assert changed == [1, 2]
    data = read_transcript(work_dir)
    assert [s["text_vi"] for s in data] == ["một", "hai"]


def test_save_segment_texts_is_atomic_on_blank(work_dir):
    """One blank line must not leave a half-written transcript."""
    with pytest.raises(EditorError, match="trống"):
        editor.save_segment_texts(work_dir, {1: "hợp lệ", 2: "  "})
    assert [s["text_vi"] for s in read_transcript(work_dir)] == ["câu 1", "câu 2"]


def test_save_segment_texts_no_edits(work_dir):
    assert editor.save_segment_texts(work_dir, {}) == []


# --------------------------- batch resynth --------------------------- #

def stub_tts(monkeypatch, log=None):
    class FakeResult:
        def to_dict(self):
            return {"actual_duration": 1.9, "speed_adjusted": False, "rate_applied": "1.0"}

    class FakeSynth:
        def synthesize(self, text, output_path, target_duration):
            if log is not None:
                log.append(text)
            with open(output_path, "wb") as f:
                f.write(b"new-audio")
            return FakeResult()

    import autodub.speech.tts as tts
    monkeypatch.setattr(tts, "get_synthesizer", lambda *a, **k: FakeSynth())


def test_resynth_segments_reports_progress(work_dir, monkeypatch):
    spoken, progress = [], []
    stub_tts(monkeypatch, spoken)
    editor.save_segment_texts(work_dir, {1: "một mới", 2: "hai mới"})

    results = editor.resynth_segments(
        work_dir, [1, 2], Settings(),
        on_progress=lambda done, total, sid: progress.append((done, total, sid)))

    # Strict 1:1 — each segment renders its own clip.
    assert spoken == ["một mới.", "hai mới."]
    assert len(results) == 2
    assert progress == [(1, 2, 1), (2, 2, 2)]


def test_resynth_segments_removes_locked_file_after_retry(work_dir, monkeypatch):
    """WinError 32 regression: a briefly locked wav must not fail the save."""
    stub_tts(monkeypatch)
    real_remove = os.remove
    state = {"denied": 0}
    locked = os.path.join(work_dir, "segments_fit", "seg_001.wav")

    def flaky_remove(path):
        if os.path.abspath(path) == os.path.abspath(locked) and state["denied"] < 2:
            state["denied"] += 1
            raise PermissionError(32, "The process cannot access the file")
        real_remove(path)

    monkeypatch.setattr(os, "remove", flaky_remove)
    monkeypatch.setattr("time.sleep", lambda s: None)

    editor.save_segment_texts(work_dir, {1: "một mới"})
    editor.resynth_segments(work_dir, [1], Settings())

    assert state["denied"] == 2                 # retried past the lock
    assert not os.path.exists(locked)
