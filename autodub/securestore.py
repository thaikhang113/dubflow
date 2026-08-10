"""Mã hóa file trung gian trong lúc hold Vox chưa được chốt (luồng wizard).

Từ lúc dịch xong tới lúc bấm "Xuất video", thành quả trả phí (bản dịch,
audio ghép, ngữ cảnh) nằm trên đĩa dưới dạng AES-256-GCM — người dùng thường
không lấy được data rồi bỏ ngang không xuất. Khóa do máy chủ sinh theo từng
hold, chỉ sống trong RAM; crash thì chạy lại cùng video → cùng run_id →
``get_hold`` cấp lại khóa.

TRUNG THỰC VỀ GIỚI HẠN: mã hóa phía máy khách chỉ chặn người dùng thường.
Lớp bảo vệ tài chính thật nằm ở phía máy chủ — hold tự chốt sau TTL, Vox đã
tiêu là đã tiêu dù có xuất hay không.

Định dạng file: ``VOXENC1\\0`` (8 byte magic) + nonce 12 byte + ciphertext
(GCM tag nằm cuối ciphertext theo chuẩn của ``cryptography``).
"""
from __future__ import annotations

import json
import os
import tempfile

from autodub.utils import save_json_atomic, setup_logging

logger = setup_logging("autodub.securestore")

MAGIC = b"VOXENC1\x00"
_NONCE_LEN = 12

#: Tên file đánh dấu dự án đang khóa (nằm trong ``data/`` của work_dir).
LOCK_FILENAME = "voxdub_lock.json"


class SecureStoreError(Exception):
    """Không đọc/ghi được file mã hóa (sai khóa, file hỏng...)."""


def _aesgcm(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(key)


def _to_key(key: bytes | str) -> bytes:
    """Nhận khóa dạng bytes hoặc chuỗi hex 64 ký tự từ máy chủ."""
    if isinstance(key, str):
        try:
            key = bytes.fromhex(key.strip())
        except ValueError as e:
            raise SecureStoreError("Khóa giải mã không đúng định dạng hex.") from e
    if len(key) != 32:
        raise SecureStoreError("Khóa giải mã phải dài đúng 32 byte (AES-256).")
    return key


def is_encrypted(path: str) -> bool:
    """File này có phải file đã mã hóa của VoxDub không (sniff magic)."""
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def encrypt_bytes(data: bytes, key: bytes | str) -> bytes:
    key = _to_key(key)
    nonce = os.urandom(_NONCE_LEN)
    return MAGIC + nonce + _aesgcm(key).encrypt(nonce, data, MAGIC)


def decrypt_bytes(blob: bytes, key: bytes | str) -> bytes:
    key = _to_key(key)
    if not blob.startswith(MAGIC):
        raise SecureStoreError("File không phải định dạng mã hóa của VoxDub.")
    nonce = blob[len(MAGIC):len(MAGIC) + _NONCE_LEN]
    ciphertext = blob[len(MAGIC) + _NONCE_LEN:]
    try:
        return _aesgcm(key).decrypt(nonce, ciphertext, MAGIC)
    except Exception as e:  # noqa: BLE001 — InvalidTag và mọi lỗi crypto khác
        raise SecureStoreError(
            "Không giải mã được file (sai khóa hoặc file đã bị sửa)."
        ) from e


def _write_atomic(path: str, blob: bytes) -> None:
    """Ghi nguyên tử: temp cùng thư mục rồi ``os.replace``."""
    dir_name = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".enc", dir=dir_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def encrypt_file(path: str, key: bytes | str, out_path: str | None = None) -> str:
    """Mã hóa một file tại chỗ (hoặc sang ``out_path``). Trả về đường dẫn kết quả.

    File đã mã hóa rồi thì bỏ qua — gọi lại an toàn (resume sau crash).
    """
    if is_encrypted(path):
        return path
    with open(path, "rb") as f:
        data = f.read()
    target = out_path or path
    _write_atomic(target, encrypt_bytes(data, key))
    return target


def decrypt_file(path: str, key: bytes | str, out_path: str | None = None) -> str:
    """Giải mã một file tại chỗ (hoặc sang ``out_path``). Trả về đường dẫn kết quả.

    File chưa mã hóa thì bỏ qua — an toàn khi lock marker liệt kê thừa.
    """
    if not is_encrypted(path):
        return path
    with open(path, "rb") as f:
        blob = f.read()
    target = out_path or path
    _write_atomic(target, decrypt_bytes(blob, key))
    return target


def read_json_secure(path: str, key: bytes | str | None = None) -> object:
    """Đọc JSON — tự nhận biết file thường hay file mã hóa.

    Không có khóa mà file lại mã hóa → :class:`SecureStoreError` (dự án đang
    khóa, cần lấy lại khóa từ máy chủ trước).
    """
    with open(path, "rb") as f:
        blob = f.read()
    if blob.startswith(MAGIC):
        if key is None:
            raise SecureStoreError(
                "File đang được mã hóa — cần khóa giải mã từ máy chủ.")
        blob = decrypt_bytes(blob, key)
    try:
        return json.loads(blob.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise SecureStoreError(f"File JSON hỏng: {os.path.basename(path)}") from e


def write_json_secure(data: object, path: str, key: bytes | str | None = None) -> None:
    """Ghi JSON — có khóa thì mã hóa, không có thì hành xử như thường."""
    if key is None:
        save_json_atomic(data, path)
        return
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    _write_atomic(path, encrypt_bytes(raw, key))


# ----------------------------------------------------------- lock marker ---

def _lock_path(work_dir: str) -> str:
    return os.path.join(work_dir, "data", LOCK_FILENAME)


def write_lock(work_dir: str, hold_id: str, encrypted_paths: list[str]) -> None:
    """Ghi marker dự án đang khóa: hold nào, những file nào đã mã hóa.

    Đường dẫn lưu TƯƠNG ĐỐI so với work_dir để copy/di chuyển thư mục dự án
    không làm marker chỉ sai chỗ.
    """
    rel = [os.path.relpath(p, work_dir) for p in encrypted_paths]
    save_json_atomic({"hold_id": hold_id, "encrypted": rel}, _lock_path(work_dir))


def read_lock(work_dir: str) -> dict | None:
    """Marker khóa của dự án, hoặc None nếu dự án không khóa."""
    path = _lock_path(work_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("hold_id"):
            return data
    except (ValueError, OSError) as e:
        logger.warning(f"Marker khóa hỏng ({e}) — coi như dự án không khóa")
    return None


def is_locked(work_dir: str) -> bool:
    """Dự án này còn đang khóa (chưa commit hold / chưa xuất video)?"""
    return read_lock(work_dir) is not None


def add_locked_file(work_dir: str, hold_id: str, path: str) -> None:
    """Thêm một file vừa mã hóa vào marker (tạo marker nếu chưa có)."""
    lock = read_lock(work_dir) or {"hold_id": hold_id, "encrypted": []}
    rel = os.path.relpath(path, work_dir)
    if rel not in lock["encrypted"]:
        lock["encrypted"].append(rel)
    save_json_atomic(lock, _lock_path(work_dir))


def unlock_all(work_dir: str, key: bytes | str) -> list[str]:
    """Giải mã mọi file trong marker rồi xóa marker. Trả về danh sách đã giải.

    File nào thiếu trên đĩa thì bỏ qua (người dùng có thể đã xóa tay) — mục
    tiêu là mở khóa dự án, không phải bắt lỗi từng file.
    """
    lock = read_lock(work_dir)
    if not lock:
        return []
    done: list[str] = []
    for rel in lock.get("encrypted", []):
        path = os.path.join(work_dir, rel)
        if not os.path.exists(path):
            continue
        decrypt_file(path, key)
        done.append(path)
    try:
        os.remove(_lock_path(work_dir))
    except OSError as e:
        logger.warning(f"Không xóa được marker khóa: {e}")
    return done
