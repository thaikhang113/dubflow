@echo off
chcp 65001 >nul
title VoxDub Studio - Cai them nghe tieng Trung Paraformer

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
echo  Cai bo nghe tieng Trung Paraformer ^(khoang 520 MB^).
echo  Nghe tieng Trung chinh xac hon Whisper va chay nhanh tren CPU.
echo  Cai xong app se tu dung no cho video tieng Trung.
echo.

%PY% scripts\setup_paraformer.py
echo.
pause
