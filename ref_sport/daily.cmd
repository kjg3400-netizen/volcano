@echo off
rem ---------------------------------------------------------------------
rem  Soccer + golf clip hunter - scheduled runner (daily)
rem
rem  --daily lets topics.py decide the mode. Both topics currently run
rem  "best": scout today's search results into the clip pool, then rank
rem  the already-viral clips. The fresh-upload hunt was measured weaker
rem  for these two channels - see hunt_spec.md - because the pool is made
rem  of aggregator channels and both target channels repackage clips.
rem
rem  The two topics run one after the other on purpose: they hit the same
rem  host, so running them in parallel would double the request rate.
rem
rem  NOTE: pure ASCII on purpose - the project folder name is Korean, and
rem  a .cmd carrying Korean argv breaks under a non-UTF8 console codepage.
rem  That is why --topic takes the aliases soccer/golf (see topics.get).
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "PY=C:\Users\kjg34\AppData\Local\Programs\Python\Python312\python.EXE"
set "LOG=ref_sport\out\_log.txt"

if not exist "ref_sport\out" mkdir "ref_sport\out"

echo. >> "%LOG%"
echo ==== %DATE% %TIME% ==================================== >> "%LOG%"

"%PY%" ref_sport\hunt.py --topic soccer --daily --top 25 >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [FAILED] soccer exit=%ERRORLEVEL% >> "%LOG%"
) else (
  rem never let the notifier decide the job's exit code
  "%PY%" ref_notify\notify_hunt.py --src soccer --top 5 >> "%LOG%" 2>&1
)

"%PY%" ref_sport\hunt.py --topic golf --daily --top 25 >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [FAILED] golf exit=%ERRORLEVEL% >> "%LOG%"
) else (
  "%PY%" ref_notify\notify_hunt.py --src golf --top 5 >> "%LOG%" 2>&1
)

rem drain the Telegram inbox while we are here - messages expire in ~24h
"%PY%" ref_clip\inbox.py >> "%LOG%" 2>&1

echo [DONE] see ref_sport\out\soccer\ and ref_sport\out\golf\ >> "%LOG%"
endlocal
