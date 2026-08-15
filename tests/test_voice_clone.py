import json
import wave

from autodub.speech.tts.voice_clone import (
    clone_voice_name,
    custom_voice_names,
    delete_custom_voice,
    reference_duration_seconds,
    select_reference_window,
    validate_reference_duration,
)
from autodub.speech.tts.vieneu_worker import (
    available_voice_names,
    load_custom_voices,
)


def test_select_reference_window_prefers_longest_clean_segment():
    segments = [
        {"start": 0.0, "end": 1.2, "text": "ngắn"},
        {"start": 2.0, "end": 7.5, "text": "đoạn thoại dài"},
    ]

    assert select_reference_window(segments) == (2.0, 7.5)


def test_reference_duration_is_limited_to_vieneu_enrollment_window():
    assert validate_reference_duration(0.9) is False
    assert validate_reference_duration(1.0) is True
    assert validate_reference_duration(8.0) is True
    assert validate_reference_duration(8.1) is False


def test_clone_voice_name_is_stable_and_safe():
    assert clone_voice_name("a" * 64) == "DubFlow Clone aaaaaaaa"


def test_worker_accepts_enrolled_custom_voice_names():
    assert "DubFlow Clone abcdef12" in available_voice_names(
        ["Preset"], {"DubFlow Clone abcdef12": {}})


def test_worker_loads_enrolled_custom_voice_embeddings(tmp_path):
    path = tmp_path / "custom_voices.json"
    path.write_text(json.dumps({
        "presets": {
            "Clone": {
                "speaker_emb": [0.1, 0.2],
                "codes": [[1, 2]],
                "style": "tu_nhien",
            }
        }
    }), encoding="utf-8")

    class FakeTts:
        _preset_voices = {}

    assert load_custom_voices(FakeTts(), str(path)) == 1
    assert "Clone" in FakeTts._preset_voices


def test_reference_wav_duration_can_be_checked(tmp_path):
    path = tmp_path / "reference.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000)

    assert reference_duration_seconds(str(path)) == 1.0

def test_delete_custom_voice_removes_only_requested_entry(tmp_path):
    path = tmp_path / "custom_voices.json"
    path.write_text(json.dumps({"presets": {
        "A": {"source": "custom"},
        "B": {"source": "custom"},
    }}), encoding="utf-8")

    assert delete_custom_voice(str(path), "A") is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["presets"]) == {"B"}
    assert custom_voice_names(str(path)) == {"B"}
