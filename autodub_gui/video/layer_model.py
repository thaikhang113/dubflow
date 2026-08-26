"""Small, serializable timeline model adapted for DubFlow's editor."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LayerType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    DUB_SUBTITLE = "dub_subtitle"
    BLUR = "blur"
    IMAGE = "image"
    MASK = "mask"
    UNKNOWN = "unknown"


@dataclass
class Layer:
    id: str
    type: LayerType | str
    name: str = ""
    start: float = 0.0
    end: float = 0.0
    z_index: int = 0
    visible: bool = True
    locked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        layer_type = self.type.value if isinstance(self.type, LayerType) else str(self.type)
        return {
            "id": self.id,
            "type": layer_type,
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "z_index": self.z_index,
            "visible": self.visible,
            "locked": self.locked,
            "metadata": dict(self.metadata),
        }


@dataclass
class SubtitleLayer(Layer):
    type: LayerType | str = LayerType.DUB_SUBTITLE
    segment_id: int = 0
    text: str = ""
    subtitle_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "segment_id": self.segment_id,
            "text": self.text,
            "subtitle_text": self.subtitle_text,
        }


@dataclass
class BlurLayer(Layer):
    type: LayerType | str = LayerType.BLUR
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    blur_strength: float = 20.0
    pixelate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "blur_strength": self.blur_strength,
            "pixelate": self.pixelate,
        }


@dataclass
class Track:
    id: str
    name: str
    type: LayerType | str
    layers: list[Layer] = field(default_factory=list)
    visible: bool = True
    locked: bool = False
    height: int = 80

    def to_dict(self) -> dict[str, Any]:
        track_type = self.type.value if isinstance(self.type, LayerType) else str(self.type)
        return {
            "id": self.id,
            "name": self.name,
            "type": track_type,
            "visible": self.visible,
            "locked": self.locked,
            "height": self.height,
            "layers": [layer.to_dict() for layer in self.layers],
        }


@dataclass
class Timeline:
    duration: float = 0.0
    tracks: list[Track] = field(default_factory=list)
    composition_width: int = 1920
    composition_height: int = 1080
    fps: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration": self.duration,
            "composition": {
                "width": self.composition_width,
                "height": self.composition_height,
                "fps": self.fps,
            },
            "tracks": [track.to_dict() for track in self.tracks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Timeline:
        composition = data.get("composition") or {}
        tracks = []
        for raw_track in data.get("tracks") or []:
            if not isinstance(raw_track, dict):
                continue
            track_type = _layer_type(raw_track.get("type"))
            layers = [
                _layer_from_dict(raw)
                for raw in raw_track.get("layers") or []
                if isinstance(raw, dict)
            ]
            tracks.append(Track(
                id=str(raw_track.get("id", "")),
                name=str(raw_track.get("name", "")),
                type=track_type,
                layers=layers,
                visible=bool(raw_track.get("visible", True)),
                locked=bool(raw_track.get("locked", False)),
                height=int(raw_track.get("height", 80)),
            ))
        return cls(
            duration=float(data.get("duration", 0.0)),
            tracks=tracks,
            composition_width=int(composition.get("width", 1920)),
            composition_height=int(composition.get("height", 1080)),
            fps=float(composition.get("fps", 30.0)),
        )

    def subtitle_layers(self) -> list[SubtitleLayer]:
        return [
            layer for track in self.tracks for layer in track.layers
            if isinstance(layer, SubtitleLayer)
        ]

    def blur_layers(self) -> list[BlurLayer]:
        return [
            layer for track in self.tracks if track.visible
            for layer in track.layers
            if isinstance(layer, BlurLayer) and layer.visible
        ]


def _layer_type(value: Any) -> LayerType | str:
    try:
        return LayerType(value)
    except (TypeError, ValueError):
        return str(value or LayerType.UNKNOWN.value)


def _common(data: dict[str, Any], layer_type: LayerType | str) -> dict[str, Any]:
    return {
        "id": str(data.get("id", "")),
        "type": layer_type,
        "name": str(data.get("name", "")),
        "start": float(data.get("start", 0.0)),
        "end": float(data.get("end", 0.0)),
        "z_index": int(data.get("z_index", 0)),
        "visible": bool(data.get("visible", True)),
        "locked": bool(data.get("locked", False)),
        "metadata": dict(data.get("metadata") or {}),
    }


def _layer_from_dict(data: dict[str, Any]) -> Layer:
    layer_type = _layer_type(data.get("type"))
    common = _common(data, layer_type)
    if layer_type == LayerType.DUB_SUBTITLE:
        return SubtitleLayer(
            **common,
            segment_id=int(data.get("segment_id", 0)),
            text=str(data.get("text", "")),
            subtitle_text=str(data.get("subtitle_text", "")),
        )
    if layer_type == LayerType.BLUR:
        return BlurLayer(
            **common,
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            width=float(data.get("width", 0.0)),
            height=float(data.get("height", 0.0)),
            blur_strength=float(data.get("blur_strength", 20.0)),
            pixelate=bool(data.get("pixelate", False)),
        )
    return Layer(**common)
