@echo off
call "%~dp0run_windows.bat" --model base --max-chunk 3 --claude-model claude-haiku-5-5 %*
