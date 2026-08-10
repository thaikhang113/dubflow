@echo off
chcp 65001 >nul
title VoxDub Studio - Nap bo giong doc mau

cd /d "%~dp0"

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"

if not defined PY (
    echo  [LOI] Khong tim thay Python. Hay chay  cai_dat.bat  truoc.
    pause
    exit /b 1
)

echo.
echo  Nap toan bo giong mau trong thu muc  voices\  vao ung dung.
echo  Can cai bo giong doc VieNeu truoc ^(cai_dat.bat buoc 5^).
echo  Tha them file .wav vao  voices\custom\  roi chay lai file nay
echo  de them giong cua rieng ban.
echo.

%PY% scripts\setup_voices.py
echo.
pause
