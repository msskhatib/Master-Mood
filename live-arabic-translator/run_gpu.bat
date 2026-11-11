@echo off
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
)
if not exist .venv\gpu_ready.txt (
  echo Installing NVIDIA GPU libraries for speech recognition ^(one time, about 500 MB^)...
  .venv\Scripts\pip install "nvidia-cublas-cu12>=12.4,<12.9.3" && echo ok> .venv\gpu_ready.txt
)
.venv\Scripts\python live_translator.py --compute cuda %*
pause
