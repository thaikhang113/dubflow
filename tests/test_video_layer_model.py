import json

from autodub_gui.video.layer_bridge import (
    build_timeline,
    preserve_layer_state,
    timeline_to_blur_regions,
    timeline_to_render_options,
    timeline_to_segments,
)
from autodub_gui.video.layer_model import Timeline


def _segments():
    return [
        {"id": 1, "start": 0.0, "end": 2.0, "text": "Mot"},
        {"id": 2, "start": 2.0, "end": 4.0, "text": "Hai", "text_vi": "Hai"},
    ]


def test_timeline_round_trip_preserves_subtitle_and_blur_layers():
    timeline = build_timeline(
        _segments(),
        [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1, "start": 1.0, "end": 3.0}],
        duration=4.0,
    )

    restored = Timeline.from_dict(json.loads(json.dumps(timeline.to_dict())))

    assert len(restored.subtitle_layers()) == 2
    assert restored.subtitle_layers()[1].text == "Hai"
    region = timeline_to_blur_regions(restored)[0]
    assert {key: region[key] for key in ("x", "y", "w", "h", "start", "end")} == {
        "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1, "start": 1.0, "end": 3.0
    }


def test_timeline_changes_sync_back_without_dropping_segment_fields():
    timeline = build_timeline(_segments(), [], duration=4.0)
    layer = timeline.subtitle_layers()[0]
    layer.start = 0.25
    layer.end = 1.75
    layer.text = "Đã sửa"

    synced = timeline_to_segments(timeline, _segments())

    assert synced[0]["start"] == 0.25
    assert synced[0]["end"] == 1.75
    assert synced[0]["text"] == "Đã sửa"
    assert synced[1]["text_vi"] == "Hai"


def test_unknown_layer_type_is_loaded_as_generic_layer():
    timeline = Timeline.from_dict({
        "duration": 1,
        "tracks": [{
            "id": "t1",
            "name": "Unknown",
            "type": "future",
            "layers": [{
                "id": "l1",
                "type": "future",
                "start": 0,
                "end": 1,
            }],
        }],
    })

    assert timeline.tracks[0].layers[0].type == "future"


def test_timeline_carries_source_media_and_logo_as_layers():
    timeline = build_timeline(
        _segments(),
        [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}],
        duration=4.0,
        video_path="source.mp4",
        audio_paths={"original": "original.wav", "voice": "voice.wav"},
        branding={
            "branding_logo_path": "logo.png",
            "branding_logo_region": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1},
            "branding_logo_opacity": 0.7,
        },
    )
    timeline.blur_layers()[0].visible = False
    timeline.tracks[-1].layers[0].visible = False

    assert [track.name for track in timeline.tracks[:3]] == [
        "Video", "Original audio", "Voice audio",
    ]
    assert timeline.tracks[-1].layers[0].metadata["source"] == "logo.png"
    assert timeline_to_blur_regions(timeline) == []
    assert timeline_to_render_options(timeline)["branding_logo_path"] == ""


def test_hidden_track_disables_its_render_layers():
    timeline = build_timeline(
        _segments(),
        [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}],
        duration=4.0,
        branding={"branding_logo_path": "logo.png"},
    )
    next(track for track in timeline.tracks if track.type.value == "blur").visible = False
    next(track for track in timeline.tracks if track.type.value == "image").visible = False

    assert timeline_to_blur_regions(timeline) == []
    assert timeline_to_render_options(timeline)["branding_logo_path"] == ""


def test_hidden_layers_remain_available_for_timeline_rebuild():
    timeline = build_timeline(
        _segments(),
        [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}],
        duration=4.0,
        branding={"branding_logo_path": "logo.png"},
    )
    timeline.blur_layers()[0].visible = False
    next(track for track in timeline.tracks
         if track.type.value == "image").layers[0].visible = False

    assert timeline_to_blur_regions(timeline) == []
    assert len(timeline_to_blur_regions(timeline, include_hidden=True)) == 1
    assert timeline_to_render_options(timeline) == {
        "branding_logo_path": ""}
    assert timeline_to_render_options(timeline, include_hidden=True)[
        "branding_logo_path"] == "logo.png"

def test_rebuilding_timeline_preserves_layer_visibility_and_lock():
    previous = build_timeline(
        _segments(),
        [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}],
        duration=4.0,
    )
    previous.tracks[0].visible = False
    previous.tracks[1].layers[0].locked = True

    current = preserve_layer_state(
        previous,
        build_timeline(
            _segments(),
            [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}],
            duration=4.0,
        ),
    )

    assert current.tracks[0].visible is False
    assert current.tracks[1].layers[0].locked is True
