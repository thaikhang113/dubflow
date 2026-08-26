import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from autodub_gui.video.layer_bridge import build_timeline
from autodub_gui.video.layer_panel import LayerPanel


def test_layer_panel_displays_tracks_and_layers():
    app = QApplication.instance() or QApplication([])
    panel = LayerPanel()
    timeline = build_timeline(
        [{"id": 1, "start": 0, "end": 2, "text": "Một"}],
        [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}],
        2,
    )

    panel.set_timeline(timeline)

    assert panel.tree.topLevelItemCount() == 2
    assert panel.tree.topLevelItem(0).text(0) == "Subtitles"
    assert panel.tree.topLevelItem(0).childCount() == 1
    panel.tree.topLevelItem(1).setCheckState(1, Qt.CheckState.Unchecked)
    app.processEvents()
    assert timeline.tracks[1].visible is False
    assert app is not None
