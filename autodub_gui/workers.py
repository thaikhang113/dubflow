"""Background workers: run the pipeline / batch / downloads off the UI thread.

Each worker is a QThread emitting Qt signals; ProgressEvent objects from the
core pipeline are forwarded as-is (they are plain dataclasses, safe across
threads via queued connections). A logging.Handler subclass forwards core log
records into the GUI log panel.
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QRunnable, QThread, Signal

from autodub.config import Settings
from autodub.pipeline import DubPipeline, DubRequest, DubResult
from autodub.progress import PipelineCancelled


# --- Lọc log cho người dùng --------------------------------------------------
# GuiLogHandler chỉ chuyển những gì người dùng cần thấy lên khung Nhật ký.
# Bảng thông báo soạn sẵn nằm trong log_text.py — chỉnh lời ở đó, không ở đây.
# Mọi log kỹ thuật (tên model, đường dẫn, tham số, id...) vẫn ra console và
# tệp log cho người phát triển, không bao giờ lên giao diện.


class GuiLogHandler(logging.Handler):
    """Chuyển log autodub.* lên signal Qt — chỉ những gì người dùng cần."""

    def __init__(self, signal):
        super().__init__()
        self._signal = signal

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from autodub_gui.log_text import notice_for
            import time as _time
            result = notice_for(record.getMessage(), record.levelno)
            if result is None:
                return
            text, level = result
            ts = _time.strftime("%H:%M", _time.localtime(record.created))
            self._signal.emit(f"{ts}  {text}", level)
        except RuntimeError:
            pass  # window closed while a worker was still logging


def attach_gui_logging(signal) -> GuiLogHandler:
    """Attach a GUI handler to the shared 'autodub' logger namespace."""
    handler = GuiLogHandler(signal)
    root = logging.getLogger("autodub")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return handler


def detach_gui_logging(handler: GuiLogHandler) -> None:
    logging.getLogger("autodub").removeHandler(handler)


class DubWorker(QThread):
    """Run one DubPipeline.run() in the background."""

    progress = Signal(object)          # ProgressEvent
    log = Signal(str, int)             # message, levelno
    finished_ok = Signal(object)       # DubResult
    failed = Signal(str)               # error message
    cancelled = Signal()

    def __init__(self, settings: Settings, request: DubRequest, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._request = request
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        handler = attach_gui_logging(self.log)
        try:
            pipeline = DubPipeline(
                self._settings,
                progress=self.progress.emit,
                cancel_event=self._cancel_event,
            )
            result: DubResult = pipeline.run(self._request)
            self.finished_ok.emit(result)
        except PipelineCancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001 — surfaced to the user verbatim
            self.failed.emit(str(e))
        finally:
            detach_gui_logging(handler)


class ExportWorker(QThread):
    """Chốt hold Vox rồi xuất video cho dự án đang chờ (luồng wizard).

    Gọi :func:`autodub.pipeline.export_committed_project`: commit hold (trừ
    Vox theo thực dùng, hoàn phần giữ chỗ thừa), giải mã file trung gian,
    rồi chạy phase Xuất video. Mất mạng ở bước commit → failed, Vox chưa
    trừ, bấm lại là chạy tiếp.
    """

    progress = Signal(object)          # ProgressEvent
    log = Signal(str, int)
    finished_ok = Signal(object)       # DubResult
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, settings: Settings, work_dir: str, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._work_dir = work_dir
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        from autodub.pipeline import export_committed_project

        handler = attach_gui_logging(self.log)
        try:
            result: DubResult = export_committed_project(
                self._work_dir, self._settings,
                progress=self.progress.emit,
                cancel_event=self._cancel_event)
            self.finished_ok.emit(result)
        except PipelineCancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001 — surfaced to the user verbatim
            self.failed.emit(str(e))
        finally:
            detach_gui_logging(handler)


class SaveAllWorker(QThread):
    """Save every edited line, then re-run TTS for the ones that changed.

    One worker for the whole batch: the user edits freely, presses save once,
    and gets a single progress stream instead of per-row round trips.
    """

    log = Signal(str, int)
    seg_done = Signal(int, int, int)          # seg_id, index, total
    finished_ok = Signal(list)                # re-synthesized seg ids
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, settings: Settings, work_dir: str, edits: dict[int, str],
                 target_key: str, voice: str | None, parent=None,
                 force_all: bool = False,
                 force_ids: set[int] | None = None):
        super().__init__(parent)
        self._settings = settings
        self._work_dir = work_dir
        self._edits = edits
        self._target_key = target_key
        self._voice = voice
        self._force_all = force_all
        # Câu chỉ đổi giọng (không sửa chữ) vẫn phải đọc lại — text không đổi
        # nên save_segment_texts không trả về chúng; force_ids bù lại chỗ thiếu đó.
        self._force_ids: set[int] = set(force_ids or [])
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        from autodub.editor import resynth_segments, save_segment_texts
        from autodub.progress import ProgressReporter

        handler = attach_gui_logging(self.log)
        reporter = ProgressReporter(lambda _e: None, self._cancel_event)
        try:
            changed = save_segment_texts(self._work_dir, self._edits, self._target_key)
            # Đổi giọng cho cả video: đọc lại mọi câu, kể cả câu không sửa chữ.
            if self._force_all:
                changed = sorted(self._edits.keys())
            # Câu chỉ đổi giọng mà không sửa chữ: bổ sung vào danh sách cần đọc lại.
            if self._force_ids:
                changed = sorted(set(changed) | self._force_ids)
            if not changed:
                self.finished_ok.emit([])
                return
            resynth_segments(
                self._work_dir, changed, self._settings,
                self._target_key, self._voice, reporter,
                on_progress=lambda done, total, sid:
                    self.seg_done.emit(sid, done, total))
            self.finished_ok.emit(changed)
        except PipelineCancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001 — surfaced to the user verbatim
            self.failed.emit(str(e))
        finally:
            detach_gui_logging(handler)


class RebuildWorker(QThread):
    """Rebuild the final audio + video from edited segments off the UI thread."""

    progress = Signal(object)          # ProgressEvent
    log = Signal(str, int)
    finished_ok = Signal(str)          # dubbed video path
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, settings: Settings, work_dir: str, target_key: str,
                 voice: str | None, bg_mode: str, bg_duck_db: float,
                 subtitle_mode: str | None, blur_regions: list[dict] | None,
                 subtitle_style: dict | None = None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._work_dir = work_dir
        self._target_key = target_key
        self._voice = voice
        self._bg_mode = bg_mode
        self._bg_duck_db = bg_duck_db
        self._subtitle_mode = subtitle_mode
        self._blur_regions = blur_regions
        self._subtitle_style = subtitle_style
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        from autodub.editor import rebuild_output
        from autodub.progress import ProgressReporter

        handler = attach_gui_logging(self.log)
        reporter = ProgressReporter(self.progress.emit, self._cancel_event)
        try:
            out = rebuild_output(
                self._work_dir, self._settings, self._target_key, self._voice,
                self._bg_mode, self._bg_duck_db,
                self._subtitle_mode, self._blur_regions,
                self._subtitle_style, reporter)
            self.finished_ok.emit(out)
        except PipelineCancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
        finally:
            detach_gui_logging(handler)


class SubtitleWorker(QThread):
    """Ghi lại phụ đề vào video mà không đụng tới giọng đọc.

    Đây là đường nhanh cho việc sửa chữ hoặc đổi kiểu chữ: chỉ vẽ lại chữ lên
    hình, dùng lại nguyên bản âm thanh của lần xuất trước.
    """

    progress = Signal(object)
    log = Signal(str, int)
    finished_ok = Signal(str)          # đường dẫn video kết quả
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, settings: Settings, work_dir: str, target_key: str,
                 subtitle_mode: str | None, blur_regions: list[dict] | None,
                 subtitle_style: dict | None = None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._work_dir = work_dir
        self._target_key = target_key
        self._subtitle_mode = subtitle_mode
        self._blur_regions = blur_regions
        self._subtitle_style = subtitle_style
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        from autodub.editor import rebuild_subtitles
        from autodub.progress import ProgressReporter

        handler = attach_gui_logging(self.log)
        reporter = ProgressReporter(self.progress.emit, self._cancel_event)
        try:
            out = rebuild_subtitles(
                self._work_dir, self._settings, self._target_key,
                self._subtitle_mode, self._blur_regions,
                self._subtitle_style, reporter)
            self.finished_ok.emit(out)
        except PipelineCancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
        finally:
            detach_gui_logging(handler)


class SegmentPreviewWorker(QThread):
    """Dựng đoạn xem thử ngắn quanh một câu, không đụng tới video kết quả.

    Chỉ mã hóa vài giây quanh câu đang chọn (ultrafast, 480p) — cho người
    dùng nghe thử giọng + nhạc nền + phụ đề đúng như bản xuất, trước khi
    tốn thời gian xuất cả phim.
    """

    log = Signal(str, int)
    finished_ok = Signal(str)          # đường dẫn mp4 xem thử
    failed = Signal(str)

    def __init__(self, settings: Settings, work_dir: str, seg_id: int,
                 target_key: str, bg_mode: str, bg_duck_db: float,
                 subtitle_mode: str | None, subtitle_style: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self._settings = settings
        self._work_dir = work_dir
        self._seg_id = seg_id
        self._target_key = target_key
        self._bg_mode = bg_mode
        self._bg_duck_db = bg_duck_db
        self._subtitle_mode = subtitle_mode
        self._subtitle_style = subtitle_style
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        from autodub.editor import render_segment_preview

        handler = attach_gui_logging(self.log)
        try:
            out = render_segment_preview(
                self._work_dir, self._settings, self._seg_id,
                self._target_key, self._bg_mode, self._bg_duck_db,
                self._subtitle_mode, self._subtitle_style)
            if not self._cancel_event.is_set():
                self.finished_ok.emit(out)
        except Exception as e:  # noqa: BLE001
            if not self._cancel_event.is_set():
                self.failed.emit(str(e))
        finally:
            detach_gui_logging(handler)


class BatchWorker(QThread):
    """Run a batch of pasted URLs (one per line) in the background."""

    progress = Signal(object)                    # ProgressEvent (current video)
    item_status = Signal(int, int, str, str, str)  # index, total, url, status, detail
    log = Signal(str, int)
    finished_ok = Signal(object)                 # BatchSummary
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, settings: Settings, req_template: DubRequest,
                 items: list, retry_done: bool = False, reuse_tts: bool = True,
                 parent=None):
        super().__init__(parent)
        self._settings = settings
        self._template = req_template
        self._items = items          # list[BatchItem] (or pasted text lines)
        self._retry_done = retry_done
        self._reuse_tts = reuse_tts
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        from autodub.batch import run_batch

        handler = attach_gui_logging(self.log)

        def observer(i, total, item, status, detail):
            self.item_status.emit(i, total, item.key, status, detail)

        synth_cache = None
        demucs_cache = None
        whisper_cache = None
        try:
            if self._reuse_tts:
                from autodub.speech.tts import SynthCache
                synth_cache = SynthCache()
            if len(self._items) > 1:
                # Giữ worker Demucs sống giữa các video — CLI (run_batch) đã
                # làm vậy, nhánh GUI trước đây quên nên nạp lại model mỗi video.
                from autodub.media.vocal_separator import DemucsCache
                demucs_cache = DemucsCache()
                from autodub.speech.transcriber import WhisperCache
                whisper_cache = WhisperCache()
            pipeline = DubPipeline(
                self._settings,
                progress=self.progress.emit,
                cancel_event=self._cancel_event,
                synth_cache=synth_cache,
                demucs_cache=demucs_cache,
                whisper_cache=whisper_cache,
            )
            summary = run_batch(self._items, self._settings, self._template,
                                pipeline=pipeline, observer=observer,
                                retry_done=self._retry_done)
            self.finished_ok.emit(summary)
        except PipelineCancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
        finally:
            if synth_cache is not None:
                synth_cache.close()
            if demucs_cache is not None:
                demucs_cache.close()
            if whisper_cache is not None:
                whisper_cache.close()
            detach_gui_logging(handler)


class ProjectScanWorker(QThread):
    """Quét thư mục kết quả ở luồng nền.

    Việc này đọc rất nhiều tệp nhỏ và tính dung lượng cả cây thư mục, nên
    chạy trên luồng giao diện sẽ làm cửa sổ đứng vài giây khi có nhiều dự án.
    """

    ready = Signal(list)          # list[Project]
    failed = Signal(str)

    def __init__(self, output_dir: str, running_dir: str = "", parent=None):
        super().__init__(parent)
        self._output_dir = output_dir
        self._running_dir = running_dir

    def run(self) -> None:
        from autodub_gui.projects import scan

        try:
            self.ready.emit(scan(self._output_dir, self._running_dir))
        except Exception as e:  # noqa: BLE001 — hiện thành màn hình lỗi
            self.failed.emit(str(e))


class ThumbnailWorker(QRunnable):
    """Tạo một ảnh đại diện bằng ffmpeg, chạy trong nhóm luồng dùng chung."""

    class Signals(QObject):
        ready = Signal(str, str)      # khóa dự án, đường dẫn ảnh

    def __init__(self, project):
        super().__init__()
        self.signals = self.Signals()
        self._project = project
        self.setAutoDelete(True)

    def run(self) -> None:
        from autodub_gui.projects import ensure_thumbnail

        try:
            path = ensure_thumbnail(self._project)
        except Exception:  # noqa: BLE001 — thiếu ảnh thì dùng ô giữ chỗ
            path = ""
        if path:
            self.signals.ready.emit(self._project.key, path)


class WaveformWorker(QThread):
    """Tính dạng sóng ở luồng nền.

    Việc này quét cả tệp âm thanh, với video dài có thể mất vài giây, nên
    không được làm trên luồng giao diện.
    """

    ready = Signal(list)      # danh sách biên độ từ 0 tới 1

    def __init__(self, wav_path: str, buckets: int = 0, parent=None,
                 cache_name: str | None = None):
        super().__init__(parent)
        self._path = wav_path
        self._buckets = buckets
        self._cache_name = cache_name

    def run(self) -> None:
        from autodub_gui.waveform import DEFAULT_BUCKETS, peaks

        try:
            self.ready.emit(peaks(self._path, self._buckets or DEFAULT_BUCKETS,
                                  cache_name=self._cache_name))
        except Exception:  # noqa: BLE001 — không vẽ được thì hiện dải phẳng
            self.ready.emit([])


class PreflightWorker(QThread):
    """Chạy kiểm tra tiền chuyến bay (autodub.preflight) ở luồng nền.

    Kiểm tra chạm đĩa và gọi ffmpeg nên không được làm trên luồng giao diện.
    Kết quả là danh sách CheckResult (dataclass thuần, an toàn qua signal).
    """

    ready = Signal(list)      # list[autodub.preflight.CheckResult]

    def run(self) -> None:
        from autodub.preflight import run_preflight

        try:
            results = run_preflight(Settings.load(override=True))
        except Exception:  # noqa: BLE001 — không được làm sập giao diện
            results = []
        self.ready.emit(results)


class UpdateCheckWorker(QThread):
    """Hỏi GitHub xem có bản VoxDub mới không, chạy ở luồng nền.

    Gọi mạng nên không được chạy trên luồng giao diện. Không có mạng hay kho
    chưa có bản phát hành nào thì im lặng — kiểm tra nền không được làm phiền.
    """

    found = Signal(object)    # autodub.updates.UpdateInfo

    def __init__(self, repo: str, current_version: str, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._current = current_version

    def run(self) -> None:
        from autodub.updates import check_for_update

        try:
            info = check_for_update(self._repo, self._current)
        except Exception:  # noqa: BLE001 — lỗi mạng thì coi như không có bản mới
            return
        if info is not None:
            self.found.emit(info)


class SystemStatusWorker(QThread):
    """Đọc lại tệp cấu hình và kiểm tra ba thứ thiết yếu, chạy ở luồng nền.

    Kiểm tra giọng đọc, dịch tự động và FFmpeg. Việc này chạm vào ổ đĩa nên
    tuyệt đối không được làm trên luồng giao diện.
    """

    ready = Signal(dict)      # {"voice": (chữ, ổn), "translate": ..., "ffmpeg": ...}

    def run(self) -> None:
        import shutil

        result: dict[str, tuple[str, bool | None]] = {}
        try:
            settings = Settings.load(override=True)
            result["voice"] = self._voice_status(settings)
            result["translate"] = self._translate_status(settings)
            ok = bool(shutil.which("ffmpeg"))
            result["ffmpeg"] = ("sẵn sàng" if ok else "chưa cài", ok)
        except Exception as e:  # noqa: BLE001 — không được làm sập giao diện
            result = {"voice": ("không đọc được", False),
                      "translate": ("không đọc được", False),
                      "ffmpeg": (str(e)[:40], False)}
        self.ready.emit(result)

    @staticmethod
    def _voice_status(settings: Settings) -> tuple[str, bool | None]:
        """Có bao nhiêu giọng dùng được — kể cả khi chưa cài VieNeu."""
        try:
            from autodub.speech.tts.voices import catalog
            count = len(catalog(settings))
        except Exception:  # noqa: BLE001 — không được làm sập giao diện
            return ("không đọc được", False)
        if not count:
            return ("chưa có giọng nào", False)
        if not settings.vieneu_configured():
            return (f"{count} giọng CapCut (chưa cài VieNeu)", True)
        return (f"{count} giọng", True)

    @staticmethod
    def _translate_status(settings: Settings) -> tuple[str, bool | None]:
        """Kết nối tới máy chủ dịch, và số Vox còn lại.

        Chạy trong luồng nền của trang Trợ giúp nên được phép gọi mạng; mất
        mạng thì báo đúng như vậy chứ không treo giao diện.
        """
        if not settings.translate_enabled:
            return ("đang tắt", None)
        from autodub.saas_client import SaasError, get_client, is_configured

        if not is_configured():
            return ("chạy thuần trên máy — bước dịch làm tay", True)
        try:
            device = get_client().ensure_session()
        except SaasError as e:
            return (f"chưa kết nối được ({str(e)[:60]})", False)
        if not device.get("creditEnabled", True):
            return ("VoxDub Cloud (đang miễn phí)", True)
        balance = int(device.get("balance", 0))
        return (f"VoxDub Cloud — còn {balance:,} Vox", balance > 0)


class DownloadWorker(QThread):
    """Download a list of URLs (no dubbing)."""

    item_status = Signal(int, int, str, str, str)  # index, total, url, status, detail
    log = Signal(str, int)
    finished_ok = Signal(int, int)                 # success, failed
    failed = Signal(str)                           # whole-run error (e.g. bad output dir)
    cancelled = Signal()

    def __init__(self, urls: list[str], output_dir: str,
                 cookies_from_browser: str | None = None,
                 cookies_file: str | None = None, parent=None):
        super().__init__(parent)
        self._urls = urls
        self._output_dir = output_dir
        self._cookies_browser = cookies_from_browser or None
        self._cookies_file = cookies_file or None
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        from autodub.media.downloader import download_one
        from autodub.utils import ensure_dir

        handler = attach_gui_logging(self.log)
        success = failed = 0
        try:
            ensure_dir(self._output_dir)
            total = len(self._urls)
            for i, url in enumerate(self._urls):
                if self._cancel_event.is_set():
                    self.cancelled.emit()
                    return
                self.item_status.emit(i, total, url, "start", "")
                try:
                    entry = download_one(url, self._output_dir,
                                         self._cookies_browser, self._cookies_file)
                    success += 1
                    self.item_status.emit(i, total, url, "success", entry["filepath"])
                except Exception as e:  # noqa: BLE001 — per-item failure
                    failed += 1
                    self.item_status.emit(i, total, url, "failed", str(e)[:200])
            self.finished_ok.emit(success, failed)
        except Exception as e:  # noqa: BLE001 — e.g. thư mục lưu không tạo được
            self.failed.emit(str(e))
        finally:
            detach_gui_logging(handler)


class TimelineThumbnailWorker(QThread):
    """Grab ~N khung nhỏ từ video bằng ffmpeg, lưu vào data/timeline_thumbs/.

    Trả về danh sách (timestamp_giây, đường_dẫn_ảnh) để TimelineCanvas vẽ.
    Không dùng QMediaPlayer — tránh giành surface phát.
    """

    ready = Signal(list)    # list[tuple[float, str]]
    failed = Signal(str)

    _THUMB_W = 90
    _THUMB_H = 51           # 16:9
    _N_FRAMES = 12
    _THUMB_DIR = "timeline_thumbs"

    def __init__(self, video_path: str, duration_s: float, work_dir: str,
                 parent=None):
        super().__init__(parent)
        self._video = video_path
        self._duration = duration_s
        self._work_dir = work_dir
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Bỏ dở phần khung còn lại — teardown không phải đợi hết 12 lệnh ffmpeg."""
        self._cancel_event.set()

    def run(self) -> None:
        import subprocess

        from autodub.workdir import data_path

        try:
            if not self._video or not __import__("os").path.isfile(self._video):
                return
            dur = max(1.0, self._duration)
            n = self._N_FRAMES
            thumbs_dir = data_path(
                self._work_dir, self._THUMB_DIR, create_dir=True)

            results: list[tuple[float, str]] = []
            for i in range(n):
                if self._cancel_event.is_set():
                    return
                t = dur * (i + 0.5) / n
                dst = __import__("os").path.join(thumbs_dir,
                                                 f"frame_{i:03d}.jpg")
                cmd = [
                    "ffmpeg", "-v", "error",
                    "-ss", f"{t:.3f}", "-i", self._video,
                    "-frames:v", "1", "-q:v", "5",
                    "-vf", f"scale={self._THUMB_W}:{self._THUMB_H}:force_original_aspect_ratio=decrease,"
                           f"pad={self._THUMB_W}:{self._THUMB_H}:(ow-iw)/2:(oh-ih)/2",
                    "-y", dst,
                ]
                flags = (subprocess.CREATE_NO_WINDOW
                         if __import__("os").name == "nt" else 0)
                subprocess.run(cmd, capture_output=True, timeout=10,
                               creationflags=flags)
                if __import__("os").path.isfile(dst):
                    results.append((t, dst))
            if results and not self._cancel_event.is_set():
                self.ready.emit(results)
        except Exception as e:  # noqa: BLE001
            if not self._cancel_event.is_set():
                self.failed.emit(str(e))


class ExportAudioWorker(QThread):
    """Chuyển audio_vi_full.wav thành MP3 bằng ffmpeg rồi lưu ra đường dẫn đã chọn."""

    log = Signal(str, int)
    finished_ok = Signal(str)   # đường dẫn MP3 kết quả
    failed = Signal(str)

    def __init__(self, work_dir: str, output_path: str,
                 bitrate: str = "192k", parent=None):
        super().__init__(parent)
        self._work_dir = work_dir
        self._output_path = output_path
        self._bitrate = bitrate
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        import subprocess

        from autodub.media.audio import wav_duration_s
        from autodub.utils import ffmpeg_timeout_s
        from autodub.workdir import data_path

        handler = attach_gui_logging(self.log)
        try:
            src = data_path(self._work_dir, "audio_vi_full.wav")
            if not __import__("os").path.isfile(src):
                self.failed.emit(
                    "Chưa có tệp audio_vi_full.wav — hãy xuất video ít nhất "
                    "một lần trước khi tải âm thanh riêng.")
                return
            cmd = [
                "ffmpeg", "-y", "-i", src,
                "-b:a", self._bitrate,
                "-map_metadata", "-1",
                self._output_path,
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=ffmpeg_timeout_s(wav_duration_s(src)))
            except subprocess.TimeoutExpired:
                if not self._cancel_event.is_set():
                    self.failed.emit(
                        "ffmpeg treo quá lâu khi chuyển sang MP3 — hãy thử lại.")
                return
            if self._cancel_event.is_set():
                return
            if result.returncode != 0:
                self.failed.emit(
                    f"ffmpeg trả về lỗi:\n{result.stderr[-800:]}")
                return
            self.finished_ok.emit(self._output_path)
        except Exception as e:  # noqa: BLE001
            if not self._cancel_event.is_set():
                self.failed.emit(str(e))
        finally:
            detach_gui_logging(handler)


class PrefetchWorker(QThread):
    """Tải trước một URL về thư mục tạm trong khi người dùng cấu hình các bước 2–4.

    Khi người dùng bấm Tiếp tục ở bước 1 (nguồn URL), worker này tải video về
    ngầm. Đến bước 5 (Phụ đề) file đã sẵn sàng nên StyleDialog lấy được frame
    để xem trước ngay, không phải đợi pipeline chạy.
    """

    finished_ok = Signal(str)   # đường dẫn file vừa tải về
    failed = Signal(str)        # lý do thất bại

    def __init__(self, url: str, output_dir: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._output_dir = output_dir
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        from autodub.media.downloader import download_video
        from autodub.utils import ensure_dir

        try:
            ensure_dir(self._output_dir)
            path = download_video(self._url, self._output_dir)
            if not self._cancel_event.is_set():
                self.finished_ok.emit(path)
        except Exception as e:  # noqa: BLE001
            if not self._cancel_event.is_set():
                self.failed.emit(str(e))


class ExportSubsFileWorker(QThread):
    """Xuất phụ đề ra tệp SRT hoặc ASS độc lập (không ghép vào video)."""

    log = Signal(str, int)
    finished_ok = Signal(str)   # đường dẫn tệp kết quả
    failed = Signal(str)

    def __init__(self, segments: list[dict], work_dir: str,
                 output_path: str, text_field: str,
                 subtitle_style: dict | None,
                 subs_format: str = "srt",   # "srt" | "ass"
                 merge_dir: str | None = None,
                 parent=None):
        super().__init__(parent)
        self._segments = segments
        self._work_dir = work_dir
        self._output_path = output_path
        self._text_field = text_field
        self._style = subtitle_style
        self._format = subs_format
        self._merge_dir = merge_dir
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        handler = attach_gui_logging(self.log)
        try:
            if self._format == "ass":
                from autodub.text.ass_karaoke import build_karaoke_ass
                from autodub.workdir import data_path

                merge_dir = self._merge_dir or data_path(
                    self._work_dir, "segments")
                build_karaoke_ass(
                    self._segments, merge_dir, self._output_path,
                    self._style, text_field=self._text_field,
                    cache_path=data_path(self._work_dir, "align_cache.json"))
            else:
                from autodub.text.srt import generate_srt_styled

                generate_srt_styled(self._segments, self._output_path,
                                    self._text_field, self._style)
            if not self._cancel_event.is_set():
                self.finished_ok.emit(self._output_path)
        except Exception as e:  # noqa: BLE001
            if not self._cancel_event.is_set():
                self.failed.emit(str(e))
        finally:
            detach_gui_logging(handler)
