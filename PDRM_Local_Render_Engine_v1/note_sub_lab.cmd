@echo off
setlocal
cd /d "%~dp0"
set OMP_NUM_THREADS=1
set MKL_NUM_THREADS=1
set OPENBLAS_NUM_THREADS=1
if not exist ".venv\Scripts\python.exe" (
  echo Put these addon files beside the working round9_lab.cmd.
  echo Existing .venv was not found. Nothing was installed or changed.
  pause
  exit /b 2
)
if "%~1"=="" (
  ".venv\Scripts\python.exe" -X utf8 note_sub_launch.py
) else (
  ".venv\Scripts\python.exe" -X utf8 note_sub_launch.py --manifest "%~1"
)
set RESULT=%ERRORLEVEL%
echo.
if not "%RESULT%"=="0" echo FAILED. Do not retry blindly. Keep the displayed diagnostic file.
pause
exit /b %RESULT%
