"""Whisper ASR worker — runs INSIDE the dedicated .venv-whisper virtualenv.

Standalone script: must NOT import anything from ``autodub`` (different env).
Wraps faster-whisper with the same JSON-line protocol used by the Paraformer
worker so ``transcriber.py`` can drive both the same way.

CLI:
    python asr_whisper_worker.py --audio in.wav --model <name|auto>
        [--language zh-CN] [--beam-size 5] [--model-dir models/whisper]
        [--cuda-dll-dir path/to/torch/lib]

stdout protocol (one JSON per line, everything else goes to stderr):
    {"ready": true}
    {"seg": true, "id": 1, "text": "...", "start": 1.02, "end": 4.31,
     "words": [{"word": "...", "start": 1.02, "end": 1.30}]}
    {"done": true, "num_segments": 42, "language": "zh", "language_prob": 0.99}
  | {"error": "..."}   then exit code 1

Design note: The worker loads the model once, prints {"ready": true}, then
reads ONE JSON request from stdin and transcribes. Single-shot like Paraformer
(ASR is one call per pipeline run — persistent pool would be overkill).
"""
import argparse
import json
import os
import sys


def _die(proto_out, msg: str) -> None:
    print(json.dumps({"error": msg}, ensure_ascii=False),
          file=proto_out, flush=True)
    sys.exit(1)


def _resolve_model(model_arg: str, cuda_ok: bool) -> str:
    if model_arg.strip().lower() != "auto":
        return model_arg.strip()
    return "large-v3" if cuda_ok else "medium"


def _try_load_cuda_dlls(dll_dir: str) -> bool:
    """Nạp cuBLAS/cuDNN từ torch lib dir — giống cách transcriber.py làm."""
    if not dll_dir or not os.path.isdir(dll_dir):
        return False
    import ctypes
    import glob

    try:
        os.add_dll_directory(dll_dir)
        matches = glob.glob(os.path.join(dll_dir, "cublas64_*.dll"))
        if matches:
            ctypes.CDLL(matches[0])
            return True
    except OSError:
        pass
    return False


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    proto_out = sys.stdout
    sys.stdout = sys.stderr   # thư viện in ra stderr, không lẫn vào JSON

    parser = argparse.ArgumentParser()
    parser.add_argument("--audio",      required=True)
    parser.add_argument("--model",      default="auto")
    parser.add_argument("--language",   default="")
    parser.add_argument("--beam-size",  type=int, default=5)
    parser.add_argument("--model-dir",  default="",
                        help="Thư mục cache model; rỗng = HuggingFace default")
    parser.add_argument("--cuda-dll-dir", default="",
                        help="Thư mục torch/lib chứa cublas64_*.dll (Windows)")
    args = parser.parse_args()

    # --- Thử GPU ---
    cuda_ok = False
    if os.name == "nt" and args.cuda_dll_dir:
        cuda_ok = _try_load_cuda_dlls(args.cuda_dll_dir)

    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        _die(proto_out, f"faster-whisper chưa cài trong .venv-whisper: {e}")

    model_name = _resolve_model(args.model, cuda_ok)
    download_root = args.model_dir if args.model_dir else None

    try:
        if cuda_ok:
            model = None
            # float16 trước: nhanh nhất trên CUDA. int8 chỉ là lưới an toàn
            # cho card thiếu VRAM.
            for compute in ("float16", "int8_float16", "int8"):
                try:
                    model = WhisperModel(model_name, device="cuda",
                                         compute_type=compute,
                                         download_root=download_root)
                    print(f"Whisper '{model_name}' trên GPU "
                          f"(CUDA, {compute})", flush=True)
                    break
                except Exception as e:
                    print(f"GPU {compute} thất bại ({e})", flush=True)
            if model is None:
                print("GPU không dùng được, chuyển sang CPU", flush=True)
                cuda_ok = False
                model_name = _resolve_model("auto", False)
                model = WhisperModel(model_name, device="cpu",
                                     compute_type="int8",
                                     download_root=download_root)
        else:
            model = WhisperModel(model_name, device="cpu",
                                 compute_type="int8",
                                 download_root=download_root)
            print(f"Whisper '{model_name}' trên CPU", flush=True)
    except Exception as e:
        _die(proto_out, f"Không nạp được model Whisper '{model_name}': {e}")

    # Model sẵn sàng
    print(json.dumps({"ready": True}), file=proto_out, flush=True)

    # Đọc request từ stdin
    try:
        raw = sys.stdin.readline()
    except (EOFError, OSError):
        _die(proto_out, "stdin đóng trước khi nhận request")

    try:
        req = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        _die(proto_out, f"Request JSON không hợp lệ: {e}")

    audio_path = req.get("audio") or args.audio
    language   = req.get("language") or args.language or None
    beam_size  = req.get("beam_size", args.beam_size)

    # Normalize language: "zh-CN" → "zh"
    if language:
        language = language.split("-")[0].lower()
        if language == "auto":
            language = None

    try:
        raw_segments, info = model.transcribe(
            audio_path,
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            word_timestamps=True,
        )
    except Exception as e:
        _die(proto_out, f"Lỗi khi nhận dạng: {e}")

    detected_lang = getattr(info, "language", "") or ""
    detected_prob = getattr(info, "language_probability", 0.0)
    if not language and detected_lang:
        print(f"Ngôn ngữ tự nhận: {detected_lang} ({detected_prob:.0%})",
              flush=True)

    seg_id = 0
    for seg in raw_segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        seg_id += 1
        words = []
        for w in (getattr(seg, "words", None) or []):
            words.append({"word": w.word,
                          "start": round(w.start, 3),
                          "end":   round(w.end, 3)})
        out = {
            "seg":   True,
            "id":    seg_id,
            "text":  text,
            "start": round(seg.start, 3),
            "end":   round(seg.end, 3),
            "words": words,
        }
        print(json.dumps(out, ensure_ascii=False), file=proto_out, flush=True)

    print(json.dumps({
        "done":         True,
        "num_segments": seg_id,
        "language":     detected_lang,
        "language_prob": round(detected_prob, 3),
    }), file=proto_out, flush=True)


if __name__ == "__main__":
    main()
