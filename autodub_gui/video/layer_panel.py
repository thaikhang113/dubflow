"""Compact layer inspector for the editor."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from autodub_gui.video.layer_model import Timeline

_KIND_ROLE = Qt.ItemDataRole.UserRole
_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class LayerPanel(QWidget):
    state_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Lớp", "Hiện", "Khóa"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)
        self._timeline: Timeline | None = None
        self._updating = False

    def set_timeline(self, timeline: Timeline | None) -> None:
        self._timeline = timeline
        self._updating = True
        try:
            self.tree.clear()
            if timeline is None:
                return
            for track in timeline.tracks:
                track_item = self._item(
                    track.name,
                    "track",
                    track.id,
                    track.visible,
                    track.locked,
                )
                self.tree.addTopLevelItem(track_item)
                for layer in track.layers:
                    track_item.addChild(self._item(
                        layer.name or layer.id,
                        "layer",
                        layer.id,
                        layer.visible,
                        layer.locked,
                    ))
                track_item.setExpanded(True)
        finally:
            self._updating = False

    def _item(
        self,
        name: str,
        kind: str,
        object_id: str,
        visible: bool,
        locked: bool,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name, "", ""])
        item.setData(0, _KIND_ROLE, kind)
        item.setData(0, _ID_ROLE, object_id)
        item.setFlags(
            item.flags()
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        item.setCheckState(1, self._check(visible))
        item.setCheckState(2, self._check(locked))
        return item

    @staticmethod
    def _check(value: bool) -> Qt.CheckState:
        return (Qt.CheckState.Checked if value
                else Qt.CheckState.Unchecked)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column not in (1, 2) or self._timeline is None:
            return
        kind = item.data(0, _KIND_ROLE)
        object_id = item.data(0, _ID_ROLE)
        visible = item.checkState(1) == Qt.CheckState.Checked
        locked = item.checkState(2) == Qt.CheckState.Checked
        if kind == "track":
            target = next(
                (track for track in self._timeline.tracks
                 if track.id == object_id),
                None,
            )
        else:
            target = next(
                (
                    layer for track in self._timeline.tracks
                    for layer in track.layers
                    if layer.id == object_id
                ),
                None,
            )
        if target is None:
            return
        target.visible = visible
        target.locked = locked
        self.state_changed.emit()
