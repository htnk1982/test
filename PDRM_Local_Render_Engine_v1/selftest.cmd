@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Run setup.cmd first.
  pause
  exit /b 1
)

.venv\Scripts\python.exe selftest_runner.py
set ERR=%ERRORLEVEL%
echo.
if "%ERR%"=="0" (
  echo PDRM CORE SELFTEST PASS
) else (
  echo PDRM CORE SELFTEST FAILED
  echo.
  echo Detailed diagnostics were saved to:
  echo   %~dp0SELFTEST_DIAGNOSTIC.txt
  echo Please send that one text file for diagnosis.
)
pause
exit /b %ERR%
