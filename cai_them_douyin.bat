@echo off
chcp 65001 >nul
title VoxDub Studio - Cai them tai video Douyin

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
echo  Cai bo tai video Douyin ^(trinh duyet Chromium, khoang 170 MB^).
echo  Chi can khi ban muon dan link Douyin thang vao app.
echo.

%PY% scripts\setup_douyin.py
echo.
pause
