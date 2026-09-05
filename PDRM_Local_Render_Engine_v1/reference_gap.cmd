@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set OMP_NUM_THREADS=1
set MKL_NUM_THREADS=1
set OPENBLAS_NUM_THREADS=1
if not exist ".venv\Scripts\python.exe" (
  echo Place these two addon files next to the working round9_lab.cmd.
  echo This addon reuses that existing virtual environment.
  pause
  exit /b 2
)
echo PDRM READ-ONLY C / REFERENCE COMPARISON
echo No audio is changed or uploaded. No new listening task is required.
if "%~1"=="" (
  ".venv\Scripts\python.exe" -u "reference_gap.py"
) else if "%~2"=="" (
  ".venv\Scripts\python.exe" -u "reference_gap.py" --job "%~1"
) else (
  ".venv\Scripts\python.exe" -u "reference_gap.py" --job "%~1" --reference "%~2"
)
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo COMPARISON FAILED. Do not repeatedly retry. Keep the traceback and ERROR.json.
)
pause
exit /b %ERR%
