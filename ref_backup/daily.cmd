@echo off
rem ---------------------------------------------------------------------
rem  Copy tools and rules to OneDrive, one dated folder per day.
rem
rem  Only ~400 KB - the scripts, the spec notes, CLAUDE.md and the API
rem  keys. The 15 GB of work_* folders are deliberately left out: they are
rem  caches, wavs and mp4s that can be rebuilt, and some hold token probes.
rem  ig_cookies.txt is never copied.
rem
rem  NOTE: pure ASCII on purpose - the project folder name is Korean.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "PY=C:\Users\kjg34\AppData\Local\Programs\Python\Python312\python.EXE"
set "LOG=ref_backup\_log.txt"

echo. >> "%LOG%"
echo ==== %DATE% %TIME% ==================================== >> "%LOG%"
"%PY%" ref_backup\backup.py >> "%LOG%" 2>&1
endlocal
