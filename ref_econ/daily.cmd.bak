@echo off
rem ---------------------------------------------------------------------
rem  Economy source hunter - scheduled runner
rem    daily.cmd          : seed_seen + hunt
rem    daily.cmd learn    : seed_seen + learn + hunt   (once a day is enough)
rem
rem  NOTE: this file stays pure ASCII on purpose. The project folder name is
rem  Korean, so hardcoding it here would break under a non-UTF8 console
rem  codepage. %~dp0 resolves the path without spelling it out.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "PY=C:\Users\kjg34\AppData\Local\Programs\Python\Python312\python.EXE"
set "LOG=ref_econ\out\_log.txt"

if not exist "ref_econ\out" mkdir "ref_econ\out"

echo. >> "%LOG%"
echo ==== %DATE% %TIME%  (%1) ==================================== >> "%LOG%"

rem keep already-made episodes out of the shortlist
"%PY%" ref_econ\seed_seen.py >> "%LOG%" 2>&1

rem relearn channel weights - only on the run that passes "learn"
if /I "%~1"=="learn" "%PY%" ref_econ\learn.py >> "%LOG%" 2>&1

"%PY%" ref_econ\hunt.py --top 20 >> "%LOG%" 2>&1

if errorlevel 1 (
  echo [FAILED] hunt.py exit=%ERRORLEVEL% >> "%LOG%"
) else (
  echo [OK] see ref_econ\out\ for the newest sheet >> "%LOG%"
  rem push the shortlist to the phone. never let this decide the job's exit code.
  "%PY%" ref_notify\notify_hunt.py --src econ --top 5 >> "%LOG%" 2>&1
)
endlocal
