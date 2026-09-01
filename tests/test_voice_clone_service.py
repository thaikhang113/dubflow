
import pytest

from autodub.speech.tts import voice_clone_service


def test_enroll_from_audio_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        voice_clone_service.enroll_from_audio(
            object(), str(tmp_path / "missing.wav"), "Clone")


def test_enroll_from_audio_normalizes_and_delegates(tmp_path, monkeypatch):
    source = tmp_path / "input.mp3"
    source.write_bytes(b"audio")
    reference = tmp_path / "reference.wav"
    calls = {}

    monkeypatch.setattr(
        voice_clone_service,
        "prepare_reference_audio",
        lambda source, output, **kwargs: calls.update(
            source=source, output=output) or str(reference),
    )
    monkeypatch.setattr(
        voice_clone_service,
        "enroll_reference_audio",
        lambda settings, path, *, name: calls.update(
            settings=settings, path=path, name=name) or name,
    )

    assert voice_clone_service.enroll_from_audio(
        "settings", str(source), "My Clone") == "My Clone"
    assert calls["source"] == str(source)
    assert calls["path"] == str(reference)


def test_validate_clone_request_requires_supported_source():
    validate = voice_clone_service.validate_clone_request
    assert validate({"source": "audio", "path": "", "name": ""})
    assert validate({"source": "audio", "path": "x.txt", "name": "A"})
    assert validate({"source": "audio", "path": "x.wav", "name": "A"}) is None
    assert validate({"source": "video", "path": "x.mp4", "name": "A"}) is None
