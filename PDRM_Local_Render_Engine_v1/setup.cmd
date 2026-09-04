@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher "py" was not found.
  echo Install Python 3.11 or 3.12 x64, then run setup.cmd again.
  pause
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv 2>nul
  if errorlevel 1 py -3 -m venv .venv
  if errorlevel 1 exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install -e .
if errorlevel 1 exit /b 1

echo.
echo Setup complete. Run selftest.cmd next.
pause
