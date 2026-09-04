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
echo Runtime/acceptance state is stored under LOCALAPPDATA by default,
echo so mapped/network/removable install volumes do not own the SQLite crash journal.
echo This test will intentionally terminate one child render, then restart it.
echo It will also render a clean comparison and run representative codec QC.
echo.

.venv\Scripts\python.exe -m pdrm_runtime.acceptance "%~1" --target-lufs -14 --tp -2
set ERR=%ERRORLEVEL%
echo.
if "%ERR%"=="0" (
  echo ACCEPTANCE PASS
  echo The report is under %%LOCALAPPDATA%%\PDRM_Local_Render_Engine_v1\acceptance by default.
  echo Keep ACCEPTANCE_REPORT.json.
) else (
  echo ACCEPTANCE FAILED. Do not start Round 9.
  echo Inspect the newest acceptance folder and ACCEPTANCE_REPORT.json/logs.
)
pause
exit /b %ERR%
