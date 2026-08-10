"""Danh mục giọng CapCut — đọc ``Voice.json`` trong gói, KHÔNG gọi mạng.

Tách khỏi :mod:`autodub.speech.tts.voices` để module danh mục chung không
phải biết chi tiết định dạng của CapCut, và để giao diện tra cứu tên giọng
mà không kéo theo client HTTP.

Tên hiển thị trong ``Voice.json`` có dạng «Thanh Lan - Nữ ngọt ngào»: phần
trước dấu gạch là TÊN giọng (định danh trong app, phải là duy nhất), phần
sau chỉ để mô tả.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid

from autodub.speech.tts.capcut_api.config import DEFAULT_DEVICE, catalog_file
from autodub.utils import save_json_atomic

#: Ngôn ngữ duy nhất app dùng — Voice.json còn nhiều giọng ngoại ngữ khác.
LANG = "vi-VN"

#: Giọng mặc định khi catalog offline rỗng (máy chưa cài VieNeu).
DEFAULT_CAPCUT_VOICE = "Minh Trang"


def _gender_of(voice_type: str) -> str:
    """Suy giới tính từ ``voice_type``; giọng hiệu ứng dựng trên nền nam."""
    vt = voice_type.lower()
    if "female" in vt or vt.startswith("bv421") or vt.startswith("bv074") \
            or vt.startswith("bv562"):
        return "female"
    return "male"


def _split_name(display_name: str) -> tuple[str, str]:
    """«Thanh Lan - Nữ ngọt ngào» → («Thanh Lan», «Nữ ngọt ngào»)."""
    name, _, description = display_name.partition(" - ")
    return name.strip(), description.strip()


#: Cache đọc file — Voice.json là tài nguyên tĩnh trong gói, đọc một lần.
_entries: list[dict] | None = None


def entries() -> list[dict]:
    """Các mục vi-VN trong Voice.json, đã tách tên và suy giới tính.

    Mỗi mục: ``{"name", "description", "gender", "voice_type",
    "resource_id"}``. Trả về danh sách rỗng nếu thiếu file (bản đóng gói
    hỏng) — app vẫn chạy được bằng giọng offline.
    """
    global _entries
    if _entries is not None:
        return _entries
    path = catalog_file()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        _entries = []
        return _entries
    result: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or item.get("lang") != LANG:
            continue
        name, description = _split_name(str(item.get("display_name", "")))
        voice_type = str(item.get("voice_type", ""))
        if not name or not voice_type or name in seen:
            continue
        seen.add(name)
        result.append({
            "name": name,
            "description": description,
            "gender": _gender_of(voice_type),
            "voice_type": voice_type,
            "resource_id": str(item.get("resource_id", "")),
        })
    _entries = result
    return _entries


def names() -> set[str]:
    """Tên mọi giọng CapCut — dùng để định tuyến engine."""
    return {e["name"] for e in entries()}


def lookup(name: str) -> dict | None:
    """Mục catalog của một tên giọng, hoặc None nếu không phải giọng CapCut."""
    for entry in entries():
        if entry["name"] == name:
            return entry
    return None


def device_file() -> str:
    """Nơi cất hồ sơ thiết bị CapCut (ghi được cả khi chạy từ bản đóng gói)."""
    return os.path.join(os.path.expanduser("~"), ".voxdub_cache",
                        "capcut_device.json")


def _fresh_ids(seed: str | None = None) -> dict:
    """Bộ ba định danh 19 chữ số. ``seed`` cố định → luôn ra cùng bộ.

    Lần đầu ta gieo bằng vân tay máy để một máy có định danh ổn định; khi bị
    máy chủ chặn thì gieo ngẫu nhiên để lấy định danh khác hẳn.
    """
    if seed is None:
        seed = uuid.uuid4().hex + uuid.uuid4().hex
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def _id(chunk: str) -> str:
        # Cùng dạng ID thật của CapCut: 19 chữ số, mở đầu bằng 7.
        return "7" + str(int(chunk, 16) % 10 ** 18).zfill(18)

    return {"device_id": _id(digest[:16]),
            "iid": _id(digest[16:32]),
            "tdid": _id(digest[32:48])}


def device_profile() -> dict:
    """Hồ sơ thiết bị CapCut, đọc từ đĩa; lần đầu thì tạo và ghi lại.

    Trước đây hồ sơ được suy thẳng từ vân tay máy, không lưu gì cả. Cách đó
    hỏng theo kiểu không cứu được: máy chủ CapCut chặn một device_id (trả
    ``ret: -6, shark block only``) thì máy đó vĩnh viễn không đọc được nữa vì
    mỗi lần chạy lại suy ra đúng ID đã bị chặn. Nay hồ sơ nằm trong tệp để
    :func:`rotate_device` thay được bằng ID mới khi bị chặn.
    """
    from autodub.device_id import get_fingerprint

    path = device_file()
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        if all(saved.get(k) for k in ("device_id", "iid", "tdid")):
            return {**DEFAULT_DEVICE, **saved}
    except (OSError, ValueError):
        pass
    try:
        seed = get_fingerprint()
    except Exception:  # noqa: BLE001 — không đọc được vân tay thì lấy ngẫu nhiên
        seed = None
    return _write_profile(_fresh_ids(seed))


def rotate_device() -> dict:
    """Cấp hồ sơ thiết bị mới và ghi đè lên tệp — dùng khi bị máy chủ chặn."""
    return _write_profile(_fresh_ids())


def _write_profile(ids: dict) -> dict:
    profile = {**DEFAULT_DEVICE, **ids,
               "region": "VN", "loc": "VN", "lan": "vi-VN"}
    try:
        save_json_atomic(profile, device_file())
    except OSError:
        pass  # không ghi được thì vẫn chạy, chỉ là lần sau lại đổi ID
    return profile
