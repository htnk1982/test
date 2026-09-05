@echo off
setlocal
cd /d "%~dp0"
set OMP_NUM_THREADS=1
set MKL_NUM_THREADS=1
set OPENBLAS_NUM_THREADS=1
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Put this CMD and PDRM_Distribution_v2 beside the working .venv folder.
  echo Nothing was installed or changed.
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -X utf8 "%~dp0PDRM_Distribution_v2\distribution_launch.py" %*
set RESULT=%ERRORLEVEL%
echo.
if not "%RESULT%"=="0" echo Some files were not published. See LAST_RUN_Distribution_v2.md or the launch log.
pause
exit /b %RESULT%
