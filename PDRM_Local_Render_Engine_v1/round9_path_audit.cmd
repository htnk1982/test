@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Put this file and round9_path_audit.py beside the EXISTING round9_lab.cmd.
  echo Use the already-working environment. Do not reinstall it for this audit.
  pause
  exit /b 2
)
if "%~1"=="" (
  echo Drag the existing Round9 job folder or its manifest.json onto this file.
  echo Do not drag an audio file. Original Round9 outputs will not be changed.
  pause
  exit /b 2
)
set "OMP_NUM_THREADS=1"
set "MKL_NUM_THREADS=1"
set "OPENBLAS_NUM_THREADS=1"
.venv\Scripts\python.exe -u round9_path_audit.py "%~1"
set "ERR=%ERRORLEVEL%"
echo.
if "%ERR%"=="0" (
  echo AUDIT COMPLETE. No new listening comparison is requested yet.
) else (
  echo AUDIT STOPPED. Do not retry repeatedly or change the winning audio.
  echo Reports are under LOCALAPPDATA\PDRM_Local_Render_Engine_v1\round9_path_audit.
)
pause
exit /b %ERR%
