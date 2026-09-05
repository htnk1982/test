@echo off
setlocal
cd /d "%~dp0"
set OMP_NUM_THREADS=1
set OPENBLAS_NUM_THREADS=1
set MKL_NUM_THREADS=1
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Put this addon beside the existing working .venv folder.
  echo Nothing was installed or changed.
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -u -X utf8 "PDRM_Release_v1_1\release_finish.py" --finished %*
set RESULT=%ERRORLEVEL%
echo.
if not "%RESULT%"=="0" echo Some files failed. See the displayed output path. Do not retry blindly.
pause
exit /b %RESULT%
