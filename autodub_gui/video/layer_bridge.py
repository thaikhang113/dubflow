"""Convert DubFlow editor data to and from the CapCap-style layer model."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from autodub_gui.video.layer_model import (
    BlurLayer,
    Layer,
    LayerType,
    SubtitleLayer,
    Timeline,
    Track,
)


def build_timeline(
    segments: list[dict[str, Any]],
    blur_regions: list[dict[str, Any]] | None,
    duration: float,
    *,
    video_path: str = "",
    audio_paths: dict[str, str] | None = None,
    branding: dict[str, Any] | None = None,
) -> Timeline:
    tracks: list[Track] = []
    if video_path:
        tracks.append(Track(
            id="video-track",
            name="Video",
            type=LayerType.VIDEO,
            height=80,
            layers=[Layer(
                id="video-source",
                type=LayerType.VIDEO,
                name="Video",
                start=0.0,
                end=max(0.0, float(duration)),
                metadata={"source": video_path},
            )],
        ))
    for kind, name in (("original", "Original audio"),
                       ("voice", "Voice audio"),
                       ("music", "Music audio")):
        source = str((audio_paths or {}).get(kind) or "")
        if source:
            tracks.append(Track(
                id=f"{kind}-audio-track",
                name=name,
                type=LayerType.AUDIO,
                height=60,
                layers=[Layer(
                    id=f"{kind}-audio-source",
                    type=LayerType.AUDIO,
                    name=name,
                    start=0.0,
                    end=max(0.0, float(duration)),
                    metadata={"source": source, "kind": kind},
                )],
            ))

    subtitle_track = Track(
        id="subtitle-track",
        name="Subtitles",
        type=LayerType.DUB_SUBTITLE,
        height=80,
    )
    for index, segment in enumerate(sorted(segments, key=_start)):
        segment_id = int(segment.get("id", index + 1))
        text = _segment_text(segment)
        subtitle_track.layers.append(SubtitleLayer(
            id=f"subtitle-{segment_id}",
            name=f"Subtitle {segment_id}",
            start=_number(segment.get("start")),
            end=_number(segment.get("end")),
            z_index=index,
            segment_id=segment_id,
            text=text,
            subtitle_text=str(segment.get("sub_text") or segment.get("subtitle_vi") or text),
            metadata={"source": "dubflow"},
        ))

    tracks.append(subtitle_track)
    if blur_regions:
        blur_track = Track(
            id="blur-track",
            name="Blur",
            type=LayerType.BLUR,
            height=60,
        )
        for index, region in enumerate(blur_regions):
            blur_track.layers.append(BlurLayer(
                id=f"blur-{index}",
                name=f"Blur {index + 1}",
                start=_number(region.get("start")),
                end=_number(region.get("end"), duration),
                z_index=index,
                x=_number(region.get("x", region.get("position_x"))),
                y=_number(region.get("y", region.get("position_y"))),
                width=_number(region.get("w", region.get("width"))),
                height=_number(region.get("h", region.get("height"))),
                blur_strength=_number(
                    region.get("blur_strength", region.get("intensity")), 20.0),
                pixelate=bool(region.get("pixelate", False)),
                metadata={
                    key: value for key, value in region.items()
                    if key not in {"x", "y", "w", "h", "width", "height",
                                   "position_x", "position_y", "start", "end",
                                   "blur_strength", "intensity", "pixelate"}
                },
            ))
        tracks.append(blur_track)
    branding = branding or {}
    logo_path = str(branding.get("branding_logo_path") or "").strip()
    if logo_path:
        region = branding.get("branding_logo_region")
        if isinstance(region, str):
            try:
                region = json.loads(region)
            except (TypeError, ValueError, json.JSONDecodeError):
                region = None
        logo_metadata = {
            "source": logo_path,
            "region": region if isinstance(region, dict) else None,
            "opacity": _number(branding.get("branding_logo_opacity"), 1.0),
            "scale": _number(branding.get("branding_logo_scale"), 1.0),
        }
        tracks.append(Track(
            id="logo-track",
            name="Logo",
            type=LayerType.IMAGE,
            height=60,
            layers=[Layer(
                id="logo-source",
                type=LayerType.IMAGE,
                name="Logo",
                start=0.0,
                end=max(0.0, float(duration)),
                metadata=logo_metadata,
            )],
        ))
    return Timeline(duration=max(0.0, float(duration)), tracks=tracks)


def timeline_to_segments(
    timeline: Timeline,
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = deepcopy(segments)
    by_id = {int(segment["id"]): segment for segment in result if "id" in segment}
    for layer in timeline.subtitle_layers():
        segment = by_id.get(layer.segment_id)
        if segment is None:
            continue
        segment["start"] = layer.start
        segment["end"] = layer.end
        segment["duration"] = max(0.0, layer.end - layer.start)
        segment["text"] = layer.text
    return sorted(result, key=_start)


def preserve_layer_state(previous: Timeline | None, current: Timeline) -> Timeline:
    """Carry editor-only visibility/lock flags across data rebuilds."""
    if previous is None:
        return current
    old_tracks = {track.id: track for track in previous.tracks}
    for track in current.tracks:
        old_track = old_tracks.get(track.id)
        if old_track is None:
            continue
        track.visible = old_track.visible
        track.locked = old_track.locked
        old_layers = {layer.id: layer for layer in old_track.layers}
        for layer in track.layers:
            old_layer = old_layers.get(layer.id)
            if old_layer is not None:
                layer.visible = old_layer.visible
                layer.locked = old_layer.locked
    return current


def timeline_to_blur_regions(
    timeline: Timeline, *, include_hidden: bool = False
) -> list[dict[str, Any]]:
    regions = []
    layers = (
        [
            layer for track in timeline.tracks
            for layer in track.layers
            if isinstance(layer, BlurLayer)
        ]
        if include_hidden
        else timeline.blur_layers()
    )
    for layer in layers:
        region = dict(layer.metadata)
        region.update({
            "x": layer.x,
            "y": layer.y,
            "w": layer.width,
            "h": layer.height,
            "start": layer.start,
            "end": layer.end,
            "blur_strength": layer.blur_strength,
            "pixelate": layer.pixelate,
        })
        regions.append(region)
    return regions


def timeline_to_render_options(
    timeline: Timeline, *, include_hidden: bool = False
) -> dict[str, Any]:
    """Return existing DubFlow render option keys from layer state."""
    for track in timeline.tracks:
        if not include_hidden and not track.visible:
            continue
        for layer in track.layers:
            if layer.type != LayerType.IMAGE:
                continue
            if not include_hidden and not layer.visible:
                continue
            source = str(layer.metadata.get("source") or "")
            if not source:
                continue
            return {
                "branding_logo_path": source,
                "branding_logo_region": layer.metadata.get("region"),
                "branding_logo_opacity": layer.metadata.get("opacity", 1.0),
                "branding_logo_scale": layer.metadata.get("scale", 1.0),
            }
    for track in timeline.tracks:
        if track.type != LayerType.IMAGE:
            continue
        for layer in track.layers:
            if layer.type == LayerType.IMAGE and layer.metadata.get("source"):
                return {"branding_logo_path": ""}
    return {}


def _segment_text(segment: dict[str, Any]) -> str:
    return str(segment.get("text_vi") or segment.get("final_text")
               or segment.get("text") or "")


def _start(value: dict[str, Any]) -> float:
    return _number(value.get("start"))


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default
