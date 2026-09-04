@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Run setup.cmd first.
  pause
  exit /b 1
)

if "%~1"=="" (
  echo Drag the Round 8 A listening-winner WAV/FLAC/AIFF/MP3 onto round9_lab.cmd.
  echo This is an isolated experiment. The production core remains hard-locked to Round 8.
  pause
  exit /b 2
)

echo.
echo PDRM ROUND 9 OPERATOR LAB - EXPERIMENTAL ONLY
echo Baseline: %~1
echo Production pdrm_engine max_round_allowed remains 8.
echo Candidates: Control / Harmonic Elasticity / Peak-Protected Loudness
echo All blind candidates will be level-matched to -14 LUFS-I.
echo.

.venv\Scripts\python.exe -m pdrm_operator_lab.round9 "%~1" --output-root "%~dp0Round9_Output" --target-lufs -14
set ERR=%ERRORLEVEL%
echo.
if "%ERR%"=="0" (
  echo ROUND 9 BLIND PACKAGE READY.
  echo Open Round9_Output and use only the BLIND zip first.
  echo Do NOT open REVEAL_AFTER_LISTENING.txt until your listening rank is fixed.
) else (
  echo ROUND 9 LAB FAILED SAFELY. Re-run after correcting the reported problem.
  echo Completed candidate renders are checkpointed and will be reused when hashes match.
)
pause
exit /b %ERR%
