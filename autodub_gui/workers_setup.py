"""Workers chạy nền cho wizard cài đặt lần đầu.

``FFmpegDownloadWorker`` — tải FFmpeg static build từ GitHub về ``<app_root>/bin/``.
``SetupScriptWorker``    — chạy scripts/setup_*.py và stream stdout ra GUI.
"""
from __future__ import annotations

import os
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

from PySide6.QtCore import QThread, Signal

from autodub.doctor import run_doctor
from autodub.utils import app_root, data_root
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
_PORTABLE_PYTHON_DIR = ".python-runtime"
_PORTABLE_PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    "20260807/cpython-3.12.13%2B20260807-x86_64-unknown-linux-gnu-"
    "install_only_stripped.tar.gz"
)
_PORTABLE_PYTHON_SHA256 = (
    "506191be3ee7bd190a8834dcdc1b3bc70aab50608deccc711935aa007239cabd"
)

def _portable_python() -> str:
    root = os.path.join(data_root(), _PORTABLE_PYTHON_DIR)
    candidate = os.path.join(root, "bin", "python3")
    return candidate if os.path.isfile(candidate) else ""

def _download_portable_python(log, progress) -> str:
    os.makedirs(data_root(), exist_ok=True)
    root = os.path.join(data_root(), _PORTABLE_PYTHON_DIR)
    archive_path = os.path.join(data_root(), "_python-runtime.tar.gz")
    temp_root = tempfile.mkdtemp(prefix="dubflow-python-", dir=data_root())
    try:
        log("Đang tải Python runtime portable cho Linux...")
        digest = hashlib.sha256()
        request = urllib.request.Request(
            _PORTABLE_PYTHON_URL,
            headers={"User-Agent": "DubFlow-Setup/1.0"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(archive_path, "wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if total:
                        progress(min(90, int(downloaded * 90 / total)))
        if digest.hexdigest() != _PORTABLE_PYTHON_SHA256:
            raise RuntimeError("Python runtime tải về không khớp SHA256.")

        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                target = os.path.realpath(os.path.join(temp_root, member.name))
                if not target.startswith(os.path.realpath(temp_root) + os.sep):
                    raise RuntimeError("Python runtime có đường dẫn archive không an toàn.")
            archive.extractall(temp_root)
        os.makedirs(os.path.dirname(root), exist_ok=True)
        if os.path.isdir(root):
            shutil.rmtree(root)
        shutil.move(os.path.join(temp_root, "python"), root)
        result = _portable_python()
        if not result:
            raise RuntimeError("Không tìm thấy Python executable sau khi giải nén.")
        progress(100)
        return result
    finally:
        try:
            os.remove(archive_path)
        except OSError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def _probe_python(cmd: list[str]) -> str:
    """Trả về đường dẫn thật của trình thông dịch nếu chạy được, else ""."""
    try:
        out = subprocess.run(
            [*cmd, "-c",
             "import sys; "
             "print(sys.executable if (3, 10) <= sys.version_info[:2] <= "
             "(3, 12) else '')"],
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

    Bản đóng gói: ``sys.executable`` là DubFlow.exe — không chạy được .py, nên
    phải mượn Python của máy. Bản dev: Python đang chạy app có thể là phiên
    bản quá mới (3.13+) so với các gói mà script cần cài, nên vẫn ưu tiên dò
    3.12/3.11/3.10 qua ``py`` launcher trước, giống các file .bat.
    """
    if sys.platform != "win32":
        portable = _portable_python()
        if portable and _probe_python([portable]):
            return portable

    if sys.platform == "win32":
        for version in _SUPPORTED_PY:
            found = _probe_python(["py", f"-{version}"])
            if found:
                return found
        candidates = (
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                         "Python", "Python312", "python.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                         "Python", "Python311", "python.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Python312",
                         "python.exe"),
        )
        for candidate in candidates:
            if os.path.isfile(candidate) and _probe_python([candidate]):
                return candidate

    # Python đang chạy app — chỉ dùng khi bản thân nó được hỗ trợ.
    if not getattr(sys, "frozen", False):
        current = f"{sys.version_info[0]}.{sys.version_info[1]}"
        if current in _SUPPORTED_PY:
            return sys.executable

    candidates = (
        "python3.12", "python3.11", "python3.10", "python3", "python"
    ) if sys.platform != "win32" else ()
    for candidate in candidates:
        exe = shutil.which(candidate)
        if exe and _probe_python([exe]):
            return exe

    raise RuntimeError(
        "Không tìm thấy Python 3.10–3.12 trên máy. Hãy cài Python 3.12 từ "
        "python.org (nhớ tích 'Add python.exe to PATH') rồi bấm Thử lại.")

class PythonRuntimeWorker(QThread):
    """Ensure external Python exists for first-run setup scripts."""

    progress = Signal(int)
    log = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def run(self) -> None:
        try:
            try:
                python = _find_python()
                self.log.emit(f"{STATUS_OK} Python đã sẵn sàng: {python}")
                self.progress.emit(100)
                self.finished_ok.emit()
                return
            except RuntimeError:
                pass

            if sys.platform == "win32":
                self.log.emit("Đang cài Python 3.12 qua winget...")
                self.progress.emit(10)
                command = [
                    "winget", "install", "--id", "Python.Python.3.12",
                    "--scope", "user", "--silent",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                ]
                proc = subprocess.run(
                    command, capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=900, creationflags=_NO_WINDOW,
                )
                if proc.returncode != 0:
                    tail = (proc.stderr or proc.stdout or "").strip()[-1200:]
                    raise RuntimeError(
                        f"winget cài Python thất bại ({proc.returncode}).\n{tail}")
            else:
                python = _download_portable_python(
                    self.log.emit, self.progress.emit)
                self.log.emit(f"{STATUS_OK} Python portable đã sẵn sàng: {python}")
                self.finished_ok.emit()
                return

            python = _find_python()
            self.log.emit(f"{STATUS_OK} Python đã sẵn sàng: {python}")
            self.progress.emit(100)
            self.finished_ok.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


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
_FFMPEG_URLS = {
    "win32": (
        "https://github.com/BtbN/ffmpeg-builds/releases/download/latest/"
        "ffmpeg-master-latest-win64-gpl.zip"
    ),
}
_FFMPEG_CHECKSUMS_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "checksums.sha256"
)
_CHUNK = 65536   # 64 KB mỗi lần đọc

def _download_ffmpeg_archive(url: str, part_path: str, archive_name: str,
                             log, progress) -> None:
    """Download FFmpeg with retry; never promote a partial archive."""
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "DubFlow-Setup/1.0"})
            with urllib.request.urlopen(request, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(part_path, "wb") as archive_file:
                    while True:
                        chunk = resp.read(_CHUNK)
                        if not chunk:
                            break
                        archive_file.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = int(downloaded / total * 75)
                            progress(pct)
                            log(f"Đang tải: {downloaded / 1_048_576:.1f} / "
                                f"{total / 1_048_576:.0f} MB")
            return
        except Exception as exc:  # noqa: BLE001 - network boundary
            last_error = exc
            try:
                os.remove(part_path)
            except OSError:
                pass
            if attempt < 3:
                log(f"Tải FFmpeg lỗi, thử lại ({attempt}/3): {exc}")
    raise RuntimeError(
        f"Không tải được FFmpeg sau 3 lần thử ({archive_name}): {last_error}")

def _system_ffmpeg_pair(which=shutil.which) -> tuple[str, str] | None:
    """Return a complete system FFmpeg install, or None."""
    candidates = [(which("ffmpeg"), which("ffprobe"), False)]
    if sys.platform.startswith("linux"):
        for directory in ("/usr/bin", "/usr/local/bin", "/snap/bin"):
            candidates.append((
                os.path.join(directory, "ffmpeg"),
                os.path.join(directory, "ffprobe"),
                True,
            ))
    for ffmpeg, ffprobe, check_files in candidates:
        if (ffmpeg and ffprobe and
                (not check_files or (
                    os.path.isfile(ffmpeg) and os.path.isfile(ffprobe)
                    and os.access(ffmpeg, os.X_OK)
                    and os.access(ffprobe, os.X_OK)))):
            return ffmpeg, ffprobe
    return None

def _verify_ffmpeg_archive(path: str, archive_name: str) -> None:
    request = urllib.request.Request(
        _FFMPEG_CHECKSUMS_URL,
        headers={"User-Agent": "DubFlow-Setup/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        checksums = response.read().decode("utf-8", errors="replace")
    expected = ""
    for line in checksums.splitlines():
        fields = line.strip().split()
        if len(fields) >= 2 and fields[-1].lstrip("*") == archive_name:
            expected = fields[0].lower()
            break
    if len(expected) != 64:
        raise RuntimeError(f"Không tìm thấy checksum cho {archive_name}.")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != expected:
        raise RuntimeError("FFmpeg tải về không khớp SHA256.")


class FFmpegDownloadWorker(QThread):
    """Tải FFmpeg về <app_root>/bin/, giải nén, patch PATH."""

    progress = Signal(int)   # 0–100
    log      = Signal(str)   # dòng log hiển thị trong wizard
    finished_ok = Signal()
    failed      = Signal(str)

    def run(self) -> None:  # noqa: C901
        try:
            os.environ.setdefault("DUBFLOW_DATA_DIR", data_root())
            bin_dir = os.path.join(data_root(), "bin")
            suffix = ".exe" if sys.platform == "win32" else ""
            ffmpeg_exe = os.path.join(bin_dir, f"ffmpeg{suffix}")
            ffprobe_exe = os.path.join(bin_dir, f"ffprobe{suffix}")

            system_pair = _system_ffmpeg_pair()
            if system_pair:
                self.log.emit(
                    f"{STATUS_OK} FFmpeg hệ thống đã sẵn sàng — bỏ qua tải.")
                _patch_path(os.path.dirname(system_pair[0]))
                self.progress.emit(100)
                self.finished_ok.emit()
                return

            # Nếu đã có sẵn thì bỏ qua tải
            if os.path.isfile(ffmpeg_exe) and os.path.isfile(ffprobe_exe):
                self.log.emit(f"{STATUS_OK} FFmpeg đã có sẵn — bỏ qua tải.")
                _patch_path(bin_dir)
                self.progress.emit(100)
                self.finished_ok.emit()
                return

            if sys.platform.startswith("linux"):
                raise RuntimeError(
                    "Linux cần gói ffmpeg và ffprobe của hệ thống. "
                    "Bản .deb tự khai báo ffmpeg; hãy cài lại gói hoặc chạy "
                    "`sudo apt install ffmpeg`, rồi mở lại DubFlow. "
                    "Không tải FFmpeg trực tiếp trong bản Linux.")

            os.makedirs(bin_dir, exist_ok=True)
            archive_path = os.path.join(bin_dir, "_ffmpeg_download.zip")
            archive_name = "ffmpeg-master-latest-win64-gpl.zip"

            # --- Tải archive ---
            url = _FFMPEG_URLS.get(sys.platform)
            if not url:
                raise RuntimeError(f"Unsupported platform: {sys.platform}")
            self.log.emit(f"Đang kết nối: {url}")
            self.progress.emit(2)
            temp_archive_path = archive_path + ".part"
            try:
                _download_ffmpeg_archive(
                    url, temp_archive_path, archive_name,
                    self.log.emit, self.progress.emit)
                os.replace(temp_archive_path, archive_path)
            finally:
                try:
                    os.remove(temp_archive_path)
                except OSError:
                    pass

            self.log.emit("Đang kiểm tra SHA256 FFmpeg...")
            self.progress.emit(75)
            _verify_ffmpeg_archive(archive_path, archive_name)
            self.log.emit("Tải xong. Đang giải nén...")
            self.progress.emit(76)

            # --- Giải nén chỉ lấy ffmpeg và ffprobe ---
            archive = (
                zipfile.ZipFile(archive_path)
                if sys.platform == "win32"
                else tarfile.open(archive_path, "r:xz")
            )
            with archive as zf:
                extracted = 0
                members = (
                    zf.infolist()
                    if sys.platform == "win32"
                    else zf.getmembers()
                )
                for info in members:
                    name = info.filename.replace("\\", "/")
                    if name.startswith("/") or ".." in name.split("/"):
                        continue
                    basename = name.split("/")[-1]
                    if basename in (f"ffmpeg{suffix}", f"ffprobe{suffix}"):
                        dest = os.path.join(bin_dir, basename)
                        if sys.platform == "win32":
                            with zf.open(info) as src, open(dest, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                        else:
                            src = zf.extractfile(info)
                            if src is None:
                                continue
                            with src, open(dest, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                        if sys.platform != "win32":
                            os.chmod(dest, 0o755)
                        extracted += 1
                        self.log.emit(f"  Giải nén: {basename}")
                        self.progress.emit(76 + extracted * 10)
                        if extracted >= 2:
                            break

            # Xóa archive tạm
            try:
                os.remove(archive_path)
            except OSError:
                pass

            if not (os.path.isfile(ffmpeg_exe)
                    and os.path.isfile(ffprobe_exe)):
                raise RuntimeError(
                    f"Không tìm thấy đủ ffmpeg{suffix} và ffprobe{suffix} "
                    "trong gói FFmpeg.")

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
    "setup_demucs.py":    35,
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
            os.environ.setdefault("DUBFLOW_DATA_DIR", data_root())
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
                cwd=data_root(),
                env=dict(os.environ, DUBFLOW_APP_ROOT=app_root()),
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


class DoctorWorker(QThread):
    """Chạy Doctor ngoài luồng GUI; chỉ kiểm tra, không sửa dữ liệu."""

    results = Signal(object)
    failed = Signal(str)

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self._settings = settings

    def run(self) -> None:
        try:
            self.results.emit(run_doctor(self._settings))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

