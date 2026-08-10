"""Source-separation step for the dubbing pipeline.

Splits ``original_audio.wav`` into ``vocals.wav`` (the original speaker) and
``no_vocals.wav`` (everything else: music, SFX, ambient). The pipeline mixes
``no_vocals.wav`` with the synthesised TTS so dubbed videos retain their
original soundtrack.

Việc tách chạy nhanh nhất trong một tiến trình con của venv có torch bản
CUDA (``.venv-gpu``) — nhanh khoảng 10 lần so với CPU. Không có venv đó thì
Demucs chạy ngay trong tiến trình chính trên CPU, qua API Python chứ không
qua lệnh ``demucs.separate``, để không bao giờ chạm vào ``torchaudio.save``:
đường đó cần ``torchcodec`` từ torchaudio 2.10 trở lên, mà bản Windows của
nó lại phụ thuộc đúng một phiên bản FFmpeg. Ở đây ghi tệp bằng ``soundfile``.
"""
import json
import os
import subprocess
import threading

from autodub.resources import GPU_LOCK
from autodub.utils import (
    bundled_file,
    ffmpeg_timeout_s,
    gpu_venv_dir,
    setup_logging,
)

logger = setup_logging("autodub.vocal_separator")

DEFAULT_MODEL = "htdemucs"

_WORKER_SCRIPT = bundled_file("autodub", "media", "demucs_worker.py")

#: Trần thời gian một video trong worker bền — như đường one-shot.
_SEPARATE_TIMEOUT = 3600


class DemucsCache:
    """Một tiến trình demucs_worker ``--serve`` sống suốt lô video.

    Model chỉ nạp MỘT lần cho cả lô (đường cũ nạp lại mỗi video, mất
    15–40 s). Sau mỗi video, worker tự đẩy model về CPU và trả VRAM để
    Whisper của video đó được trọn card đồ họa. Worker chết hay không có
    venv GPU thì :func:`separate_vocals` tự rơi về đường cũ — cache này
    chỉ là tối ưu, không bao giờ là điểm chết.
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._failed = False        # worker chết một lần → thôi, dùng đường cũ
        self._lock = threading.Lock()

    def _ensure(self) -> bool:
        """Khởi động worker nếu chưa chạy; False khi không dùng được."""
        if self._failed:
            return False
        if self._proc is not None and self._proc.poll() is None:
            return True
        python = gpu_venv_python()
        if not python:
            self._failed = True
            return False
        from autodub.sysinfo import available_ram_gb
        avail = available_ram_gb()
        if avail is not None and avail < 6.0:
            # Máy ít RAM: giữ worker + model thường trực chỉ làm chật thêm.
            self._failed = True
            return False
        try:
            self._proc = subprocess.Popen(
                [python, _WORKER_SCRIPT, "--serve"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace")
            ready = json.loads(self._read_line(_SEPARATE_TIMEOUT))
        except Exception as e:
            logger.warning(f"Demucs cache không khởi động được ({e}) — "
                           "mỗi video sẽ tự nạp model như cũ")
            self._shutdown()
            self._failed = True
            return False
        if not ready.get("ready"):
            logger.warning(f"Demucs cache từ chối chạy ({ready.get('error')})")
            self._shutdown()
            self._failed = True
            return False
        logger.info(f"Demucs cache sẵn sàng trên {ready.get('device')} — "
                    "model dùng chung cho cả lô")
        return True

    def _read_line(self, timeout: float) -> str:
        """Đọc một dòng stdout với thời hạn (thread — Windows không select được pipe).

        Hết hạn thì GIẾT tiến trình con trước khi ném lỗi: không làm vậy,
        ``readline()`` nằm chặn mãi và thread đọc sống tới hết phiên, ghim theo
        cả handle pipe. Mọi caller đều coi timeout là cache chết hẳn
        (``_shutdown()`` + ``_failed = True``) nên giết ở đây không mất gì.
        """
        result: list[str] = []

        def _read() -> None:
            result.append(self._proc.stdout.readline())

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or not result or not result[0]:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.kill()
                except OSError:
                    pass
                t.join(2.0)
            raise RuntimeError("Demucs serve worker timed out or died")
        return result[0]

    def separate(self, input_wav: str, vocals_out: str, no_vocals_out: str,
                 chunked: bool) -> bool:
        """Tách một video qua worker bền. False → caller dùng đường cũ."""
        with self._lock:
            if not self._ensure():
                return False
            req = {"input": os.path.abspath(input_wav),
                   "vocals": os.path.abspath(vocals_out),
                   "no_vocals": os.path.abspath(no_vocals_out),
                   "chunked": chunked}
            try:
                self._proc.stdin.write(json.dumps(req) + "\n")
                self._proc.stdin.flush()
                resp = json.loads(self._read_line(_SEPARATE_TIMEOUT))
            except Exception as e:
                logger.warning(f"Demucs cache chết giữa chừng ({e}) — "
                               "video này tách theo đường thường")
                self._shutdown()
                self._failed = True
                return False
            if not resp.get("ok"):
                logger.warning(f"Demucs cache lỗi ({resp.get('error')}) — "
                               "video này tách theo đường thường")
                return False
            logger.info(f"Demucs separation done on {resp.get('device')} "
                        "(model dùng lại từ cache)")
            return True

    def _shutdown(self) -> None:
        p, self._proc = self._proc, None
        if p is None:
            return
        try:
            if p.poll() is None:
                p.stdin.close()
                p.wait(timeout=10)
        except Exception:
            p.kill()
        finally:
            for s in (p.stdin, p.stdout):
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        pass

    def close(self) -> None:
        with self._lock:
            self._shutdown()


def separate_vocals(
    input_wav: str,
    output_dir: str,
    model: str = DEFAULT_MODEL,
    sample_rate: int = 16000,
    channels: int = 1,
    demucs_cache: "DemucsCache | None" = None,
) -> dict[str, str | None]:
    """Run Demucs two-stem separation on ``input_wav``.

    Writes ``<output_dir>/vocals.wav`` and ``<output_dir>/no_vocals.wav``,
    re-encoded to ``sample_rate``/``channels``. The HQ path hands in the
    44.1 kHz stereo extract and keeps that layout, so the background track
    retains its full bandwidth into the final mix; the legacy path keeps the
    old 16 kHz mono behaviour. ``demucs_cache`` (batch runs) reuses one
    loaded model across videos; when absent or broken the one-shot paths run.

    Returns ``{"vocals": path, "no_vocals": path}`` on success, or both ``None``
    on failure (caller falls back to silent-base merge). If both output files
    already exist the function short-circuits — useful when resuming a
    partially-run work directory.
    """
    vocals_out = os.path.join(output_dir, "vocals.wav")
    no_vocals_out = os.path.join(output_dir, "no_vocals.wav")

    if (os.path.exists(no_vocals_out) and os.path.getsize(no_vocals_out) > 0
            and os.path.exists(vocals_out) and os.path.getsize(vocals_out) > 0):
        logger.info(f"Reusing existing separation: {no_vocals_out}")
        return {"vocals": vocals_out, "no_vocals": no_vocals_out}

    if not os.path.exists(input_wav):
        logger.error(f"Input audio not found: {input_wav}")
        return {"vocals": None, "no_vocals": None}

    raw_vocals = os.path.join(output_dir, "_vocals_raw.wav")
    raw_no_vocals = os.path.join(output_dir, "_no_vocals_raw.wav")

    try:
        done = (demucs_cache is not None
                and demucs_cache.separate(input_wav, raw_vocals,
                                          raw_no_vocals, _low_ram()))
        if not done and not _run_demucs_gpu_worker(
                input_wav, raw_vocals, raw_no_vocals, model):
            _run_demucs(input_wav, raw_vocals, raw_no_vocals, model)
    except Exception as exc:
        logger.warning(f"Demucs separation failed: {exc}; falling back to silent base.")
        for path in (raw_vocals, raw_no_vocals):
            if os.path.exists(path):
                os.remove(path)
        return {"vocals": None, "no_vocals": None}

    sample_rate_str = str(sample_rate)
    try:
        _normalize(raw_vocals, vocals_out, sample_rate_str, channels)
        _normalize(raw_no_vocals, no_vocals_out, sample_rate_str, channels)
    except RuntimeError as exc:
        logger.warning(f"Post-processing Demucs output failed: {exc}")
        for path in (vocals_out, no_vocals_out):
            if os.path.exists(path):
                os.remove(path)
        return {"vocals": None, "no_vocals": None}
    except BaseException:
        # Cancel/crash giữa lúc ghi: file cắt cụt mà còn nằm lại sẽ được
        # lần resume sau tin dùng (short-circuit chỉ check size > 0) →
        # nhạc nền hỏng âm thầm. Xóa rồi mới re-raise.
        for path in (vocals_out, no_vocals_out):
            if os.path.exists(path):
                os.remove(path)
        raise
    finally:
        for path in (raw_vocals, raw_no_vocals):
            if os.path.exists(path):
                os.remove(path)

    logger.info(f"Vocal separation complete: {no_vocals_out}")
    return {"vocals": vocals_out, "no_vocals": no_vocals_out}


def gpu_venv_python() -> str:
    """Trình thông dịch của venv có torch bản CUDA, hoặc chuỗi rỗng.

    ``DEMUCS_VENV_PYTHON`` trong .env ghi đè, cho ai muốn trỏ tới venv khác.
    """
    override = os.environ.get("DEMUCS_VENV_PYTHON", "").strip()
    if override:
        return override if os.path.isfile(override) else ""
    venv = gpu_venv_dir()
    if not venv:
        return ""
    exe = os.path.join(venv, "Scripts" if os.name == "nt" else "bin",
                       "python.exe" if os.name == "nt" else "python")
    return exe if os.path.isfile(exe) else ""


def _low_ram() -> bool:
    """Máy còn ít RAM trống — ép Demucs tách theo khúc dù video ngắn."""
    from autodub.sysinfo import available_ram_gb

    avail = available_ram_gb()
    return avail is not None and avail < 6.0


def _run_demucs_gpu_worker(
    input_wav: str, vocals_out: str, no_vocals_out: str, model_name: str
) -> bool:
    """Thử tách bằng tiến trình con chạy trên card đồ họa.

    Trả về False để quay về đường CPU trong tiến trình chính (không có venv,
    venv đó chưa cài demucs, hoặc tiến trình con chết).
    """
    python = gpu_venv_python()
    if not python:
        return False

    cmd = [python, _WORKER_SCRIPT,
           "--input", os.path.abspath(input_wav),
           "--vocals", os.path.abspath(vocals_out),
           "--no-vocals", os.path.abspath(no_vocals_out),
           "--model", model_name]
    if _low_ram():
        cmd.append("--chunked")
    logger.info(f"Running Demucs ({model_name}) in GPU worker on {input_wav}")
    try:
        # GPU_LOCK: pipeline đã *dự đoán* ASR không dùng GPU trước khi cho hai
        # việc chạy song song. Lock là lưới an toàn cho lúc dự đoán sai — khi
        # đó hai việc chạy lần lượt (chậm) chứ không CUDA OOM (mất cả lượt).
        # timeout: video 1-2h hợp lệ mất nhiều phút, nhưng CUDA init treo
        # hoặc tải model kẹt thì không được khóa pipeline vĩnh viễn.
        with GPU_LOCK:
            result = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                                    errors="replace", timeout=3600)
    except subprocess.TimeoutExpired:
        logger.warning("Demucs GPU worker quá 60 phút — chuyển sang CPU")
        return False
    try:
        resp = json.loads((result.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        resp = {"ok": False, "error": (result.stderr or "no output")[-200:]}
    if not resp.get("ok"):
        logger.warning(
            f"Demucs GPU worker failed ({resp.get('error')}) — dùng CPU")
        return False
    logger.info(f"Demucs separation done on {resp.get('device')}")
    return True


def _run_demucs(input_wav: str, vocals_out: str, no_vocals_out: str, model_name: str) -> None:
    """Run Demucs via its Python API; write stems with soundfile.

    Dùng chung :func:`autodub.media.demucs_worker.separate_file` với tiến
    trình con GPU — một chỗ logic duy nhất: đọc float32, denormalize tại
    chỗ, và tự chuyển sang tách theo khúc khi video dài / máy ít RAM.
    """
    from autodub.media.demucs_worker import separate_file

    logger.info(f"Loading Demucs model: {model_name}")
    logger.info(f"Running Demucs ({model_name}) on {input_wav}")
    separate_file(input_wav, vocals_out, no_vocals_out,
                  model_name=model_name, device="cpu",
                  force_chunked=_low_ram())


def _normalize(src: str, dst: str, sample_rate: str, channels: int = 1) -> None:
    """Re-encode raw stem to PCM at the pipeline's rate/channel layout.

    ``timeout`` là bắt buộc theo quy ước ở :func:`autodub.utils.ffmpeg_timeout_s`:
    không có nó thì một ffmpeg kẹt (file bị khóa trên Windows, codec lỗi) treo cả
    pipeline vĩnh viễn và không hủy được.
    """
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-ac", str(channels),
        "-ar", sample_rate,
        "-acodec", "pcm_s16le",
        dst,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace",
            timeout=ffmpeg_timeout_s(_probe_duration_s(src)),
        )
    except subprocess.TimeoutExpired as exc:
        # Cùng dạng lỗi với nhánh thất bại bên dưới nên caller ở :204 vẫn rơi
        # đúng vào fallback "nền im lặng".
        raise RuntimeError(f"ffmpeg normalize timed out for {src}") from exc
    if result.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
        tail = (result.stderr or "")[-300:].strip()
        raise RuntimeError(f"ffmpeg normalize failed for {src}: {tail}")


def _probe_duration_s(path: str) -> float | None:
    """Thời lượng file, hoặc None nếu không đọc được (trần 1 giờ được dùng)."""
    try:
        from autodub.media.audio import wav_duration_s

        return wav_duration_s(path)
    except Exception:  # noqa: BLE001 — chỉ để tính timeout, không đáng làm hỏng
        return None
