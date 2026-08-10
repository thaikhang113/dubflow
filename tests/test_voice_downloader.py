"""Tải và cài đặt thư viện giọng đọc lần đầu chạy app.

Bước này chạy MỘT LẦN trên máy người dùng và chặn màn hình chờ, nên hai điều
phải chắc chắn đúng: (1) máy đã cài rồi thì không tải lại, và (2) embeddings
đóng sẵn trong zip được dùng thay vì bắt máy mã hóa lại 120 giọng — bước mã
hóa mất nhiều phút và cho ra kết quả y hệt trên mọi máy.
"""
from __future__ import annotations

import json
import os

import pytest

from autodub.config import Settings
from autodub.speech.tts import voice_downloader


@pytest.fixture
def settings(tmp_path):
    """Cấu hình trỏ vào thư mục model rỗng, tách khỏi máy thật."""
    return Settings(vieneu_model_dir=str(tmp_path / "vieneu"))


def write_custom(settings, presets: dict) -> None:
    path = settings.vieneu_custom_voices_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"presets": presets}, f, ensure_ascii=False)


# ------------------------------------------------------ voices_installed --- #

def test_not_installed_when_manifest_missing(settings):
    assert voice_downloader.voices_installed(settings) is False


def test_not_installed_when_custom_voices_missing(settings, tmp_path,
                                                  monkeypatch):
    # Có manifest nhưng chưa enroll giọng nào → coi như chưa cài.
    monkeypatch.setattr(voice_downloader, "app_root", lambda: str(tmp_path))
    voices_dir = tmp_path / voice_downloader.VOICES_TARGET_DIR
    voices_dir.mkdir(parents=True)
    (voices_dir / voice_downloader.MANIFEST_NAME).write_text("{}",
                                                             encoding="utf-8")
    assert voice_downloader.voices_installed(settings) is False


def test_not_installed_when_too_few_presets(settings, tmp_path, monkeypatch):
    """Enroll dở dang (đứt mạng, tắt app giữa chừng) phải bị coi là chưa cài."""
    monkeypatch.setattr(voice_downloader, "app_root", lambda: str(tmp_path))
    voices_dir = tmp_path / voice_downloader.VOICES_TARGET_DIR
    voices_dir.mkdir(parents=True)
    (voices_dir / voice_downloader.MANIFEST_NAME).write_text("{}",
                                                             encoding="utf-8")
    write_custom(settings, {f"Giọng {i}": {"gender": "male"} for i in range(10)})
    assert voice_downloader.voices_installed(settings) is False


def test_installed_when_manifest_and_enough_presets(settings, tmp_path,
                                                    monkeypatch):
    monkeypatch.setattr(voice_downloader, "app_root", lambda: str(tmp_path))
    voices_dir = tmp_path / voice_downloader.VOICES_TARGET_DIR
    voices_dir.mkdir(parents=True)
    (voices_dir / voice_downloader.MANIFEST_NAME).write_text("{}",
                                                             encoding="utf-8")
    write_custom(settings, {f"Giọng {i}": {"gender": "male"} for i in range(60)})
    assert voice_downloader.voices_installed(settings) is True


# ------------------------------------------- ensure_voices_available ------- #

def test_ensure_is_noop_when_already_installed(settings, tmp_path, monkeypatch):
    """Đã cài rồi thì không được gọi mạng — mở app lần hai phải tức thì."""
    monkeypatch.setattr(voice_downloader, "app_root", lambda: str(tmp_path))
    voices_dir = tmp_path / voice_downloader.VOICES_TARGET_DIR
    voices_dir.mkdir(parents=True)
    (voices_dir / voice_downloader.MANIFEST_NAME).write_text("{}",
                                                             encoding="utf-8")
    write_custom(settings, {f"Giọng {i}": {"gender": "male"} for i in range(60)})

    def _boom(*a, **kw):
        raise AssertionError("không được tải lại khi đã cài")

    monkeypatch.setattr(voice_downloader, "download_voices", _boom)
    assert voice_downloader.ensure_voices_available(settings) is True


def test_bundled_embeddings_skip_enroll(settings, tmp_path, monkeypatch):
    """Zip kèm custom_voices.json → chép thẳng, KHÔNG chạy bước mã hóa.

    Đây là đường tiết kiệm nhiều phút nhất của lần chạy đầu: embeddings là
    hằng số (cùng model + cùng file WAV → cùng kết quả), nên tính lại trên
    máy người dùng là lãng phí thuần túy.
    """
    monkeypatch.setattr(voice_downloader, "app_root", lambda: str(tmp_path))
    voices_dir = tmp_path / voice_downloader.VOICES_TARGET_DIR
    voices_dir.mkdir(parents=True)
    bundled = {f"Giọng {i}": {"gender": "male"} for i in range(60)}
    (voices_dir / "custom_voices.json").write_text(
        json.dumps({"presets": bundled}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(voice_downloader, "download_voices",
                        lambda cb=None: str(tmp_path / "voices.zip"))
    monkeypatch.setattr(voice_downloader, "extract_voices",
                        lambda z: str(voices_dir))

    def _boom(*a, **kw):
        raise AssertionError("không được enroll khi zip đã kèm embeddings")

    monkeypatch.setattr(voice_downloader, "enroll_voices", _boom)

    assert voice_downloader.ensure_voices_available(settings) is True
    # Embeddings đã nằm đúng chỗ app đọc.
    with open(settings.vieneu_custom_voices_path(), encoding="utf-8") as f:
        assert json.load(f)["presets"] == bundled


def test_slim_zip_contract_no_wav_still_counts_as_installed(settings, tmp_path,
                                                            monkeypatch):
    """Release gọn chỉ có manifest + embeddings, KHÔNG wav → vẫn coi là đã cài.

    Đây là hợp đồng của bản phát hành không kèm audio: xóa wav khỏi zip không
    được làm app tưởng chưa cài rồi tải lại mỗi lần mở.
    """
    monkeypatch.setattr(voice_downloader, "app_root", lambda: str(tmp_path))
    voices_dir = tmp_path / voice_downloader.VOICES_TARGET_DIR
    voices_dir.mkdir(parents=True)
    (voices_dir / voice_downloader.MANIFEST_NAME).write_text("[]",
                                                             encoding="utf-8")
    write_custom(settings, {f"Giọng {i}": {"gender": "male", "source": "library"}
                            for i in range(60)})
    # Không có bất kỳ file .wav nào trong thư mục voices.
    assert not list(voices_dir.glob("*.wav"))
    assert voice_downloader.voices_installed(settings) is True
