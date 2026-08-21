@echo off
rem ---------------------------------------------------------------------
rem  Soccer + golf - deep scout (weekly)
rem
rem  daily.cmd already scouts with the default thresholds. This one digs
rem  wider: a lower view floor and more channels resolved per run, so
rem  smaller channels that never clear 300k get a chance into the pool.
rem  Too slow to run daily (~2x the request count), pointless more often
rem  than weekly since the pool changes over weeks.
rem
rem  NOTE: pure ASCII on purpose - see daily.cmd for why.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "PY=C:\Users\kjg34\AppData\Local\Programs\Python\Python312\python.EXE"
set "LOG=ref_sport\out\_log_scout.txt"

if not exist "ref_sport\out" mkdir "ref_sport\out"

echo. >> "%LOG%"
echo ==== %DATE% %TIME% ==================================== >> "%LOG%"

"%PY%" ref_sport\hunt.py --topic soccer --scout --min-views 120000 --resolve 160 --ttl 1 >> "%LOG%" 2>&1
"%PY%" ref_sport\hunt.py --topic golf   --scout --min-views 120000 --resolve 160 --ttl 1 >> "%LOG%" 2>&1

echo [DONE] pools widened >> "%LOG%"
endlocal
