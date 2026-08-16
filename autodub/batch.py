"""Batch dubbing: process a list of videos typed one per line, with crash-safe
status tracking.

The user pastes URLs â€” one per line â€” and the batch runner does the rest. An
optional voice name may follow the URL after ``|``, ``,`` or a tab::

    https://youtu.be/aaa
    https://youtu.be/bbb | TrÃºc Ly
    https://youtu.be/ccc | Pháº¡m TuyÃªn

Progress is persisted to ``batch_state.json`` inside the output directory after
every video, so an interrupted batch can be resumed by pasting the same list
again: videos already marked ``success`` are skipped automatically.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable

from autodub.config import Settings
from autodub.pipeline import DubPipeline, DubRequest
from autodub.progress import PipelineCancelled
from autodub.utils import save_json_atomic, setup_logging

logger = setup_logging("autodub.batch")

STATE_FILENAME = "batch_state.json"

# TÃ¡ch má»™t dÃ²ng thÃ nh liÃªn káº¿t + TÃŠN GIá»ŒNG tÃ¹y chá»n. Chá»‰ tÃ¡ch á»Ÿ cÃ¡c dáº¥u rÃµ
# rÃ ng (| , ; tab, hoáº·c tá»« hai khoáº£ng tráº¯ng trá»Ÿ lÃªn) vÃ¬ tÃªn giá»ng tiáº¿ng Viá»‡t
# cÃ³ khoáº£ng tráº¯ng bÃªn trong â€” tÃ¡ch á»Ÿ má»™t dáº¥u cÃ¡ch sáº½ cáº¯t Ä‘Ã´i Â«TrÃºc LyÂ».
_SPLIT_RE = re.compile(r"[|,;\t]|\s{2,}")
_URL_RE = re.compile(r"https?://[^\s<>\[\]{}]+", re.IGNORECASE)


def _urls_from_line(line: str) -> list[str]:
    return [
        value.rstrip(".,!?;:，。！？；：）)]}")
        for value in _URL_RE.findall(line)
        if value.rstrip(".,!?;:，。！？；：）)]}")
    ]


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
    """Táº£i trÆ°á»›c video Káº¾ TIáº¾P trong khi video hiá»‡n táº¡i Ä‘ang xá»­ lÃ½.

    Táº£i máº¡ng hoÃ n toÃ n Ä‘á»™c láº­p vá»›i cÃ¡c bÆ°á»›c GPU/CPU cá»§a video Ä‘ang cháº¡y â€”
    chá»“ng láº¥n hai viá»‡c lÃ  thá»i gian táº£i gáº§n nhÆ° miá»…n phÃ­. Má»—i lÃºc chá»‰ táº£i
    trÆ°á»›c má»™t video (khÃ´ng táº£i cáº£ danh sÃ¡ch: tá»‘n Ä‘Ä©a vÃ  bÄƒng thÃ´ng vÃ´ Ã­ch
    khi ngÆ°á»i dÃ¹ng há»§y giá»¯a chá»«ng).

    File táº£i trÆ°á»›c náº±m á»Ÿ ``<output_dir>/_prefetch/<n>/``; khi video cháº¡y
    xong thÃ nh cÃ´ng, file Ä‘Æ°á»£c dá»n vÃ o work_dir cá»§a chÃ­nh video Ä‘Ã³ (resume
    tá»± tÃ¬m tháº¥y nhÆ° video táº£i bÃ¬nh thÆ°á»ng).
    """

    def __init__(
        self, root_dir: str, max_workers: int = 2, fragment_workers: int = 2
    ):
        self._root = os.path.join(root_dir, "_prefetch")
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(4, int(max_workers))),
            thread_name_prefix="batch-prefetch")
        self._futures = {}
        self._fragment_workers = max(1, min(16, int(fragment_workers)))

    def start(self, index: int, item: BatchItem) -> None:
        """Báº¯t Ä‘áº§u táº£i ná»n cho ``item`` (bá» qua náº¿u lÃ  file local)."""
        if not item.url or item.file_path:
            return
        dest = os.path.join(self._root, str(index))
        result: dict = {}
        def _download():
            try:
                from autodub.media.downloader import download_video
                result["path"] = download_video(
                    item.url, dest, fragment_workers=self._fragment_workers)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Táº£i trÆ°á»›c tháº¥t báº¡i ({item.label}): {e}")
                result["error"] = str(e)
            return result

        logger.info(f"Táº£i trÆ°á»›c video: {item.label}")
        self._futures[index] = self._executor.submit(_download)

    def take(self, index: int, timeout: float = 3600.0) -> str | None:
        """Chá» lÆ°á»£t táº£i ná»n xong; tráº£ vá» Ä‘Æ°á»ng dáº«n file hoáº·c None."""
        future = self._futures.pop(index, None)
        if future is None:
            return None
        try:
            result = future.result(timeout=timeout)
        except TimeoutError:
            logger.warning("Táº£i trÆ°á»›c quÃ¡ lÃ¢u â€” video sáº½ tá»± táº£i láº¡i")
            return None
        return result.get("path")

    @staticmethod
    def adopt(prefetched: str, work_dir: str) -> None:
        """Dá»n file Ä‘Ã£ táº£i trÆ°á»›c vÃ o work_dir cá»§a video (best-effort)."""
        try:
            if os.path.isfile(prefetched) and os.path.isdir(work_dir):
                target = os.path.join(work_dir,
                                      os.path.basename(prefetched))
                if not os.path.exists(target):
                    shutil.move(prefetched, target)
                parent = os.path.dirname(prefetched)
                # video_meta.json (title) Ä‘i kÃ¨m video â€” dá»n vÃ o data/ cá»§a
                # work_dir Ä‘á»ƒ cÃ¡c bÆ°á»›c dá»‹ch/metadata Ä‘á»c Ä‘Æ°á»£c.
                meta = os.path.join(parent, "data", "video_meta.json")
                if os.path.isfile(meta):
                    from autodub.workdir import data_path
                    meta_target = data_path(work_dir, "video_meta.json",
                                            create_dir=True)
                    if not os.path.exists(meta_target):
                        shutil.move(meta, meta_target)
                    else:
                        os.remove(meta)  # _resolve_video Ä‘Ã£ chÃ©p sáºµn
                    meta_dir = os.path.dirname(meta)
                    if os.path.isdir(meta_dir) and not os.listdir(meta_dir):
                        os.rmdir(meta_dir)
                if os.path.isdir(parent) and not os.listdir(parent):
                    os.rmdir(parent)
        except OSError as e:
            logger.warning(f"KhÃ´ng dá»n Ä‘Æ°á»£c file táº£i trÆ°á»›c: {e}")

    def cleanup(self) -> None:
        """XoÃ¡ cÃ¡c file táº£i trÆ°á»›c cÃ²n sÃ³t (video lá»—i giá»¯ nguyÃªn Ä‘á»ƒ resume)."""
        for future in self._futures.values():
            future.cancel()
        self._futures.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)
        try:
            if os.path.isdir(self._root) and not os.listdir(self._root):
                os.rmdir(self._root)
        except OSError:
            pass


def parse_lines(text: str | Iterable[str]) -> list[BatchItem]:
    """Turn pasted text (or a list of lines) into batch items.

    DÃ²ng trá»‘ng vÃ  dÃ²ng báº¯t Ä‘áº§u báº±ng ``#`` bá»‹ bá» qua, liÃªn káº¿t trÃ¹ng chá»‰ láº¥y
    láº§n Ä‘áº§u. TÃªn giá»ng Ä‘Æ°á»£c giá»¯ nguyÃªn nhÆ° ngÆ°á»i dÃ¹ng gÃµ; giá»ng khÃ´ng cÃ³
    trong danh má»¥c sáº½ tá»± rÆ¡i vá» giá»ng máº·c Ä‘á»‹nh lÃºc cháº¡y chá»© khÃ´ng lÃ m há»ng
    cáº£ danh sÃ¡ch."""
    lines = text.splitlines() if isinstance(text, str) else list(text)
    items: list[BatchItem] = []
    seen: set[str] = set()

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        embedded_urls = _urls_from_line(line)
        if embedded_urls and not line.lower().startswith(("http://", "https://")):
            for url in embedded_urls:
                if url not in seen:
                    seen.add(url)
                    items.append(BatchItem(url=url))
            continue

        parts = [p.strip() for p in _SPLIT_RE.split(line, maxsplit=1)
                 if p and p.strip()]
        if not parts:
            continue
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
    per-item events â€” used by the GUI. A :class:`PipelineCancelled` from the
    pipeline aborts the whole batch (it is not recorded as a failure)."""
    summary = BatchSummary(total=len(items))
    # req_template.output_dir cÃ³ thá»ƒ None â€” dÃ¹ng default cá»§a pipeline Ä‘á»ƒ
    # thÆ° má»¥c _prefetch náº±m cáº¡nh cÃ¡c work_dir.
    from autodub.languages import get_target
    prefetch_root = (req_template.output_dir
                     or pipeline.default_output_dir(get_target(req_template.target)))
    prefetch_workers = getattr(
        getattr(pipeline, "settings", None),
        "download_prefetch_workers", 2)
    fragment_workers = getattr(
        getattr(pipeline, "settings", None),
        "download_fragment_workers", 2)
    prefetcher = _Prefetcher(
        prefetch_root, prefetch_workers, fragment_workers)

    for i, item in enumerate(items):
        logger.info(f"[{i + 1}/{len(items)}] Processing: {item.label}")
        if on_start:
            on_start(item)
        if observer:
            observer(i, len(items), item, "start", "")
        # Video nÃ y Ä‘Ã£ Ä‘Æ°á»£c táº£i trÆ°á»›c trong lÃºc video trÆ°á»›c xá»­ lÃ½?
        prefetched = prefetcher.take(i)
        # Báº¯t Ä‘áº§u táº£i ná»n video Káº¾ TIáº¾P ngay khi video nÃ y khá»Ÿi Ä‘á»™ng.
        prefetch_count = prefetch_workers
        for next_index in range(i + 1, min(len(items), i + 1 + prefetch_count)):
            prefetcher.start(next_index, items[next_index])
        try:
            # má»¥c cÅ©: pháº§n Ä‘Ã£ táº£i/nghe-chÃ©p/dá»‹ch Ä‘Æ°á»£c dÃ¹ng láº¡i, khÃ´ng táº¡o
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
                        "Video chá» báº£n dá»‹ch tay â€” má»Ÿ video nÃ y á»Ÿ trang Táº¡o "
                        "dá»± Ã¡n Ä‘á»ƒ dá»‹ch rá»“i cháº¡y tiáº¿p."),
                }
                raise RuntimeError(reasons.get(
                    result.status,
                    f"Pipeline dá»«ng á»Ÿ tráº¡ng thÃ¡i {result.status} "
                    f"(work_dir={result.work_dir})."))
            summary.success += 1
            logger.info(f"[{i + 1}/{len(items)}] SUCCESS â†’ {result.report['session_id']}")
            if prefetched:
                # Dá»n file táº£i trÆ°á»›c vÃ o work_dir Ä‘á»ƒ resume tá»± tÃ¬m tháº¥y.
                _Prefetcher.adopt(prefetched, result.report.get("output_dir", ""))
            on_result(item, result.report, None)
            if observer:
                observer(i, len(items), item, "success", result.report["session_id"])
        except PipelineCancelled:
            logger.info("Batch cancelled by user")
            # Nhá»› thÆ° má»¥c dá»Ÿ dang Ä‘á»ƒ láº§n cháº¡y láº¡i Ä‘i tiáº¿p tá»« chá»— dá»«ng.
            if isinstance(item.ref, dict) and getattr(pipeline, "last_work_dir", ""):
                item.ref["work_dir"] = pipeline.last_work_dir
            prefetcher.cleanup()
            raise
        except Exception as e:
            summary.failed += 1
            error_msg = str(e)[:200]
            logger.error(f"[{i + 1}/{len(items)}] FAILED: {error_msg}")
            # Ghi láº¡i thÆ° má»¥c cá»§a lÆ°á»£t cháº¡y há»ng â€” cháº¡y láº¡i sáº½ resume Ä‘Ãºng
            # thÆ° má»¥c nÃ y thay vÃ¬ táº£i + nghe-chÃ©p láº¡i tá»« Ä‘áº§u.
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
    except Exception as e:  # noqa: BLE001 â€” a corrupt state file must not block a run
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
    ``| voice`` suffix) or a ready list of :class:`BatchItem` â€” the GUI's
    upload table passes items directly, with per-video blur regions and
    subtitle modes.

    Videos recorded as ``success`` in ``batch_state.json`` are skipped unless
    ``retry_done`` is set. The state file is rewritten after every video, so a
    crashed or cancelled batch resumes cleanly from the same list.

    ``reuse_tts`` keeps one warmed TTS model alive across all videos instead
    of reloading it per video (10-60 s each) â€” only applies when no custom
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
            # Worker chá»‰ thá»±c sá»± khá»Ÿi Ä‘á»™ng á»Ÿ video Ä‘áº§u tiÃªn cáº§n Demucs â€”
            # táº¡o object á»Ÿ Ä‘Ã¢y lÃ  miá»…n phÃ­, gating (venv GPU, RAM) náº±m trong
            # DemucsCache._ensure().
            from autodub.media.vocal_separator import DemucsCache
            demucs_cache = DemucsCache()
            # TÆ°Æ¡ng tá»± cho Whisper: gating (CPU luÃ´n giá»¯, GPU cáº§n Ä‘á»§ VRAM)
            # náº±m trong WhisperCache.get().
            from autodub.speech.transcriber import WhisperCache
            whisper_cache = WhisperCache()
        pipeline = DubPipeline(settings, synth_cache=synth_cache,
                               demucs_cache=demucs_cache,
                               whisper_cache=whisper_cache)
    try:
        summary = _run_items(pending, pipeline, req_template, on_result,
                             on_start=on_start, observer=observer)
    finally:
        # LÆ°u láº§n cuá»‘i: báº¥m Dá»«ng giá»¯a chá»«ng thÃ¬ work_dir dá»Ÿ dang vá»«a Ä‘Æ°á»£c
        # ghi vÃ o item.ref cÅ©ng xuá»‘ng Ä‘Ä©a, láº§n cháº¡y láº¡i má»›i resume Ä‘Æ°á»£c.
        flush()
        if synth_cache is not None:
            synth_cache.close()
        if demucs_cache is not None:
            demucs_cache.close()
        if whisper_cache is not None:
            whisper_cache.close()
    summary.skipped = skipped
    return summary


async def run_batch_async(
    lines: str | Iterable[str] | list[BatchItem],
    settings: Settings,
    req_template: DubRequest,
    pipeline: DubPipeline | None = None,
    observer: BatchObserver | None = None,
    state_path: str | None = None,
    retry_done: bool = False,
    reuse_tts: bool = True,
) -> BatchSummary:
    """Run the existing sequential batch without blocking asyncio."""
    import asyncio

    return await asyncio.to_thread(
        run_batch,
        lines,
        settings,
        req_template,
        pipeline,
        observer,
        state_path,
        retry_done,
        reuse_tts,
    )

