import json
import os
import logging
import sys
import tempfile


def app_root() -> str:
    """Thư mục gốc chứa ``models/``, ``.env``, ``output/`` và các venv phụ.

    - Bản đóng gói: thư mục chứa tệp .exe — dữ liệu ngoài luôn nằm CẠNH ứng
      dụng, không bao giờ nằm trong gói.
    - Bản mã nguồn: thư mục gốc dự án (thư mục cha của gói ``autodub``).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


#: Venv được dò khi cần bản torch có CUDA (tách nhạc nền bằng card đồ họa,
#: và các thư viện cuBLAS/cuDNN cho Whisper).
GPU_VENVS = (".venv-gpu",)


def gpu_venv_dir() -> str:
    """Thư mục venv có torch bản CUDA, hoặc chuỗi rỗng nếu không có."""
    for venv in GPU_VENVS:
        path = os.path.join(app_root(), venv)
        if os.path.isdir(path):
            return path
    return ""


def bundled_file(*relative: str) -> str:
    """Path of a file shipped inside the app bundle (worker scripts, assets).

    Frozen: resolves under PyInstaller's ``_internal`` dir (``sys._MEIPASS``);
    source checkout: under the project root.
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
        return os.path.join(base, *relative)
    return os.path.join(app_root(), *relative)


def setup_logging(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(level)
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(handler)
    return logger


#: Số ngày giữ lại log cũ; quá hạn thì tệp tự bị xóa khi xoay vòng.
LOG_RETENTION_DAYS = 14

_FILE_HANDLER: logging.Handler | None = None


def logs_dir() -> str:
    """Thư mục log của ứng dụng: ``<app_root>/logs`` (cạnh exe khi đóng gói)."""
    return ensure_dir(os.path.join(app_root(), "logs"))


def init_file_logging() -> str:
    """Ghi mọi log ``autodub.*`` ra tệp, xoay vòng theo ngày.

    Gọi một lần lúc khởi động (GUI hoặc CLI); gọi lại là vô hại — chỉ có một
    trình ghi tệp duy nhất cho cả tiến trình. Trả về đường dẫn tệp log hiện
    tại để hiện cho người dùng khi cần.
    """
    global _FILE_HANDLER
    if _FILE_HANDLER is not None:
        return _FILE_HANDLER.baseFilename
    from logging.handlers import TimedRotatingFileHandler

    path = os.path.join(logs_dir(), "voxdub.log")
    # delay=True: chưa ghi dòng nào thì chưa tạo tệp (mở app rồi tắt ngay
    # không để lại tệp rỗng).
    handler = TimedRotatingFileHandler(
        path, when="midnight", backupCount=LOG_RETENTION_DAYS,
        encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(name)s - %(levelname)s - %(message)s"))
    root = logging.getLogger("autodub")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    _FILE_HANDLER = handler
    return path


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def save_json_atomic(data: object, path: str) -> None:
    """Crash-safe JSON save: write to a temp file then ``os.replace``.

    A crash/disk-full mid-write must never destroy files that are expensive
    to recreate (translated transcripts, batch state).
    """
    dir_name = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=dir_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def fonts_dir() -> str:
    """Thư mục font kèm app: ``<app_root>/fonts`` (cạnh exe khi đóng gói).

    Nằm NGOÀI bundle PyInstaller có chủ đích: người dùng tự thả thêm file
    .ttf/.otf (ví dụ tải từ fonts.google.com) là app nhận ngay, không cần
    build lại. Cả GUI (QFontDatabase) lẫn ffmpeg/libass (fontsdir) cùng đọc
    thư mục này nên font chọn trong app luôn render đúng trên video.
    """
    return os.path.join(app_root(), "fonts")


def bundled_font_files() -> list[str]:
    """Mọi file font trong :func:`fonts_dir` (rỗng khi thư mục chưa có)."""
    d = fonts_dir()
    if not os.path.isdir(d):
        return []
    return sorted(
        os.path.join(d, f) for f in os.listdir(d)
        if f.lower().endswith((".ttf", ".otf", ".ttc"))
    )


def seg_wav_path(seg_dir: str, seg_id: int) -> str:
    """Canonical per-segment WAV path (5-digit zero-padded id).

    Older work dirs used 3-digit names (``seg_001.wav``); if such a file
    already exists it wins, so resuming a pre-migration dir keeps reusing
    (and overwriting) the legacy names instead of mixing both widths in one
    directory. 5 digits covers 1-2 h videos (the old 3-digit format broke
    ordering above 999 segments).
    """
    new = os.path.join(seg_dir, f"seg_{seg_id:05d}.wav")
    if os.path.exists(new):
        return new
    old = os.path.join(seg_dir, f"seg_{seg_id:03d}.wav")
    if os.path.exists(old):
        return old
    return new


def ffmpeg_timeout_s(duration_s: float | None, floor: int = 300) -> int:
    """Trần thời gian cho một lệnh ffmpeg xử lý ``duration_s`` giây media.

    ffmpeg treo (codec lỗi, file bị khóa trên Windows, driver NVENC kẹt) mà
    không có timeout thì pipeline đứng vĩnh viễn và không hủy được — mọi
    ``subprocess.run`` gọi ffmpeg phải đặt ``timeout=``. Quy tắc: gấp 4 lần
    thời lượng media (encode chậm nhất vẫn nhanh hơn nhiều), tối thiểu
    ``floor`` giây; không biết thời lượng thì dùng trần rộng 1 giờ.
    """
    if not duration_s or duration_s <= 0:
        return 3600
    return max(floor, int(duration_s * 4))


def format_timestamp(seconds: float) -> str:
    """SRT timestamp ``HH:MM:SS,mmm``.

    Derived from total milliseconds so fractions like 59.9996 carry into the
    seconds field instead of producing an invalid ``,1000`` millisecond part.
    """
    ms_total = max(0, int(round(seconds * 1000)))
    secs_total, millis = divmod(ms_total, 1000)
    hours, rem = divmod(secs_total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
