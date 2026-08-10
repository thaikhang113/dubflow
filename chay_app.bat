@echo off
chcp 65001 >nul
title VoxDub Studio

cd /d "%~dp0"

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"

if not defined PY (
    echo.
    echo  [LOI] Khong tim thay Python. Hay chay  cai_dat.bat  truoc.
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" copy ".env.example" ".env" >nul
)

echo  Dang mo VoxDub Studio...
%PY% -m autodub_gui
if errorlevel 1 (
    echo.
    echo  [LOI] App khong mo duoc. Hay chay lai  cai_dat.bat  roi thu lai.
    echo  Van loi thi bao loi tai:
    echo      https://github.com/ttthanh2044/voxdub/issues
    echo.
    pause
)
