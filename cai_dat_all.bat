@echo off
chcp 65001 >nul
setlocal
title VoxDub Studio - Cai tat ca
cd /d "%~dp0"

echo.
echo ============================================================
echo   VoxDub Studio - CAI TAT CA THANH PHAN
echo ============================================================
echo   Se cai core, Whisper, VieNeu, Paraformer va Chromium.
echo   Co the mat nhieu GB dung luong va nhieu phut.
echo ============================================================
echo.

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (
  echo [LOI] Khong tim thay Python 3.10+.
  pause
  exit /b 1
)

%PY% -m pip install --upgrade pip
if errorlevel 1 goto :fail
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :fail

if not exist ".env" copy ".env.example" ".env" >nul

%PY% scripts\setup_whisper.py
if errorlevel 1 goto :fail
%PY% scripts\setup_vieneu.py
if errorlevel 1 goto :fail
%PY% scripts\setup_paraformer.py
if errorlevel 1 goto :fail
%PY% scripts\setup_douyin.py
if errorlevel 1 goto :fail

echo.
echo [OK] Cai tat ca thanh phan xong.
echo Chay ung dung bang chay_app.bat
pause
exit /b 0

:fail
echo.
echo [LOI] Buoc cai dat that bai. Chay lai file nay de resume.
pause
exit /b 1
