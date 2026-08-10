"""Vietnamese TTS via VieNeu-TTS v3-Turbo (free, local, CPU — no GPU needed).

The model runs in its own virtualenv (``.venv-vieneu``, created by
``scripts/setup_vieneu.py``) inside persistent worker subprocesses
(:mod:`autodub.speech.tts.vieneu_worker`): each worker loads the ONNX model
once per run, then serves segments as JSON requests over stdio. Preset
voices (7 male + 7 female, three regions) — no reference audio needed.

Because inference is CPU-only, N workers genuinely scale N× and the GPU
stays free for Whisper/Demucs. Duration
fitting uses a post-render ffmpeg atempo pass — the model has no render-speed
parameter.
"""
import atexit
import collections
import json
import os
import queue
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

from autodub.config import Settings
from autodub.resources import cpu_share
from autodub.speech.tts.base import TTSResult, write_silence
from autodub.utils import bundled_file, setup_logging

logger = setup_logging("autodub.tts.vieneu")

# First request loads the model + warm-up render; later segments are ~1s each.
STARTUP_TIMEOUT = 600
SYNTH_TIMEOUT = 300

_WORKER_SCRIPT = bundled_file("autodub", "speech", "tts", "vieneu_worker.py")


class _VieNeuWorker:
    """One persistent vieneu_worker.py subprocess.

    Not thread-safe by itself — the pool's free-queue guarantees at most one
    thread talks to a worker at a time.
    """

    def __init__(self, owner: "VieNeuSynthesizer", idx: int):
        self._owner = owner
        self._idx = idx
        self._proc: subprocess.Popen | None = None
        self._restarted = False
        # Last stderr lines of the worker — the only diagnostics when it
        # dies. A daemon thread drains the pipe so it can never fill up.
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=30)
        # A4 fix: persistent reader queue instead of a new thread per response.
        # Initialized empty; _start() creates a new queue and reader thread.
        self._resp_queue: queue.Queue[str | None] = queue.Queue()

    def _drain_stderr(self, stream) -> None:
        try:
            for line in stream:
                line = line.rstrip()
                if line:
                    self._stderr_tail.append(line)
        except (ValueError, OSError):
            pass  # stream closed

    def _tail(self) -> str:
        return "\n".join(list(self._stderr_tail)[-10:])

    # --- lifecycle --------------------------------------------------------

    def _pump_stdout(self, stream) -> None:
        """Persistent reader thread — pumps JSON lines into _resp_queue.

        Putting None signals that the stream closed (process died).
        A4 fix: one long-lived thread instead of a new thread per response.
        """
        try:
            for raw in stream:
                raw = raw.rstrip()
                if not raw:
                    continue
                if raw.lstrip().startswith("{"):
                    self._resp_queue.put(raw)
                # else: skip non-JSON diagnostic lines the worker may emit
        except (ValueError, OSError):
            pass
        finally:
            self._resp_queue.put(None)   # sentinel: stream closed

    def _start(self) -> None:
        settings = self._owner.settings
        cmd = [
            settings.vieneu_venv_python_path(),
            _WORKER_SCRIPT,
            "--voice", self._owner.voice_name,
            "--style", settings.vieneu_style,
            "--model-dir", settings.vieneu_model_dir_path(),
            "--custom-voices", settings.vieneu_custom_voices_path(),
            "--intra-threads", str(self._owner.intra_threads),
        ]
        logger.info(f"[worker {self._idx}] Starting VieNeu worker "
                    f"(voice: {self._owner.voice_name})...")
        # stderr=PIPE + drain thread (xem f5_vi.py — cùng lý do).
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )
        # Reset the response queue — each (re)start gets a clean queue so
        # stale sentinels from a previous dead process don't confuse us.
        self._resp_queue = queue.Queue()
        threading.Thread(target=self._drain_stderr,
                         args=(self._proc.stderr,), daemon=True).start()
        threading.Thread(target=self._pump_stdout,
                         args=(self._proc.stdout,), daemon=True,
                         name=f"vieneu-stdout-{self._idx}").start()
        ready = self._read_response(STARTUP_TIMEOUT)
        if not ready.get("ready"):
            raise RuntimeError(
                f"VieNeu worker failed to start: {ready}\n{self._tail()}")
        logger.info(f"[worker {self._idx}] VieNeu worker ready")

    def ensure(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            # One model load at a time keeps peak RAM sane on small machines.
            with self._owner._start_lock:
                if self._proc is None or self._proc.poll() is not None:
                    self._start()

    def close(self) -> None:
        """Terminate the worker subprocess (idempotent)."""
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
            for s in (p.stdin, p.stdout, p.stderr):
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        pass

    def _read_response(self, timeout: float) -> dict:
        """Read the next JSON line from the persistent stdout reader queue.

        A4 fix: no new thread per call — the persistent _pump_stdout thread
        puts lines into _resp_queue; we just block here with a timeout.
        None in the queue means the stream closed (worker died).
        """
        try:
            line = self._resp_queue.get(timeout=timeout)
        except queue.Empty:
            if self._proc is not None:
                self._proc.kill()
            raise RuntimeError(
                f"VieNeu worker timed out after {timeout}s\n{self._tail()}")
        if line is None:
            raise RuntimeError(
                f"VieNeu worker stream closed unexpectedly\n{self._tail()}")
        return json.loads(line)

    # --- synthesis --------------------------------------------------------

    def render(self, text: str, output_path: str) -> float:
        """Render text to WAV and return the actual duration in seconds.

        The worker reports duration in its JSON response — we use that
        directly instead of re-reading the WAV file with pydub (A1 fix).
        """
        self.ensure()
        req = {"text": text, "out": output_path}
        try:
            self._proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
            resp = self._read_response(SYNTH_TIMEOUT)
        except (OSError, RuntimeError) as e:
            # Worker died — restart once per incident, then give up. The flag
            # resets after a success so one transient blip early in a long
            # run doesn't disable recovery for the rest of it.
            if self._restarted:
                raise
            logger.warning(f"[worker {self._idx}] VieNeu worker error ({e}) "
                           "— restarting once...")
            self._restarted = True
            self.close()
            return self.render(text, output_path)
        if not resp.get("ok"):
            raise RuntimeError(f"VieNeu synthesis failed: {resp.get('error')}")
        self._restarted = False
        return float(resp.get("duration", 0.0))


class VieNeuSynthesizer:
    """VieNeu preset-voice synthesizer for Vietnamese dub segments."""

    def __init__(self, settings: Settings, voice_name: str,
                 num_workers: int = 1):
        self.settings = settings
        self.voice_name = voice_name
        n = max(1, num_workers)
        # Partition CPU cores across workers so N ONNX sessions don't fight
        # over every core (oversubscription is a net loss). cpu_share chừa
        # thêm vài lõi cho GUI và cho các slot ffmpeg — TTS không chạy một
        # mình trên máy.
        self.intra_threads = cpu_share(n)
        self._start_lock = threading.Lock()
        # Guards _workers/_free against concurrent mutation (warm-up thread
        # dropping a failed worker vs. dispatch threads pulling from _free).
        self._pool_lock = threading.Lock()
        self._workers = [_VieNeuWorker(self, i) for i in range(n)]
        self._free: queue.Queue[_VieNeuWorker] = queue.Queue()
        for w in self._workers:
            self._free.put(w)
        atexit.register(self.close)

    # --- worker lifecycle -------------------------------------------------

    @property
    def recommended_threads(self) -> int:
        """Dispatch threads the pipeline should use — one per worker."""
        with self._pool_lock:
            return max(1, len(self._workers))

    def warm_up_async(self) -> None:
        """Khởi động tất cả worker song song trong một background thread.

        CPU-only — không tranh VRAM với Whisper/Demucs, nên pipeline có thể
        gọi sớm mà không cần chờ Demucs xong. Worker nào khởi động lỗi sẽ bị
        loại; run tiếp tục với ít luồng hơn thay vì dừng hẳn.

        A2 fix: dùng ThreadPoolExecutor để load tất cả worker song song thay
        vì tuần tự — 3 worker × 30-60s → giảm từ ~3 phút xuống ~1 phút.
        """
        def _warm_one(w: _VieNeuWorker) -> None:
            try:
                w.ensure()
            except Exception as e:
                if w._idx == 0:
                    logger.warning(
                        f"Không khởi động sớm được VieNeu ({e}) — "
                        "sẽ thử lại ở bước tạo giọng")
                else:
                    logger.warning(
                        f"[worker {w._idx}] Không khởi động được ({e}) — "
                        "chạy tiếp với ít luồng hơn")
                    self._drop_worker(w)

        def _warm() -> None:
            workers = list(self._workers)
            with ThreadPoolExecutor(max_workers=len(workers),
                                    thread_name_prefix="vieneu-warm") as ex:
                # submit tất cả rồi chờ — lỗi được bắt trong _warm_one
                list(ex.map(_warm_one, workers))

        threading.Thread(target=_warm, daemon=True, name="vieneu-warmup").start()

    def _drop_worker(self, w: _VieNeuWorker) -> None:
        """Remove a worker that cannot start (e.g. RAM exhausted)."""
        with self._pool_lock:
            if w in self._workers and len(self._workers) > 1:
                self._workers.remove(w)
            else:
                return
            # Rebuild the free queue without it (it may or may not be
            # queued). Done under the lock so a dispatch thread can't put
            # the dropped worker back between drain and rebuild.
            drained: list[_VieNeuWorker] = []
            try:
                while True:
                    drained.append(self._free.get_nowait())
            except queue.Empty:
                pass
            for x in drained:
                if x is not w:
                    self._free.put(x)
        w.close()

    def close(self) -> None:
        """Terminate all worker subprocesses (idempotent)."""
        # Drop our atexit hook so closed instances (batch/SynthCache churn)
        # don't pile up handlers for the life of the process.
        atexit.unregister(self.close)
        with self._pool_lock:
            workers = list(self._workers)
        for w in workers:
            w.close()

    # --- synthesis --------------------------------------------------------

    def _render(self, text: str, output_path: str) -> float:
        """Render text to WAV via a free worker; returns actual duration (s)."""
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Bounded wait: if the pool ever loses a worker (drop-race, crash),
        # fail loudly instead of hanging the whole run on an empty queue.
        try:
            w = self._free.get(timeout=SYNTH_TIMEOUT + 60)
        except queue.Empty:
            raise RuntimeError(
                "Không còn luồng VieNeu nào rảnh (worker chết hoặc kẹt) — "
                "thử chạy lại; nếu lặp lại, giảm VIENEU_MAX_WORKERS")
        try:
            return w.render(text, output_path)
        finally:
            self._free.put(w)

    def synthesize(
        self,
        text: str,
        output_path: str,
        target_duration: float | None = None,
    ) -> TTSResult:
        """Render at natural pace, always.

        No synth-time compression: the timing knobs are global (VIDEO_SPEED
        slows the picture, VOICE_SPEED is applied to every clip uniformly
        after TTS). ``target_duration`` is accepted for engine-interface
        compatibility and ignored.

        Duration comes directly from the worker response — no extra disk read.
        """
        # Numbers must be spelled out for clean reading. NO lowercasing —
        # VieNeu is trained on cased text (better for brand names).
        from autodub.text.vi_numbers import normalize_vi_text
        text = normalize_vi_text(text.strip())
        if not text.strip(".,!?;: "):
            # Dòng trống (transcript sửa tay) — clip im lặng ngắn thay vì
            # đẩy chuỗi rỗng vào model (crash/treo cả run vì một dòng).
            return write_silence(output_path)

        # A1 fix: duration trả thẳng từ worker JSON, không đọc lại file WAV.
        actual_duration = self._render(text, output_path)

        return TTSResult(
            path=output_path,
            actual_duration=round(actual_duration, 3),
            speed_adjusted=False,
            rate_applied="1.0x",
        )
