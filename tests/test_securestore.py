"""Kiểm thử autodub/securestore.py — mã hóa file trung gian khi hold chưa chốt."""
from __future__ import annotations

import json
import os

import pytest

from autodub import securestore
from autodub.securestore import SecureStoreError

KEY = "ab" * 32          # 32 byte hex — như máy chủ sinh
OTHER_KEY = "cd" * 32


def test_roundtrip_bytes():
    blob = securestore.encrypt_bytes(b"xin chao", KEY)
    assert blob.startswith(securestore.MAGIC)
    assert securestore.decrypt_bytes(blob, KEY) == b"xin chao"


def test_wrong_key_raises_clean_error():
    blob = securestore.encrypt_bytes(b"data", KEY)
    with pytest.raises(SecureStoreError):
        securestore.decrypt_bytes(blob, OTHER_KEY)


def test_tampered_blob_rejected():
    blob = bytearray(securestore.encrypt_bytes(b"data", KEY))
    blob[-1] ^= 0xFF
    with pytest.raises(SecureStoreError):
        securestore.decrypt_bytes(bytes(blob), KEY)


def test_bad_key_format():
    with pytest.raises(SecureStoreError):
        securestore.encrypt_bytes(b"x", "khong-phai-hex")
    with pytest.raises(SecureStoreError):
        securestore.encrypt_bytes(b"x", "abcd")   # hex nhưng quá ngắn


def test_file_roundtrip_binary(tmp_path):
    p = str(tmp_path / "audio.wav")
    payload = os.urandom(4096)
    with open(p, "wb") as f:
        f.write(payload)

    securestore.encrypt_file(p, KEY)
    assert securestore.is_encrypted(p)
    with open(p, "rb") as f:
        assert f.read() != payload   # không còn plaintext trên đĩa

    # Mã hóa lại lần hai là no-op (resume sau crash).
    securestore.encrypt_file(p, KEY)

    securestore.decrypt_file(p, KEY)
    assert not securestore.is_encrypted(p)
    with open(p, "rb") as f:
        assert f.read() == payload

    # Giải mã file thường cũng là no-op.
    securestore.decrypt_file(p, KEY)


def test_json_secure_with_key(tmp_path):
    p = str(tmp_path / "transcript_vi.json")
    data = {"segments": [{"id": 1, "text_vi": "xin chào"}]}
    securestore.write_json_secure(data, p, KEY)
    assert securestore.is_encrypted(p)
    assert securestore.read_json_secure(p, KEY) == data


def test_json_secure_passthrough_without_key(tmp_path):
    """Không có khóa → hành xử như save_json_atomic thường (luồng batch)."""
    p = str(tmp_path / "plain.json")
    data = {"a": 1}
    securestore.write_json_secure(data, p, None)
    assert not securestore.is_encrypted(p)
    with open(p, encoding="utf-8") as f:
        assert json.load(f) == data
    assert securestore.read_json_secure(p, None) == data


def test_read_encrypted_without_key_raises(tmp_path):
    p = str(tmp_path / "x.json")
    securestore.write_json_secure({"a": 1}, p, KEY)
    with pytest.raises(SecureStoreError):
        securestore.read_json_secure(p, None)


def test_read_json_with_key_on_plain_file(tmp_path):
    """Có khóa nhưng file lại thường (hold đã chốt trước đó) → vẫn đọc được."""
    p = str(tmp_path / "plain.json")
    securestore.write_json_secure({"a": 1}, p, None)
    assert securestore.read_json_secure(p, KEY) == {"a": 1}


def test_lock_marker_lifecycle(tmp_path):
    work = str(tmp_path)
    os.makedirs(os.path.join(work, "data"))
    assert not securestore.is_locked(work)

    f1 = os.path.join(work, "data", "transcript_vi.json")
    f2 = os.path.join(work, "data", "audio_vi_full.wav")
    securestore.write_json_secure({"x": 1}, f1, KEY)
    with open(f2, "wb") as f:
        f.write(b"RIFF....")
    securestore.encrypt_file(f2, KEY)

    securestore.add_locked_file(work, "hold-abc", f1)
    securestore.add_locked_file(work, "hold-abc", f2)
    # Thêm trùng không nhân đôi danh sách.
    securestore.add_locked_file(work, "hold-abc", f1)
    lock = securestore.read_lock(work)
    assert lock["hold_id"] == "hold-abc"
    assert len(lock["encrypted"]) == 2

    assert securestore.is_locked(work)

    done = securestore.unlock_all(work, KEY)
    assert len(done) == 2
    assert not securestore.is_locked(work)
    assert securestore.read_json_secure(f1) == {"x": 1}
    with open(f2, "rb") as f:
        assert f.read() == b"RIFF...."


def test_unlock_skips_missing_files(tmp_path):
    work = str(tmp_path)
    os.makedirs(os.path.join(work, "data"))
    ghost = os.path.join(work, "data", "da_bi_xoa.json")
    securestore.write_lock(work, "hold-abc", [ghost])
    assert securestore.unlock_all(work, KEY) == []
    assert not securestore.is_locked(work)


def test_is_encrypted_on_missing_file(tmp_path):
    assert not securestore.is_encrypted(str(tmp_path / "khong_ton_tai"))
