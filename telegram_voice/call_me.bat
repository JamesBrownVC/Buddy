@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe call.py %*
pause
