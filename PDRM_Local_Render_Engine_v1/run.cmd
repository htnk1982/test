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
set "WORKROOT=%~dp0.pdrm_runtime"

.venv\Scripts\python.exe -m pdrm_runtime.cli --work-root "%WORKROOT%" render "%INPUT%" "%OUTPUT%" --target-lufs -9 --tp -2
set ERR=%ERRORLEVEL%
echo.
if "%ERR%"=="0" (
  echo Output: %OUTPUT%
  echo Proof:  %OUTPUT%.pdrm.json
  echo Runtime state: %WORKROOT%
) else (
  echo Render failed safely. Existing/foreign output is not overwritten.
  echo Re-run the same command after correcting the reported problem.
)
pause
exit /b %ERR%
