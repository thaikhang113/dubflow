"""Batch dubbing: process a list of videos typed one per line, with crash-safe
status tracking.

The user pastes URLs — one per line — and the batch runner does the rest. An
optional voice name may follow the URL after ``|``, ``,`` or a tab::

    https://youtu.be/aaa
    https://youtu.be/bbb | Trúc Ly
    https://youtu.be/ccc | Phạm Tuyên

Progress is persisted to ``batch_state.json`` inside the output directory after
every video, so an interrupted batch can be resumed by pasting the same list
again: videos already marked ``success`` are skipped automatically.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from typing import Callable, Iterable

from autodub.config import Settings
from autodub.pipeline import DubPipeline, DubRequest
from autodub.progress import PipelineCancelled
from autodub.utils import save_json_atomic, setup_logging

logger = setup_logging("autodub.batch")

STATE_FILENAME = "batch_state.json"

# Tách một dòng thành liên kết + TÊN GIỌNG tùy chọn. Chỉ tách ở các dấu rõ
# ràng (| , ; tab, hoặc từ hai khoảng trắng trở lên) vì tên giọng tiếng Việt
# có khoảng trắng bên trong — tách ở một dấu cách sẽ cắt đôi «Trúc Ly».
_SPLIT_RE = re.compile(r"[|,;\t]|\s{2,}")


@dataclass
class BatchItem:
    """One video in a batch: a URL or a local file, plus per-video options."""
    url: str | None = None
    file_path: str | None = None
    voice: str | None = None
    blur_regions: list = None          # per-video blur rectangles (or None)
    subtitle_mode: str | None = None   # per-video override (or None = template)
    subtitle_style: dict | None = None  # per-video style (or None = template)
    ref: object = None  # backend-specific handle (state dict entry)

    @property
    def key(self) -> str:
        """Stable identity for state tracking (URL or absolute file path)."""
        return self.url or os.path.abspath(self.file_path or "")

    @property
    def label(self) -> str:
        """Short display name for tables/logs."""
        if self.url:
            return self.url
        return os.path.basename(self.file_path or "")


@dataclass
class BatchSummary:
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0


# Observer signature: (index, total, item, status, detail)
# status: "start" | "success" | "failed"
BatchObserver = Callable[[int, int, BatchItem, str, str], None]


class _Prefetcher:
    """Tải trước video KẾ TIẾP trong khi video hiện tại đang xử lý.

    Tải mạng hoàn toàn độc lập với các bước GPU/CPU của video đang chạy —
    chồng lấn hai việc là thời gian tải gần như miễn phí. Mỗi lúc chỉ tải
    trước một video (không tải cả danh sách: tốn đĩa và băng thông vô ích
    khi người dùng hủy giữa chừng).

    File tải trước nằm ở ``<output_dir>/_prefetch/<n>/``; khi video chạy
    xong thành công, file được dọn vào work_dir của chính video đó (resume
    tự tìm thấy như video tải bình thường).
    """

    def __init__(self, root_dir: str):
        self._root = os.path.join(root_dir, "_prefetch")
        self._thread: threading.Thread | None = None
        self._result: dict = {}

    def start(self, index: int, item: BatchItem) -> None:
        """Bắt đầu tải nền cho ``item`` (bỏ qua nếu là file local)."""
        self._thread = None
        self._result = {}
        if not item.url or item.file_path:
            return
        dest = os.path.join(self._root, str(index))
        result = self._result

        def _work():
            try:
                from autodub.media.downloader import download_video
                result["path"] = download_video(item.url, dest)
            except Exception as e:  # noqa: BLE001 — video này sẽ tải lại bình thường
                logger.warning(f"Tải trước thất bại ({item.label}): {e}")
                result["error"] = str(e)

        logger.info(f"Tải trước video kế tiếp: {item.label}")
        t = threading.Thread(target=_work, daemon=True,
                             name="batch-prefetch")
        t.start()
        self._thread = t

    def take(self, timeout: float = 3600.0) -> str | None:
        """Chờ lượt tải nền xong; trả về đường dẫn file hoặc None."""
        t, self._thread = self._thread, None
        if t is None:
            return None
        t.join(timeout)
        if t.is_alive():
            logger.warning("Tải trước quá lâu — video sẽ tự tải lại")
            return None
        return self._result.get("path")

    @staticmethod
    def adopt(prefetched: str, work_dir: str) -> None:
        """Dọn file đã tải trước vào work_dir của video (best-effort)."""
        try:
            if os.path.isfile(prefetched) and os.path.isdir(work_dir):
                target = os.path.join(work_dir,
                                      os.path.basename(prefetched))
                if not os.path.exists(target):
                    shutil.move(prefetched, target)
                parent = os.path.dirname(prefetched)
                # video_meta.json (title) đi kèm video — dọn vào data/ của
                # work_dir để các bước dịch/metadata đọc được.
                meta = os.path.join(parent, "data", "video_meta.json")
                if os.path.isfile(meta):
                    from autodub.workdir import data_path
                    meta_target = data_path(work_dir, "video_meta.json",
                                            create_dir=True)
                    if not os.path.exists(meta_target):
                        shutil.move(meta, meta_target)
                    else:
                        os.remove(meta)  # _resolve_video đã chép sẵn
                    meta_dir = os.path.dirname(meta)
                    if os.path.isdir(meta_dir) and not os.listdir(meta_dir):
                        os.rmdir(meta_dir)
                if os.path.isdir(parent) and not os.listdir(parent):
                    os.rmdir(parent)
        except OSError as e:
            logger.warning(f"Không dọn được file tải trước: {e}")

    def cleanup(self) -> None:
        """Xoá các file tải trước còn sót (video lỗi giữ nguyên để resume)."""
        self._thread = None
        try:
            if os.path.isdir(self._root) and not os.listdir(self._root):
                os.rmdir(self._root)
        except OSError:
            pass


def parse_lines(text: str | Iterable[str]) -> list[BatchItem]:
    """Turn pasted text (or a list of lines) into batch items.

    Dòng trống và dòng bắt đầu bằng ``#`` bị bỏ qua, liên kết trùng chỉ lấy
    lần đầu. Tên giọng được giữ nguyên như người dùng gõ; giọng không có
    trong danh mục sẽ tự rơi về giọng mặc định lúc chạy chứ không làm hỏng
    cả danh sách."""
    lines = text.splitlines() if isinstance(text, str) else list(text)
    items: list[BatchItem] = []
    seen: set[str] = set()

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in _SPLIT_RE.split(line, maxsplit=1) if p and p.strip()]
        if not parts:
            continue  # dòng chỉ có ký tự phân tách ("|", ",") — bỏ qua
        url = parts[0]
        voice = parts[1] if len(parts) > 1 else None

        if url in seen:
            logger.info(f"Skipping duplicate URL: {url}")
            continue
        seen.add(url)
        items.append(BatchItem(url=url, voice=voice))

    return items


def _run_items(
    items: list[BatchItem],
    pipeline: DubPipeline,
    req_template: DubRequest,
    on_result: Callable[[BatchItem, dict | None, str | None], None],
    on_start: Callable[[BatchItem], None] | None = None,
    observer: BatchObserver | None = None,
) -> BatchSummary:
    """Process items sequentially; call ``on_result(item, report, error)`` after
    each one (report on success, error message on failure) so the caller can
    persist status crash-safely. ``observer`` (if given) receives display-only
    per-item events — used by the GUI. A :class:`PipelineCancelled` from the
    pipeline aborts the whole batch (it is not recorded as a failure)."""
    summary = BatchSummary(total=len(items))
    # req_template.output_dir có thể None — dùng default của pipeline để
    # thư mục _prefetch nằm cạnh các work_dir.
    from autodub.languages import get_target
    prefetch_root = (req_template.output_dir
                     or pipeline.default_output_dir(get_target(req_template.target)))
    prefetcher = _Prefetcher(prefetch_root)

    for i, item in enumerate(items):
        logger.info(f"[{i + 1}/{len(items)}] Processing: {item.label}")
        if on_start:
            on_start(item)
        if observer:
            observer(i, len(items), item, "start", "")
        # Video này đã được tải trước trong lúc video trước xử lý?
        prefetched = prefetcher.take()
        # Bắt đầu tải nền video KẾ TIẾP ngay khi video này khởi động.
        if i + 1 < len(items):
            prefetcher.start(i + 1, items[i + 1])
        try:
            # Video này từng chạy dở (lỗi, thiếu Vox…)? Chạy TIẾP đúng thư
            # mục cũ: phần đã tải/nghe-chép/dịch được dùng lại, không tạo
            # thư mục mới — job_id giữ nguyên nên không bị trừ Vox lần nữa.
            resume_dir = None
            if isinstance(item.ref, dict):
                prev_dir = item.ref.get("work_dir") or ""
                if prev_dir and os.path.isdir(prev_dir):
                    resume_dir = prev_dir
            result = pipeline.run(DubRequest(
                url=item.url,
                file_path=prefetched or item.file_path,
                source_lang=req_template.source_lang,
                voice=item.voice or req_template.voice,
                bg_mode=req_template.bg_mode,
                bg_duck_db=req_template.bg_duck_db,
                skip_video=req_template.skip_video,
                subtitle_mode=item.subtitle_mode or req_template.subtitle_mode,
                subtitle_style=(item.subtitle_style
                                if item.subtitle_style is not None
                                else req_template.subtitle_style),
                blur_regions=(item.blur_regions
                              if item.blur_regions is not None
                              else req_template.blur_regions),
                output_dir=req_template.output_dir,
                resume_dir=resume_dir,
            ))
            if result.status != "completed":
                # Vietnamese-first: this string lands in the batch table and
                # the user's log, not just the console.
                reasons = {
                    "translate_pending": (
                        "Video chờ bản dịch tay — mở video này ở trang Tạo "
                        "dự án để dịch rồi chạy tiếp."),
                    "credit_blocked": (
                        "Không đủ Vox cho video này — nạp thêm rồi chạy lại; "
                        "phần đã nghe-chép được dùng lại, chưa bị trừ Vox."),
                }
                raise RuntimeError(reasons.get(
                    result.status,
                    f"Pipeline dừng ở trạng thái {result.status} "
                    f"(work_dir={result.work_dir})."))
            summary.success += 1
            logger.info(f"[{i + 1}/{len(items)}] SUCCESS → {result.report['session_id']}")
            if prefetched:
                # Dọn file tải trước vào work_dir để resume tự tìm thấy.
                _Prefetcher.adopt(prefetched, result.report.get("output_dir", ""))
            on_result(item, result.report, None)
            if observer:
                observer(i, len(items), item, "success", result.report["session_id"])
        except PipelineCancelled:
            logger.info("Batch cancelled by user")
            # Nhớ thư mục dở dang để lần chạy lại đi tiếp từ chỗ dừng.
            if isinstance(item.ref, dict) and getattr(pipeline, "last_work_dir", ""):
                item.ref["work_dir"] = pipeline.last_work_dir
            prefetcher.cleanup()
            raise
        except Exception as e:
            summary.failed += 1
            error_msg = str(e)[:200]
            logger.error(f"[{i + 1}/{len(items)}] FAILED: {error_msg}")
            # Ghi lại thư mục của lượt chạy hỏng — chạy lại sẽ resume đúng
            # thư mục này thay vì tải + nghe-chép lại từ đầu.
            if isinstance(item.ref, dict) and getattr(pipeline, "last_work_dir", ""):
                item.ref["work_dir"] = pipeline.last_work_dir
            on_result(item, None, error_msg)
            if observer:
                observer(i, len(items), item, "failed", error_msg)

    prefetcher.cleanup()
    logger.info("=" * 60)
    logger.info("BATCH COMPLETE")
    logger.info(f"  Total:   {summary.total}")
    logger.info(f"  Success: {summary.success}")
    logger.info(f"  Failed:  {summary.failed}")
    if summary.skipped:
        logger.info(f"  Skipped: {summary.skipped} (already done)")
    logger.info("=" * 60)
    return summary


def _save_json_atomic(data: object, path: str) -> None:
    """Crash-safe save: write to temp file then replace."""
    save_json_atomic(data, path)


def _load_state(state_path: str) -> dict[str, dict]:
    """Read the per-URL status map from a previous run (empty if none)."""
    if not os.path.exists(state_path):
        return {}
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
        return {v["video_url"]: v for v in data.get("videos", []) if v.get("video_url")}
    except Exception as e:  # noqa: BLE001 — a corrupt state file must not block a run
        logger.warning(f"Ignoring unreadable {STATE_FILENAME}: {e}")
        return {}


def run_batch(
    lines: str | Iterable[str] | list[BatchItem],
    settings: Settings,
    req_template: DubRequest,
    pipeline: DubPipeline | None = None,
    observer: BatchObserver | None = None,
    state_path: str | None = None,
    retry_done: bool = False,
    reuse_tts: bool = True,
) -> BatchSummary:
    """Dub every video in the batch.

    ``lines`` is either pasted text/lines of URLs (one per line, optional
    ``| voice`` suffix) or a ready list of :class:`BatchItem` — the GUI's
    upload table passes items directly, with per-video blur regions and
    subtitle modes.

    Videos recorded as ``success`` in ``batch_state.json`` are skipped unless
    ``retry_done`` is set. The state file is rewritten after every video, so a
    crashed or cancelled batch resumes cleanly from the same list.

    ``reuse_tts`` keeps one warmed TTS model alive across all videos instead
    of reloading it per video (10-60 s each) — only applies when no custom
    ``pipeline`` is injected.

    ``pipeline`` lets a frontend inject a DubPipeline wired with its own
    progress callback / cancel event; defaults to a plain one."""
    if (isinstance(lines, list) and lines
            and all(isinstance(x, BatchItem) for x in lines)):
        items = lines
    else:
        items = parse_lines(lines)
    if not items:
        logger.info("No videos in the batch list.")
        return BatchSummary()

    state_path = state_path or os.path.join(
        req_template.output_dir or settings.output_dir, STATE_FILENAME)
    previous = _load_state(state_path)

    pending: list[BatchItem] = []
    skipped = 0
    for item in items:
        done = previous.get(item.key, {}).get("status") == "success"
        if done and not retry_done:
            logger.info(f"Already done, skipping: {item.label}")
            skipped += 1
            continue
        pending.append(item)

    # Rebuild the state file around this run's list so the on-disk order matches
    # what the user provided, keeping results for videos they kept in the list.
    pending_keys = {item.key for item in pending}
    videos: list[dict] = []
    for item in items:
        entry = dict(previous.get(item.key, {}))
        entry["video_url"] = item.key
        entry["voice"] = item.voice or req_template.voice
        if item.key in pending_keys or not entry.get("status"):
            entry["status"] = "waiting"
        videos.append(entry)
    by_key = {v["video_url"]: v for v in videos}
    for item in pending:
        item.ref = by_key[item.key]

    state = {"output_dir": os.path.dirname(os.path.abspath(state_path)), "videos": videos}

    def flush() -> None:
        _save_json_atomic(state, state_path)

    if not pending:
        logger.info(f"Nothing to do: all {len(items)} video(s) already completed.")
        flush()
        return BatchSummary(total=len(items), skipped=skipped)

    logger.info(f"{len(pending)} video(s) to process, {skipped} already done")
    logger.info("=" * 60)
    flush()

    def on_start(item: BatchItem) -> None:
        item.ref["status"] = "processing"
        item.ref.pop("error", None)
        flush()

    def on_result(item: BatchItem, report: dict | None, error: str | None) -> None:
        entry = item.ref
        if report:
            entry["status"] = "success"
            entry["output_folder"] = report["session_id"]
            entry["segments"] = report["total_segments"]
            entry["duration_original"] = report["total_original_duration"]
            entry["duration_dub"] = report["total_tts_duration"]
            entry["processing_time"] = report["processing_time_seconds"]
            entry.pop("error", None)
        else:
            entry["status"] = "failed"
            entry["error"] = error
        flush()

    synth_cache = None
    demucs_cache = None
    whisper_cache = None
    if pipeline is None:
        if reuse_tts and len(pending) > 1:
            from autodub.speech.tts import SynthCache
            synth_cache = SynthCache()
        if len(pending) > 1:
            # Worker chỉ thực sự khởi động ở video đầu tiên cần Demucs —
            # tạo object ở đây là miễn phí, gating (venv GPU, RAM) nằm trong
            # DemucsCache._ensure().
            from autodub.media.vocal_separator import DemucsCache
            demucs_cache = DemucsCache()
            # Tương tự cho Whisper: gating (CPU luôn giữ, GPU cần đủ VRAM)
            # nằm trong WhisperCache.get().
            from autodub.speech.transcriber import WhisperCache
            whisper_cache = WhisperCache()
        pipeline = DubPipeline(settings, synth_cache=synth_cache,
                               demucs_cache=demucs_cache,
                               whisper_cache=whisper_cache)
    try:
        summary = _run_items(pending, pipeline, req_template, on_result,
                             on_start=on_start, observer=observer)
    finally:
        # Lưu lần cuối: bấm Dừng giữa chừng thì work_dir dở dang vừa được
        # ghi vào item.ref cũng xuống đĩa, lần chạy lại mới resume được.
        flush()
        if synth_cache is not None:
            synth_cache.close()
        if demucs_cache is not None:
            demucs_cache.close()
        if whisper_cache is not None:
            whisper_cache.close()
    summary.skipped = skipped
    return summary

