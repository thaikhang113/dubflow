"""Tải và cài đặt thư viện giọng đọc.

Bộ giọng mẫu đi kèm sẵn trong repo tại ``voices/preset_voices_vn/`` nên
thường chỉ cần bước enroll. Module này lo cả hai việc: tải ``voices.zip``
từ GitHub release khi thư mục trống, rồi enroll toàn bộ giọng vào
``custom_voices.json`` qua VieNeu worker.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from autodub.config import Settings
from autodub.utils import app_root, setup_logging

logger = setup_logging("autodub.voice_downloader")

# URL voices.zip trên GitHub release — chỉ dùng khi thư mục voices/ trống
# (bản đóng gói exe, hoặc người dùng tải mã nguồn dạng zip thiếu thư mục).
VOICES_RELEASE_URL = "https://github.com/ttthanh2044/voxdub/releases/download/voices-v1.0.0/preset_voices_vn.zip"
VOICES_TARGET_DIR = "voices/preset_voices_vn"
MANIFEST_NAME = "voices_manifest.json"


def voices_installed(settings: Settings) -> bool:
    """Kiểm tra xem voice library đã được tải và enrolled chưa."""
    voices_dir = os.path.join(app_root(), VOICES_TARGET_DIR)
    manifest = os.path.join(voices_dir, MANIFEST_NAME)
    if not os.path.isfile(manifest):
        return False
    # Kiểm tra có giọng enrolled trong custom_voices.json chưa
    custom_path = settings.vieneu_custom_voices_path()
    if not os.path.isfile(custom_path):
        return False
    try:
        with open(custom_path, encoding="utf-8") as f:
            data = json.load(f)
        presets = data.get("presets", {})
        # Coi như đã cài nếu có ít nhất 50 giọng (thư viện có 120)
        return len(presets) >= 50
    except Exception:
        return False


def download_voices(progress_callback=None) -> str:
    """Tải voices.zip từ GitHub về thư mục tạm.

    Args:
        progress_callback: hàm nhận (bytes_downloaded, total_bytes)

    Returns:
        Đường dẫn file zip đã tải
    """
    logger.info(f"Đang tải voice library từ {VOICES_RELEASE_URL}...")

    temp_zip = os.path.join(tempfile.gettempdir(), "voxdub_voices.zip")

    def _report(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if progress_callback:
            progress_callback(downloaded, total_size)

    urllib.request.urlretrieve(VOICES_RELEASE_URL, temp_zip, _report)
    logger.info(f"Đã tải xong: {temp_zip}")
    return temp_zip


def extract_voices(zip_path: str) -> str:
    """Giải nén voices.zip vào voices/preset_voices_vn/.

    Target là voices/preset_voices_vn/ — nếu zip chứa subfolder preset_voices_vn/
    thì hoist nội dung lên, tránh double-nesting.

    Returns:
        Đường dẫn thư mục đã giải nén
    """
    target = os.path.join(app_root(), VOICES_TARGET_DIR)

    logger.info(f"Đang giải nén voices.zip...")

    with tempfile.TemporaryDirectory() as tmp:
        # Extract toàn bộ vào temp trước
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)

        # Kiểm tra cấu trúc: nếu temp chỉ có 1 thư mục duy nhất → đó là root
        items = os.listdir(tmp)
        if len(items) == 1 and os.path.isdir(os.path.join(tmp, items[0])):
            # Zip có wrapper folder (preset_voices_vn/) → lấy nội dung bên trong
            src = os.path.join(tmp, items[0])
        else:
            # Zip chứa thẳng file → dùng temp làm src
            src = tmp

        # Move nội dung vào target
        os.makedirs(target, exist_ok=True)
        for item in os.listdir(src):
            src_path = os.path.join(src, item)
            dst_path = os.path.join(target, item)
            # Xóa nếu đã tồn tại (overwrite)
            if os.path.exists(dst_path):
                if os.path.isdir(dst_path):
                    shutil.rmtree(dst_path)
                else:
                    os.remove(dst_path)
            shutil.move(src_path, dst_path)

    # Rename manifest nếu cần
    for variant in ("voices_manifest_vn.json", "voices_manifest_vi.json"):
        old_manifest = os.path.join(target, variant)
        new_manifest = os.path.join(target, MANIFEST_NAME)
        if os.path.isfile(old_manifest) and not os.path.isfile(new_manifest):
            shutil.move(old_manifest, new_manifest)
            break

    logger.info(f"Đã giải nén {len(os.listdir(target))} file vào {target}")
    return target


def enroll_voices(settings: Settings, progress_callback=None) -> dict:
    """Enroll tất cả giọng trong voices/ vào custom_voices.json.

    Args:
        progress_callback: hàm nhận (current, total, voice_name)

    Returns:
        {"ok": bool, "added": list, "failed": list}
    """
    from autodub.speech.tts import voice_library
    from autodub.speech.tts.vieneu_vi import _WORKER_SCRIPT

    pending = voice_library.pending(settings)
    if not pending:
        logger.info("Không có giọng nào cần enroll")
        return {"ok": True, "added": [], "failed": []}

    logger.info(f"Đang enroll {len(pending)} giọng...")

    # Tạo batch list JSON
    batch_list = [v.to_batch_item() for v in pending]
    batch_file = os.path.join(tempfile.gettempdir(), "voxdub_enroll_batch.json")
    with open(batch_file, "w", encoding="utf-8") as f:
        json.dump(batch_list, f, ensure_ascii=False)

    try:
        return _run_enroll_worker(settings, batch_file, progress_callback)
    finally:
        # Dọn file tạm dù enroll thành công hay ném lỗi giữa chừng.
        try:
            os.remove(batch_file)
        except OSError:
            pass


def _run_enroll_worker(settings: Settings, batch_file: str,
                       progress_callback=None) -> dict:
    """Chạy worker enroll một lượt; caller lo việc dọn ``batch_file``."""
    from autodub.speech.tts.vieneu_vi import _WORKER_SCRIPT

    # Gọi vieneu_worker.py --enroll-batch
    cmd = [
        settings.vieneu_venv_python_path(),
        _WORKER_SCRIPT,
        "--enroll-batch", batch_file,
        "--model-dir", settings.vieneu_model_dir_path(),
        "--custom-voices", settings.vieneu_custom_voices_path(),
        "--style", "tu_nhien",
    ]

    logger.info(f"Chạy worker: {' '.join(cmd[:3])}...")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )

    import threading

    # Đọc stderr trong thread riêng để track progress (KHÔNG dùng communicate()
    # khi đã có thread đọc stderr — hai bên sẽ tranh nhau pipe và gây lỗi).
    def _read_stderr():
        try:
            for line in proc.stderr:
                if not progress_callback:
                    continue
                # Worker ghi: "[vieneu-worker] (12/120) đang học giọng «Tên»"
                if "đang học giọng" in line and "/" in line:
                    try:
                        parts = line.split("(")[1].split(")")[0].split("/")
                        current = int(parts[0])
                        total = int(parts[1])
                        name = line.split("«")[1].split("»")[0] if "«" in line else ""
                        progress_callback(current, total, name)
                    except Exception:
                        pass
        except (ValueError, OSError):
            pass  # pipe bị đóng khi process kết thúc

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

    # Đọc stdout trực tiếp (worker chỉ ghi đúng một dòng JSON kết quả rồi thoát)
    try:
        stdout = proc.stdout.read()
        proc.wait(timeout=3600)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return {"ok": False, "error": "Timeout sau 1 giờ chờ enroll"}
    finally:
        stderr_thread.join(timeout=5)

    try:
        result = json.loads(stdout.strip())
    except json.JSONDecodeError:
        logger.error(f"Worker output không phải JSON: {stdout[:200]}")
        return {"ok": False, "error": "Worker output hỏng"}

    if result.get("ok"):
        logger.info(f"Đã enroll {len(result.get('added', []))} giọng")
        # Danh mục giọng vừa đổi — bỏ cache để giao diện thấy giọng mới ngay.
        from autodub.speech.tts.voices import invalidate_catalog_cache
        invalidate_catalog_cache()
    else:
        logger.error(f"Enroll thất bại: {result}")

    return result


def ensure_voices_available(settings: Settings, progress_callback=None) -> bool:
    """Đảm bảo voice library đã sẵn sàng (tải + enroll nếu chưa có).

    Nếu zip đóng kèm ``custom_voices.json`` (embeddings tính sẵn), bước enroll
    bị bỏ qua hoàn toàn — app mở ngay mà không cần chờ mã hóa 120 giọng.

    Args:
        progress_callback: hàm nhận các event:
            ("download_start", None, None)
            ("download_progress", bytes_downloaded, total_bytes)
            ("extract_start", None, None)
            ("enroll_start", total_voices, None)
            ("enroll_progress", current, total, voice_name)
            ("done", None, None)

    Returns:
        True nếu thành công
    """
    if voices_installed(settings):
        logger.info("Voice library đã được cài đặt")
        return True

    try:
        # 1. Tải voices.zip
        if progress_callback:
            progress_callback("download_start", None, None)

        def _dl_progress(downloaded, total):
            if progress_callback:
                progress_callback("download_progress", downloaded, total)

        zip_path = download_voices(_dl_progress)

        # 2. Giải nén — xoá zip tạm dù giải nén thành công hay lỗi.
        if progress_callback:
            progress_callback("extract_start", None, None)
        try:
            voices_dir = extract_voices(zip_path)
        finally:
            try:
                os.remove(zip_path)
            except OSError:
                pass

        # 3. Dùng embeddings đóng sẵn nếu zip kèm custom_voices.json —
        #    bỏ qua bước enroll (chạy ONNX model × 120 giọng) tốn nhiều phút.
        #    Embeddings là hằng số: cùng model + cùng WAV → cùng kết quả trên
        #    mọi máy, không cần tính lại.
        bundled_json = os.path.join(voices_dir, "custom_voices.json")
        custom_path = settings.vieneu_custom_voices_path()
        if os.path.isfile(bundled_json) and os.path.abspath(bundled_json) != os.path.abspath(custom_path):
            os.makedirs(os.path.dirname(custom_path), exist_ok=True)
            shutil.copy2(bundled_json, custom_path)
            from autodub.speech.tts.voices import invalidate_catalog_cache
            invalidate_catalog_cache()
            logger.info("Dùng embeddings đóng sẵn — bỏ qua bước enroll")
            if progress_callback:
                progress_callback("done", None, None)
            return True

        # 4. Fallback: enroll thủ công (khi zip cũ không kèm embeddings)
        if progress_callback:
            from autodub.speech.tts import voice_library
            pending_count = len(voice_library.pending(settings))
            progress_callback("enroll_start", pending_count, None)

        def _enroll_progress(current, total, name):
            if progress_callback:
                progress_callback("enroll_progress", current, total, name)

        result = enroll_voices(settings, _enroll_progress)

        if progress_callback:
            progress_callback("done", None, None)

        return result.get("ok", False)

    except Exception as e:
        logger.error(f"Lỗi khi cài đặt voice library: {e}", exc_info=True)
        if progress_callback:
            progress_callback("error", str(e), None)
        return False
