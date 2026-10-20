import json
import threading

import numpy as np
import pytest

from autodub.progress import PipelineCancelled
from autodub.speech.diarization import (
    assign_speakers,
    assign_voice_names,
    assign_voice_names_with_fallback,
    cluster_embeddings,
    load_diarization_cache,
    save_diarization_cache,
    select_reference_segments,
)


def test_cluster_embeddings_groups_similar_speakers():
    embeddings = np.asarray([
        [1.0, 0.0],
        [0.99, 0.05],
        [0.0, 1.0],
        [0.05, 0.99],
    ])

    labels = cluster_embeddings(embeddings, threshold=0.8)

    assert labels == [0, 0, 1, 1]


def test_cluster_embeddings_discovers_distinct_speakers():
    labels = cluster_embeddings(np.asarray([
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]), threshold=0.8)

    assert labels == [0, 1, 2]


def test_assign_speakers_keeps_segment_order():
    segments = [
        {"id": 0, "start": 0, "end": 1, "text": "a"},
        {"id": 1, "start": 1, "end": 2, "text": "b"},
    ]

    result = assign_speakers(segments, [1, 0])

    assert [item["speaker_id"] for item in result] == [
        "speaker_02",
        "speaker_01",
    ]
    assert result[0]["text"] == "a"


def test_select_reference_segments_picks_longest_per_speaker():
    segments = [
        {"speaker_id": "speaker_01", "start": 0, "end": 1.2},
        {"speaker_id": "speaker_01", "start": 2, "end": 5.5},
        {"speaker_id": "speaker_02", "start": 6, "end": 8},
    ]

    selected = select_reference_segments(segments, minimum=1.0, maximum=8.0)

    assert selected == {
        "speaker_01": [(2.0, 5.5)],
        "speaker_02": [(6.0, 8.0)],
    }


def test_diarization_cache_round_trips(tmp_path):
    path = tmp_path / "speakers.json"
    payload = {
        "version": 1,
        "segments": [{"id": 1, "speaker_id": "speaker_01"}],
        "embeddings": [[1.0, 0.0]],
    }

    save_diarization_cache(str(path), payload)

    assert load_diarization_cache(str(path)) == payload


def test_diarization_cache_rejects_wrong_shape(tmp_path):
    path = tmp_path / "speakers.json"
    path.write_text(json.dumps({"segments": "bad"}), encoding="utf-8")

    assert load_diarization_cache(str(path)) is None


def test_assign_speakers_honors_cancel_event():
    event = threading.Event()
    event.set()

    with pytest.raises(PipelineCancelled):
        assign_speakers([{"id": 0}], [0], cancel_event=event)


def test_assign_voice_names_maps_every_segment():
    segments = [
        {"speaker_id": "speaker_01", "text": "a"},
        {"speaker_id": "speaker_02", "text": "b"},
        {"speaker_id": "speaker_01", "text": "c"},
    ]

    result = assign_voice_names(segments, {
        "speaker_01": "Clone A",
        "speaker_02": "Clone B",
    })

    assert [item["voice"] for item in result] == ["Clone A", "Clone B", "Clone A"]

def test_assign_voice_names_falls_back_per_missing_speaker():
    segments = [
        {"id": 1, "speaker_id": "speaker_01"},
        {"id": 2, "speaker_id": "speaker_02"},
        {"id": 3, "speaker_id": "speaker_03"},
    ]

    result, fallback_speakers = assign_voice_names_with_fallback(
        segments,
        {"speaker_01": "Clone A"},
        fallback_voice="Preset",
    )

    assert [item["voice"] for item in result] == [
        "Clone A", "Preset", "Preset"
    ]
    assert fallback_speakers == ["speaker_02", "speaker_03"]

def test_load_speaker_map_round_trips(tmp_path):
    from autodub.speech.diarization import (
        load_speaker_map,
        speaker_segment_counts,
    )

    path = tmp_path / "speaker_map.json"
    path.write_text(json.dumps({
        "version": 1,
        "default_voice": "Giọng chung",
        "speakers": [
            {"speaker_id": "speaker_01", "voice": "Minh",
             "assigned": True, "segments": 3},
            {"speaker_id": "speaker_02", "voice": "",
             "assigned": False, "segments": 2},
        ],
    }), encoding="utf-8")

    # Nhân vật chưa được gán giọng thì không có mặt trong bảng: mã gọi
    # không phải phân biệt "không có giọng" với "giọng rỗng".
    assert load_speaker_map(str(path)) == {"speaker_01": "Minh"}

    segments = [
        {"speaker_id": "speaker_01"},
        {"speaker_id": "speaker_01"},
        {"speaker_id": "speaker_02"},
        {"id": 4},
    ]
    assert speaker_segment_counts(segments) == {
        "speaker_01": 2,
        "speaker_02": 1,
    }


def test_load_speaker_map_tolerates_broken_files(tmp_path):
    from autodub.speech.diarization import load_speaker_map

    missing = tmp_path / "khong-co.json"
    assert load_speaker_map(str(missing)) == {}

    broken = tmp_path / "hong.json"
    broken.write_text("{khong phai json", encoding="utf-8")
    assert load_speaker_map(str(broken)) == {}

    wrong = tmp_path / "sai.json"
    wrong.write_text('{"speakers": "khong phai list"}',
                      encoding="utf-8")
    assert load_speaker_map(str(wrong)) == {}

    empty = tmp_path / "rong.json"
    empty.write_text(json.dumps([]), encoding="utf-8")
    assert load_speaker_map(str(empty)) == {}
