import zipfile
from pathlib import Path

from autodub.speech.tts import voice_downloader


def test_local_voice_library_prefers_bundled_asset(monkeypatch, tmp_path):
    bundled = tmp_path / "data" / "voices" / "preset_voices_vn"
    bundled.mkdir(parents=True)
    (bundled / "voices_manifest.json").write_text("{}", encoding="utf-8")
    (bundled / "sample.wav").write_bytes(b"RIFF")

    monkeypatch.setattr(voice_downloader, "data_root", lambda: str(tmp_path / "user"))
    monkeypatch.setattr(voice_downloader, "bundled_file", lambda *parts: str(
        tmp_path / "data" / Path(*parts)
    ))

    assert voice_downloader._local_voice_library() == str(bundled)

def test_extract_voices_rejects_unsafe_zip_path(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_downloader, "data_root", lambda: str(tmp_path / "user"))
    archive = tmp_path / "voices.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "must not be written")

    try:
        voice_downloader.extract_voices(str(archive))
    except ValueError as exc:
        assert "unsafe path" in str(exc)
    else:
        raise AssertionError("unsafe voice archive was accepted")
    assert not (tmp_path / "escape.txt").exists()
