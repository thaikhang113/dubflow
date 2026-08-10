"""Workers chạy nền cho wizard cài đặt lần đầu.

``FFmpegDownloadWorker`` — tải FFmpeg static build từ GitHub về ``<app_root>/bin/``.
``SetupScriptWorker``    — chạy scripts/setup_*.py và stream stdout ra GUI.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

from PySide6.QtCore import QThread, Signal

from autodub.utils import app_root
from autodub_gui.status_text import STATUS_ERROR, STATUS_OK

# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #

def _patch_path(bin_dir: str) -> None:
    """Thêm bin_dir vào PATH của tiến trình hiện tại (idempotent)."""
    path = os.environ.get("PATH", "")
    if bin_dir.lower() not in path.lower():
        os.environ["PATH"] = bin_dir + os.pathsep + path


#: Chạy tiến trình con không bật cửa sổ console đen (Windows).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


#: Phiên bản Python được VieNeu / faster-whisper hỗ trợ, ưu tiên mới nhất.
#: Giữ khớp với thứ tự dò trong các file .bat do build_exe.py sinh ra —
#: 3.13+ chưa có wheel cho onnxruntime/ctranslate2 nên KHÔNG được chọn.
_SUPPORTED_PY = ("3.12", "3.11", "3.10")


def _probe_python(cmd: list[str]) -> str:
    """Trả về đường dẫn thật của trình thông dịch nếu chạy được, else ""."""
    try:
        out = subprocess.run(
            [*cmd, "-c", "import sys; print(sys.executable)"],
            capture_output=True, text=True, timeout=15,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if out.returncode != 0:
        return ""
    return (out.stdout or "").strip()


def _find_python() -> str:
    """Đường dẫn Python chạy được scripts/setup_*.py.

    Bản đóng gói: ``sys.executable`` là VoxDub.exe — không chạy được .py, nên
    phải mượn Python của máy. Bản dev: Python đang chạy app có thể là phiên
    bản quá mới (3.13+) so với các gói mà script cần cài, nên vẫn ưu tiên dò
    3.12/3.11/3.10 qua ``py`` launcher trước, giống các file .bat.
    """
    if sys.platform == "win32":
        for version in _SUPPORTED_PY:
            found = _probe_python(["py", f"-{version}"])
            if found:
                return found

    # Python đang chạy app — chỉ dùng khi bản thân nó được hỗ trợ.
    if not getattr(sys, "frozen", False):
        current = f"{sys.version_info[0]}.{sys.version_info[1]}"
        if current in _SUPPORTED_PY:
            return sys.executable

    for candidate in ("py", "python3", "python"):
        exe = shutil.which(candidate)
        if exe and _probe_python([exe]):
            return exe

    raise RuntimeError(
        "Không tìm thấy Python 3.10–3.12 trên máy. Hãy cài Python 3.12 từ "
        "python.org (nhớ tích 'Add python.exe to PATH') rồi bấm Thử lại.")


def _find_script(rel_path: str) -> str:
    """Tìm file script trong thư mục app hoặc thư mục bundle (_internal/data)."""
    root = app_root()
    for subdir in ("", "_internal", "data"):
        candidate = (os.path.join(root, subdir, rel_path)
                     if subdir else os.path.join(root, rel_path))
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        f"Không tìm thấy script '{rel_path}'. "
        "Hãy chạy từ thư mục chứa mã nguồn ứng dụng.")


# --------------------------------------------------------------------------- #
# FFmpegDownloadWorker
# --------------------------------------------------------------------------- #

# URL ffmpeg static build đầy đủ (có libass) — Windows 64-bit
_FFMPEG_URL = (
    "https://github.com/BtbN/ffmpeg-builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
_CHUNK = 65536   # 64 KB mỗi lần đọc


class FFmpegDownloadWorker(QThread):
    """Tải FFmpeg về <app_root>/bin/, giải nén, patch PATH."""

    progress = Signal(int)   # 0–100
    log      = Signal(str)   # dòng log hiển thị trong wizard
    finished_ok = Signal()
    failed      = Signal(str)

    def run(self) -> None:  # noqa: C901
        try:
            bin_dir = os.path.join(app_root(), "bin")
            ffmpeg_exe = os.path.join(bin_dir, "ffmpeg.exe")
            ffprobe_exe = os.path.join(bin_dir, "ffprobe.exe")

            # Nếu đã có sẵn thì bỏ qua tải
            if os.path.isfile(ffmpeg_exe) and os.path.isfile(ffprobe_exe):
                self.log.emit(f"{STATUS_OK} FFmpeg đã có sẵn — bỏ qua tải.")
                _patch_path(bin_dir)
                self.progress.emit(100)
                self.finished_ok.emit()
                return

            # Nếu ffmpeg có trên PATH hệ thống thì dùng luôn
            if shutil.which("ffmpeg") and shutil.which("ffprobe"):
                self.log.emit(f"{STATUS_OK} FFmpeg đã có trên PATH hệ thống.")
                self.progress.emit(100)
                self.finished_ok.emit()
                return

            os.makedirs(bin_dir, exist_ok=True)
            zip_path = os.path.join(bin_dir, "_ffmpeg_download.zip")

            # --- Tải file zip ---
            self.log.emit(f"Đang kết nối: {_FFMPEG_URL}")
            self.progress.emit(2)

            req = urllib.request.Request(
                _FFMPEG_URL,
                headers={"User-Agent": "VoxDub-Setup/1.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                buf = io.BytesIO()
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    buf.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded / total * 75)   # tải = 0–75%
                        self.progress.emit(pct)
                        mb = downloaded / 1_048_576
                        total_mb = total / 1_048_576
                        self.log.emit(
                            f"Đang tải: {mb:.1f} / {total_mb:.0f} MB")

            self.log.emit("Tải xong. Đang giải nén...")
            self.progress.emit(76)

            # --- Giải nén chỉ lấy ffmpeg.exe và ffprobe.exe ---
            buf.seek(0)
            with zipfile.ZipFile(buf) as zf:
                extracted = 0
                for info in zf.infolist():
                    name = info.filename.replace("\\", "/")
                    # Lấy ffmpeg.exe và ffprobe.exe từ bất kỳ subdir nào
                    basename = name.split("/")[-1]
                    if basename in ("ffmpeg.exe", "ffprobe.exe"):
                        dest = os.path.join(bin_dir, basename)
                        with zf.open(info) as src, open(dest, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        extracted += 1
                        self.log.emit(f"  Giải nén: {basename}")
                        self.progress.emit(76 + extracted * 10)
                        if extracted >= 2:
                            break

            # Xóa file zip tạm
            try:
                os.remove(zip_path)
            except OSError:
                pass

            if not os.path.isfile(ffmpeg_exe):
                raise RuntimeError("Không tìm thấy ffmpeg.exe trong file zip.")

            # Patch PATH cho lần chạy này
            _patch_path(bin_dir)
            self.log.emit(f"{STATUS_OK} FFmpeg đã cài vào: {bin_dir}")
            self.progress.emit(100)
            self.finished_ok.emit()

        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# --------------------------------------------------------------------------- #
# SetupScriptWorker
# --------------------------------------------------------------------------- #

# Số dòng ước tính mỗi script sinh ra — dùng để tính tiến độ xấp xỉ
_SCRIPT_LINES_ESTIMATE = {
    "setup_vieneu.py":    35,
    "setup_whisper.py":   25,
    "setup_paraformer.py": 30,
}


class SetupScriptWorker(QThread):
    """Chạy scripts/setup_*.py và stream stdout ra GUI."""

    progress    = Signal(int)   # 0–100
    log         = Signal(str)   # dòng log
    finished_ok = Signal()
    failed      = Signal(str)

    def __init__(self, script_rel: str, parent=None):
        super().__init__(parent)
        self._script_rel = script_rel   # ví dụ: "scripts/setup_vieneu.py"

    def run(self) -> None:
        try:
            script_path = _find_script(self._script_rel)
            python_exe  = _find_python()

            script_name = os.path.basename(self._script_rel)
            total_lines = _SCRIPT_LINES_ESTIMATE.get(script_name, 30)

            self.log.emit(f"Chạy: {script_name}")
            self.progress.emit(2)

            proc = subprocess.Popen(
                [python_exe, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=app_root(),
                creationflags=_NO_WINDOW,
            )

            lines_seen = 0
            tail: list[str] = []
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                if not line:
                    continue
                lines_seen += 1
                tail.append(line)
                if len(tail) > 200:
                    tail.pop(0)
                self.log.emit(line)
                pct = min(95, int(lines_seen / total_lines * 95))
                self.progress.emit(pct)

            proc.wait()
            if proc.returncode == 0:
                self.progress.emit(100)
                self.finished_ok.emit()
            else:
                err = "\n".join(tail[-20:]) if tail else "Không có output."
                self.failed.emit(
                    f"Script kết thúc với mã lỗi {proc.returncode}:\n{err}")

        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

