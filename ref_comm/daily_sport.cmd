@echo off
rem ---------------------------------------------------------------------
rem  Football / golf / dance source hunter - once a day
rem
rem  For the clip channels (jjack, shortview, chipchip). These repackage
rem  other people's video, so the general community feed alone misses them.
rem
rem  --tag sport keeps the output OUT of the regular community sheet;
rem  without it this run would overwrite ref_comm's normal shortlist.
rem  FIFA is dropped by default (owner's instruction 2026-08-21).
rem
rem  NOTE: pure ASCII on purpose - the project folder name is Korean.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "PY=C:\Users\kjg34\AppData\Local\Programs\Python\Python312\python.EXE"
set "LOG=ref_comm\out\_log_sport.txt"

if not exist "ref_comm\out" mkdir "ref_comm\out"

echo. >> "%LOG%"
echo ==== %DATE% %TIME% ==================================== >> "%LOG%"

rem --sport is shorthand for the Korean topic list plus --tag sport.
rem The topic names live in hunt.py on purpose: Korean text inside a .cmd
rem gets mangled depending on the console codepage.
"%PY%" ref_comm\hunt.py --sport --top 20 >> "%LOG%" 2>&1

if errorlevel 1 (
  echo [FAILED] hunt.py exit=%ERRORLEVEL% >> "%LOG%"
) else (
  echo [OK] sport sheet written to ref_comm\out\ >> "%LOG%"
  rem push to the phone. never let this decide the job's exit code.
  "%PY%" ref_notify\notify_hunt.py --src sport --top 8 >> "%LOG%" 2>&1
)
endlocal
