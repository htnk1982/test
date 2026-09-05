@echo off
setlocal
cd /d "%~dp0"
set OMP_NUM_THREADS=1
set MKL_NUM_THREADS=1
set OPENBLAS_NUM_THREADS=1
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Put pdrm_finish.cmd and PDRM_Finish_v1 beside the working round9_lab.cmd.
  echo Existing .venv was not found. No installation was attempted.
  pause
  exit /b 2
)
set SCRIPT=accepted_finish.py
if exist "PDRM_Finish_v1\accepted_finish.py" set SCRIPT=PDRM_Finish_v1\accepted_finish.py
".venv\Scripts\python.exe" -X utf8 "%SCRIPT%" %*
set RESULT=%ERRORLEVEL%
echo.
if not "%RESULT%"=="0" echo One or more files were not published. See LAST_RUN.md or the error above.
pause
exit /b %RESULT%
