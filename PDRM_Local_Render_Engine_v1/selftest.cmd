@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Run setup.cmd first.
  pause
  exit /b 1
)

.venv\Scripts\python.exe -m unittest discover -s tests -v
set ERR=%ERRORLEVEL%
echo.
if "%ERR%"=="0" (
  echo PDRM CORE SELFTEST PASS
) else (
  echo PDRM CORE SELFTEST FAILED
)
pause
exit /b %ERR%
