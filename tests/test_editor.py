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
    _branding_options,
    _refresh_ocr_regions,
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


def test_branding_options_reads_legacy_json_region(tmp_path):
    settings = Settings(
        branding_logo_path="default.png",
        branding_logo_region='{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}',
        branding_logo_opacity=0.8,
    )
    state = editor.EditorState(
        work_dir=str(tmp_path), target=None, segments=[], render_opts={})

    options = _branding_options(state, settings)

    assert options["logo_path"] == "default.png"
    assert options["logo_region"] == {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}
    assert options["logo_opacity"] == 0.8
    assert options["logo_scale"] == Settings().branding_logo_scale
    assert options["vision_enabled"] is Settings().branding_vision_enabled

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

def test_refresh_ocr_regions_replaces_ocr_and_keeps_manual_regions(
    work_dir, monkeypatch
):
    settings = Settings(ocr_enabled=True, ocr_subtitle_y_min=0.65)
    old_manual = {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.1}
    old_logo = {"x": 0.7, "y": 0.05, "w": 0.15, "h": 0.08, "source": "logo"}
    old_ocr = {"x": 0.2, "y": 0.8, "w": 0.3, "h": 0.1, "source": "ocr"}
    save_render_opts(work_dir, {
        "ocr_enabled": True,
        "ocr_subtitle_y_min": 0.72,
        "blur_regions": [old_manual, old_logo, old_ocr],
    })
    seen = {}

    def fake_detect(video, width, height, duration, detected_settings):
        seen.update({
            "video": video,
            "width": width,
            "height": height,
            "duration": duration,
            "y_min": detected_settings.ocr_subtitle_y_min,
        })
        return (
            [{"x": 0.4, "y": 0.75, "w": 0.2, "h": 0.1, "source": "ocr"}],
            [],
        )

    monkeypatch.setattr(editor, "_probe_ocr_video", lambda _path: (1920, 1080, 4.0))
    monkeypatch.setattr("autodub.media.ocr.detect_regions_with_logo", fake_detect)

    state = load_work_dir(work_dir)
    result = _refresh_ocr_regions(
        work_dir, settings, state, [old_manual, old_logo, old_ocr])

    assert result == [
        old_manual,
        old_logo,
        {"x": 0.4, "y": 0.75, "w": 0.2, "h": 0.1, "source": "ocr"},
    ]
    assert seen["y_min"] == 0.72
    assert load_render_opts(work_dir)["blur_regions"] == result

def test_refresh_ocr_regions_disabled_removes_only_ocr(work_dir):
    settings = Settings(ocr_enabled=True, branding_vision_enabled=False)
    manual = {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.1}
    logo = {"x": 0.7, "y": 0.1, "w": 0.2, "h": 0.1, "source": "logo"}
    ocr = {"x": 0.2, "y": 0.8, "w": 0.3, "h": 0.1, "source": "ocr"}
    save_render_opts(work_dir, {"ocr_enabled": False,
                                "blur_regions": [manual, logo, ocr]})

    state = load_work_dir(work_dir)
    result = _refresh_ocr_regions(work_dir, settings, state, [manual, logo, ocr])

    assert result == [manual, logo]
    assert load_render_opts(work_dir)["blur_regions"] == [manual, logo]

def test_refresh_ocr_regions_explicit_editor_settings_override_persisted_values(
    work_dir, monkeypatch
):
    settings = Settings(ocr_enabled=True, ocr_subtitle_y_min=0.65)
    manual = {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.1}
    old_ocr = {"x": 0.2, "y": 0.8, "w": 0.3, "h": 0.1, "source": "ocr"}
    save_render_opts(work_dir, {
        "ocr_enabled": True,
        "ocr_subtitle_y_min": 0.72,
        "blur_regions": [manual, old_ocr],
    })
    monkeypatch.setattr(
        "autodub.media.ocr.detect_regions",
        lambda *_args: pytest.fail("OCR must stay disabled by explicit editor value"),
    )

    state = load_work_dir(work_dir)
    result = _refresh_ocr_regions(
        work_dir, settings, state, [manual, old_ocr],
        ocr_enabled=False, ocr_y_min=0.35, source_logo_auto=False,
    )

    assert result == [manual]
    assert load_render_opts(work_dir)["blur_regions"] == [manual]
    assert load_render_opts(work_dir)["ocr_enabled"] is False
    assert load_render_opts(work_dir)["ocr_subtitle_y_min"] == 0.35

def test_refresh_ocr_regions_auto_adds_source_logo(work_dir, monkeypatch):
    settings = Settings(
        ocr_enabled=False,
        branding_vision_enabled=True,
        branding_vision_model="test-model",
    )
    manual = {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.1}
    save_render_opts(work_dir, {
        "branding_vision_enabled": True,
        "blur_regions": [manual],
    })
    monkeypatch.setattr(
        editor,
        "_probe_ocr_video",
        lambda _path: (1920, 1080, 4.0),
    )
    monkeypatch.setattr(
        "autodub.media.vision.detect_logo_region_video",
        lambda *_args, **_kwargs: {
            "x": 0.8, "y": 0.05, "w": 0.15, "h": 0.08,
        },
    )

    state = load_work_dir(work_dir)
    result = _refresh_ocr_regions(
        work_dir, settings, state, [manual],
        source_logo_auto=True,
    )

    assert result == [
        manual,
        {"x": 0.8, "y": 0.05, "w": 0.15, "h": 0.08, "source": "logo"},
    ]
    assert load_render_opts(work_dir)["blur_regions"] == result

def test_refresh_ocr_regions_uses_ocr_for_stable_source_logo(
    work_dir, monkeypatch
):
    settings = Settings(
        ocr_enabled=True,
        branding_vision_enabled=True,
        branding_vision_model="test-model",
    )
    save_render_opts(work_dir, {"blur_regions": []})
    monkeypatch.setattr(
        editor,
        "_probe_ocr_video",
        lambda _path: (1920, 1080, 4.0),
    )
    monkeypatch.setattr(
        "autodub.media.ocr.detect_regions_with_logo",
        lambda *_args, **_kwargs: (
            [{"x": 0.2, "y": 0.75, "w": 0.3, "h": 0.1, "source": "ocr"}],
            [{"x": 0.8, "y": 0.05, "w": 0.15, "h": 0.08, "source": "logo"}],
        ),
    )
    monkeypatch.setattr(
        "autodub.media.vision.detect_logo_region_video",
        lambda *_args, **_kwargs: pytest.fail("Vision is fallback only"),
    )

    state = load_work_dir(work_dir)
    result = _refresh_ocr_regions(
        work_dir, settings, state, [], source_logo_auto=True,
    )

    assert [region["source"] for region in result] == ["ocr", "logo"]


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

def test_repair_over_budget_translations_updates_only_shortened_lines(
    tmp_path,
):
    from autodub.editor import repair_over_budget_translations

    data = tmp_path / "data"
    data.mkdir()
    transcript = [
        {
            "id": 1, "text": "a", "start": 0.0, "end": 2.0,
            "duration": 2.0, "text_vi": "Câu này dài quá nhiều."
        },
        {
            "id": 2, "text": "b", "start": 0.5, "end": 2.5,
            "duration": 2.0, "text_vi": "Ổn."
        },
    ]
    (data / "transcript_vi.json").write_text(
        json.dumps(transcript, ensure_ascii=False), encoding="utf-8")

    class FakeProvider:
        def shorten_translations(self, segments):
            assert [item["id"] for item in segments] == [1]
            return [{"id": 1, "text_vi": "Ngắn."}]

    result = repair_over_budget_translations(
        str(tmp_path), Settings(), provider=FakeProvider())

    assert result["changed_ids"] == [1]
    saved = json.loads((data / "transcript_vi.json").read_text(encoding="utf-8"))
    assert saved[0]["text_vi"] == "Ngắn."
    assert saved[1]["text_vi"] == "Ổn."
    assert (data / "transcript_vi.before_quality_repair.json").is_file()


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
