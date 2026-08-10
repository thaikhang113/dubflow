"""Làm mới toàn bộ tệp phụ đề của một dự án — một chỗ duy nhất.

Cả pipeline lẫn trình chỉnh sửa đều phải sinh lại phụ đề mỗi khi lời thoại
hoặc mốc thời gian đổi. Trước đây hai nơi tự viết lấy nên rất dễ lệch nhau
(sửa phụ đề trong trình chỉnh sửa mà video xuất ra vẫn dùng bản cũ). Giờ cả
hai gọi chung :func:`refresh_subtitles`, nên chữ trong tệp .srt, chữ ghi vào
video và chữ xem trước luôn là MỘT.
"""
from __future__ import annotations

import os

from autodub.languages import TargetLang
from autodub.utils import setup_logging
from autodub.workdir import data_path

logger = setup_logging("autodub.subtitles")

#: Tên tệp phụ đề kiểu cụm chữ, nằm trong thư mục data của dự án.
KARAOKE_NAME = "transcript_karaoke.ass"


def srt_path_of(work_dir: str, target: TargetLang) -> str:
    """Tệp .srt tiếng Việt — để ở gốc thư mục dự án cho người dùng dễ thấy."""
    return os.path.join(work_dir, target.srt_name)


def refresh_subtitles(
    segments: list[dict],
    work_dir: str,
    target: TargetLang,
    style: dict | None,
    *,
    merge_dir: str | None = None,
    settings=None,
    for_burn: bool = False,
) -> tuple[str, str]:
    """Ghi lại phụ đề từ danh sách câu hiện tại.

    Luôn ghi tệp ``.srt`` (dùng cho phụ đề rời, và là bản dự phòng khi phụ đề
    kiểu cụm chữ hỏng). Khi ``for_burn`` và người dùng chọn kiểu cụm chữ thì
    sinh thêm tệp ``.ass`` có hiệu ứng.

    Trả về ``(đường dẫn .srt, đường dẫn tệp sẽ ghi vào hình)``. Hai giá trị
    bằng nhau nghĩa là đang dùng phụ đề cả câu.
    """
    from autodub.text.srt import generate_srt_styled

    srt_path = srt_path_of(work_dir, target)
    generate_srt_styled(segments, srt_path, target.text_field, style)

    if not for_burn or (style or {}).get("display") != "karaoke" or not merge_dir:
        return srt_path, srt_path

    # Phụ đề cụm chữ: sinh .ass từ mốc chữ thật của chính bản giọng đọc cuối
    # cùng. Hỏng thì quay về phụ đề cả câu — video vẫn phải ra được.
    try:
        from autodub.text.ass_karaoke import build_karaoke_ass
        burn_path = build_karaoke_ass(
            segments, merge_dir, data_path(work_dir, KARAOKE_NAME),
            style, text_field=target.text_field, settings=settings,
            cache_path=data_path(work_dir, "align_cache.json"))
        return srt_path, burn_path
    except Exception as e:
        logger.warning(f"Không tạo được phụ đề kiểu cụm chữ ({e}) — "
                       "dùng phụ đề hiện cả câu")
        return srt_path, srt_path
