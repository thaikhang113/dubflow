"""File-queue worker contract for remote OpenClaw jobs."""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from autodub.cancel import cancel_processes, cancel_scope
from autodub.progress import PipelineCancelled

_TOP_LEVEL_KEYS = {"job_id", "request", "branding"}
_REQUEST_KEYS = {
    "url", "file_path", "source_lang", "voice", "clone_voice",
    "clone_source", "clone_reference_audio", "bg_mode", "bg_duck_db",
    "skip_video", "output_dir", "resume_dir", "subtitle_mode",
    "blur_regions", "subtitle_style", "mirror", "ocr_enabled", "target",
}
_BRANDING_KEYS = {
    "logo_path", "intro_path", "outro_path", "vision_enabled",
    "logo_opacity", "logo_scale", "logo_position", "logo_region",
}
_SETTINGS_KEYS = {
    "translate_enabled", "translate_batch_size", "translate_cps_budget",
    "translate_domain", "translate_context", "translate_pronouns",
    "translate_glossary", "translate_style_notes", "generate_metadata",
}


class JobValidationError(ValueError):
    pass


def request_from_payload(payload: dict):
    from autodub.pipeline import DubRequest

    request_data = dict(payload.get("request", {}))
    request_data.update(payload.get("branding", {}))
    request_data.pop("logo_position", None)
    return DubRequest(**request_data)


def _root(root: str) -> Path:
    return Path(root).expanduser().resolve()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _validate_job(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise JobValidationError("job must be an object")
    unknown = set(payload) - (_TOP_LEVEL_KEYS | {"settings"})
    if unknown:
        raise JobValidationError(f"unknown job fields: {sorted(unknown)}")
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip() or "/" in job_id or "\\" in job_id:
        raise JobValidationError("job_id must be a safe non-empty filename")
    for name, allowed in (("request", _REQUEST_KEYS), ("branding", _BRANDING_KEYS)):
        value = payload.get(name, {})
        if not isinstance(value, dict):
            raise JobValidationError(f"{name} must be an object")
        unknown = set(value) - allowed
        if unknown:
            raise JobValidationError(f"unknown {name} fields: {sorted(unknown)}")
    settings = payload.get("settings", {})
    if not isinstance(settings, dict):
        raise JobValidationError("settings must be an object")
    unknown = set(settings) - _SETTINGS_KEYS
    if unknown:
        raise JobValidationError(f"unknown settings fields: {sorted(unknown)}")
    return dict(payload)


def settings_from_payload(payload: dict, settings):
    overrides = payload.get("settings", {})
    if not overrides:
        return settings
    try:
        return replace(settings, **overrides)
    except TypeError as exc:
        raise JobValidationError(f"invalid settings override: {exc}") from exc


def _job_paths(root: Path, job_id: str) -> list[Path]:
    return [root / folder / f"{job_id}.json" for folder in ("inbox", "running", "status")]


def submit_job(root: str, payload: dict) -> str:
    job = _validate_job(payload)
    base = _root(root)
    job_id = job["job_id"]
    if any(path.exists() for path in _job_paths(base, job_id)):
        raise JobValidationError(f"job already exists: {job['job_id']}")
    inbox_path = base / "inbox" / f"{job_id}.json"
    status_path = base / "status" / f"{job_id}.json"
    try:
        _atomic_json(inbox_path, job)
        _atomic_json(
            status_path,
            {
                "job_id": job_id,
                "status": "queued",
                "percent": 0,
                "step": "queued",
                "detail": "",
                "output": {},
                "warnings": [],
                "error": "",
            },
        )
    except Exception:
        for path in (inbox_path, status_path):
            try:
                path.unlink()
            except OSError:
                pass
            try:
                path.with_name(path.name + ".part").unlink()
            except OSError:
                pass
        raise
    return job_id


def load_job(root: str, job_id: str) -> dict:
    if not isinstance(job_id, str) or "/" in job_id or "\\" in job_id:
        raise JobValidationError("invalid job_id")
    base = _root(root)
    for path in _job_paths(base, job_id):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise JobValidationError(f"invalid job JSON: {job_id}") from exc
    raise FileNotFoundError(job_id)


#: Nhịp tim ghi mỗi 5 giây; coi là cũ khi quá 45 giây không đập. Khoảng cách
#: 5s/45s chịu được vài lần lỡ nhịp (máy bận, GIL) mà vẫn phát hiện chết nhanh.
_HEARTBEAT_INTERVAL_S = 5.0
_HEARTBEAT_STALE_S = 45.0


def _pid_alive(pid: int) -> bool:
    """Tiến trình ``pid`` còn sống không? KHÔNG BAO GIỜ giết tiến trình.

    CẢNH BÁO: ``os.kill(pid, 0)`` KHÔNG dùng được để dò trên Windows — ở đó
    Python gọi ``TerminateProcess`` và lời gọi dò sẽ GIẾT tiến trình đang
    chạy. Trên Windows dùng ``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)``
    (quyền hỏi thăm, không phải quyền kết liễu) rồi đọc mã thoát: chỉ mã
    ``STILL_ACTIVE`` mới là còn sống. Trên POSIX thì ``os.kill(pid, 0)`` chỉ
    kiểm tra sự tồn tại, không gửi tín hiệu nào.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        _STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == _STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _heartbeat_path(root: Path, job_id: str) -> Path:
    return root / "running" / f"{job_id}.heartbeat"


def _read_heartbeat(root: Path, job_id: str) -> dict | None:
    try:
        data = json.loads(
            _heartbeat_path(root, job_id).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _running_for(root: Path, job_id: str) -> bool:
    """Job có ĐANG được một tiến trình sống chạy thật không?

    Tín hiệu sống phải là THẬT (nhịp tim + PID), không phải ngưỡng thời gian
    trên mtime: đo bằng mtime thì job bị giết cứng 60 giây trước vẫn "trông
    như đang sống" (batch kẹt 'running' tới hết 5 phút), còn job thật đang ở
    bước im lặng dài (Demucs/ASR video dài, không sự kiện tiến trình >5 phút)
    lại bị coi là mồ côi và bị đóng oan.

    Còn sống khi và chỉ khi CẢ BA đúng: có tệp nhịp tim, PID trong đó còn
    sống, và mốc thời gian còn mới.
    """
    beat = _read_heartbeat(root, job_id)
    if beat is None:
        return False
    if not _pid_alive(beat.get("pid")):
        return False
    stamp = beat.get("ts")
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
        return False
    return (time.time() - stamp) < _HEARTBEAT_STALE_S


def job_is_live(root, job_id: str) -> bool:
    """API công khai cho tầng tool: job này còn ai chạy thật không?"""
    return _running_for(_root(str(root)), job_id)


def _write_heartbeat(root: Path, job_id: str) -> None:
    _atomic_json(_heartbeat_path(root, job_id), {
        "pid": os.getpid(), "ts": time.time(), "job_id": job_id,
    })


def _clear_heartbeat(root: Path, job_id: str) -> None:
    try:
        _heartbeat_path(root, job_id).unlink()
    except OSError:
        pass


def _heartbeat_loop(root: Path, job_id: str, stop_event) -> None:
    while not stop_event.wait(_HEARTBEAT_INTERVAL_S):
        try:
            _write_heartbeat(root, job_id)
        except OSError:
            pass


def start_heartbeat(root: Path, job_id: str):
    """Bắt đầu đập nhịp cho ``job_id``; trả (stop_event, thread)."""
    _write_heartbeat(root, job_id)
    beat_stop = threading.Event()
    thread = threading.Thread(
        target=_heartbeat_loop, args=(root, job_id, beat_stop), daemon=True,
    )
    thread.start()
    return beat_stop, thread


def cancel_job(root: str, job_id: str) -> bool:
    """Yêu cầu hủy ``job_id``. Trả True nếu job đã AN VỊ ngay tại đây.

    Trả False khi job còn một tiến trình sống đang chạy: lúc đó lệnh hủy
    chỉ là cái cờ trong ``cancel/`` để worker tự nhận ra và tự kết thúc,
    ta KHÔNG được ghi trạng thái kết thúc hộ nó. Tầng gọi phải phân biệt
    được hai ca này, nếu không API sẽ báo "đã hủy xong" trong khi batch
    vẫn nằm ở 'running'.
    """
    if not isinstance(job_id, str) or not job_id or "/" in job_id or "\\" in job_id:
        raise JobValidationError("invalid job_id")
    base = _root(root)
    marker = base / "cancel" / job_id
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="ascii")
    try:
        status = json.loads(
            (base / "status" / f"{job_id}.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        status = {}
    if status.get("status") in (None, "queued"):
        # Chưa từng chạy (status 'queued') HOẶC không có tệp trạng thái nào.
        # Cả hai đều KHÔNG có tiến trình nào đang chạy job này, nên hủy là
        # an vị ngay: không cần nhịp tim, không có gì để chờ.
        try:
            (base / "inbox" / f"{job_id}.json").unlink()
        except FileNotFoundError:
            pass
        _write_status(
            base,
            job_id,
            status="cancelled",
            percent=100,
            step="done",
            detail="Job cancelled before worker start",
        )
        _clear_heartbeat(base, job_id)
        return True
    if status.get("status") == "running" and not _running_for(base, job_id):
        # Job mồ côi: tệp nằm trong running/ mà KHÔNG còn ai chạy nó (app bị
        # giết cứng, hoặc luồng worker đã chết vì lỗi). Không ghi trạng thái
        # kết thúc ở đây thì batch kẹt vĩnh viễn ở "running": không API nào
        # cứu được, vì "running" không nằm trong nhóm đáng thử lại.
        try:
            (base / "inbox" / f"{job_id}.json").unlink()
        except FileNotFoundError:
            pass
        _write_status(
            base,
            job_id,
            status="cancelled",
            percent=100,
            step="done",
            detail="Job cancelled while running",
            error="",
        )
        _clear_heartbeat(base, job_id)
        return True
    # Còn tiến trình sống: để worker tự thấy cờ hủy và tự ghi kết cục.
    return False


def settle_orphan_status(root, job_id: str) -> dict | None:
    """Job mồ côi thì đóng lại thành "interrupted"; trả status cũ (None nếu không phải).

    Dùng chung cho mọi chỗ cần trả lời "job này còn ai chạy thật không?".
    """
    base = _root(str(root))
    try:
        status = json.loads(
            (base / "status" / f"{job_id}.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(status, dict):
        return None
    if status.get("status") != "running" or _running_for(base, job_id):
        return None
    return status


def _write_status(root: Path, job_id: str, **changes) -> None:
    path = root / "status" / f"{job_id}.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current = {"job_id": job_id}
    current.update(changes)
    _atomic_json(path, current)


def run_worker(root: str, settings, stop_event=None, poll_s: float = 1.0) -> None:
    """Process queued jobs serially until ``stop_event`` is set."""
    from autodub.pipeline import DubPipeline

    base = _root(root)
    (base / "inbox").mkdir(parents=True, exist_ok=True)
    while stop_event is None or not stop_event.is_set():
        jobs = sorted((base / "inbox").glob("*.json"))
        if not jobs:
            time.sleep(poll_s)
            continue
        inbox_path = jobs[0]
        job_id = inbox_path.stem
        running_path = base / "running" / inbox_path.name
        running_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(inbox_path, running_path)
        except OSError:
            continue
        cancel_event = None
        watcher = None
        cancel_reason = None
        beat_stop = None
        beat_thread = None
        # Phải gán TRƯỚC khối try: nhánh except PipelineCancelled đọc biến
        # này, mà vài câu lệnh đầu khối try (đọc tệp, dựng request, dựng
        # settings) đều có thể ném. Thiếu dòng này, lệnh hủy ném từ đó làm
        # worker chết bằng NameError và job kẹt vĩnh viễn ở 'running'.
        reason_box = ["user"]
        try:
            # Nhịp tim TRƯỚC tiên: từ giây phút job nằm trong running/ nó
            # phải có tín hiệu sống thật, kể cả khi tệp job hỏng hay dựng
            # request/settings ném — nếu không, job vừa nhận đã bị coi là mồ
            # côi. Luồng đập nhịp dừng ở finally phía dưới, nên luồng worker
            # chết vì bất cứ lý do gì thì nhịp cũng tắt theo.
            beat_stop, beat_thread = start_heartbeat(base, job_id)
            payload = _validate_job(json.loads(running_path.read_text(encoding="utf-8")))
            _write_status(base, job_id, status="running", step="pipeline")
            request = request_from_payload(payload)
            job_settings = settings_from_payload(payload, settings)
            scope = f"openclaw_{job_id}"
            cancel_event = threading.Event()
            # Hộp đựng dùng chung: luồng theo dõi ghi LÝ DO hủy, luồng chính
            # đọc lại. Tắt ứng dụng không phải người dùng hủy.
            watcher = threading.Thread(
                target=_watch_cancel,
                args=(base, job_id, cancel_event, stop_event, scope, reason_box),
                daemon=True,
            )
            watcher.start()

            def on_progress(event, job_id=job_id):
                percent = round(
                    (event.current / event.total) * 100
                    if event.total else 0
                )
                _write_status(
                    base, job_id, status="running", step=event.step,
                    percent=percent, detail=event.detail,
                )

            with cancel_scope(scope):
                result = DubPipeline(
                    job_settings, progress=on_progress, cancel_event=cancel_event,
                ).run(request)
            cancel_reason = reason_box[0]
            if cancel_reason == "shutdown":
                # Ứng dụng tắt giữa chừng — không phải người dùng hủy. Ghi
                # trạng thái chạy tiếp được để lần mở sau retry-failed chạy
                # tiếp đúng thư mục cũ, thay vì "cancelled" vĩnh viễn.
                _write_status(
                    base,
                    job_id, status="interrupted",
                    step="interrupted",
                    detail="Ứng dụng đã tắt khi job đang chạy — chạy tiếp được",
                    error="",
                )
            else:
                final_status = ("cancelled" if cancel_event.is_set()
                                else result.status)
                _write_status(
                    base,
                    job_id, status=final_status,
                    percent=100,
                    step="done",
                    output=result.report,
                )
        except PipelineCancelled:
            if cancel_reason is None:
                cancel_reason = reason_box[0] if reason_box else "user"
            if cancel_reason == "shutdown":
                _write_status(
                    base,
                    job_id, status="interrupted",
                    step="interrupted",
                    detail="Ứng dụng đã tắt khi job đang chạy — chạy tiếp được",
                    error="",
                )
            else:
                # Người dùng chủ động hủy là một KẾT CỤC, không phải lỗi.
                _write_status(
                    base,
                    job_id, status="cancelled",
                    percent=100,
                    step="done",
                    error="",
                )
        except Exception as exc:
            _write_status(base, job_id, status="failed", error=str(exc))
        finally:
            if cancel_event is not None:
                cancel_event.set()
            if watcher is not None:
                watcher.join(timeout=1.0)
            # Tắt nhịp TRƯỚC khi dọn tệp: để lại một tệp nhịp tim đã cũ là
            # gieo một job "trông như đang sống" cho lần quét sau.
            if beat_stop is not None:
                beat_stop.set()
            if beat_thread is not None:
                beat_thread.join(timeout=1.0)
            _clear_heartbeat(base, job_id)
            try:
                running_path.unlink()
            except OSError:
                pass


def _watch_cancel(root: Path, job_id: str, cancel_event, stop_event,
                  scope: str | None = None, reason_box: list | None = None) -> None:
    marker = root / "cancel" / job_id
    while not cancel_event.is_set():
        if marker.exists() or (stop_event is not None and stop_event.is_set()):
            if reason_box is not None:
                reason_box[0] = ("user" if marker.exists()
                                 else "shutdown")
            cancel_event.set()
            if scope:
                cancel_processes(scope=scope)
            return
        time.sleep(0.25)
