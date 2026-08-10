"""Đóng gói VoxDub Studio thành thư mục exe phân phối được.

Chạy từ project root với Python chính (đã cài đủ requirements + pyinstaller):

    py scripts/build_exe.py            # build + smoke test
    py scripts/build_exe.py --no-test  # chỉ build

Các bước:
  1. Đọc VOXDUB_API_URL từ .env của máy build → sinh
     autodub_gui/_embedded.py (địa chỉ máy chủ nhúng TRONG exe, không lộ ra
     file .env của người dùng). Khôi phục file rỗng sau khi build.
  2. PyInstaller onedir theo autodub.spec → build/, dist/VoxDub/
  3. Lắp ráp thư mục phân phối dist/VoxDub/:
       - scripts/setup_*.py + các file .bat cài đặt (VieNeu, Paraformer, Douyin)
       - HUONG_DAN_CAI_DAT.md (sinh từ script này)
       - .env.example (KHÔNG kèm .env thật)
       - models/ rỗng (điểm đến khi người dùng cài model)
  4. Smoke test: chạy VoxDub.exe với AUTODUB_SMOKE=1, đọc
     smoke_test_result.json, in kết quả từng mục.

Bản phân phối KHÔNG chứa: model, các venv phụ, ffmpeg — người dùng
cài theo HUONG_DAN_CAI_DAT.md.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMBEDDED_PY = os.path.join(PROJECT_ROOT, "autodub_gui", "_embedded.py")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist", "VoxDub")

EMBEDDED_TEMPLATE = '''"""Giá trị nhúng cứng vào bản đóng gói (exe).

File này trong repo LUÔN rỗng. Khi build exe, ``scripts/build_exe.py`` sinh
lại nó với VOXDUB_API_URL đọc từ .env của máy build, rồi khôi phục về rỗng
sau khi build xong — địa chỉ máy chủ nằm TRONG exe, không lộ ra .env của
người dùng và người dùng không chỉnh được.
"""

# Rỗng = không nhúng; saas_client rơi về địa chỉ cố định trong mã, rồi tới
# biến môi trường VOXDUB_API_URL (chỉ khi chạy từ mã nguồn).
VOXDUB_API_URL = {url!r}
'''


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

def read_env_value(key: str) -> str:
    """Đọc 1 khóa từ .env của máy build (không dùng python-dotenv để script
    chạy được cả khi thiếu package)."""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.isfile(env_path):
        return ""
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{key}=") and not line.startswith("#"):
                return line.partition("=")[2].strip()
    return ""


def write_embedded(url: str) -> None:
    with open(EMBEDDED_PY, "w", encoding="utf-8") as f:
        f.write(EMBEDDED_TEMPLATE.format(url=url))


def step_embed_api_url() -> str:
    url = read_env_value("VOXDUB_API_URL")
    if url:
        log(f"nhúng VOXDUB_API_URL vào exe: {url}")
    else:
        log("(.env không có VOXDUB_API_URL — exe dùng địa chỉ cố định "
            "trong autodub/saas_client.py)")
    write_embedded(url)
    return url


def step_pyinstaller() -> None:
    # Xóa dist cũ để không lẫn file rác từ lần build trước.
    if os.path.isdir(DIST_DIR):
        log("xóa dist/VoxDub cũ...")
        try:
            shutil.rmtree(DIST_DIR)
        except PermissionError:
            raise SystemExit(
                "!! Không xóa được dist/VoxDub — đóng VoxDub.exe đang chạy, "
                "cửa sổ Explorer/terminal đang mở thư mục đó, rồi build lại.")
    log("chạy PyInstaller (vài phút)...")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         os.path.join(PROJECT_ROOT, "autodub.spec")])
    exe = os.path.join(DIST_DIR, "VoxDub.exe")
    if not os.path.isfile(exe):
        raise SystemExit(f"!! PyInstaller xong nhưng không thấy {exe}")


def step_assemble() -> None:
    log("lắp ráp thư mục phân phối...")

    # Script cài phần mở rộng (giọng đọc, ASR tiếng Trung, Douyin) chạy trên
    # máy người dùng — exe chỉ chứa phần lõi.
    scripts_dst = os.path.join(DIST_DIR, "scripts")
    os.makedirs(scripts_dst, exist_ok=True)
    for script in ("setup_vieneu.py", "setup_paraformer.py",
                   "setup_whisper.py", "setup_douyin.py"):
        shutil.copy2(os.path.join(PROJECT_ROOT, "scripts", script),
                     scripts_dst)

    # Phiên bản Python của máy build — setup_douyin.py kiểm tra để libs/
    # (C-extension) khớp với python trong exe.
    with open(os.path.join(scripts_dst, "python_tag.txt"), "w",
              encoding="utf-8") as f:
        f.write(f"{sys.version_info[0]}.{sys.version_info[1]}\n")

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

    # Giọng VieNeu: KHÔNG đóng gói voices/ hay custom_voices.json nữa.
    # App tự tải voices.zip từ GitHub release lần đầu chạy (voice_downloader).
    # Lý do: giảm kích thước exe ~60-100 MB, dễ update voices riêng biệt.
    log("voices/ và custom_voices.json KHÔNG đóng gói — app tự tải lần đầu")

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
        f.write(GUIDE_MD)

    # Đảm bảo không có .env nào lọt vào dist.
    stray = os.path.join(DIST_DIR, ".env")
    if os.path.isfile(stray):
        os.remove(stray)
        log("!! đã xóa .env lọt vào dist")


def step_restore_embedded() -> None:
    write_embedded("")
    log("khôi phục autodub_gui/_embedded.py về rỗng")


def step_smoke_test() -> bool:
    log("smoke test: chạy VoxDub.exe với AUTODUB_SMOKE=1 ...")
    result_json = os.path.join(DIST_DIR, "smoke_test_result.json")
    if os.path.isfile(result_json):
        os.remove(result_json)

    env = dict(os.environ, AUTODUB_SMOKE="1")
    # QT_QPA_PLATFORM=offscreen nếu chạy trên máy không có màn hình:
    # env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.run([os.path.join(DIST_DIR, "VoxDub.exe")], env=env,
                          cwd=DIST_DIR, timeout=180)

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
    ok = bool(checks.get("ok")) and proc.returncode == 0
    os.remove(result_json)
    # Bài kiểm tra ghi .env đã tạo file .env trong dist — dọn đi để bản
    # phân phối sạch (người dùng tự tạo qua tab Cài đặt).
    stray = os.path.join(DIST_DIR, ".env")
    if os.path.isfile(stray):
        os.remove(stray)
    log("SMOKE TEST PASS" if ok else "SMOKE TEST FAIL")
    return ok


# --------------------------------------------------------------- payloads --

SETUP_VIENEU_BAT = r"""@echo off
chcp 65001 >nul
title Cai dat giong doc VieNeu cho VoxDub Studio
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
title Cai dat Whisper ASR cho VoxDub Studio
echo.
echo  Script nay cai faster-whisper vao venv rieng (.venv-whisper).
echo  Whisper se chay ngoai exe — giam ~112 MB kich thuoc ban phan phoi.
echo  Yeu cau: da cai Python 3.10-3.12 (xem HUONG_DAN_CAI_DAT.md, Buoc 2).
echo.
cd /d "%~dp0"
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
title Cai dat ASR tieng Trung (Paraformer) cho VoxDub Studio
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
title Cai dat tinh nang tai video Douyin cho VoxDub Studio
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

GUIDE_MD = """# Hướng dẫn cài đặt VoxDub Studio

VoxDub Studio lồng tiếng video tự động sang tiếng Việt: tải video → nhận dạng
giọng nói → dịch → đọc giọng Việt (clone giọng) → ghép lại thành video.

Nhận dạng giọng nói, đọc giọng Việt và ghép video đều chạy **trên máy của
bạn**; riêng bước dịch chạy qua máy chủ VoxDub và tính bằng **Vox**. Bạn cần
cài vài công cụ trước khi dùng — làm đúng thứ tự dưới đây, mỗi bước chỉ làm
**một lần duy nhất**.

> **Cài tối thiểu để chạy được ngay:** Bước 1 (FFmpeg) + Bước 3 (giọng đọc
> VieNeu). Máy mới được tặng sẵn Vox dùng thử, không cần mua gì để thử.

> **Máy cần có:** Windows 10/11 64-bit, card đồ họa NVIDIA (khuyến nghị,
> để chạy nhanh), ~10 GB dung lượng trống, kết nối mạng để tải model.

---

## Bước 1 — Cài FFmpeg (xử lý âm thanh/video)

Mở **PowerShell** (bấm phím Windows, gõ `powershell`, Enter) rồi chạy:

```
winget install Gyan.FFmpeg
```

Xong **đóng PowerShell và mở lại**, gõ `ffmpeg -version` — thấy số phiên
bản là được.

*Không dùng được winget?* Tải bản "release full" tại
<https://www.gyan.dev/ffmpeg/builds/>, giải nén, rồi chép 2 file
`ffmpeg.exe` và `ffprobe.exe` trong thư mục `bin` vào **cùng thư mục với
VoxDub.exe** — app sẽ tự nhận, không cần chỉnh PATH.

## Bước 2 — Cài Python (để cài giọng đọc VieNeu)

Trong PowerShell:

```
winget install Python.Python.3.12
```

Đóng và mở lại PowerShell, gõ `py --version` — thấy `Python 3.12.x` là được.

> Nếu máy đã có Python 3.10–3.12 thì bỏ qua bước này.

## Bước 3 — Cài giọng đọc VieNeu (bắt buộc, ~300 MB, chạy CPU)

Đúp chuột vào file **`Cai dat giong VieNeu.bat`** trong thư mục VoxDub Studio.

Script tự tạo môi trường riêng (`.venv-vieneu`), tải model (~300 MB) và
chạy thử. Chỉ mất vài phút, **không cần card đồ họa** — đây là bộ giọng
đọc của app với hàng chục giọng nam/nữ.

## Bước 4 — Vox (tài nguyên dịch)

Bước dịch chạy qua máy chủ VoxDub nên bạn **không phải đăng ký tài khoản
hay lấy API key của ai cả**. Máy này đã được tặng sẵn Vox dùng thử — mở app
là dịch được ngay.

Hết Vox thì mua thêm:

1. Vào trang web VoxDub, chọn gói (hoặc tự nhập số tiền bạn muốn).
2. Chuyển khoản theo mã QR hiện trên màn hình. **Giữ nguyên nội dung chuyển
   khoản** — đó là mã đơn hàng, ghi sai thì hệ thống không khớp được.
3. Vài giây sau bạn nhận **mã kích hoạt** dạng `VOX-XXXX-XXXX-XXXX` (hiện
   trên web và gửi vào email nếu bạn có điền).
4. Mở **VoxDub.exe → Tài khoản**, dán mã, bấm **Kích hoạt**.

> Mỗi mã chỉ kích hoạt được **một lần trên một máy**. Vox gắn với chiếc máy
> này chứ không gắn với tài khoản, nên cài lại app hay xóa cấu hình đều
> không mất Vox. Đổi máy thì liên hệ hỗ trợ kèm mã máy (xem ở trang Tài
> khoản) để được chuyển sang.

## Bước 5 — Mở VoxDub Studio và kiểm tra

1. Đúp chuột **VoxDub.exe**.
2. Kiểm tra nhanh:
   - Trang **Tài khoản**: xem số Vox còn lại.
   - Trang **Giọng đọc AI**: chọn giọng bạn thích, bấm **Nghe thử**.
   - Trang **Dịch thuật**: điền ngữ cảnh video nếu muốn bản dịch bám đúng
     chủ đề và xưng hô của kênh bạn (không bắt buộc).
3. Về tab **Lồng tiếng**, dán link video YouTube, bấm chạy. Lần chạy đầu
   app tự tải model nhận dạng giọng nói (~1.5 GB, một lần duy nhất).

Video kết quả nằm trong thư mục `output` cạnh VoxDub.exe.

## Tùy chọn

- **Tải video Douyin:** đúp chuột **`Cai dat tinh nang Douyin.bat`** (cài
  thư viện + Chromium, ~210 MB, một lần). YouTube và link trực tiếp không
  cần bước này.
- **Nhận dạng tiếng Trung chính xác hơn:** đúp chuột
  **`Cai dat ASR tieng Trung (Paraformer).bat`** (~520 MB, chạy CPU). Video
  tiếng Trung sẽ được nghe-chép bằng Paraformer thay vì Whisper — chính xác
  hơn rõ rệt; ngôn ngữ khác tự dùng Whisper như cũ.
- **Tiêu đề, mô tả và hashtag tự động:** bật/tắt ở trang **Dịch thuật**,
  mục "Nội dung đăng bài". Tốn thêm một khoản Vox nhỏ mỗi video.
- **Giọng đọc riêng:** thu một file WAV 5–10 giây giọng bạn muốn clone
  (rõ, không nhạc nền) + file `.txt` cùng tên chứa đúng nội dung câu nói,
  rồi chọn nó trong tab Cài đặt.
- **Dịch đúng ngữ cảnh hơn:** vào trang **Dịch thuật**, mục **"Ngữ cảnh
  video"** — điền chủ đề, xưng hô và thuật ngữ cố định; bản dịch sẽ bám đúng
  văn phong kênh của bạn.

---

## Xử lý lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `ffmpeg` không nhận sau khi cài | Đóng mở lại PowerShell/app; hoặc chép `ffmpeg.exe`+`ffprobe.exe` vào cạnh `VoxDub.exe` |
| `py` không nhận | Cài lại Python bằng winget (Bước 2), nhớ mở PowerShell mới |
| App báo hết Vox | Mở trang Tài khoản để nạp thêm, rồi chạy tiếp dự án đang dở — phần đã dịch xong không bị tính tiền lại |
| Mã kích hoạt báo "đã dùng trên máy khác" | Mỗi mã chỉ dùng cho một máy. Nếu bạn chưa từng dùng mã này, liên hệ hỗ trợ kèm mã đơn hàng |
| App báo không kết nối được máy chủ | Kiểm tra mạng. Các bước chạy trên máy (nghe chép, giọng đọc, xuất video) vẫn dùng bình thường |
| App báo chưa cài bộ giọng VieNeu | Chạy `Cai dat giong VieNeu.bat` (Bước 3) |
| Chạy chậm, GPU không dùng | Cần card NVIDIA + driver mới (`nvidia-smi` trong PowerShell phải chạy được) |
| Antivirus chặn VoxDub.exe | Thêm thư mục VoxDub Studio vào danh sách loại trừ — app không có mã độc, exe đóng gói bằng PyInstaller hay bị nhận nhầm |

## Cấu trúc thư mục sau khi cài đủ

```
VoxDub Studio/
├── VoxDub.exe             ← mở app tại đây
├── _internal/             ← thư viện của app (không đụng vào)
├── Cai dat giong VieNeu.bat            ← Bước 3 (giọng đọc, bắt buộc)
├── Cai dat ASR tieng Trung (Paraformer).bat ← tùy chọn, nghe tiếng Trung chuẩn hơn
├── Cai dat tinh nang Douyin.bat        ← tùy chọn, tải video Douyin
├── scripts/
├── libs/                  ← thư viện Douyin (sau khi cài, nếu dùng)
├── models/vieneu/         ← model VieNeu (sau Bước 3)
├── models/paraformer-zh/  ← model Paraformer (nếu cài)
├── .venv-vieneu/          ← môi trường VieNeu (sau Bước 3)
├── .venv-asr/             ← môi trường Paraformer (nếu cài)
├── pw-browsers/           ← Chromium (nếu dùng Douyin)
├── .env                   ← app tự tạo khi bạn Lưu cài đặt
└── output/                ← video kết quả
```
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-test", action="store_true",
                        help="bỏ qua smoke test sau khi build")
    parser.add_argument("--no-zip", action="store_true",
                        help="bỏ qua bước nén .zip phát hành")
    args = parser.parse_args()

    _force_utf8_stdio()
    start = time.time()
    step_embed_api_url()
    try:
        step_pyinstaller()
    finally:
        # Kill-switch URL không được nằm lại trong source tree.
        step_restore_embedded()

    step_assemble()

    ok = True
    if not args.no_test:
        ok = step_smoke_test()

    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(DIST_DIR) for f in fs)
    log(f"xong sau {time.time() - start:.0f}s — dist/VoxDub ({size >> 20} MB)")

    # Nén sẵn gói phát hành: dist/VoxDub-Studio-v<ver>.zip, giải nén ra
    # thư mục gốc "VoxDub Studio/" (đúng tên trong HUONG_DAN_CAI_DAT.md).
    # Chỉ nén khi smoke test đạt — không bao giờ phát hành bản hỏng.
    if ok and not args.no_zip:
        # Đọc APP_VERSION bằng regex — import autodub_gui.app sẽ kéo cả Qt
        # và chạy _frozen.init(), không đáng cho một chuỗi số.
        import re
        src = open(os.path.join(PROJECT_ROOT, "autodub_gui", "app.py"),
                   encoding="utf-8").read()
        m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', src, re.M)
        version = m.group(1) if m else "0.0"
        zip_path = os.path.join(PROJECT_ROOT, "dist",
                                f"VoxDub-Studio-v{version}.zip")
        log(f"đang nén gói phát hành: {os.path.basename(zip_path)} ...")
        import zipfile
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for dp, _, fs in os.walk(DIST_DIR):
                for f in fs:
                    full = os.path.join(dp, f)
                    rel = os.path.relpath(full, DIST_DIR)
                    zf.write(full, os.path.join("VoxDub Studio", rel))
        zsize = os.path.getsize(zip_path)
        log(f"gói phát hành sẵn sàng: {zip_path} ({zsize >> 20} MB)")
    elif not ok:
        log("SMOKE TEST FAIL — bỏ qua bước nén .zip")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
