"""Local JSON tool adapter for OpenClaw batch dubbing."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from autodub.batch import parse_lines
from autodub.config import Settings
from autodub.remote_worker import (
    cancel_job,
    job_is_live,
    settle_orphan_status,
    submit_job,
)


class BatchNotFound(ValueError):
    """Batch không tồn tại: route hợp lệ nhưng ``batch_id`` sai → HTTP 404.

    Là lớp con của ``ValueError`` nên mọi nơi bắt ``ValueError`` cũ vẫn chạy
    đúng; tầng HTTP phân biệt được 404 với 400 nhờ tên lớp.
    """

_OPTION_KEYS = {
    "source_lang", "voice", "bg_mode", "bg_duck_db", "skip_video",
    "subtitle_mode", "subtitle_style", "blur_regions", "mirror",
    "ocr_enabled", "target", "translate_enabled", "translate_batch_size",
    "translate_cps_budget", "translate_domain", "translate_context",
    "translate_pronouns", "translate_glossary", "translate_style",
    "translate_note", "generate_metadata", "branding", "vsr_enabled", "vsr_mode",
}
_REQUEST_KEYS = {
    "source_lang", "voice", "bg_mode", "bg_duck_db", "skip_video",
    "subtitle_mode", "subtitle_style", "blur_regions", "mirror",
    "ocr_enabled", "target",
}
_SETTINGS_KEYS = {
    "translate_enabled", "translate_batch_size", "translate_cps_budget",
    "translate_domain", "translate_context", "translate_pronouns",
    "translate_glossary", "translate_style_notes", "generate_metadata",
    "vsr_enabled", "vsr_mode",
}
_STYLE_NOTES = {
    "natural": "",
    "formal": "Dịch trang trọng, lịch sự, dùng từ chuẩn mực; tránh tiếng lóng.",
    "literal": "Bám sát nghĩa gốc, giữ nguyên cấu trúc câu khi tiếng Việt vẫn xuôi.",
    "creative": "Dịch thoáng, ưu tiên câu chữ mượt và hấp dẫn hơn là bám từng chữ.",
    "humorous": "Giữ giọng vui, dí dỏm; dùng cách nói đời thường của giới trẻ Việt.",
    "social": "Câu ngắn, nhịp nhanh, dễ nghe khi lướt; tránh câu dài lê thê.",
}
_TERMINAL = {"completed", "failed", "cancelled", "translate_pending"}
#: "interrupted" = app bị tắt khi job đang chạy. Không còn tiến trình nào
#: chạy nữa nên batch đã "an vị" — nhưng KHÁC "cancelled": còn chạy tiếp
#: được, nên giao diện phải thấy trạng thái này thay vì "Đang chạy".
_SETTLED = _TERMINAL | {"interrupted"}


def recover_orphan_running(queue_root: str) -> list[str]:
    """Đánh dấu 'interrupted' cho job còn nằm trong running/ lúc khởi động.

    App bị giết cứng để lại tệp job trong ``running/`` mà không ai ghi
    trạng thái kết thúc. Không quét lúc khởi động thì batch đó kẹt vĩnh viễn
    ở 'running' và KHÔNG API nào cứu được. Trả về danh sách job_id đã cứu.
    """
    base = Path(queue_root).expanduser().resolve()
    running_dir = base / "running"
    recovered: list[str] = []
    if not running_dir.is_dir():
        return recovered
    for path in sorted(running_dir.glob("*.json")):
        job_id = path.stem
        try:
            status = _read_status(queue_root, job_id)
        except FileNotFoundError:
            status = {}
        if status.get("status") in _SETTLED:
            continue
        if job_is_live(base, job_id):
            # Nhịp tim còn đập và PID còn sống — không phải job mồ côi. Quét
            # lúc khởi động có thể chạy trong khi một tiến trình khác đang
            # thật sự làm việc; đóng nó lại là giết việc đang chạy.
            continue
        _settle_orphan(queue_root, job_id, status)
        recovered.append(job_id)
    return recovered


def _settle_orphan(queue_root: str, job_id: str, status: dict) -> None:
    """Ghi trạng thái 'interrupted' cho một job mồ côi (giữ tiến độ cũ)."""
    base = Path(queue_root).expanduser().resolve()
    status_dir = base / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    updated = dict(status) if isinstance(status, dict) else {}
    updated.setdefault("job_id", job_id)
    updated.update({
        "status": "interrupted",
        "step": "interrupted",
        "detail": "Ứng dụng đã tắt khi job đang chạy — chạy tiếp được",
        "error": "",
    })
    status_path = status_dir / f"{job_id}.json"
    temp = status_path.with_name(f".{job_id}.json.tmp")
    temp.write_text(json.dumps(updated, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    temp.replace(status_path)
#: Job còn chạy tiếp được khi người dùng yêu cầu: lỗi thật, đang chờ dịch
#: tay, hoặc bị cắt vì ứng dụng tắt giữa chừng (không phải người dùng hủy).
_RETRYABLE = {"failed", "translate_pending", "interrupted"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_http_url(value: str) -> bool:
    """Chuỗi này có phải URL http(s) thật không (không chỉ là 'có gì đó')?"""
    parts = urlsplit(value.strip())
    return parts.scheme.lower() in ("http", "https") and bool(parts.netloc)


def _links(payload: dict) -> list[str]:
    raw = payload.get("links", payload.get("text", ""))
    if isinstance(raw, str):
        items = parse_lines(raw)
    elif isinstance(raw, list):
        items = parse_lines("\n".join(str(value) for value in raw))
    else:
        raise TypeError("links hoặc text phải là chuỗi hoặc danh sách")
    links = [item.url for item in items if item.url]
    if not links:
        raise ValueError("Không tìm thấy link video http(s)")
    # parse_lines coi MỌI dòng không rỗng là một URL, nên chuỗi rác ("not a
    # url") lọt tới đây nguyên vẹn và tạo batch thật rồi chết ở bước tải. Chặn
    # ngay tại biên API, nói rõ dòng nào sai.
    invalid = [link for link in links if not _is_http_url(link)]
    if invalid:
        raise ValueError(
            "Link không hợp lệ (phải là http:// hoặc https://): "
            + ", ".join(repr(link) for link in invalid[:5]))
    if len(links) > 100:
        raise ValueError("Tối đa 100 link mỗi batch")
    return links


def _options(payload: dict) -> dict:
    options = payload.get("options", {})
    if not isinstance(options, dict):
        raise TypeError("options phải là object")
    unknown = set(options) - _OPTION_KEYS
    if unknown:
        raise ValueError(f"options không hợp lệ: {sorted(unknown)}")
    branding = options.get("branding", {})
    if not isinstance(branding, dict):
        raise TypeError("branding phải là object")
    if "blur_regions" in options:
        regions = options["blur_regions"]
        if not isinstance(regions, list):
            raise TypeError("blur_regions phải là danh sách (list)")
        for r in regions:
            if not isinstance(r, dict):
                raise TypeError("Mỗi vùng trong blur_regions phải là một object")
    return dict(options)


def _defaults(settings: Settings) -> dict:
    return {
        "source_lang": settings.default_source_lang,
        "voice": settings.vieneu_voice,
        "bg_mode": "demucs",
        "bg_duck_db": -12.0,
        "skip_video": False,
        "subtitle_mode": settings.subtitle_mode,
        "ocr_enabled": settings.ocr_enabled,
        "translate_enabled": settings.translate_enabled,
        "translate_batch_size": settings.translate_batch_size,
        "translate_cps_budget": settings.translate_cps_budget,
        "generate_metadata": settings.generate_metadata,
        "vsr_enabled": settings.vsr_enabled,
        "vsr_mode": settings.vsr_mode,
    }


def _questions(options: dict, defaults: dict) -> list[dict]:
    questions = []
    if "voice" not in options:
        questions.append({
            "id": "voice",
            "type": "text",
            "prompt": "Dùng giọng đọc nào? Trả lời 'mặc định' để dùng giọng hiện tại.",
            "default": defaults["voice"] or "giọng mặc định",
        })
    if "translate_style" not in options:
        questions.append({
            "id": "translate_style",
            "type": "choice",
            "prompt": "Phong cách dịch?",
            "options": ["natural", "formal", "literal", "creative",
                         "humorous", "social"],
            "default": "natural",
        })
    if "subtitle_mode" not in options:
        questions.append({
            "id": "subtitle_mode",
            "type": "choice",
            "prompt": "Phụ đề đầu ra?",
            "options": ["none", "soft", "burn"],
            "default": defaults["subtitle_mode"],
        })
    return questions


def _settings_overrides(options: dict) -> dict:
    overrides = {
        key: options[key] for key in _SETTINGS_KEYS if key in options
    }
    style = options.get("translate_style")
    note = str(options.get("translate_note", "") or "").strip()
    style_note = _STYLE_NOTES.get(style, "") if style else ""
    merged = "\n".join(value for value in (style_note, note) if value)
    if merged:
        overrides["translate_style_notes"] = merged
    return overrides


def _job_payload(job_id: str, link: str, options: dict,
                 settings: Settings) -> dict:
    effective = {**_defaults(settings), **options}
    request = {
        key: effective[key] for key in _REQUEST_KEYS if key in effective
    }
    settings_overrides = _settings_overrides(effective)
    branding = dict(effective.get("branding", {}))
    return {
        "job_id": job_id,
        "request": {"url": link, **request},
        "settings": settings_overrides,
        "branding": branding,
    }


def _manifest_path(queue_root: str, batch_id: str) -> Path:
    return Path(queue_root).expanduser().resolve() / "batches" / f"{batch_id}.json"

def _write_manifest(path: Path, manifest: dict) -> None:
    temp = path.with_name(path.name + ".part")
    try:
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise

def _rollback_jobs(queue_root: str, jobs: list[dict]) -> None:
    for job in jobs:
        cancel_job(queue_root, job["job_id"])


def _read_manifest(queue_root: str, batch_id: str) -> dict:
    path = _manifest_path(queue_root, batch_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchNotFound(f"Không tìm thấy batch: {batch_id}") from exc


def _read_status(queue_root: str, job_id: str) -> dict:
    path = Path(queue_root).expanduser().resolve() / "status" / f"{job_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileNotFoundError(job_id) from exc


def load_batch_status(queue_root: str, batch_id: str) -> dict:
    manifest = _read_manifest(queue_root, batch_id)
    jobs = []
    counts: dict[str, int] = {}
    for job_id in manifest["job_ids"]:
        try:
            status = _read_status(queue_root, job_id)
        except FileNotFoundError:
            status = {"job_id": job_id, "status": "failed",
                      "error": "Không tìm thấy trạng thái job"}
        state = str(status.get("status", "queued"))
        counts[state] = counts.get(state, 0) + 1
        jobs.append({
            "job_id": job_id,
            "status": state,
            "percent": int(status.get("percent", 0) or 0),
            "step": status.get("step", ""),
            "detail": status.get("detail", ""),
            "error": status.get("error", ""),
            "output": status.get("output", {}),
        })
    percent = round(sum(item["percent"] for item in jobs) / len(jobs)) if jobs else 0
    return {
        "ok": True,
        "batch_id": batch_id,
        "status": _aggregate_status(jobs),
        "percent": percent,
        "counts": counts,
        "jobs": jobs,
    }


def _aggregate_status(jobs: list[dict]) -> str:
    states = {item["status"] for item in jobs}
    if states == {"completed"}:
        return "completed"
    if states and states <= _SETTLED:
        if "failed" in states:
            return "failed"
        if "translate_pending" in states:
            return "translate_pending"
        # Ưu tiên "interrupted" hơn "cancelled": batch còn chạy tiếp được
        # thì phải hiện nút Thử lại, đừng để người dùng kẹt.
        if "interrupted" in states:
            return "interrupted"
        if "cancelled" in states:
            return "cancelled"
    return "running"


def _submit(payload: dict, queue_root: str, settings: Settings) -> dict:
    links = _links(payload)
    options = _options(payload)
    batch_id = "batch-" + uuid.uuid4().hex[:12]
    jobs = []
    try:
        for index, link in enumerate(links, 1):
            job_id = f"{batch_id}-{index:03d}"
            job = _job_payload(job_id, link, options, settings)
            submit_job(queue_root, job)
            jobs.append(job)
    except Exception:
        _rollback_jobs(queue_root, jobs)
        raise
    manifest = {
        "batch_id": batch_id,
        "job_ids": [job["job_id"] for job in jobs],
        "jobs": jobs,
        "links": links,
        "options": options,
        "created_at": _now(),
        "defaults": _defaults(settings),
    }
    path = _manifest_path(queue_root, batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_manifest(path, manifest)
    except Exception:
        _rollback_jobs(queue_root, jobs)
        raise
    return {"ok": True, "batch_id": batch_id,
            "job_ids": manifest["job_ids"], "status": "queued"}


def _cancel(payload: dict, queue_root: str) -> dict:
    manifest = _read_manifest(queue_root, payload.get("batch_id", ""))
    cancelled = []
    signalled = []
    alive = []
    for job_id in manifest["job_ids"]:
        # Tệp trạng thái có thể không tồn tại (job kẹt ở inbox/, worker chết
        # trước khi ghi) — hủy vẫn phải chạy, không được ném FileNotFoundError
        # rồi bị _dispatch đổi thành HTTP 400.
        try:
            status = _read_status(queue_root, job_id)
        except FileNotFoundError:
            status = {}
        if status.get("status") in _TERMINAL:
            continue
        # cancel_job trả False khi job còn tiến trình sống: lúc đó ta mới chỉ
        # CẮM CỜ để worker tự dừng, chưa đóng được job. Báo "đã hủy xong" ở
        # đây chính là nguồn của ca "cancel trả ok=True nhưng batch vẫn
        # 'running'". Phải phân biệt và nói đúng sự thật.
        if cancel_job(queue_root, job_id):
            cancelled.append(job_id)
        else:
            signalled.append(job_id)
            if job_is_live(queue_root, job_id):
                alive.append(job_id)
    return {"ok": True, "batch_id": manifest["batch_id"],
            "cancelled": cancelled, "signalled": signalled,
            "still_running": alive}


def _retry_failed(payload: dict, queue_root: str) -> dict:
    manifest = _read_manifest(queue_root, payload.get("batch_id", ""))
    replacement_jobs = []
    replacement_by_old_id = {}
    try:
        for job in manifest["jobs"]:
            try:
                status = _read_status(queue_root, job["job_id"])
            except FileNotFoundError:
                # Không có tệp trạng thái = job chưa từng chạy xong: coi như
                # đáng thử lại thay vì ném lỗi ra tầng HTTP.
                status = {}
            # Job mồ côi (kẹt ở 'running' vì app bị giết cứng) cũng phải cứu
            # được: đóng nó lại thành 'interrupted' rồi thay bằng job mới,
            # thay vì để batch không bao giờ kết thúc.
            #
            # NHƯNG job còn nhịp tim thì TUYỆT ĐỐI không được đụng vào. Với
            # phép thử bằng mtime, một job đang chạy thật ở bước im lặng dài
            # (Demucs/ASR video dài, >5 phút không sự kiện tiến trình) bị coi
            # là mồ côi: nó bị đổi thành 'interrupted' dù vẫn đang chạy, rồi
            # một job MỚI giữ nguyên request (kèm output_dir) được tạo ra —
            # hai job ghi cùng một thư mục.
            orphan = (status.get("status") not in _RETRYABLE
                      and settle_orphan_status(
                          queue_root, job["job_id"]) is not None)
            if status.get("status") not in _RETRYABLE and not orphan:
                continue
            new_id = f"{manifest['batch_id']}-retry-{uuid.uuid4().hex[:6]}"
            replacement = dict(job)
            replacement["job_id"] = new_id
            # GIỮ NGUYÊN request (kể cả output_dir/resume_dir) để job mới tìm
            # lại đúng thư mục làm việc cũ và tái dùng video/.part đã tải dở.
            # Đổi item_dir là mất ~18% đã tải và lỗi lại đúng chỗ cũ.
            submit_job(queue_root, replacement)
            replacement_jobs.append(replacement)
            replacement_by_old_id[job["job_id"]] = replacement
    except Exception:
        _rollback_jobs(queue_root, replacement_jobs)
        raise
    manifest["jobs"] = [
        replacement_by_old_id.get(job["job_id"], job)
        for job in manifest["jobs"]
    ]
    manifest["job_ids"] = [job["job_id"] for job in manifest["jobs"]]
    path = _manifest_path(queue_root, manifest["batch_id"])
    try:
        _write_manifest(path, manifest)
    except Exception:
        _rollback_jobs(queue_root, replacement_jobs)
        raise
    return {"ok": True, "batch_id": manifest["batch_id"],
            "job_ids": [job["job_id"] for job in replacement_jobs]}


def handle(payload: dict, *, queue_root: str = "remote_queue",
           settings: Settings | None = None) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("Request phải là object")
    action = payload.get("action")
    settings = settings or Settings.load()
    if action == "prepare":
        links = _links(payload)
        options = _options(payload)
        defaults = _defaults(settings)
        return {"ok": True, "links": links, "defaults": defaults,
                "questions": _questions(options, defaults)}
    if action == "submit":
        return _submit(payload, queue_root, settings)
    if action == "status":
        return load_batch_status(queue_root, payload.get("batch_id", ""))
    if action == "cancel":
        return _cancel(payload, queue_root)
    if action == "retry_failed":
        return _retry_failed(payload, queue_root)
    if action == "tools_call":
        from autodub.openclaw_tools_registry import dispatch_tool
        return dispatch_tool(payload.get("name"), payload.get("arguments", {}), settings=settings)
    raise ValueError("action phải là prepare, submit, status, cancel, retry_failed hoặc tools_call")


def _configure_stdout() -> None:
    """Ép stdout sang UTF-8 mà không chết trên console Windows cp1252.

    ``errors="strict"`` làm tiến trình ném UnicodeEncodeError ngay khi in
    tên video có tiếng Việt/tiếng Trung ra console mặc định của Windows
    (cp1252) — CLI chết giữa lúc trả kết quả, exit code 1. ``replace`` giữ
    đúng hợp đồng "một dòng JSON trên stdout": ký tự không mã hoá được
    thành "?" nhưng payload vẫn tới tay client.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass


def _emit(payload: dict) -> None:
    """In một dòng JSON, không bao giờ để lỗi mã hoá giết tiến trình."""
    line = json.dumps(payload, ensure_ascii=False)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            line.encode("utf-8", "replace") + b"\n")
        sys.stdout.buffer.flush()


def main() -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default="remote_queue")
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        result = handle(payload, queue_root=args.queue)
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        _emit(result)
        return 1
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
