@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title VoxDub Studio - Cai dat

cd /d "%~dp0"

echo.
echo ============================================================
echo   VoxDub Studio - CAI DAT TU DONG
echo ============================================================
echo.
echo   Script nay se lam giup ban:
echo     1. Kiem tra Python va ffmpeg
echo     2. Cai cac thu vien Python can thiet
echo     3. Tao file cau hinh .env
echo     4. Cai bo nghe-chep Whisper       (chay tren may, mien phi)
echo     5. Cai bo giong doc VieNeu        (chay tren may, mien phi)
echo.
echo   Lan dau chay se tai ve khoang 1-2 GB va mat mot luc.
echo   Chay lai script nay bat cu luc nao cung an toan - phan da
echo   xong se duoc bo qua.
echo.
pause

echo.
echo ------------------------------------------------------------
echo  [1/5] Kiem tra Python
echo ------------------------------------------------------------

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"

if not defined PY (
    echo.
    echo  [LOI] Khong tim thay Python.
    echo.
    echo  Hay tai Python 3.10 tro len tai:
    echo      https://www.python.org/downloads/
    echo.
    echo  QUAN TRONG: khi cai NHO TICH o "Add Python to PATH".
    echo  Cai xong mo lai file nay.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo  Da tim thay Python !PYVER!

echo.
echo ------------------------------------------------------------
echo  [2/5] Kiem tra ffmpeg
echo ------------------------------------------------------------

where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [CANH BAO] Khong tim thay ffmpeg. Thieu no thi KHONG xuat
    echo  duoc video.
    echo.
    echo  Cach cai:
    echo    1. Tai ban "full" tai https://www.gyan.dev/ffmpeg/builds/
    echo       ^(file ffmpeg-release-full.7z^)
    echo    2. Giai nen ra vd C:\ffmpeg
    echo    3. Them C:\ffmpeg\bin vao PATH cua Windows
    echo    4. Mo lai file nay
    echo.
    echo  Ban van co the cai tiep phan con lai ngay bay gio.
    echo.
    pause
) else (
    echo  Da tim thay ffmpeg
)

echo.
echo ------------------------------------------------------------
echo  [3/5] Cai thu vien Python
echo ------------------------------------------------------------
echo.

%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [LOI] Cai thu vien that bai. Kiem tra mang roi thu lai.
    pause
    exit /b 1
)
echo.
echo  Xong phan thu vien.

echo.
echo ------------------------------------------------------------
echo  [4/5] Tao file cau hinh .env
echo ------------------------------------------------------------

if exist ".env" (
    echo  Da co .env tu truoc - giu nguyen, khong ghi de.
) else (
    copy ".env.example" ".env" >nul
    echo  Da tao .env tu .env.example
)

echo.
echo ------------------------------------------------------------
echo  [5/5] Cai bo nghe-chep va giong doc
echo ------------------------------------------------------------
echo.
echo  Hai buoc duoi tai ve khoang 1-2 GB. Deu chay tren may ban,
echo  mien phi, khong can API key.
echo.

set /p DOASR="  Cai bo nghe-chep Whisper bay gio? (c/k) [c]: "
if /i "!DOASR!"=="k" (
    echo  Bo qua. Chay lai sau bang: %PY% scripts\setup_whisper.py
) else (
    %PY% scripts\setup_whisper.py
    if errorlevel 1 echo  [CANH BAO] Cai Whisper that bai - chay lai sau bang: %PY% scripts\setup_whisper.py
)

echo.
set /p DOTTS="  Cai bo giong doc VieNeu bay gio? (c/k) [c]: "
if /i "!DOTTS!"=="k" (
    echo  Bo qua. Chay lai sau bang: %PY% scripts\setup_vieneu.py
) else (
    %PY% scripts\setup_vieneu.py
    if errorlevel 1 echo  [CANH BAO] Cai VieNeu that bai - chay lai sau bang: %PY% scripts\setup_vieneu.py
)

echo.
echo ============================================================
echo   CAI DAT XONG
echo ============================================================
echo.
echo   Mo ung dung: dup chuot vao file  chay_app.bat
echo.
echo   Cai them (khong bat buoc):
echo     cai_them_douyin.bat      - tai video tu Douyin
echo     cai_them_paraformer.bat  - nghe tieng Trung chinh xac hon
echo     nap_giong_doc.bat        - nap bo giong mau di kem repo
echo.
pause
