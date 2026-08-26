from types import SimpleNamespace

from autodub_gui.pages.editor_page import EditorPage
from autodub_gui.video.timeline_state import load_timeline


class _Panel:
    def __init__(self):
        self.timeline = None

    def set_timeline(self, timeline):
        self.timeline = timeline


def test_editor_timeline_state_survives_save_and_reload(tmp_path):
    work_dir = str(tmp_path / "project")
    (tmp_path / "project").mkdir()
    page = SimpleNamespace(
        _work_dir=work_dir,
        _segments=[{"id": 1, "start": 0.0, "end": 2.0, "text": "Một"}],
        _blur_regions=[{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}],
        _branding_options={"branding_logo_path": ""},
        _project=SimpleNamespace(duration_s=2.0),
        _state=SimpleNamespace(video_path=""),
        _layer_timeline=None,
        layer_panel=_Panel(),
    )

    EditorPage._save_timeline_state(page)
    page._layer_timeline.tracks[1].visible = False
    EditorPage._save_timeline_state(page)

    page._layer_timeline = None
    EditorPage._load_timeline_state(page)

    assert page.layer_panel.timeline is page._layer_timeline
    assert page._layer_timeline.tracks[1].visible is False
    assert load_timeline(work_dir, [], [], 0).tracks[1].visible is False

def test_editor_save_keeps_hidden_blur_and_logo_layers(tmp_path):
    work_dir = str(tmp_path / "project")
    (tmp_path / "project").mkdir()
    page = SimpleNamespace(
        _work_dir=work_dir,
        _segments=[{"id": 1, "start": 0.0, "end": 2.0, "text": "Mot"}],
        _blur_regions=[{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}],
        _branding_options={
            "branding_logo_path": "logo.png",
            "branding_logo_region": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
        },
        _project=SimpleNamespace(duration_s=2.0),
        _state=SimpleNamespace(video_path=""),
        _layer_timeline=None,
        layer_panel=_Panel(),
    )

    EditorPage._save_timeline_state(page)
    next(track for track in page._layer_timeline.tracks
         if track.type.value == "blur").layers[0].visible = False
    next(track for track in page._layer_timeline.tracks
         if track.type.value == "image").layers[0].visible = False

    EditorPage._save_timeline_state(page)
    page._layer_timeline = None
    EditorPage._load_timeline_state(page)

    blur_track = next(track for track in page._layer_timeline.tracks
                      if track.type.value == "blur")
    assert len(blur_track.layers) == 1
    assert blur_track.layers[0].visible is False
    logo_track = next(track for track in page._layer_timeline.tracks
                      if track.type.value == "image")
    assert logo_track.layers[0].visible is False
