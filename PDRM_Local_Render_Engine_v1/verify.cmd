@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.cmd first.
  pause
  exit /b 1
)
if "%~1"=="" (
  echo Drag a PDRM output WAV onto verify.cmd.
  pause
  exit /b 2
)
.venv\Scripts\python.exe -m pdrm_runtime.cli --work-root "%~dp0.pdrm_runtime" verify "%~1"
set ERR=%ERRORLEVEL%
pause
exit /b %ERR%
