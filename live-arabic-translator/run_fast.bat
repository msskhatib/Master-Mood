@echo off
call "%~dp0run_windows.bat" --compute cpu --model base --max-chunk 3 --cpu-threads 2 %*
