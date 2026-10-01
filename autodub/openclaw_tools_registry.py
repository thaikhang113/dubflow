"""Tool registry for OpenClaw dynamic app control."""
from __future__ import annotations

import math
import os
import re
from typing import Any, Callable

from dotenv import set_key

from autodub.config import Settings
from autodub.utils import data_root

#: Tên biến môi trường hợp lệ. Siết chặt vì dotenv.set_key KHÔNG trích dẫn tên
#: khoá: một tên chứa ký tự xuống dòng sẽ đẻ ra khoá mới trong .env, vòng qua
#: mọi danh sách trắng.
_ENV_KEY_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9_]*\Z")

#: Ký tự điều khiển bị cấm trong giá trị (tab được phép). Xuống dòng thật sẽ phá
#: cấu trúc tệp .env; muốn ngắt dòng thì gửi chuỗi \n như .env vẫn lưu.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

#: Trần độ dài giá trị chuỗi — rộng cho ngữ cảnh dịch dài, vẫn có chặn trên.
_MAX_TEXT = 8000

_TRUE_WORDS = ("true", "1", "yes", "on")
_FALSE_WORDS = ("false", "0", "no", "off")


def _as_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and value in (0, 1):
        return "true" if value else "false"
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_WORDS:
            return "true"
        if text in _FALSE_WORDS:
            return "false"
    raise ValueError(f"cần true/false, nhận {value!r}")


def _as_float(low: float, high: float) -> Callable[[Any], str]:
    def coerce(value: Any) -> str:
        if isinstance(value, bool):
            raise ValueError(f"cần số, nhận {value!r}")
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            try:
                number = float(value.strip())
            except ValueError:
                raise ValueError(f"cần số, nhận {value!r}") from None
        else:
            raise ValueError(f"cần số, nhận {value!r}")
        if not math.isfinite(number):
            raise ValueError(f"cần số hữu hạn, nhận {value!r}")
        if not low <= number <= high:
            raise ValueError(f"phải trong khoảng {low}-{high}, nhận {number}")
        return repr(number)

    return coerce


def _as_choice(*allowed: str) -> Callable[[Any], str]:
    def coerce(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError(f"cần chuỗi, nhận {value!r}")
        text = value.strip().lower()
        if text not in allowed:
            raise ValueError(
                f"phải là một trong {', '.join(allowed)}; nhận {value!r}"
            )
        return text

    return coerce


def _as_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"cần chuỗi, nhận {value!r}")
    text = value.strip()
    if _CONTROL_RE.search(text):
        raise ValueError("không được chứa ký tự điều khiển hoặc xuống dòng")
    if len(text) > _MAX_TEXT:
        raise ValueError(f"dài quá {_MAX_TEXT} ký tự")
    return text


#: Danh sách trắng khoá được ghi vào .env, kèm hàm ép kiểu và miền giá trị.
#: Cố ý trùng ĐÚNG tám khoá mà get_settings trả về — đọc được gì thì ghi được
#: nấy. Mọi khoá khác (TRANSLATION_ENDPOINT, TRANSLATION_API_KEY,
#: BILIBILI_COOKIES_FILE, các *_PATH, ...) đều bị từ chối.
_WRITABLE: dict[str, Callable[[Any], str]] = {
    "TRANSLATE_ENABLED": _as_bool,
    "TRANSLATE_DOMAIN": _as_text,
    "TRANSLATE_CONTEXT": _as_text,
    "SUBTITLE_MODE": _as_choice("none", "soft", "burn"),
    "QUALITY_PRESET": _as_choice("fast", "balanced", "quality"),
    "VIENEU_VOICE": _as_text,
    "VIDEO_SPEED": _as_float(0.5, 1.0),
    "VOICE_SPEED": _as_float(0.5, 2.0),
    "VIENEU_PRECISION": _as_choice("fp32", "int8"),
    "VSR_ENABLED": _as_bool,
    "VSR_MODE": _as_choice("sttn-det", "sttn", "propainter"),
}


def get_settings(*args, settings: Settings | None = None, **kwargs) -> dict[str, Any]:
    """Get current application settings."""
    settings = Settings.load(override=True)
    return {
        "ok": True,
        "settings": {
            "translate_enabled": settings.translate_enabled,
            "translate_domain": settings.translate_domain,
            "translate_context": settings.translate_context,
            "subtitle_mode": settings.subtitle_mode,
            "quality_preset": settings.quality_preset,
            "vieneu_voice": settings.vieneu_voice,
            "video_speed": settings.video_speed,
            "voice_speed": settings.voice_speed,
            "vieneu_precision": getattr(settings, "vieneu_precision", "fp32"),
            "vsr_enabled": getattr(settings, "vsr_enabled", True),
            "vsr_mode": getattr(settings, "vsr_mode", "sttn-det"),
        }
    }


def update_settings(updates: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
    """Update application settings — chỉ những khoá trong _WRITABLE.

    Kiểm tra TOÀN BỘ lô trước khi ghi câu nào, nên một lô lẫn khoá bị từ chối sẽ
    không để lại thay đổi dở dang nào trong .env.
    """
    if not isinstance(updates, dict):
        raise TypeError("updates phải là đối tượng key-value")
    if not updates:
        raise ValueError("updates rỗng: không có gì để cập nhật")

    problems: list[str] = []
    normalized: dict[str, Any] = {}

    for key, value in updates.items():
        if not isinstance(key, str) or not _ENV_KEY_RE.match(key.strip()):
            problems.append(f"tên khoá không hợp lệ: {key!r}")
            continue
        env_key = key.strip().upper()
        if env_key not in _WRITABLE:
            problems.append(f"khoá không nằm trong danh sách trắng: {env_key}")
            continue
        normalized[env_key] = value

    resolved: dict[str, str] = {}
    for env_key, value in normalized.items():
        try:
            resolved[env_key] = _WRITABLE[env_key](value)
        except ValueError as exc:
            problems.append(f"{env_key}: {exc}")

    if problems:
        raise ValueError(
            "; ".join(problems)
            + ". Khoá được phép: " + ", ".join(sorted(_WRITABLE))
        )

    env_path = os.path.join(data_root(), ".env")
    if not os.path.exists(env_path):
        open(env_path, "a", encoding="utf-8").close()

    for env_key, val_str in resolved.items():
        set_key(env_path, env_key, val_str)

    # Reload settings to ensure they take effect
    Settings.load(override=True)
    return {"ok": True, "updated_keys": list(resolved)}


def list_voices(*args, settings: Settings, **kwargs) -> dict[str, Any]:
    """List available voices for dubbing."""
    try:
        from autodub.speech.tts.voices import catalog
        voices = catalog(settings)
        return {
            "ok": True, 
            "voices": [
                {
                    "name": v.name, 
                    "gender": v.gender, 
                    "region": v.region
                } for v in voices
            ]
        }
    except Exception as exc:
        return {"ok": False, "error": f"Failed to list voices: {exc}"}


def get_system_status(*args, **kwargs) -> dict[str, Any]:
    """Get system resource status (RAM, CPU)."""
    from autodub.sysinfo import available_ram_gb
    
    return {
        "ok": True,
        "cpu_cores": os.cpu_count(),
        "ram_gb_free": available_ram_gb(),
    }


def update_vieneu(*args, **kwargs) -> dict[str, Any]:
    """Cập nhật VieNeu TTS lên phiên bản mới nhất và làm mới danh sách giọng."""
    import subprocess
    import sys
    from autodub.utils import app_root, data_root

    script_path = os.path.join(app_root(), "scripts", "setup_vieneu.py")
    if not os.path.isfile(script_path):
        return {"ok": False, "error": f"Không tìm thấy script: {script_path}"}

    data_dir = data_root()
    env = dict(os.environ)
    env["DUBFLOW_DATA_DIR"] = data_dir
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    try:
        proc = subprocess.run(
            [sys.executable, script_path, "--upgrade"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=data_dir,
            env=env,
            timeout=600,
            creationflags=flags,
            check=False,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-1000:]
            return {
                "ok": False,
                "error": f"Cập nhật VieNeu thất bại (mã lỗi {proc.returncode}): {tail}",
            }
        return {
            "ok": True,
            "message": "Cập nhật VieNeu TTS thành công lên phiên bản mới nhất.",
            "output": (proc.stdout or "").strip()[-500:],
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def get_vsr_status(*args, settings: Settings | None = None, **kwargs) -> dict[str, Any]:
    """Kiểm tra tình trạng cài đặt và cấu hình của bộ Video Subtitle Remover (VSR)."""
    settings = Settings.load(override=True)
    python_path = settings.vsr_venv_python_path()
    worker_script = settings.vsr_worker_path()
    model_dir = settings.vsr_model_dir_path()
    marker = os.path.join(model_dir, "installed_ok.json")

    has_python = os.path.isfile(python_path)
    has_worker = os.path.isfile(worker_script)
    has_marker = os.path.isfile(marker)
    is_configured = settings.vsr_configured()

    return {
        "ok": True,
        "vsr": {
            "configured": is_configured,
            "enabled": settings.vsr_enabled,
            "mode": settings.vsr_mode,
            "python_installed": has_python,
            "worker_installed": has_worker,
            "model_ready": has_marker,
            "model_dir": model_dir,
            "python_path": python_path if has_python else "",
        },
        "message": (
            "Video Subtitle Remover đã sẵn sàng."
            if is_configured and settings.vsr_enabled
            else "VSR chưa được cài đặt đầy đủ hoặc đang bị tắt trong cài đặt."
        ),
    }


def apply_blur_boxes(
    video_path: str,
    regions: list[dict],
    output_path: str = "",
    *args,
    **kwargs,
) -> dict[str, Any]:
    """Bôi mờ các vùng chỉ định (phụ đề, watermark, logo) trên video bằng FFmpeg filter."""
    from autodub.utils import app_root, data_root, ensure_bin_in_path
    from autodub.media.subtitle import build_filter_complex
    from autodub.media.video import probe_dimensions, video_codec_args
    from autodub.cancel import run_registered

    ensure_bin_in_path()

    if not isinstance(video_path, str) or not video_path.strip():
        return {"ok": False, "error": "video_path không được để trống"}

    resolved_video = video_path.strip()
    if not os.path.isabs(resolved_video):
        for candidate_root in (data_root(), app_root(), os.getcwd()):
            cand = os.path.join(candidate_root, resolved_video)
            if os.path.isfile(cand):
                resolved_video = cand
                break

    if not os.path.isfile(resolved_video):
        return {"ok": False, "error": f"Không tìm thấy tệp video: {video_path}"}

    if not isinstance(regions, list) or not regions:
        return {"ok": False, "error": "regions phải là danh sách ít nhất 1 vùng tọa độ"}

    norm_regions = []
    for r in regions:
        if not isinstance(r, dict):
            continue
        try:
            x = max(0.0, min(1.0, float(r.get("x", 0.0))))
            y = max(0.0, min(1.0, float(r.get("y", 0.0))))
            w = max(0.0, min(1.0 - x, float(r.get("w", 0.0))))
            h = max(0.0, min(1.0 - y, float(r.get("h", 0.0))))
        except (ValueError, TypeError):
            continue
        if w > 0 and h > 0:
            item = {"x": x, "y": y, "w": w, "h": h}
            if "t_start" in r and "t_end" in r:
                try:
                    item["t_start"] = float(r["t_start"])
                    item["t_end"] = float(r["t_end"])
                except (ValueError, TypeError):
                    pass
            norm_regions.append(item)

    if not norm_regions:
        return {"ok": False, "error": "Không có vùng tọa độ hợp lệ nào để bôi mờ"}

    if not output_path or not output_path.strip():
        base, ext = os.path.splitext(resolved_video)
        resolved_output = f"{base}_blurred{ext or '.mp4'}"
    else:
        resolved_output = output_path.strip()
        if not os.path.isabs(resolved_output):
            resolved_output = os.path.join(data_root(), resolved_output)

    os.makedirs(os.path.dirname(os.path.abspath(resolved_output)), exist_ok=True)
    temp_output = resolved_output + ".part.mp4"

    try:
        width, height = probe_dimensions(resolved_video)
        filter_complex = build_filter_complex(norm_regions, width, height)
        if not filter_complex:
            return {"ok": False, "error": "Không tạo được bộ lọc làm mờ cho các vùng đã chọn"}

        cmd = [
            "ffmpeg", "-y",
            "-i", resolved_video,
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a?",
            *video_codec_args(),
            "-c:a", "copy",
            "-movflags", "+faststart",
            temp_output,
        ]
        run_registered(cmd, capture_output=True, text=True, timeout=1200)

        if not os.path.isfile(temp_output) or os.path.getsize(temp_output) <= 0:
            return {"ok": False, "error": "FFmpeg chạy xong nhưng không tạo được tệp đầu ra"}

        if os.path.exists(resolved_output):
            os.remove(resolved_output)
        os.replace(temp_output, resolved_output)

        return {
            "ok": True,
            "output_path": resolved_output,
            "boxes_applied": len(norm_regions),
            "regions": norm_regions,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except OSError:
                pass


def remove_video_subtitles(
    video_path: str,
    output_path: str = "",
    regions: list[dict] | None = None,
    mode: str = "",
    fallback_to_blur: bool = True,
    *args,
    settings: Settings | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Xóa phụ đề cứng hoặc watermark trên video bằng AI (VSR) hoặc làm mờ (Blur)."""
    from autodub.utils import app_root, data_root
    from autodub.media.vsr import remove_subtitles

    settings = settings or Settings.load(override=True)

    if not isinstance(video_path, str) or not video_path.strip():
        return {"ok": False, "error": "video_path không được để trống"}

    resolved_video = video_path.strip()
    if not os.path.isabs(resolved_video):
        for candidate_root in (data_root(), app_root(), os.getcwd()):
            cand = os.path.join(candidate_root, resolved_video)
            if os.path.isfile(cand):
                resolved_video = cand
                break

    if not os.path.isfile(resolved_video):
        return {"ok": False, "error": f"Không tìm thấy tệp video: {video_path}"}

    if not regions:
        regions = [{"x": 0.0, "y": 0.75, "w": 1.0, "h": 0.25, "source": "ocr"}]

    norm_regions = []
    for r in regions:
        if not isinstance(r, dict):
            continue
        try:
            x = max(0.0, min(1.0, float(r.get("x", 0.0))))
            y = max(0.0, min(1.0, float(r.get("y", 0.0))))
            w = max(0.0, min(1.0 - x, float(r.get("w", 0.0))))
            h = max(0.0, min(1.0 - y, float(r.get("h", 0.0))))
        except (ValueError, TypeError):
            continue
        if w > 0 and h > 0:
            norm_regions.append({
                "x": x, "y": y, "w": w, "h": h,
                "source": r.get("source", "ocr"),
            })

    if not norm_regions:
        return {"ok": False, "error": "Không có vùng tọa độ hợp lệ"}

    if not output_path or not output_path.strip():
        base, ext = os.path.splitext(resolved_video)
        resolved_output = f"{base}_nosub{ext or '.mp4'}"
    else:
        resolved_output = output_path.strip()
        if not os.path.isabs(resolved_output):
            resolved_output = os.path.join(data_root(), resolved_output)

    os.makedirs(os.path.dirname(os.path.abspath(resolved_output)), exist_ok=True)

    if settings.vsr_configured() and settings.vsr_enabled:
        temp_vsr_output = resolved_output + ".vsr.mp4"
        try:
            vsr_result = remove_subtitles(
                resolved_video,
                temp_vsr_output,
                norm_regions,
                settings,
                fallback=lambda: "",
            )
            if vsr_result.used_vsr and os.path.isfile(temp_vsr_output) and os.path.getsize(temp_vsr_output) > 0:
                if os.path.exists(resolved_output):
                    os.remove(resolved_output)
                os.replace(temp_vsr_output, resolved_output)
                return {
                    "ok": True,
                    "output_path": resolved_output,
                    "method": "vsr",
                    "regions": norm_regions,
                    "message": "Đã xóa phụ đề cứng bằng AI (Video Subtitle Remover).",
                }
        finally:
            if os.path.exists(temp_vsr_output):
                try:
                    os.remove(temp_vsr_output)
                except OSError:
                    pass

    if fallback_to_blur:
        blur_res = apply_blur_boxes(resolved_video, norm_regions, resolved_output)
        if blur_res.get("ok"):
            return {
                "ok": True,
                "output_path": resolved_output,
                "method": "blur_fallback",
                "regions": norm_regions,
                "message": "Đã che phụ đề cứng bằng bộ lọc làm mờ (VSR chưa sẵn sàng hoặc không áp dụng được).",
            }
        return blur_res

    return {
        "ok": False,
        "error": "VSR chưa được cài đặt hoặc gặp lỗi và tính năng fallback bị tắt.",
    }


def setup_vsr(*args, **kwargs) -> dict[str, Any]:
    """Cài đặt hoặc tải lại Video Subtitle Remover (VSR)."""
    import subprocess
    import sys
    from autodub.utils import app_root, data_root

    script_path = os.path.join(app_root(), "scripts", "setup_vsr.py")
    if not os.path.isfile(script_path):
        return {"ok": False, "error": f"Không tìm thấy script: {script_path}"}

    data_dir = data_root()
    env = dict(os.environ)
    env["DUBFLOW_DATA_DIR"] = data_dir
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    try:
        proc = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=data_dir,
            env=env,
            timeout=1200,
            creationflags=flags,
            check=False,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-1000:]
            return {
                "ok": False,
                "error": f"Cài đặt VSR thất bại (mã lỗi {proc.returncode}): {tail}",
            }
        return {
            "ok": True,
            "message": "Cài đặt Video Subtitle Remover thành công.",
            "output": (proc.stdout or "").strip()[-500:],
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


_REGISTRY = {
    "get_vsr_status": get_vsr_status,
    "apply_blur_boxes": apply_blur_boxes,
    "remove_video_subtitles": remove_video_subtitles,
    "setup_vsr": setup_vsr,
    "update_vieneu": update_vieneu,
    "get_settings": get_settings,
    "update_settings": update_settings,
    "list_voices": list_voices,
    "get_system_status": get_system_status,
}


def dispatch_tool(name: str | None, arguments: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
    if not name:
        raise ValueError("Tool name is required")
    func = _REGISTRY.get(name)
    if not func:
        raise ValueError(f"Tool not found: {name}")
    try:
        return func(**arguments, settings=settings)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
