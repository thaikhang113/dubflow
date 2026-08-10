"""VieNeu-TTS worker — runs INSIDE the dedicated .venv-vieneu virtualenv.

Standalone script: must not import anything from ``autodub`` (different env).
Loads the VieNeu v3-Turbo model once (ONNX Runtime, CPU — zero VRAM), then
serves synthesis requests over stdio as JSON lines:

    stdin:  {"text": "...", "out": "path/to/seg.wav"}
    stdout: {"ok": true, "duration": 2.31}
          | {"ok": false, "error": "..."}

Prints ``{"ready": true, "backend": "onnx", "voice": "..."}`` once the model
is loaded so the parent process knows startup finished. All logging goes to
stderr — stdout carries only the JSON protocol.

Enroll mode (one-shot, used by the GUI "thêm giọng" button): pass
``--enroll ref.wav --enroll-name "Tên" --enroll-gender male`` to encode the
reference clip into a speaker embedding + reference codes and append it to
the ``--custom-voices`` JSON file, then exit. Enrolled voices load at serve
startup and behave exactly like the built-in presets (no per-sentence cost).
"""
import argparse
import json
import os
import sys


def load_custom_voices(tts, path: str) -> int:
    """Merge enrolled voices from ``path`` into the model's preset table.

    Same shape as the package's voices_v3_turbo.json (speaker_emb + codes,
    precomputed at enroll time) so a custom voice costs nothing extra per
    sentence. Returns the number of voices loaded; a broken/missing file
    never kills the worker — the built-in presets still work.
    """
    import numpy as np
    if not path or not os.path.isfile(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        n = 0
        for name, v in data.get("presets", {}).items():
            emb, codes = v.get("speaker_emb"), v.get("codes")
            if not name or emb is None:
                continue
            tts._preset_voices[name] = {
                "description": v.get("description", ""),
                "gender": v.get("gender", ""),
                "region": v.get("region", ""),
                "style": v.get("style", "tu_nhien"),
                "speaker_emb": np.asarray(emb, dtype=np.float32),
                "codes": (np.asarray(codes, dtype=np.int64)
                          if codes is not None else None),
            }
            n += 1
        return n
    except Exception as e:
        print(f"[vieneu-worker] bỏ qua custom voices hỏng ({e})",
              file=sys.stderr, flush=True)
        return 0


def _kaldi_fbank_numpy(wav, sr: int, n_mels: int = 80):
    """Mean-normalized Kaldi fbank — numpy mirror of the speaker encoder's
    front-end (``torchaudio.compliance.kaldi.fbank``: povey window, preemph
    0.97, remove-DC, snip-edges, 25/10 ms, log-mel, dither 0).

    The vieneu package computes this via torch/torchaudio, which this venv
    deliberately does NOT ship (ONNX-only). Enrollment is the one place that
    needs it, so we redo the ~30 lines of math here instead of dragging a
    ~300 MB torch install into every user's machine. Validated numerically
    against torchaudio (max |diff| ~1e-4 after mean-norm).
    """
    import numpy as np
    win, shift = int(0.025 * sr), int(0.010 * sr)
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    if len(wav) < win:
        raise ValueError("Clip quá ngắn để học giọng (cần ≥ 1 giây).")
    num_frames = 1 + (len(wav) - win) // shift
    idx = np.arange(win)[None, :] + shift * np.arange(num_frames)[:, None]
    frames = wav[idx]
    frames = frames - frames.mean(axis=1, keepdims=True)        # remove DC
    prev = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
    frames = frames - 0.97 * prev                               # preemphasis
    frames = frames * (np.hanning(win).astype(np.float32) ** 0.85)  # povey
    nfft = 1 << (win - 1).bit_length()
    spec = np.abs(np.fft.rfft(frames, n=nfft, axis=1)).astype(np.float32) ** 2

    def mel(f):
        return 1127.0 * np.log(1.0 + np.asarray(f, dtype=np.float64) / 700.0)

    mlow, mhigh = mel(20.0), mel(0.5 * sr)
    delta = (mhigh - mlow) / (n_mels + 1)
    left = mlow + np.arange(n_mels)[:, None] * delta
    m = mel(sr / nfft * np.arange(nfft // 2))[None, :]
    banks = np.maximum(0.0, np.minimum((m - left) / delta,
                                       (left + 2 * delta - m) / delta))
    banks = np.pad(banks, ((0, 0), (0, 1))).astype(np.float32)  # nyquist = 0
    feat = np.log(np.maximum(spec @ banks.T, 1.1920929e-07))
    return feat - feat.mean(axis=0, keepdims=True)              # mean-norm


def _speaker_embed(engine, wav, sr: int):
    """Waveform → 192-d speaker x-vector, without torch.

    Resolves ``speaker_encoder.onnx`` the same way the package does (local
    file/dir, else HF hub — cached under HF_HOME = models/vieneu) and runs
    it on our numpy fbank.
    """
    import numpy as np
    if sr != 16000:
        import soxr
        wav = soxr.resample(np.asarray(wav, dtype=np.float32).reshape(-1),
                            sr, 16000).astype(np.float32)
        sr = 16000
    wav = wav[: 30 * sr]                                        # encoder cap
    feat = _kaldi_fbank_numpy(wav, sr)[None].astype(np.float32)  # (1, T, 80)

    repo = engine.checkpoint_path
    fname = getattr(engine, "speaker_encoder_filename", "speaker_encoder.onnx")
    if os.path.isfile(repo):
        onnx_path = repo
    elif os.path.isdir(repo):
        onnx_path = os.path.join(repo, fname)
    else:
        from huggingface_hub import hf_hub_download
        onnx_path = hf_hub_download(repo, fname)
    import onnxruntime as ort
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    out = sess.run([sess.get_outputs()[0].name],
                   {sess.get_inputs()[0].name: feat})[0]        # (1, 192)
    return out[0].astype(np.float32)


def _encode_one(tts, wav_path: str, style: str, no_denoise: bool,
                meta: dict) -> dict:
    """Mã hóa một đoạn ghi âm thành mục giọng đầy đủ.

    Bám theo engine.prepare_reference() nhưng dùng bộ nhúng không cần torch:
    nạp mono → cắt còn 8 giây → khử ồn → (vector giọng, mã tham chiếu).
    """
    import numpy as np

    engine = tts.engine
    wav, sr = engine._load_mono(wav_path, None)
    wav = wav[: int(8.0 * sr)]
    if not no_denoise and engine.denoiser is not None:
        wav = engine.denoiser.denoise(wav, sr)
        sr = 44100
    speaker_emb = (_speaker_embed(engine, wav, sr)
                   if engine.use_speaker_embedding else None)
    ref_codes = engine._encode_ref_wav(wav, sr)
    return {
        "description": meta.get("description", ""),
        "gender": meta.get("gender", ""),
        "region": meta.get("region", ""),
        "country": meta.get("country") or "vn",
        # "library" = giọng đóng kèm trong thư mục voices/, "custom" = giọng
        # người dùng tự học từ một đoạn ghi âm của riêng họ.
        "source": meta.get("source") or "custom",
        "style": meta.get("style") or style,
        "speaker_emb": ([round(float(x), 6)
                         for x in np.asarray(speaker_emb).reshape(-1)]
                        if speaker_emb is not None else None),
        "codes": (np.asarray(ref_codes, dtype=int).tolist()
                  if ref_codes is not None else None),
    }


def _save_presets(path: str, presets: dict) -> None:
    """Ghi tệp giọng tùy chỉnh theo kiểu ghi nguyên khối."""
    data = {"presets": {}}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("presets", {})
    data["presets"].update(presets)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
    return data


def enroll_voice(tts, args, proto_out) -> None:
    """Chạy một phát: mã hóa ``--enroll`` rồi ghi vào tệp giọng tùy chỉnh."""
    try:
        entry = _encode_one(tts, args.enroll, args.style,
                            args.enroll_no_denoise,
                            {"description": args.enroll_desc,
                             "gender": args.enroll_gender,
                             "region": args.enroll_region,
                             "country": args.enroll_country})
        data = _save_presets(args.custom_voices, {args.enroll_name: entry})
        print(json.dumps({"ok": True, "enrolled": args.enroll_name,
                          "voices": sorted(data["presets"])},
                         ensure_ascii=False),
              file=proto_out, flush=True)
    except Exception as e:
        print(json.dumps({"ok": False,
                          "error": f"{type(e).__name__}: {e}"},
                         ensure_ascii=False),
              file=proto_out, flush=True)
        sys.exit(1)


def enroll_batch(tts, args, proto_out) -> None:
    """Học NHIỀU giọng trong một lần chạy.

    Nạp model đúng một lần rồi mã hóa cả danh sách, nên học 60 giọng nhanh
    hơn hẳn so với gọi 60 lần chế độ một giọng. Tệp danh sách là mảng JSON
    các mục ``{"wav", "name", "gender", "region", "country", "description"}``.
    Một giọng hỏng chỉ bị bỏ qua và được ghi vào phần ``failed``, cả lô vẫn
    chạy tiếp.
    """
    try:
        with open(args.enroll_batch, encoding="utf-8") as f:
            items = json.load(f)
    except Exception as e:
        print(json.dumps({"ok": False,
                          "error": f"Không đọc được danh sách: {e}"},
                         ensure_ascii=False), file=proto_out, flush=True)
        sys.exit(1)

    existing: set = set()
    if os.path.isfile(args.custom_voices):
        try:
            with open(args.custom_voices, encoding="utf-8") as f:
                existing = set(json.load(f).get("presets", {}))
        except Exception:
            existing = set()

    added: dict = {}
    failed: list = []
    skipped = 0
    total = len(items)
    for i, item in enumerate(items, 1):
        name = str(item.get("name", "")).strip()
        wav = item.get("wav", "")
        if not name or not wav:
            failed.append({"name": name or "(không tên)",
                           "error": "thiếu tên hoặc đường dẫn"})
            continue
        if name in existing and not args.enroll_overwrite:
            skipped += 1
            continue
        # Tiến độ ra stderr — stdout chỉ dành cho dòng JSON kết quả.
        print(f"[vieneu-worker] ({i}/{total}) đang học giọng «{name}»",
              file=sys.stderr, flush=True)
        try:
            added[name] = _encode_one(tts, wav, args.style,
                                      args.enroll_no_denoise, item)
        except Exception as e:
            failed.append({"name": name, "error": f"{type(e).__name__}: {e}"})

    if added:
        _save_presets(args.custom_voices, added)
    print(json.dumps({"ok": True, "added": sorted(added),
                      "skipped": skipped, "failed": failed},
                     ensure_ascii=False), file=proto_out, flush=True)


def main() -> None:
    # Vietnamese text over Windows pipes — force UTF-8 on the protocol streams.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Third-party libraries print progress info. Keep the real stdout for the
    # JSON protocol only, and send every other print to stderr.
    proto_out = sys.stdout
    sys.stdout = sys.stderr

    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", default="",
                        help="preset voice name, e.g. 'Phạm Tuyên' "
                             "(required in serve mode)")
    parser.add_argument("--style", default="tu_nhien",
                        choices=("tu_nhien", "tin_tuc", "doc_truyen"))
    parser.add_argument("--model-dir", required=True,
                        help="HF cache dir holding the downloaded model")
    parser.add_argument("--intra-threads", type=int, default=0,
                        help="ONNX intra-op threads (0 = library default). "
                             "Set to cores//num_workers when several workers "
                             "share the CPU.")
    parser.add_argument("--custom-voices", default="",
                        help="JSON file with user-enrolled voices "
                             "(models/vieneu/custom_voices.json)")
    parser.add_argument("--enroll", default="",
                        help="enroll mode: path to reference wav; encodes the "
                             "voice into --custom-voices then exits")
    parser.add_argument("--enroll-name", default="",
                        help="display name of the enrolled voice")
    parser.add_argument("--enroll-gender", default="",
                        choices=("", "male", "female"))
    parser.add_argument("--enroll-region", default="",
                        choices=("", "bac", "trung", "nam"),
                        help="vùng miền của giọng, dùng để lọc trong app")
    parser.add_argument("--enroll-country", default="vn",
                        help="mã quốc gia của giọng (vn, us, ...)")
    parser.add_argument("--enroll-desc", default="")
    parser.add_argument("--enroll-no-denoise", action="store_true",
                        help="skip the denoise pass (clip is already clean)")
    parser.add_argument("--enroll-batch", default="",
                        help="học hàng loạt: tệp JSON là mảng các mục "
                             "{wav, name, gender, region, country}")
    parser.add_argument("--enroll-overwrite", action="store_true",
                        help="học lại cả những giọng đã có trong tệp")
    args = parser.parse_args()

    enrolling = bool(args.enroll or args.enroll_batch)
    if args.enroll and (not args.enroll_name or not args.custom_voices):
        print(json.dumps({"ok": False,
                          "error": "--enroll cần --enroll-name và "
                                   "--custom-voices"}),
              file=proto_out, flush=True)
        sys.exit(2)
    if args.enroll_batch and not args.custom_voices:
        print(json.dumps({"ok": False,
                          "error": "--enroll-batch cần --custom-voices"}),
              file=proto_out, flush=True)
        sys.exit(2)
    if not enrolling and not args.voice:
        print(json.dumps({"ok": False, "error": "--voice là bắt buộc"}),
              file=proto_out, flush=True)
        sys.exit(2)

    # Self-contained model location + no oversubscription when N workers run.
    os.environ["HF_HOME"] = args.model_dir
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if args.intra_threads > 0:
        os.environ["OMP_NUM_THREADS"] = str(args.intra_threads)
        os.environ["ORT_INTRA_OP_NUM_THREADS"] = str(args.intra_threads)

    try:
        from vieneu import Vieneu
        tts = Vieneu(backend="onnx")
        if args.enroll_batch:
            enroll_batch(tts, args, proto_out)
            return
        if args.enroll:
            enroll_voice(tts, args, proto_out)
            return
        n_custom = load_custom_voices(tts, args.custom_voices)
        if n_custom:
            print(f"[vieneu-worker] nạp {n_custom} giọng tùy chỉnh",
                  file=sys.stderr, flush=True)
        known = [name for _, name in tts.list_preset_voices()]
        if args.voice not in known:
            print(json.dumps({"ready": False,
                              "error": f"unknown voice '{args.voice}'; "
                                       f"valid: {', '.join(known)}"}),
                  file=proto_out, flush=True)
            return
        # Warm-up render: first inference pays for session init — burn it on
        # a throw-away sentence, not the first real segment.
        tts.infer("xin chào các bạn", voice=args.voice, style=args.style)
    except Exception as e:
        print(json.dumps({"ready": False,
                          "error": f"{type(e).__name__}: {e}"}),
              file=proto_out, flush=True)
        return

    print(json.dumps({"ready": True, "backend": "onnx", "voice": args.voice}),
          file=proto_out, flush=True)

    import numpy as np
    import soundfile as sf

    def trim_edges(audio, threshold=1e-3, keep_s=0.05):
        """Cut leading/trailing silence, keeping a small natural pad.

        VieNeu pads its output with silence — dub segments must be tight or
        every line runs long and gets tempo-compressed to fit the timeline.
        """
        # np.argmax trên mask 2-D trả flat index → cắt sai trục âm thầm.
        audio = np.asarray(audio).reshape(-1)
        mask = np.abs(audio) > threshold
        if not mask.any():
            return audio
        keep = int(keep_s * tts.sample_rate)
        start = max(0, int(np.argmax(mask)) - keep)
        end = min(len(audio), len(audio) - int(np.argmax(mask[::-1])) + keep)
        return audio[start:end]

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            audio = tts.infer(req["text"], voice=args.voice, style=args.style,
                              silence_p=0.0)
            audio = trim_edges(audio)
            sf.write(req["out"], audio, tts.sample_rate)
            print(json.dumps({"ok": True,
                              "duration": round(len(audio) / tts.sample_rate, 3)}),
                  file=proto_out, flush=True)
        except Exception as e:  # report and keep serving
            print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}),
                  file=proto_out, flush=True)


if __name__ == "__main__":
    main()
