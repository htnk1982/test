@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.cmd first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pdrm_runtime.cli --work-root "%~dp0.pdrm_runtime" doctor
set ERR=%ERRORLEVEL%
pause
exit /b %ERR%
