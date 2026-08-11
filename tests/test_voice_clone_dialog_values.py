from autodub_gui.voice_clone_dialog import validate_clone_request


def test_clone_dialog_validation_accepts_audio_and_video():
    assert validate_clone_request(
        {"source": "audio", "path": "voice.wav", "name": "Lan"})
    assert validate_clone_request(
        {"source": "video", "path": "clip.mp4", "name": "Lan"})


def test_clone_dialog_validation_rejects_missing_or_unsupported_values():
    assert not validate_clone_request({"source": "audio", "path": "", "name": "Lan"})
    assert not validate_clone_request(
        {"source": "audio", "path": "voice.txt", "name": "Lan"})
    assert not validate_clone_request(
        {"source": "audio", "path": "voice.wav", "name": ""})
