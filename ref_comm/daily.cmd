@echo off
rem ---------------------------------------------------------------------
rem  Korean community source hunter - scheduled runner
rem
rem  NOTE: pure ASCII on purpose. The project folder name is Korean, so
rem  hardcoding it here would break under a non-UTF8 console codepage.
rem  %~dp0 resolves the path without spelling it out.
rem
rem  The seen-list is shared with the economy hunter, and ref_econ\daily.cmd
rem  already refreshes it, so it is not called again here.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "PY=C:\Users\kjg34\AppData\Local\Programs\Python\Python312\python.EXE"
set "LOG=ref_comm\out\_log.txt"

if not exist "ref_comm\out" mkdir "ref_comm\out"

echo. >> "%LOG%"
echo ==== %DATE% %TIME% ==================================== >> "%LOG%"

"%PY%" ref_comm\hunt.py --top 20 >> "%LOG%" 2>&1

if errorlevel 1 (
  echo [FAILED] hunt.py exit=%ERRORLEVEL% >> "%LOG%"
) else (
  echo [OK] see ref_comm\out\ for the newest sheet >> "%LOG%"
  rem push the shortlist to the phone. never let this decide the job's exit code.
  "%PY%" ref_notify\notify_hunt.py --src comm --top 5 >> "%LOG%" 2>&1
)
endlocal
