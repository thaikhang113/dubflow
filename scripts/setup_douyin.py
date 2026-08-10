"""Cài tính năng tải video Douyin — thư viện playwright + trình duyệt Chromium.

Chạy 1 lần:  py scripts/setup_douyin.py   (hoặc đúp chuột file .bat cùng tên)

playwright KHÔNG đóng trong exe để bản phân phối nhỏ gọn — script này cài nó
vào thư mục libs/ cạnh app (pip --target) rồi tải Chromium (~170 MB) vào
pw-browsers/. Yêu cầu Python cùng phiên bản với bản build exe (xem
scripts/python_tag.txt) vì greenlet là C-extension.
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBS_DIR = os.path.join(PROJECT_ROOT, "libs")
BROWSERS_DIR = os.path.join(PROJECT_ROOT, "pw-browsers")
TAG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "python_tag.txt")


def log(msg: str) -> None:
    print(f"[setup-douyin] {msg}", flush=True)


def step_check_python() -> None:
    """C-extension (greenlet) phải khớp phiên bản Python của exe."""
    if not os.path.isfile(TAG_FILE):
        return  # chạy từ source — dùng interpreter hiện tại là đúng
    with open(TAG_FILE, encoding="utf-8") as f:
        wanted = f.read().strip()
    have = f"{sys.version_info[0]}.{sys.version_info[1]}"
    if wanted and have != wanted:
        raise SystemExit(
            f"!! Cần Python {wanted} (đang chạy {have}).\n"
            f"   Cài bằng:  winget install Python.Python.{wanted}\n"
            f"   rồi chạy lại file .bat này.")


def step_install_libs() -> None:
    probe = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {LIBS_DIR!r}); import playwright"],
        capture_output=True)
    if probe.returncode == 0:
        log("playwright đã cài trong libs/ — bỏ qua")
        return
    log("cài playwright vào libs/ (~40 MB) ...")
    os.makedirs(LIBS_DIR, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet",
         "--target", LIBS_DIR, "--upgrade", "playwright>=1.50,<2"],
        check=True)


def step_install_chromium() -> None:
    if os.path.isdir(BROWSERS_DIR) and any(
            name.startswith("chromium") for name in os.listdir(BROWSERS_DIR)):
        log("Chromium đã cài trong pw-browsers/ — bỏ qua")
        return
    log("tải Chromium (~170 MB, vài phút) ...")
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=BROWSERS_DIR,
               PYTHONPATH=LIBS_DIR + os.pathsep
               + os.environ.get("PYTHONPATH", ""))
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True, env=env)


def main() -> None:
    log("Cài tính năng tải video Douyin (playwright + Chromium)")
    step_check_python()
    step_install_libs()
    step_install_chromium()
    log("XONG — mở lại VoxDub, tính năng tải Douyin đã sẵn sàng.")


if __name__ == "__main__":
    main()
