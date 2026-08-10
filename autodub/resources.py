"""Trần tài nguyên dùng chung cho cả pipeline — không có scheduler.

Mỗi tầng trong pipeline trước đây tự quyết định dùng bao nhiêu máy: pool ffmpeg
lấy ``cpu-1`` luồng, TTS lấy ``cpu // n`` thread mỗi worker, Demucs mở tiến
trình GPU riêng, ASR nạp model của nó. Ai cũng đúng khi chạy một mình, nhưng
chạy chồng nhau thì một máy 8 lõi dễ có 8 ffmpeg + 3 worker ONNX + Demucs cùng
lúc. Module này giữ ba thứ dùng chung để cái trần là thật, thay vì là giả định
của từng chỗ.

Các pool KHÔNG bị thu nhỏ: chúng vẫn nhận số việc như cũ, chỉ có số tiến trình
ffmpeg sống cùng lúc bị chặn.

QUY TẮC BẮT BUỘC cho ``FFMPEG_SLOTS``: chỉ acquire trong hàm lá — hàm trực
tiếp gọi ``subprocess.run`` — và tuyệt đối không quanh ``pool.map`` hay quanh
một hàm còn gọi tiếp hàm lá khác. Semaphore này không đệ quy: acquire hai lần
lồng nhau trong cùng một luồng là deadlock.
"""
from __future__ import annotations

import os
import threading

_CPU = os.cpu_count() or 4

#: Số tiến trình ffmpeg được sống cùng lúc trong toàn tiến trình. Cùng công
#: thức với ``audio._FFMPEG_WORKERS`` cũ (chừa một lõi cho GUI), nhưng là trần
#: chung cho MỌI pool thay vì trần riêng của từng pool — nên các call site
#: truyền ``min(8, parallel_workers)`` không còn cộng dồn lên được nữa.
#:
#: BoundedSemaphore (không phải Semaphore) để release lệch nhịp báo lỗi ngay
#: thay vì âm thầm nới trần.
FFMPEG_SLOTS = threading.BoundedSemaphore(max(2, min(6, _CPU - 1)))

#: Giữ khi dùng GPU: nhánh Demucs GPU và lúc nạp model Whisper trên CUDA.
#: Cổng sẵn có trong pipeline chỉ là *dự đoán* xem ASR có dùng GPU không; lock
#: này là sự thật. Dự đoán sai thì hai việc chạy lần lượt — chậm, nhưng không
#: CUDA OOM. Không được giữ lock xuyên qua một lượt chờ future của việc khác.
GPU_LOCK = threading.Lock()


def cpu_share(n_workers: int, reserve: int = 2) -> int:
    """Số thread cho MỘT worker khi có ``n_workers`` worker chạy song song.

    ``reserve`` là số lõi chừa lại cho GUI và cho các slot ffmpeg — không chừa
    thì cửa sổ đứng trong lúc TTS chạy. Luôn trả về ít nhất 1.
    """
    return max(1, (_CPU - max(0, reserve)) // max(1, n_workers))
