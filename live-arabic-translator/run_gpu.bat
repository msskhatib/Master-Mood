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
if not exist ".venv\gpu_ready.txt" (
  echo Installing NVIDIA GPU library - one time, about 500 MB...
  ".venv\Scripts\python.exe" -m pip install "nvidia-cublas-cu12>=12.4,<12.9.3" || goto :fail
  echo ok> ".venv\gpu_ready.txt"
)
".venv\Scripts\python.exe" live_translator.py --compute cuda %*
pause
exit /b

:fail
echo.
echo *** Setup failed. Check your internet connection, then run this file again. ***
echo *** If it keeps failing, send a screenshot of this window. ***
pause
exit /b 1
