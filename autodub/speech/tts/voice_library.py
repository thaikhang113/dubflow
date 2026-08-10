"""Thư viện giọng mẫu trong thư mục ``voices/`` cạnh ứng dụng.

Người dùng thả các đoạn ghi âm mẫu vào ``voices/<bộ nào đó>/`` kèm một tệp
``voices_manifest.json`` mô tả từng đoạn. Module này chỉ ĐỌC danh sách đó;
việc học giọng (mã hóa thành vector giọng) do
:mod:`autodub.speech.tts.vieneu_worker` làm ở chế độ học hàng loạt, và
:mod:`scripts.setup_voices` là nút bấm chạy việc đó.

Mỗi mục trong manifest cần tối thiểu ``file_name`` và ``display_name``;
``gender``, ``country``, ``region`` và ``language`` là tùy chọn và được dùng
làm bộ lọc trong giao diện.

Thêm một bộ giọng mới chỉ là: tạo thư mục con, chép các tệp .wav vào, viết
manifest — không phải sửa dòng mã nào.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from autodub.utils import app_root, setup_logging

logger = setup_logging("autodub.voice_library")

MANIFEST_NAME = "voices_manifest.json"

#: Ngôn ngữ trong manifest → mã quốc gia mặc định, khi manifest không ghi rõ.
_LANG_COUNTRY = {"vi": "vn", "en": "us", "ja": "jp", "ko": "kr", "zh": "cn"}


@dataclass(frozen=True)
class LibraryVoice:
    """Một đoạn ghi âm mẫu chờ được học thành giọng đọc."""

    name: str
    wav: str
    gender: str = ""
    region: str = ""
    country: str = "vn"
    description: str = ""

    def to_batch_item(self) -> dict:
        """Mục truyền cho chế độ học hàng loạt của tiến trình con."""
        return {
            "name": self.name,
            "wav": self.wav,
            "gender": self.gender,
            "region": self.region,
            "country": self.country,
            "description": self.description,
            "source": "library",
        }


def library_dir() -> str:
    """Thư mục ``voices/`` cạnh ứng dụng (có thể chưa tồn tại)."""
    return os.path.join(app_root(), "voices")


def _entry_to_voice(entry: dict, folder: str) -> LibraryVoice | None:
    file_name = str(entry.get("file_name", "")).strip()
    name = str(entry.get("display_name", "")).strip()
    if not file_name:
        return None
    wav = os.path.join(folder, file_name)
    if not os.path.isfile(wav):
        return None
    if not name:
        # Không có tên hiển thị thì lấy phần đuôi của tên tệp, kiểu
        # «vn_male_01_Hoàng_Nam.wav» → «Hoàng Nam».
        stem = os.path.splitext(file_name)[0]
        parts = stem.split("_")
        name = " ".join(parts[3:]) if len(parts) > 3 else stem.replace("_", " ")
    language = str(entry.get("language", "")).lower()
    country = str(entry.get("country", "")).lower() or _LANG_COUNTRY.get(
        language, "vn")
    return LibraryVoice(
        name=name,
        wav=wav,
        gender=str(entry.get("gender", "")).lower(),
        region=str(entry.get("region", "")).lower(),
        country=country,
        description=str(entry.get("description", "")),
    )


def scan(root: str | None = None) -> list[LibraryVoice]:
    """Mọi giọng mẫu tìm thấy trong thư viện, theo thứ tự của từng manifest.

    Tên trùng nhau chỉ lấy lần đầu, để hai bộ giọng cùng tên không đè nhau.
    """
    root = root or library_dir()
    if not os.path.isdir(root):
        return []
    voices: list[LibraryVoice] = []
    taken: set[str] = set()
    for folder, _dirs, files in os.walk(root):
        if MANIFEST_NAME not in files:
            continue
        path = os.path.join(folder, MANIFEST_NAME)
        try:
            with open(path, encoding="utf-8") as f:
                entries = json.load(f)
        except (OSError, ValueError) as e:
            logger.warning(f"Bỏ qua danh sách giọng hỏng {path}: {e}")
            continue
        if not isinstance(entries, list):
            logger.warning(f"Bỏ qua {path}: nội dung phải là một mảng JSON")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            voice = _entry_to_voice(entry, folder)
            if voice is not None and voice.name not in taken:
                voices.append(voice)
                taken.add(voice.name)
    return voices


def pending(settings, root: str | None = None) -> list[LibraryVoice]:
    """Những giọng trong thư viện mà máy này CHƯA học."""
    from autodub.speech.tts.voices import catalog

    known = {v.name for v in catalog(settings)}
    return [v for v in scan(root) if v.name not in known]


def summary(settings, root: str | None = None) -> tuple[int, int]:
    """(số giọng trong thư viện, số giọng chưa học)."""
    all_voices = scan(root)
    from autodub.speech.tts.voices import catalog

    known = {v.name for v in catalog(settings)}
    return len(all_voices), sum(1 for v in all_voices if v.name not in known)
