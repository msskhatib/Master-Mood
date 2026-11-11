@echo off
setlocal
cd /d "%~dp0"
rem ---- one-time setup (repeats automatically until it has fully succeeded) ----
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  python -m venv .venv || goto :fail
)
if not exist ".venv\installed.txt" (
  echo Installing packages - first run takes 5-10 minutes, keep this window open...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
  echo ok> ".venv\installed.txt"
)
".venv\Scripts\python.exe" live_translator.py --compute cpu --model base --cpu-threads 2 %*
pause
exit /b

:fail
echo.
echo *** Setup failed. Check your internet connection, then run this file again. ***
echo *** If it keeps failing, send a screenshot of this window. ***
pause
exit /b 1
