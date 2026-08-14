@echo off
chcp 65001 >nul
title DubFlow

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  [LOI] Chua co .venv. Hay chay cai_dat_all.bat truoc.
  echo.
  pause
  exit /b 1
)

if not exist ".env" (
    if exist ".env.example" copy ".env.example" ".env" >nul
)

echo  Dang mo DubFlow...
.venv\Scripts\python.exe -m autodub_gui
if errorlevel 1 (
  echo.
  echo  [LOI] App khong mo duoc. Hay chay lai cai_dat_all.bat roi thu lai.
  echo  Van loi thi bao loi tai:
  echo      https://github.com/thaikhang113/dubflow/issues
    echo.
    pause
)
