@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Run setup.cmd first.
  pause
  exit /b 1
)

if "%~1"=="" (
  echo Drag a WAV file onto run.cmd.
  echo Optional direct use:
  echo   run.cmd "C:\path\song.wav"
  pause
  exit /b 2
)

set "INPUT=%~1"
set "OUTPUT=%~dpn1_PDRM.wav"
set "REPORT=%~dpn1_PDRM.json"

.venv\Scripts\python.exe -m pdrm_engine.cli "%INPUT%" "%OUTPUT%" --target-lufs -9 --tp -2 --report "%REPORT%"
set ERR=%ERRORLEVEL%
echo.
if "%ERR%"=="0" (
  echo Output: %OUTPUT%
  echo Report: %REPORT%
) else (
  echo Render failed. No automatic retry is performed by this launcher.
)
pause
exit /b %ERR%
