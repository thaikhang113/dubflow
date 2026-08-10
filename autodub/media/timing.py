"""Soft timing fit — đặt clip giọng lên timeline mà KHÔNG chồng tiếng.

Ràng buộc số 1 (từ người dùng): tốc độ đọc phải đồng đều giữa các câu —
người nghe không được cảm thấy "câu nhanh câu chậm". Vì vậy thứ tự ưu tiên
khi một clip dài hơn khoảng trống của nó là:

1. **Dồn trễ (shift)** — câu sau bắt đầu muộn hơn một chút, phần trễ tự
   tan ở khoảng lặng kế tiếp (drift tích luỹ có trần ``timing_max_drift_s``).
   Tốc độ đọc không đổi — tai người nghe chỉ thấy nhịp video "thở" tự nhiên.
2. **Nén nhẹ bất khả kháng** — chỉ khi dồn trễ đã kịch trần mà clip vẫn
   tràn, nén ĐÚNG clip đó bằng atempo với trần rất thấp
   (``timing_max_atempo``, mặc định 1.1× — dưới ngưỡng tai thường nhận ra).
3. **Chấp nhận + ghi nhận** — phần tràn còn lại được chấp nhận (như kiến
   trúc cũ) nhưng ghi vào báo cáo để người dùng biết chính xác câu nào cần
   sửa tay (rút gọn bản dịch / hạ VIDEO_SPEED).

So với "auto-fit" cũ (đã xoá): bản cũ nén/cắt MỌI câu theo từng slot —
tempo nhảy loạn giữa các dòng. Bản này không đụng vào tốc độ đọc trừ bước 2
(hiếm, trần thấp, có công tắc), và không bao giờ cắt âm thanh.

Toàn bộ là một lượt quét tuyến tính, thuần số học — chỉ các clip bị nén mới
tốn thêm một lệnh ffmpeg.
"""
from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from autodub.utils import ensure_dir, seg_wav_path, setup_logging

logger = setup_logging("autodub.timing")

# Nén dưới mức này không bõ một lệnh ffmpeg (chênh <2% tai không thấy).
_MIN_WORTHWHILE_ATEMPO = 1.02


@dataclass
class TimingReport:
    """Kết quả đặt timeline — nguồn cho quality_report.json."""
    segments_total: int = 0
    segments_shifted: int = 0        # câu bị dồn trễ > 50 ms
    max_shift_s: float = 0.0
    segments_compressed: int = 0     # câu phải nén atempo (bất khả kháng)
    segments_overlapped: int = 0     # câu vẫn còn chồng sau mọi biện pháp
    total_overlap_s: float = 0.0
    details: list[dict] = field(default_factory=list)  # per-segment issues

    def to_dict(self) -> dict:
        return {
            "segments_total": self.segments_total,
            "segments_shifted": self.segments_shifted,
            "max_shift_s": round(self.max_shift_s, 3),
            "segments_compressed": self.segments_compressed,
            "segments_overlapped": self.segments_overlapped,
            "total_overlap_s": round(self.total_overlap_s, 3),
            "details": self.details,
        }


def plan_placements(
    segments: list[dict],
    durations: list[float | None],
    max_drift_s: float = 1.5,
    min_gap_s: float = 0.12,
    max_atempo: float = 1.1,
) -> tuple[list[dict], TimingReport]:
    """Tính vị trí đặt + hệ số nén (nếu buộc phải) cho từng clip.

    Trả về ``(placements, report)`` — ``placements[i]`` gồm:
    ``{"start": <giây>, "atempo": <1.0..max_atempo>}``. Thuần số học, không
    đụng file — phần render nằm ở :func:`apply_soft_timing`.
    """
    rep = TimingReport(segments_total=len(segments))
    placements: list[dict] = []
    prev_end = float("-inf")

    for i, seg in enumerate(segments):
        natural = float(seg["start"])
        dur = durations[i] or 0.0

        # 1) Dồn trễ: bắt đầu tại mốc gốc, trừ khi clip trước còn đang nói.
        t = max(natural, prev_end + min_gap_s) if dur > 0 else natural
        if t - natural > max_drift_s:
            t = natural + max_drift_s  # kịch trần — phần thiếu tính là chồng
        shift = t - natural
        if shift > 0.05:
            rep.segments_shifted += 1
            rep.max_shift_s = max(rep.max_shift_s, shift)

        # Chồng còn lại với clip trước (sau khi đã dồn hết mức cho phép).
        overlap_prev = max(0.0, (prev_end + min_gap_s) - t) if dur > 0 else 0.0

        # 2) Nén bất khả kháng: chỉ khi clip này (đặt tại t) sẽ ép câu SAU
        # vượt trần drift của chính nó. Nhìn trước một câu là đủ vì drift
        # lan truyền qua prev_end.
        atempo = 1.0
        if dur > 0 and i + 1 < len(segments):
            next_natural = float(segments[i + 1]["start"])
            latest_end = next_natural + max_drift_s - min_gap_s
            available = latest_end - t
            if 0 < available < dur:
                want = dur / available
                if want >= _MIN_WORTHWHILE_ATEMPO:
                    atempo = min(max_atempo, want)

        final_dur = dur / atempo if atempo > 1.0 else dur
        if atempo > 1.0:
            rep.segments_compressed += 1

        issue: dict = {}
        if overlap_prev > 0.01:
            rep.segments_overlapped += 1
            rep.total_overlap_s += overlap_prev
            issue["overlap_prev_s"] = round(overlap_prev, 3)
        if shift > 0.05:
            issue["shift_s"] = round(shift, 3)
        if atempo > 1.0:
            issue["atempo"] = round(atempo, 3)
        if issue:
            issue["id"] = seg.get("id")
            rep.details.append(issue)

        placements.append({"start": round(t, 3), "atempo": round(atempo, 4)})
        if dur > 0:
            prev_end = max(prev_end, t + final_dur)

    return placements, rep


def apply_soft_timing(
    segments: list[dict],
    src_dir: str,
    dst_dir: str,
    settings,
    max_workers: int = 4,
) -> tuple[str, TimingReport]:
    """Đặt lại timeline cho các clip trong ``src_dir`` (mutate ``segments``).

    - Mọi clip đều được tham chiếu từ MỘT thư mục kết quả (merge đọc một
      chỗ): clip không nén được copy sang, clip nén chạy atempo.
    - ``segments`` được cập nhật ``start``/``end``/``duration`` theo vị trí
      đặt thật — SRT và bước merge dùng đúng timeline người nghe sẽ nghe.
    - Trả về ``(dir_dùng_để_merge, report)``. Khi không có gì phải làm
      (mọi câu nằm gọn trong chỗ của nó) trả về ``(src_dir, report)`` —
      không copy vô ích.
    """
    from autodub.media.audio import apply_atempo, wav_duration_s

    durations = [wav_duration_s(seg_wav_path(src_dir, s["id"]))
                 for s in segments]
    placements, report = plan_placements(
        segments, durations,
        max_drift_s=settings.timing_max_drift_s,
        min_gap_s=settings.timing_min_gap_s,
        max_atempo=settings.timing_max_atempo,
    )

    needs_render = any(p["atempo"] > 1.0 for p in placements)
    out_dir = src_dir
    if needs_render:
        out_dir = ensure_dir(dst_dir)

        def _one(i: int) -> None:
            seg = segments[i]
            src = seg_wav_path(src_dir, seg["id"])
            if not os.path.exists(src):
                return
            dst = os.path.join(out_dir, os.path.basename(src))
            atempo = placements[i]["atempo"]
            # Resume-safe: đầu ra còn mới hơn nguồn VÀ đúng thời lượng kỳ
            # vọng (hệ số nén có thể đổi giữa hai lần chạy) thì bỏ qua.
            if (os.path.exists(dst) and os.path.getsize(dst) > 0
                    and os.path.getmtime(dst) >= os.path.getmtime(src)):
                want = (durations[i] or 0.0) / atempo
                have = wav_duration_s(dst) or -1.0
                if abs(have - want) < 0.05:
                    return
            if atempo > 1.0:
                apply_atempo(src, dst, atempo)
            else:
                # Copy thay vì link: dst_dir có thể bị xoá độc lập.
                shutil.copyfile(src, dst)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            list(pool.map(_one, range(len(segments))))

    # Mutate start/end lên timeline THẬT (sau shift + nén) — SRT, merge và
    # total_duration cùng nhìn một sự thật. GIỮ NGUYÊN seg["duration"] (thời
    # lượng câu GỐC) — report/timing_guide vẫn so được dub với nguồn.
    from autodub.media.audio import wav_duration_s as _dur
    for i, seg in enumerate(segments):
        t = placements[i]["start"]
        final = _dur(seg_wav_path(out_dir, seg["id"])) or durations[i] or \
            float(seg.get("duration", 0) or 0)
        seg["start"] = round(t, 3)
        seg["end"] = round(t + final, 3)

    if report.segments_shifted or report.segments_compressed \
            or report.segments_overlapped:
        parts = []
        if report.segments_shifted:
            parts.append(f"{report.segments_shifted} câu được lùi nhẹ vào "
                         f"khoảng lặng (nhiều nhất {report.max_shift_s:.1f} "
                         "giây)")
        if report.segments_compressed:
            parts.append(f"{report.segments_compressed} câu đọc nhanh hơn "
                         "một chút cho vừa chỗ")
        if report.segments_overlapped:
            parts.append(f"{report.segments_overlapped} câu vẫn còn chồng "
                         "tiếng nhẹ")
        logger.info("Sắp xếp thời gian các câu: " + ", ".join(parts) + ".")
    else:
        logger.info("Sắp xếp thời gian các câu: mọi câu đều vừa khít, "
                    "không phải chỉnh gì")
    return out_dir, report
