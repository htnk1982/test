@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "RUNTIME=%~dp0PDRM_OBSERVER_RUNTIME"
set "PY=%RUNTIME%\python.exe"
set "WORKER=%RUNTIME%\observer_worker_spleeter_v47.py"
set "EXE=%~dp0PDRM_P01_Calibrate.exe"
set "LOG=%~dp0P01_RUNTIME_SELFTEST.txt"

echo.
echo ============================================
echo  PDRM P01 Private Calibration
echo ============================================
echo.
echo Runtime preflight is running.
echo Do not close this window.
echo.

if not exist "%PY%" goto missing_runtime
if not exist "%WORKER%" goto missing_runtime
if not exist "%EXE%" goto missing_exe

> "%LOG%" echo PDRM P01 native runtime preflight

"%PY%" -I -c "import json,numpy,scipy,soundfile,tensorflow as tf;print(json.dumps({'success':True,'numpy':numpy.__version__,'scipy':scipy.__version__,'soundfile':soundfile.__version__,'tensorflow':tf.__version__}))" >> "%LOG%" 2>&1
if errorlevel 1 goto native_fail

"%PY%" -I "%WORKER%" --self-test >> "%LOG%" 2>&1
if errorlevel 1 goto worker_fail

echo Runtime preflight PASSED.
echo Starting PDRM P01...
echo.
"%EXE%"
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" goto done

echo.
echo PDRM P01 failed. Exit code: %RC%
echo Return the new P01_FAILURE.json to ChatGPT.
echo.
pause
exit /b %RC%

:native_fail
echo.
echo Native runtime preflight FAILED.
echo Return this file to ChatGPT:
echo %LOG%
echo.
type "%LOG%"
echo.
pause
exit /b 21

:worker_fail
echo.
echo Observer worker self-test FAILED.
echo Return this file to ChatGPT:
echo %LOG%
echo.
type "%LOG%"
echo.
pause
exit /b 22

:missing_runtime
echo ERROR: PDRM_OBSERVER_RUNTIME is incomplete.
pause
exit /b 10

:missing_exe
echo ERROR: PDRM_P01_Calibrate.exe is missing.
pause
exit /b 11

:done
echo.
echo PDRM P01 finished.
echo Return CALIBRATION_MANIFEST.json to ChatGPT if processing completed.
echo.
pause
exit /b 0
