"""Lightweight local speaker clustering for translated video segments."""
from __future__ import annotations

import json
import os
from typing import Callable

import numpy as np

from autodub.progress import PipelineCancelled


def _check_cancelled(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise PipelineCancelled("Pipeline cancelled by user")


def _normalized(embeddings: np.ndarray) -> np.ndarray:
    values = np.asarray(embeddings, dtype=np.float32)
    if values.ndim != 2:
        raise ValueError("speaker embeddings must be a 2-D array")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(norms, 1e-8)


def cluster_embeddings(
    embeddings: np.ndarray,
    *,
    threshold: float = 0.72,
    cancel_event=None,
) -> list[int]:
    """Incrementally cluster normalized speaker embeddings by cosine similarity."""
    values = _normalized(embeddings)
    if not len(values):
        return []
    labels: list[int] = []
    centroids: list[np.ndarray] = []
    counts: list[int] = []
    for value in values:
        _check_cancelled(cancel_event)
        if not centroids:
            labels.append(0)
            centroids.append(value.copy())
            counts.append(1)
            continue
        scores = [float(value @ centroid) for centroid in centroids]
        index = int(np.argmax(scores))
        if scores[index] < threshold:
            index = len(centroids)
            centroids.append(value.copy())
            counts.append(1)
        else:
            counts[index] += 1
            centroids[index] = (
                centroids[index] * (counts[index] - 1) + value
            )
            centroids[index] /= max(float(np.linalg.norm(centroids[index])), 1e-8)
        labels.append(index)
    return labels


def assign_speakers(
    segments: list[dict],
    labels: list[int],
    *,
    cancel_event=None,
) -> list[dict]:
    """Attach stable, human-readable speaker IDs without reordering segments."""
    if len(segments) != len(labels):
        raise ValueError("segments and speaker labels must have equal length")
    result = []
    for segment, label in zip(segments, labels):
        _check_cancelled(cancel_event)
        item = dict(segment)
        item["speaker_id"] = f"speaker_{int(label) + 1:02d}"
        result.append(item)
    return result


def assign_voice_names(
    segments: list[dict],
    voice_names: dict[str, str],
    *,
    cancel_event=None,
) -> list[dict]:
    result = []
    for segment in segments:
        _check_cancelled(cancel_event)
        item = dict(segment)
        speaker = str(item.get("speaker_id", "")).strip()
        voice = voice_names.get(speaker)
        if voice:
            item["voice"] = voice
        result.append(item)
    return result

def assign_voice_names_with_fallback(
    segments: list[dict],
    voice_names: dict[str, str],
    *,
    fallback_voice: str,
    cancel_event=None,
) -> tuple[list[dict], list[str]]:
    """Assign cloned voices and record speakers that used preset fallback."""
    result = []
    fallback_speakers: list[str] = []
    for segment in segments:
        _check_cancelled(cancel_event)
        item = dict(segment)
        speaker = str(item.get("speaker_id", "")).strip()
        voice = voice_names.get(speaker) or fallback_voice
        if speaker and speaker not in voice_names and speaker not in fallback_speakers:
            fallback_speakers.append(speaker)
        if voice:
            item["voice"] = voice
        result.append(item)
    return result, fallback_speakers


def select_reference_segments(
    segments: list[dict],
    *,
    minimum: float = 1.0,
    maximum: float = 8.0,
) -> dict[str, list[tuple[float, float]]]:
    """Choose one longest usable transcript window for each detected speaker."""
    best: dict[str, tuple[float, float, float]] = {}
    for segment in segments:
        speaker = str(segment.get("speaker_id", "")).strip()
        if not speaker:
            continue
        try:
            start, end = float(segment["start"]), float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        duration = end - start
        if duration < minimum:
            continue
        clipped_end = min(end, start + maximum)
        candidate = (clipped_end - start, start, clipped_end)
        if speaker not in best or candidate[0] > best[speaker][0]:
            best[speaker] = candidate
    return {
        speaker: [(round(start, 3), round(end, 3))]
        for speaker, (_, start, end) in best.items()
    }


def save_diarization_cache(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
    os.replace(temp, path)


def load_diarization_cache(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("segments"), list):
            return None
        if "embeddings" in payload and not isinstance(payload["embeddings"], list):
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None


def diarize_segments(
    segments: list[dict],
    embeddings: np.ndarray | None = None,
    *,
    embedder: Callable[[dict], np.ndarray] | None = None,
    threshold: float = 0.72,
    cancel_event=None,
) -> tuple[list[dict], np.ndarray]:
    """Embed usable ASR segments, cluster them, and attach speaker IDs.

    ``embedder`` receives each segment and keeps audio/model concerns outside
    this dependency-light module. Callers may pass precomputed embeddings when
    resuming a run.
    """
    if embeddings is None:
        if embedder is None:
            raise ValueError("embedder is required when embeddings are absent")
        values = []
        kept = []
        for segment in segments:
            _check_cancelled(cancel_event)
            try:
                duration = float(segment["end"]) - float(segment["start"])
            except (KeyError, TypeError, ValueError):
                continue
            if duration < 1.0:
                continue
            value = np.asarray(embedder(segment), dtype=np.float32).reshape(-1)
            if value.size:
                kept.append(segment)
                values.append(value)
        if not values:
            return [dict(segment) for segment in segments], np.empty((0, 0), dtype=np.float32)
        embeddings = np.asarray(values, dtype=np.float32)
        segments = kept
    values = np.asarray(embeddings, dtype=np.float32)
    labels = cluster_embeddings(values, threshold=threshold, cancel_event=cancel_event)
    return assign_speakers(segments, labels, cancel_event=cancel_event), values
