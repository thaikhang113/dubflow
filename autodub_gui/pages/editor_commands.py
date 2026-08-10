"""Các thao tác hoàn tác được của Trình chỉnh sửa.

Mỗi thao tác sửa cấu trúc câu thoại được gói thành một lệnh, nhờ vậy người
dùng bấm Ctrl+Z là quay lại đúng trạng thái trước đó.

Cách hoàn tác: trước khi làm gì, lệnh chụp lại toàn bộ danh sách câu; khi
hoàn tác thì ghi lại bản chụp đó rồi báo trang cha đọc lại từ đĩa. Cách này
đơn giản và luôn đúng, kể cả với thao tác tách hay gộp làm đổi nhiều câu.

Riêng phần tệp giọng đọc thì không khôi phục được — hoàn tác một thao tác xóa
sẽ trả lại lời thoại nhưng câu đó cần được đọc lại. Băng nhắc ở trên cùng luôn
nói rõ điều này.
"""
from __future__ import annotations

import copy
import json

from PySide6.QtGui import QUndoCommand

from autodub.workdir import data_path


def _transcript_path(page) -> str:
    from autodub.languages import get_target

    target = get_target(page.target_key())
    return data_path(page.work_dir(), target.transcript_name)


class _SegmentCommand(QUndoCommand):
    """Khung chung: chụp lại danh sách câu rồi gọi một hàm của lõi xử lý."""

    #: Thao tác đổi cấu trúc câu sẽ xóa video kết quả (dubbed_video.mp4) để
    #: làm mới — mà trình phát trong editor đang mở đúng tệp đó. Trên Windows
    #: tệp đang mở là tệp bị khóa (WinError 32), nên phải nhả video ra trước
    #: rồi mở lại sau. Sửa chữ thuần túy thì không đụng tệp video.
    releases_video = True

    def __init__(self, page, description: str):
        super().__init__(description)
        self._page = page
        self._before: list[dict] | None = None
        self._failed = False

    def redo(self) -> None:      # noqa: D102 — Qt gọi cả lần đầu lẫn khi làm lại
        if self._before is None:
            self._before = copy.deepcopy(self._read())
        position = (self._page.release_video()
                    if self.releases_video else None)
        try:
            self._apply()
        except Exception as e:  # noqa: BLE001 — hiện thành thông báo thân thiện
            self._failed = True
            self._page.report_error(str(e))
            self._page.restore_video(position)
            return
        self._page.reload_segments()
        self._page.restore_video(position)

    def undo(self) -> None:      # noqa: D102 — Qt gọi khi người dùng hoàn tác
        if self._failed or self._before is None:
            return
        position = (self._page.release_video()
                    if self.releases_video else None)
        self._write(self._before)
        self._page.reload_segments()
        self._page.restore_video(position)

    def _apply(self) -> None:
        """Việc mà lệnh này thực sự làm, lớp con phải viết."""
        raise NotImplementedError

    def _read(self) -> list[dict]:
        with open(_transcript_path(self._page), encoding="utf-8") as f:
            return json.load(f)

    def _write(self, segments: list[dict]) -> None:
        from autodub.utils import save_json_atomic

        save_json_atomic(segments, _transcript_path(self._page))


class EditTextCommand(_SegmentCommand):
    """Sửa lời thoại của một câu."""

    releases_video = False   # chỉ sửa chữ, không đụng tệp video

    def __init__(self, page, seg_id: int, text: str):
        super().__init__(page, f"Sửa lời thoại câu {seg_id}")
        self._seg_id = seg_id
        self._text = text

    def _apply(self) -> None:
        from autodub.editor import save_segment_texts

        save_segment_texts(self._page.work_dir(), {self._seg_id: self._text},
                           self._page.target_key())


class AddSegmentCommand(_SegmentCommand):
    """Chèn một câu mới."""

    def __init__(self, page, after_id: int, start: float, end: float,
                 text: str = ""):
        super().__init__(page, "Thêm câu thoại")
        self._after_id = after_id
        self._start = start
        self._end = end
        self._text = text

    def _apply(self) -> None:
        from autodub.editor import add_segment

        add_segment(self._page.work_dir(), self._after_id, self._start,
                    self._end, self._text,
                    target_key=self._page.target_key())


class DeleteSegmentCommand(_SegmentCommand):
    """Xóa một câu."""

    def __init__(self, page, seg_id: int):
        super().__init__(page, f"Xóa câu {seg_id}")
        self._seg_id = seg_id

    def _apply(self) -> None:
        from autodub.editor import delete_segment

        delete_segment(self._page.work_dir(), self._seg_id,
                       self._page.target_key())


class SplitSegmentCommand(_SegmentCommand):
    """Tách một câu làm đôi."""

    def __init__(self, page, seg_id: int, at_time: float):
        super().__init__(page, f"Tách câu {seg_id}")
        self._seg_id = seg_id
        self._at_time = at_time

    def _apply(self) -> None:
        from autodub.editor import split_segment

        split_segment(self._page.work_dir(), self._seg_id, self._at_time,
                      self._page.target_key())


class MergeSegmentCommand(_SegmentCommand):
    """Gộp nhiều câu liền nhau."""

    def __init__(self, page, seg_ids: list[int]):
        super().__init__(page, "Gộp câu thoại")
        self._seg_ids = list(seg_ids)

    def _apply(self) -> None:
        from autodub.editor import merge_segments

        merge_segments(self._page.work_dir(), self._seg_ids,
                       self._page.target_key())


class MoveSegmentCommand(_SegmentCommand):
    """Đổi mốc thời gian của một câu bằng cách kéo trên dải thời gian."""

    def __init__(self, page, seg_id: int, start: float, end: float):
        super().__init__(page, f"Đổi thời điểm câu {seg_id}")
        self._seg_id = seg_id
        self._start = start
        self._end = end

    def _apply(self) -> None:
        from autodub.editor import set_segment_time

        set_segment_time(self._page.work_dir(), self._seg_id, self._start,
                         self._end, self._page.target_key())
