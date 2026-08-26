from autodub_gui.video.layer_bridge import build_timeline
from autodub_gui.video.timeline_state import (
    load_timeline,
    save_timeline,
    timeline_exists,
)


def test_timeline_state_uses_workdir_layout_and_round_trips(tmp_path):
    work_dir = tmp_path / "project"
    work_dir.mkdir()
    timeline = build_timeline(
        [{"id": 1, "start": 0, "end": 2, "text": "Xin chào"}],
        [],
        2,
    )

    save_timeline(str(work_dir), timeline)

    assert timeline_exists(str(work_dir))
    restored = load_timeline(str(work_dir), [], [], 0)
    assert restored.duration == 2
    assert restored.subtitle_layers()[0].text == "Xin chào"


def test_missing_or_invalid_state_falls_back_to_current_editor_data(tmp_path):
    work_dir = tmp_path / "project"
    work_dir.mkdir()
    (work_dir / "data").mkdir()
    (work_dir / "data" / "timeline.json").write_text("{bad", encoding="utf-8")

    restored = load_timeline(
        str(work_dir),
        [{"id": 7, "start": 1, "end": 3, "text": "Mới"}],
        [],
        3,
    )

    assert restored.subtitle_layers()[0].segment_id == 7
    assert restored.subtitle_layers()[0].text == "Mới"
