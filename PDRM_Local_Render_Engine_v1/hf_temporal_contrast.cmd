@echo off
setlocal
cd /d "%~dp0"
set OMP_NUM_THREADS=1
set MKL_NUM_THREADS=1
set OPENBLAS_NUM_THREADS=1
if not exist ".venv\Scripts\python.exe" (
  echo Put this addon beside the working note_sub_lab.cmd. No installation attempted.
  pause
  exit /b 2
)
if "%~1"=="" (
  ".venv\Scripts\python.exe" -X utf8 hf_temporal_contrast_lab.py
) else (
  ".venv\Scripts\python.exe" -X utf8 hf_temporal_contrast_lab.py --source "%~1"
)
set RESULT=%ERRORLEVEL%
if not "%RESULT%"=="0" echo FAILED. Preserve the message above; do not retry blindly.
pause
exit /b %RESULT%
