"""Tiến trình con tách nhạc nền — chạy trong venv có torch bản CUDA.

Venv chính chỉ mang torch bản CPU. Chạy việc tách ở đây là Demucs dùng được
card đồ họa mà không phải cài thêm gì vào venv chính. Được
:mod:`autodub.media.vocal_separator` gọi một phát rồi thoát:

    python demucs_worker.py --input in.wav --vocals v.wav --no-vocals nv.wav

Prints one JSON line to stdout: {"ok": true, "device": "cuda"} or
{"ok": false, "error": "..."}.

QUAN TRỌNG: file này chạy độc lập trong venv khác — KHÔNG import autodub.
Nó cũng là module bình thường (``autodub.media.demucs_worker``) để đường CPU
trong :func:`vocal_separator._run_demucs` dùng chung :func:`separate_file`,
khỏi chép đôi logic.

Video dài (hoặc máy ít RAM) được tách THEO KHÚC: ``apply_model(split=True)``
chỉ chia nhỏ phần TÍNH TOÁN chứ vẫn đòi nguyên tensor trong RAM — video 1 giờ
44.1 kHz stereo là ~1.2 GB mỗi bản sao, cộng 4 stem đầu ra thì máy 8 GB chết
đứng. Khúc ~180 s + chồng lấn 6 s, làm mượt chỗ nối bằng crossfade tuyến
tính, ghi dần ra đĩa — RAM đỉnh chỉ còn cỡ MỘT khúc bất kể video dài bao lâu.
"""
import argparse
import json
import sys

#: Ngưỡng thời lượng bật chế độ theo khúc (giây). Dưới ngưỡng này đường một
#: phát giữ nguyên hành vi cũ — không đổi gì cho video ngắn thường gặp.
CHUNK_THRESHOLD_S = 480.0
CHUNK_S = 180.0        # độ dài lõi mỗi khúc
OVERLAP_S = 6.0        # phần chồng lấn giữa hai khúc kề nhau


def plan_chunks(total_frames: int, chunk_frames: int,
                overlap_frames: int) -> list[tuple[int, int]]:
    """Chia ``total_frames`` thành các khoảng [start, stop) chồng lấn nhau.

    Hai khoảng kề nhau chia sẻ đúng ``overlap_frames`` khung. Khoảng cuối luôn
    dài hơn ``overlap_frames`` (dồn phần lẻ vào khoảng cuối) để crossfade
    không bao giờ thiếu dữ liệu.
    """
    if total_frames <= chunk_frames:
        return [(0, total_frames)]
    hop = chunk_frames - overlap_frames
    ranges = []
    start = 0
    while start + chunk_frames < total_frames:
        ranges.append((start, start + chunk_frames))
        start += hop
    ranges.append((start, total_frames))
    return ranges


def crossfade_into(tail, head):
    """Hòa ``tail`` (đuôi khúc trước) vào đầu ``head`` bằng dốc tuyến tính.

    ``tail``/``head`` là mảng (channels, frames); sửa ``head`` tại chỗ và trả
    về nó. Khung đầu nghiêng hẳn về khúc trước, khung cuối về khúc sau.
    """
    import numpy as np

    o = min(tail.shape[1], head.shape[1])
    if o > 0:
        t = np.linspace(0.0, 1.0, o, dtype=np.float32)
        head[:, :o] = tail[:, :o] * (1.0 - t) + head[:, :o] * t
    return head


def _stream_stats(path) -> tuple[float, float]:
    """(mean, std) của bản trộn mono, đọc THEO KHỐI — không nạp cả file.

    Giữ đúng ngữ nghĩa chuẩn hóa toàn cục của đường một phát: mọi khúc đều
    normalize/denormalize bằng cùng một cặp mean/std nên biên độ giữa các
    khúc khớp nhau tuyệt đối.
    """
    import numpy as np
    import soundfile as sf

    n = 0
    s = 0.0
    ss = 0.0
    for block in sf.blocks(path, blocksize=1_048_576, always_2d=True,
                           dtype="float32"):
        mono = block.mean(axis=1, dtype=np.float64)
        n += mono.size
        s += float(mono.sum())
        ss += float((mono * mono).sum())
    if n == 0:
        return 0.0, 0.0
    mean = s / n
    var = max(ss / n - mean * mean, 0.0)
    return mean, var ** 0.5


def _split_stems(sources, model, np):
    """(vocals, no_vocals) dạng numpy từ tensor 4 stem — cộng dồn tại chỗ."""
    stem_index = {name: i for i, name in enumerate(model.sources)}
    if "vocals" not in stem_index:
        raise RuntimeError(f"Model has no 'vocals' stem; got {model.sources}")
    vocals = sources[stem_index["vocals"]].numpy()
    other_is = [i for name, i in stem_index.items() if name != "vocals"]
    no_vocals = sources[other_is[0]]
    for i in other_is[1:]:
        no_vocals.add_(sources[i])
    return vocals, no_vocals.numpy()


def load_model(model_name: str = "htdemucs", device: str | None = None):
    """Nạp model Demucs một lần; trả về ``(model, device)``.

    Tách khỏi :func:`separate_file` để chế độ ``--serve`` nạp MỘT lần cho cả
    lô video thay vì mỗi video một lần (~15–40 s tiết kiệm mỗi video).
    """
    import torch
    from demucs.pretrained import get_model

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = get_model(model_name)
    model.eval()
    return model, device


def separate_file(input_path: str, vocals_path: str, no_vocals_path: str,
                  model_name: str = "htdemucs", device: str | None = None,
                  force_chunked: bool = False, model=None) -> str:
    """Tách ``input_path`` thành hai stem; trả về tên device đã dùng.

    Video ngắn đi đường một phát (hành vi cũ, không đổi một bit); video dài
    hơn :data:`CHUNK_THRESHOLD_S` hoặc ``force_chunked`` (máy ít RAM) đi
    đường theo khúc. ``model`` cho phép chế độ serve tái dùng model đã nạp.
    """
    import soundfile as sf

    if model is None:
        model, device = load_model(model_name, device)
    model.to(device)

    info = sf.info(input_path)
    duration_s = info.frames / float(info.samplerate)
    if force_chunked or duration_s > CHUNK_THRESHOLD_S:
        _separate_chunked(input_path, vocals_path, no_vocals_path,
                          model, device, info)
    else:
        _separate_single(input_path, vocals_path, no_vocals_path,
                         model, device)
    return device


def _separate_single(input_path, vocals_path, no_vocals_path, model, device):
    """Đường một phát — video ngắn, giữ nguyên hành vi cũ."""
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.audio import convert_audio

    # dtype="float32": mặc định soundfile trả float64, torch lại cần
    # float32 — đọc thẳng float32 để không giữ hai bản trong RAM.
    audio, src_sr = sf.read(input_path, always_2d=True, dtype="float32")
    wav = torch.from_numpy(audio.T)
    del audio
    wav = convert_audio(wav, src_sr, model.samplerate, model.audio_channels)
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)

    with torch.no_grad():
        sources = apply_model(model, wav[None].to(device), split=True,
                              overlap=0.25, progress=False)[0].cpu()
    del wav
    # Denormalize tại chỗ — tránh nhân đôi tensor 4 stem.
    sources.mul_(ref.std() + 1e-8).add_(ref.mean())

    vocals, no_vocals = _split_stems(sources, model, np)
    _write_stem(vocals_path, vocals, model.samplerate, np, sf)
    _write_stem(no_vocals_path, no_vocals, model.samplerate, np, sf)


def _separate_chunked(input_path, vocals_path, no_vocals_path, model,
                      device, info):
    """Đường theo khúc — RAM đỉnh cỡ một khúc, ghi dần ra đĩa."""
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.audio import convert_audio

    src_sr = info.samplerate
    mean, std = _stream_stats(input_path)
    denom = std + 1e-8
    ratio = model.samplerate / float(src_sr)

    ranges = plan_chunks(info.frames, int(CHUNK_S * src_sr),
                         int(OVERLAP_S * src_sr))
    tails = None   # (vocals_tail, no_vocals_tail) chờ crossfade với khúc sau

    with sf.SoundFile(vocals_path, "w", samplerate=model.samplerate,
                      channels=model.audio_channels,
                      subtype="PCM_16") as f_v, \
         sf.SoundFile(no_vocals_path, "w", samplerate=model.samplerate,
                      channels=model.audio_channels,
                      subtype="PCM_16") as f_nv:
        for ci, (start, stop) in enumerate(ranges):
            block, _ = sf.read(input_path, start=start, stop=stop,
                               always_2d=True, dtype="float32")
            wav = torch.from_numpy(block.T)
            del block
            wav = convert_audio(wav, src_sr, model.samplerate,
                                model.audio_channels)
            wav = (wav - mean) / denom
            with torch.no_grad():
                sources = apply_model(model, wav[None].to(device), split=True,
                                      overlap=0.25, progress=False)[0].cpu()
            del wav
            sources.mul_(denom).add_(mean)
            vocals, no_vocals = _split_stems(sources, model, np)
            del sources

            if tails is not None:
                crossfade_into(tails[0], vocals)
                crossfade_into(tails[1], no_vocals)

            last = ci == len(ranges) - 1
            keep = vocals.shape[1] if last else (
                vocals.shape[1] - int(round(OVERLAP_S * src_sr * ratio)))
            _append_stem(f_v, vocals[:, :keep], np)
            _append_stem(f_nv, no_vocals[:, :keep], np)
            tails = None if last else (vocals[:, keep:].copy(),
                                       no_vocals[:, keep:].copy())


def _write_stem(path, arr, samplerate, np, sf) -> None:
    """Ghi một stem (channels, samples) ra WAV 16-bit."""
    data = np.clip(arr, -1.0, 1.0).T
    sf.write(path, data, samplerate, subtype="PCM_16")


def _append_stem(handle, arr, np) -> None:
    handle.write(np.clip(arr, -1.0, 1.0).T)


def serve() -> int:
    """Chế độ phục vụ cả lô: nạp model MỘT lần, nhận việc qua stdin.

    Giao thức JSON-mỗi-dòng (cùng khuôn vieneu_worker): in
    ``{"ready": true, "device": ...}`` khi model sẵn sàng, rồi mỗi dòng vào
    ``{"input": ..., "vocals": ..., "no_vocals": ..., "chunked": bool}``
    trả một dòng ``{"ok": true, "device": ...}`` / ``{"ok": false, ...}``.
    Sau MỖI video model được đẩy về CPU + trả VRAM — Whisper của video đó
    cần trọn card đồ họa, model nằm lại chỉ chiếm ~2 GB vô ích.
    """
    import torch

    try:
        model, device = load_model()
    except Exception as e:  # noqa: BLE001 — report everything to the parent
        print(json.dumps({"ready": False,
                          "error": f"{type(e).__name__}: {e}"}), flush=True)
        return 1
    print(json.dumps({"ready": True, "device": device}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            used = separate_file(req["input"], req["vocals"],
                                 req["no_vocals"], device=device,
                                 force_chunked=bool(req.get("chunked")),
                                 model=model)
            resp = {"ok": True, "device": used}
        except Exception as e:  # noqa: BLE001
            resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            # Trả VRAM ngay cả khi lỗi — video sau còn cần GPU cho Whisper.
            if device == "cuda":
                model.cpu()
                torch.cuda.empty_cache()
        print(json.dumps(resp), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true",
                        help="Chế độ phục vụ cả lô (JSON qua stdin/stdout)")
    parser.add_argument("--input")
    parser.add_argument("--vocals")
    parser.add_argument("--no-vocals")
    parser.add_argument("--model", default="htdemucs")
    parser.add_argument("--chunked", action="store_true",
                        help="Ép tách theo khúc (máy ít RAM)")
    args = parser.parse_args()

    if args.serve:
        return serve()
    if not (args.input and args.vocals and args.no_vocals):
        parser.error("--input/--vocals/--no-vocals là bắt buộc khi không --serve")

    try:
        device = separate_file(args.input, args.vocals, args.no_vocals,
                               model_name=args.model,
                               force_chunked=args.chunked)
        print(json.dumps({"ok": True, "device": device}), flush=True)
        return 0
    except Exception as e:  # noqa: BLE001 — report everything to the parent
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}),
              flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
