@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Run setup.cmd first.
  pause
  exit /b 1
)

if "%~1"=="" (
  echo Drag one private 3+ minute WAV file onto accept_real_audio.cmd.
  echo The audio stays on this PC. Nothing is uploaded.
  pause
  exit /b 2
)

echo.
echo PDRM PRE-ROUND-9 REAL AUDIO ACCEPTANCE
echo Input stays local: %~1
echo This test will intentionally terminate one child render, then restart it.
echo It will also render a clean comparison and run representative codec QC.
echo.

.venv\Scripts\python.exe -m pdrm_runtime.acceptance "%~1" --acceptance-root "%~dp0.pdrm_acceptance" --target-lufs -14 --tp -2
set ERR=%ERRORLEVEL%
echo.
if "%ERR%"=="0" (
  echo ACCEPTANCE PASS
  echo Open .pdrm_acceptance and keep ACCEPTANCE_REPORT.json.
) else (
  echo ACCEPTANCE FAILED. Do not start Round 9.
  echo Open the newest .pdrm_acceptance folder and inspect ACCEPTANCE_REPORT.json/logs.
)
pause
exit /b %ERR%
