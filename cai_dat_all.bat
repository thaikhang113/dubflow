@echo off
chcp 65001 >nul
setlocal
title DubFlow - Cai tat ca
cd /d "%~dp0"

echo.
echo ============================================================
echo   DubFlow - CAI TAT CA THANH PHAN
echo ============================================================
echo   Se cai runtime .venv, Demucs, Whisper, VieNeu,
echo   Paraformer, PaddleOCR, VSR va Chromium.
echo ============================================================
echo.

where py >nul 2>&1
if errorlevel 1 (
  echo [LOI] Khong tim thay Python 3.10+.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto :fail
)

if not exist ".env" copy ".env.example" ".env" >nul

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
%VENV_PY% -m pip --version >nul 2>&1
if errorlevel 1 %VENV_PY% -m ensurepip --upgrade
if errorlevel 1 goto :fail
%VENV_PY% -m pip install --upgrade pip
if errorlevel 1 goto :fail
%VENV_PY% -m pip install -r requirements.txt
if errorlevel 1 goto :fail

py -3 scripts\setup_whisper.py
if errorlevel 1 goto :fail
py -3 scripts\setup_vieneu.py
if errorlevel 1 goto :fail
py -3 scripts\setup_paraformer.py
if errorlevel 1 goto :fail
py -3 scripts\setup_ocr.py
if errorlevel 1 echo [CANH BAO] OCR khong cai duoc - app van chay voi blur thu cong
py -3 scripts\setup_vsr.py
if errorlevel 1 echo [CANH BAO] VSR khong cai duoc - app van chay voi blur thu cong
py -3 scripts\setup_douyin.py
if errorlevel 1 goto :fail
py -3 scripts\setup_demucs.py
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
