@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.cmd first.
  pause
  exit /b 1
)
echo.
echo PDRM DOCTOR - runtime state is stored under LOCALAPPDATA by default.
echo Override only with PDRM_STATE_ROOT if you intentionally need another local fixed-volume path.
echo.
.venv\Scripts\python.exe -m pdrm_runtime.cli doctor
set ERR=%ERRORLEVEL%
pause
exit /b %ERR%
