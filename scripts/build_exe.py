"""Đóng gói DubFlow thành thư mục exe phân phối được.

Chạy từ project root với Python chính (đã cài đủ requirements + pyinstaller):

    py scripts/build_exe.py            # build + smoke test
    py scripts/build_exe.py --no-test  # chỉ build

Các bước:
  1. PyInstaller onedir theo autodub.spec → build/, dist/DubFlow/
  2. Lắp ráp thư mục phân phối dist/DubFlow/ với wizard first-run,
     setup scripts dự phòng, tài liệu release và dữ liệu mẫu.
  3. Smoke test: chạy DubFlow.exe với AUTODUB_SMOKE=1, đọc
     smoke_test_result.json, in kết quả từng mục.

Bản phân phối không chứa model, virtualenv phụ hoặc FFmpeg. Wizard tải và cài
toàn bộ thành phần vào thư mục dữ liệu người dùng ở lần chạy đầu tiên.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMBEDDED_PY = os.path.join(PROJECT_ROOT, "autodub_gui", "_embedded.py")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist", "DubFlow")

def _bundle_data_dir() -> str:
    for name in ("_internal", "data"):
        path = os.path.join(DIST_DIR, name)
        if os.path.isdir(path):
            return path
    return os.path.join(DIST_DIR, "_internal")
SETUP_PYTHON_VERSION = "3.12"

def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def _force_utf8_stdio() -> None:
    """Log tiếng Việt trên console cp1252 của Windows không được làm vỡ build."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def run(cmd: list[str], **kw) -> None:
    log("$ " + " ".join(os.path.basename(c) if os.sep in c else c for c in cmd[:8]))
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT, **kw)


# ------------------------------------------------------------------ steps --

def step_pyinstaller() -> None:
    # Xóa dist cũ để không lẫn file rác từ lần build trước.
    if os.path.isdir(DIST_DIR):
        log("xóa dist/DubFlow cũ...")
        try:
            shutil.rmtree(DIST_DIR)
        except PermissionError:
            raise SystemExit(
                "!! Không xóa được dist/DubFlow — đóng DubFlow.exe đang chạy, "
                "cửa sổ Explorer/terminal đang mở thư mục đó, rồi build lại.")
    log("chạy PyInstaller (vài phút)...")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         os.path.join(PROJECT_ROOT, "autodub.spec")])
    exe = os.path.join(DIST_DIR, "DubFlow.exe")
    if not os.path.isfile(exe):
        raise SystemExit(f"!! PyInstaller xong nhưng không thấy {exe}")
    for worker in (
            os.path.join("autodub", "speech", "asr_whisper_worker.py"),
            os.path.join("autodub", "speech", "asr_paraformer_worker.py"),
            os.path.join("autodub", "speech", "tts", "vieneu_worker.py"),
            os.path.join("autodub", "media", "demucs_worker.py"),
            os.path.join("autodub", "media", "ocr_worker.py"),
            os.path.join("autodub", "media", "deepseek_ocr_worker.py"),
            os.path.join("autodub", "media", "vsr_worker.py")):
        bundled = os.path.join(_bundle_data_dir(), worker)
        if not os.path.isfile(bundled):
            raise SystemExit(f"!! thiếu worker trong bundle: {bundled}")


def step_assemble() -> None:
    log("lắp ráp thư mục phân phối...")

    clean_distribution_artifacts()

    version = _build_version()
    with open(os.path.join(DIST_DIR, "VERSION"), "w", encoding="utf-8") as f:
        f.write(f"{version}\n")

    # Script cài phần mở rộng (giọng đọc, ASR, OCR, Douyin) chạy trên máy
    # người dùng — exe chứa worker Python cần thiết, không chứa model/venv.
    scripts_dst = os.path.join(DIST_DIR, "scripts")
    os.makedirs(scripts_dst, exist_ok=True)
    for script in ("setup_support.py", "setup_vieneu.py",
                   "setup_paraformer.py", "setup_whisper.py",
                   "setup_ocr.py", "setup_douyin.py", "setup_demucs.py",
                   "setup_voices.py", "setup_deepseek_ocr.py", "setup_vsr.py"):
        shutil.copy2(os.path.join(PROJECT_ROOT, "scripts", script),
                     scripts_dst)

    # Setup extensions dùng Python 3.10–3.12. Build bằng Python khác không được
    # ghi vào tag vì người dùng cần runtime tương thích, không phải build host.
    with open(os.path.join(scripts_dst, "python_tag.txt"), "w",
              encoding="utf-8") as f:
        f.write(f"{SETUP_PYTHON_VERSION}\n")

    # .bat để người dùng đúp chuột là cài — không cần biết dòng lệnh.
    for name, content in (
            ("Cai dat giong VieNeu.bat", SETUP_VIENEU_BAT),
            ("Cai dat Whisper ASR.bat", SETUP_WHISPER_BAT),
            ("Cai dat ASR tieng Trung (Paraformer).bat", SETUP_PARAFORMER_BAT),
            ("Cai dat tinh nang Douyin.bat", SETUP_DOUYIN_BAT)):
        with open(os.path.join(DIST_DIR, name), "w", encoding="utf-8") as f:
            f.write(content)

    # .env.example làm mẫu; TUYỆT ĐỐI không copy .env thật của máy build
    # (địa chỉ máy chủ đã nhúng trong exe).
    src_example = os.path.join(PROJECT_ROOT, ".env.example")
    if os.path.isfile(src_example):
        shutil.copy2(src_example, os.path.join(DIST_DIR, ".env.example"))

    for name in ("LICENSE",):
        src = os.path.join(PROJECT_ROOT, name)
        if os.path.isfile(src):
            shutil.copy2(src, DIST_DIR)

    # Thư mục models rỗng — đích đến của các script cài model.
    os.makedirs(os.path.join(DIST_DIR, "models"), exist_ok=True)

    voices_src = os.path.join(PROJECT_ROOT, "voices", "preset_voices_vn")
    if os.path.isdir(voices_src):
        shutil.copytree(
            voices_src,
            os.path.join(_bundle_data_dir(), "voices", "preset_voices_vn"),
            dirs_exist_ok=True,
        )
        log("đã kèm voice preset trong bundle — không phụ thuộc URL ngoài")

    # Font kèm app: copy nguyên fonts/ (file .ttf/.otf + license + README).
    # Nằm CẠNH exe (không trong _internal) để người dùng tự thả thêm font
    # tải từ fonts.google.com mà không cần build lại.
    fonts_src = os.path.join(PROJECT_ROOT, "fonts")
    if os.path.isdir(fonts_src):
        shutil.copytree(fonts_src, os.path.join(DIST_DIR, "fonts"),
                        dirs_exist_ok=True)
        n_fonts = sum(1 for f in os.listdir(fonts_src)
                      if f.lower().endswith((".ttf", ".otf", ".ttc")))
        log(f"đã kèm {n_fonts} font trong fonts/")
    else:
        os.makedirs(os.path.join(DIST_DIR, "fonts"), exist_ok=True)

    with open(os.path.join(DIST_DIR, "HUONG_DAN_CAI_DAT.md"), "w",
              encoding="utf-8") as f:
        f.write(release_guide())

    # Đảm bảo không có .env nào lọt vào dist.
    stray = os.path.join(DIST_DIR, ".env")
    if os.path.isfile(stray):
        os.remove(stray)
        log("!! đã xóa .env lọt vào dist")


def clean_distribution_artifacts() -> None:
    """Remove files generated only while running local smoke tests."""
    for generated in (".env", "smoke_test_result.json", "smoke_startup_trace.txt"):
        generated_path = os.path.join(DIST_DIR, generated)
        if os.path.isfile(generated_path):
            os.remove(generated_path)
    for generated_dir in ("bin", "logs", "output", "downloads", "VN"):
        generated_path = os.path.join(DIST_DIR, generated_dir)
        if os.path.isdir(generated_path):
            shutil.rmtree(generated_path, ignore_errors=True)

def _build_version() -> str:
    """Use explicit release version, else source app version."""
    requested = getattr(_build_version, "requested", None)
    if requested:
        return requested
    src = open(os.path.join(PROJECT_ROOT, "autodub_gui", "app.py"),
               encoding="utf-8").read()
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', src, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def step_smoke_test() -> bool:
    log("smoke test: chạy DubFlow.exe với AUTODUB_SMOKE=1 ...")
    result_json = os.path.join(DIST_DIR, "smoke_test_result.json")
    if os.path.isfile(result_json):
        os.remove(result_json)

    env = dict(
        os.environ,
        AUTODUB_SMOKE="1",
        DUBFLOW_DATA_DIR=DIST_DIR,
    )
    # QT_QPA_PLATFORM=offscreen nếu chạy trên máy không có màn hình:
    # env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.run([os.path.join(DIST_DIR, "DubFlow.exe")], env=env,
                          cwd=DIST_DIR, timeout=180)

    try:
        if not os.path.isfile(result_json):
            log("!! exe không ghi smoke_test_result.json — khởi động thất bại?")
            return False
        with open(result_json, encoding="utf-8") as f:
            checks = json.load(f)

        log("--- kết quả smoke test ---")
        for key, val in checks.items():
            mark = ""
            if isinstance(val, bool):
                mark = "OK " if val else "FAIL "
            log(f"  {mark}{key} = {val}")

        # Trên máy build chưa chắc có model/ffmpeg cạnh dist — chỉ các mục
        # bắt buộc (exe chạy, GUI dựng được, ghi .env được, import đủ) quyết
        # định pass/fail; phần còn lại là thông tin.
        return bool(checks.get("ok")) and proc.returncode == 0
    finally:
        # Smoke test writes runtime state beside the executable. Never let
        # those local files enter an installer or archive.
        clean_distribution_artifacts()


# --------------------------------------------------------------- payloads --

SETUP_VIENEU_BAT = r"""@echo off
chcp 65001 >nul
title Cai dat giong doc VieNeu cho DubFlow
echo.
echo  Script nay cai giong doc VieNeu (chay CPU, ~300 MB, 14 giong).
echo  Yeu cau: da cai Python 3.10-3.12 (xem HUONG_DAN_CAI_DAT.md, Buoc 2).
echo.
cd /d "%~dp0"
py -3.12 scripts\setup_vieneu.py 2>nul || py -3.11 scripts\setup_vieneu.py 2>nul || py -3.10 scripts\setup_vieneu.py 2>nul || py scripts\setup_vieneu.py || python scripts\setup_vieneu.py
if errorlevel 1 (
    echo.
    echo  !! Cai dat that bai. Kiem tra da cai Python chua: py --version
    echo     Xem muc "Xu ly loi" trong HUONG_DAN_CAI_DAT.md
)
echo.
pause
"""

SETUP_WHISPER_BAT = r"""@echo off
chcp 65001 >nul
title Cai dat Whisper ASR cho DubFlow
echo.
echo  Script nay cai faster-whisper vao venv rieng (.venv-whisper).
echo  Whisper se chay ngoai exe — giam ~112 MB kich thuoc ban phan phoi.
echo  Yeu cau: da cai Python 3.10-3.12 (xem HUONG_DAN_CAI_DAT.md, Buoc 2).
echo.
cd /d "%~dp0"
set "DUBFLOW_APP_ROOT=%CD%"
if not defined DUBFLOW_DATA_DIR set "DUBFLOW_DATA_DIR=%LOCALAPPDATA%\DubFlow"
py -3.12 scripts\setup_whisper.py 2>nul || py -3.11 scripts\setup_whisper.py 2>nul || py -3.10 scripts\setup_whisper.py 2>nul || py scripts\setup_whisper.py || python scripts\setup_whisper.py
if errorlevel 1 (
    echo.
    echo  !! Cai dat that bai. Kiem tra da cai Python chua: py --version
    echo     Xem muc "Xu ly loi" trong HUONG_DAN_CAI_DAT.md
)
echo.
pause
"""

SETUP_PARAFORMER_BAT = r"""@echo off
chcp 65001 >nul
title Cai dat ASR tieng Trung (Paraformer) cho DubFlow
echo.
echo  Script nay cai bo nhan dang tieng Trung Paraformer (~520 MB, chay CPU)
echo  — chinh xac hon Whisper voi video tieng Trung.
echo  Yeu cau: da cai Python 3.10-3.12 (xem HUONG_DAN_CAI_DAT.md, Buoc 2).
echo.
cd /d "%~dp0"
py -3.12 scripts\setup_paraformer.py 2>nul || py -3.11 scripts\setup_paraformer.py 2>nul || py -3.10 scripts\setup_paraformer.py 2>nul || py scripts\setup_paraformer.py || python scripts\setup_paraformer.py
if errorlevel 1 (
    echo.
    echo  !! Cai dat that bai. Kiem tra da cai Python chua: py --version
    echo     Xem muc "Xu ly loi" trong HUONG_DAN_CAI_DAT.md
)
echo.
pause
"""

SETUP_DOUYIN_BAT = r"""@echo off
chcp 65001 >nul
title Cai dat tinh nang tai video Douyin cho DubFlow
echo.
echo  Script nay cai thu vien playwright (~40 MB) va trinh duyet Chromium
echo  (~170 MB) de tai video Douyin. YouTube va link truc tiep KHONG can.
echo  Yeu cau: Python DUNG phien ban ghi trong scripts\python_tag.txt.
echo.
cd /d "%~dp0"
py -3.12 scripts\setup_douyin.py 2>nul || py scripts\setup_douyin.py || python scripts\setup_douyin.py
if errorlevel 1 (
    echo.
    echo  !! Cai dat that bai. Kiem tra da cai Python dung phien ban:
    echo     type scripts\python_tag.txt   va   py --version
    echo     Xem muc "Xu ly loi" trong HUONG_DAN_CAI_DAT.md
)
echo.
pause
"""

def release_guide() -> str:
    return """# Hướng dẫn cài đặt DubFlow

DubFlow là ứng dụng desktop mã nguồn mở cho Windows. App tải video, nhận dạng
giọng nói, dịch, tạo giọng Việt, thêm phụ đề và xuất video trên máy của bạn.

## Lần chạy đầu tiên

Mở `DubFlow.exe`. Wizard sẽ cài lần lượt toàn bộ thành phần cần thiết:

1. Python runtime
2. FFmpeg và ffprobe
3. VieNeu TTS
4. Whisper ASR
5. Paraformer ASR tiếng Trung
6. OCR
7. Chromium cho Douyin
8. Demucs và model htdemucs
9. Voice library

Mỗi bước có tiến độ, log, retry và trạng thái lưu trong thư mục dữ liệu user.
Đóng app giữa chừng rồi mở lại để tiếp tục. Không thể dùng app chính trước khi
setup hoàn tất.

Model, virtualenv và dữ liệu ghi được lưu tại:

```text
%LOCALAPPDATA%\\DubFlow
```

Không xóa thư mục này nếu muốn giữ model, voice và project.

## Dịch

Mặc định app dừng ở bước dịch tay và tạo `TRANSLATE_PENDING.txt`. Gửi transcript
cho công cụ dịch bạn chọn, lưu kết quả vào `data/transcript_vi.json`, rồi bấm
**Đã dịch xong, tiếp tục**.

Muốn dịch tự động, cấu hình endpoint OpenAI-compatible trong trang Cài đặt hoặc
`.env`:

```dotenv
TRANSLATION_ENDPOINT=https://api.example.com/v1
TRANSLATION_API_KEY=your-api-key
TRANSLATION_MODEL=model-id
```

## Tính năng

- Douyin cần Chromium, được cài tự động ở bước setup.
- Paraformer dùng cho video tiếng Trung.
- Demucs tách giọng khỏi nhạc nền, được cài tự động ở bước setup.
- OCR dùng để nhận dạng/xử lý vùng chữ gốc.
- Voice clone chỉ dùng với giọng bạn có quyền sử dụng.

## Kết quả

Video và dữ liệu dự án nằm trong thư mục `output`. Có thể mở lại dự án sau khi
app bị đóng; pipeline tiếp tục từ file cache còn nguyên.

## Cập nhật

DubFlow tự kiểm tra GitHub Releases khi app đã setup xong. Nếu có bản mới, app
hiển thị dialog tải package, kiểm tra SHA256 rồi chạy installer phù hợp:

- Windows: `DubFlow-...-setup.exe`
- Linux: `dubflow_..._amd64.deb`

Không tắt app trong lúc đang cài cập nhật.

## Xử lý lỗi

Nếu một bước setup lỗi, bấm **Retry**. Kiểm tra mạng, dung lượng ổ đĩa và quyền
ghi thư mục dữ liệu. Log nằm trong thư mục `logs` của dữ liệu DubFlow.
"""


def main() -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-test", action="store_true",
                        help="bỏ qua smoke test sau khi build")
    parser.add_argument("--no-zip", action="store_true",
                        help="bỏ qua bước nén .zip phát hành")
    parser.add_argument("--version", default=None,
                        help="version dùng cho tên artifact (mặc định lấy APP_VERSION)")
    args = parser.parse_args()
    _build_version.requested = args.version

    start = time.time()
    step_pyinstaller()
    step_assemble()

    ok = True
    if not args.no_test:
        ok = step_smoke_test()

    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(DIST_DIR) for f in fs)
    log(f"xong sau {time.time() - start:.0f}s — dist/DubFlow ({size >> 20} MB)")

    # Nén sẵn gói phát hành: dist/DubFlow-v<ver>-windows-x64.zip, giải nén ra
    # thư mục gốc "DubFlow/" (đúng tên trong HUONG_DAN_CAI_DAT.md).
    # Chỉ nén khi smoke test đạt — không bao giờ phát hành bản hỏng.
    if ok and not args.no_zip:
        # Đọc APP_VERSION bằng regex — import autodub_gui.app sẽ kéo cả Qt
        # và chạy _frozen.init(), không đáng cho một chuỗi số.
        import re
        src = open(os.path.join(PROJECT_ROOT, "autodub_gui", "app.py"),
                   encoding="utf-8").read()
        m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', src, re.MULTILINE)
        version = args.version or (m.group(1) if m else "0.0")
        zip_path = os.path.join(PROJECT_ROOT, "dist",
                                f"DubFlow-v{version}-windows-x64.zip")
        log(f"đang nén gói phát hành: {os.path.basename(zip_path)} ...")
        import zipfile
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for dp, _, fs in os.walk(DIST_DIR):
                for f in fs:
                    full = os.path.join(dp, f)
                    rel = os.path.relpath(full, DIST_DIR)
                    zf.write(full, os.path.join("DubFlow", rel))
        zsize = os.path.getsize(zip_path)
        log(f"gói phát hành sẵn sàng: {zip_path} ({zsize >> 20} MB)")
    elif not ok:
        log("SMOKE TEST FAIL — bỏ qua bước nén .zip")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
