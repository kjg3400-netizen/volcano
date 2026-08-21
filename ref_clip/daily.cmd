@echo off
rem ---------------------------------------------------------------------
rem  Drain the Telegram bot inbox into the local clip queue.
rem
rem  Telegram only keeps incoming messages for about 24 hours. This must
rem  run often enough that nothing is lost - it is hooked onto every
rem  scheduled hunter run, not given its own schedule.
rem
rem  Cheap: one HTTPS call, no scraping. Safe to run many times a day.
rem  NOTE: pure ASCII on purpose - the project folder name is Korean.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "PY=C:\Users\kjg34\AppData\Local\Programs\Python\Python312\python.EXE"
set "LOG=ref_clip\_log.txt"

echo. >> "%LOG%"
echo ==== %DATE% %TIME% ==================================== >> "%LOG%"
"%PY%" ref_clip\inbox.py >> "%LOG%" 2>&1
endlocal
