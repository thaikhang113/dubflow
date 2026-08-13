@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [LOI] Chua co .venv. Hay chay cai_dat_all.bat truoc.
  exit /b 1
)
if not exist "remote_queue\inbox" mkdir "remote_queue\inbox"
if not exist "remote_queue\status" mkdir "remote_queue\status"
if not exist "remote_queue\running" mkdir "remote_queue\running"
echo Dang chay OpenClaw worker. Queue: %cd%\remote_queue
.venv\Scripts\python.exe scripts\run_remote_worker.py --queue "%cd%\remote_queue"
