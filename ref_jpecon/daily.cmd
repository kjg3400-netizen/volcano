@echo off
rem ---------------------------------------------------------------------
rem  Japanese economy source hunter - scheduled runner
rem    daily.cmd          : seed_seen + hunt
rem    daily.cmd learn    : seed_seen + learn + hunt
rem
rem  NOTE: pure ASCII on purpose. The project folder name is Korean, so
rem  hardcoding it here would break under a non-UTF8 console codepage.
rem  %~dp0 resolves the path without spelling it out.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "PY=C:\Users\kjg34\AppData\Local\Programs\Python\Python312\python.EXE"
set "LOG=ref_jpecon\out\_log.txt"

if not exist "ref_jpecon\out" mkdir "ref_jpecon\out"

echo. >> "%LOG%"
echo ==== %DATE% %TIME%  (%1) ==================================== >> "%LOG%"

rem keep already-made episodes out of the shortlist
"%PY%" ref_jpecon\seed_seen.py >> "%LOG%" 2>&1

rem relearn channel weights - needs 5 mature episodes, exits cleanly until then
if /I "%~1"=="learn" "%PY%" ref_jpecon\learn.py >> "%LOG%" 2>&1

"%PY%" ref_jpecon\hunt.py --top 20 >> "%LOG%" 2>&1

if errorlevel 1 (
  echo [FAILED] hunt.py exit=%ERRORLEVEL% >> "%LOG%"
) else (
  echo [OK] see ref_jpecon\out\ for the newest sheet >> "%LOG%"
  rem push the shortlist to the phone. never let this decide the job's exit code.
  "%PY%" ref_notify\notify_hunt.py --src jp --top 5 >> "%LOG%" 2>&1
)
endlocal
