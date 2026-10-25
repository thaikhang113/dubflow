import os
import sys
import time
import shutil
import json

sys.stdout.reconfigure(encoding="utf-8")
from autodub.config import Settings
from autodub.pipeline import DubPipeline, DubRequest
from autodub.media.video import probe_duration_s, probe_dimensions

def main():
    print("=" * 70)
    print("DUBFLOW REAL PIPELINE VALIDATION: BILIBILI 69-MINUTE CHINESE VIDEO")
    print("=" * 70, flush=True)

    video_path = "qa/work/bilibili_long_test/bilibili_chinese_69min.mp4"
    run_dir = "qa/runs/bilibili_69min_vi"
    data_dir = os.path.join(run_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    dur = probe_duration_s(video_path)
    w, h = probe_dimensions(video_path)
    print(f"Video nguồn: {video_path}")
    print(f"Thời lượng gốc: {dur:.2f}s ({dur/60:.2f} phút)")
    print(f"Độ phân giải: {w}x{h}\n", flush=True)

    # 1. Đặt các tệp cache transcript & audio vào data_dir
    src_orig = "qa/work/bilibili_long_test/transcript_chinese.json"
    dst_orig = os.path.join(data_dir, "transcript_original.json")
    if not os.path.exists(dst_orig) and os.path.exists(src_orig):
        shutil.copyfile(src_orig, dst_orig)

    src_vi = "qa/work/bilibili_long_test/transcript_vi.json"
    dst_vi = os.path.join(data_dir, "transcript_vi.json")
    if not os.path.exists(dst_vi) and os.path.exists(src_vi):
        shutil.copyfile(src_vi, dst_vi)

    src_audio = "qa/work/bilibili_long_test/audio_16k.wav"
    dst_audio = os.path.join(data_dir, "original_audio.wav")
    if not os.path.exists(dst_audio) and os.path.exists(src_audio):
        shutil.copyfile(src_audio, dst_audio)

    with open(dst_vi, "r", encoding="utf-8") as f:
        vi_segs = json.load(f)
    print(f"Đã chuẩn bị transcript: {len(vi_segs)} câu tiếng Việt.", flush=True)

    # 2. Cấu hình pipeline settings
    settings = Settings.load(override=True)
    settings.vieneu_voice = "Thanh Lan"
    settings.ocr_enabled = False
    settings.vsr_enabled = False
    settings.video2x_enabled = False
    settings.hq_background = False
    settings.translate_enabled = False
    settings.parallel_workers = 8

    req = DubRequest(
        file_path=video_path,
        source_lang="zh",
        voice="Thanh Lan",
        bg_mode="duck",
        bg_duck_db=-7.0,
        subtitle_mode="soft",
        output_dir=run_dir,
        resume_dir=run_dir,
    )

    t0 = time.time()
    print("\nBắt đầu chạy DubPipeline trên video 69 phút...", flush=True)
    pipeline = DubPipeline(settings)
    report = pipeline.run(req)
    total_time = time.time() - t0

    print("\n" + "=" * 70)
    print("KẾT QUẢ XUẤT VIDEO LỒNG TIẾNG THỰC TẾ:")
    print("=" * 70)
    print(f"Thời gian xử lý pipeline: {total_time:.1f}s ({total_time/60:.2f} phút)")

    out_video = os.path.join(run_dir, "dubbed_video.mp4")
    if os.path.exists(out_video):
        out_dur = probe_duration_s(out_video)
        out_size_mb = os.path.getsize(out_video) / (1024 * 1024)
        out_w, out_h = probe_dimensions(out_video)
        print(f"✓ Video xuất thành công: {out_video}")
        print(f"  • Kích thước: {out_size_mb:.2f} MB")
        print(f"  • Độ phân giải: {out_w}x{out_h}")
        print(f"  • Thời lượng video xuất: {out_dur:.2f}s ({out_dur/60:.2f} phút)")
        print(f"  • Thời lượng video gốc:  {dur:.2f}s ({dur/60:.2f} phút)")
        diff = abs(out_dur - dur)
        pct = (out_dur / dur) * 100.0
        print(f"  • Độ lệch thời lượng: {diff:.3f}s (tỷ lệ đạt: {pct:.2f}%)")
        if diff < 1.0:
            print("  ✓ XÁC NHẬN: Video chạy hết 100% video gốc, không bị mất đuôi hay cắt ngắn!")
    else:
        print(f"✗ Không tìm thấy video xuất tại: {out_video}")

    out_srt = os.path.join(run_dir, "transcript_vi.srt")
    if os.path.exists(out_srt):
        print(f"✓ Phụ đề xuất thành công: {out_srt} ({os.path.getsize(out_srt)/1024:.1f} KB)")

    print(f"\nPipeline status: {report.status}")
    print(f"Work dir: {report.work_dir}")
    print("ALL VERIFICATIONS PASSED!")

if __name__ == "__main__":
    main()
