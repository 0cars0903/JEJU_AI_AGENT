@echo off
rem Run once. Creates .venv and installs packages. Needs Python 3.9 and internet.
py -3.9 -m venv .venv || python -m venv .venv
rem If pip in .venv does not run on this Python (seen on a Windows PC, 2026-11-16), reinstall the pip made for Python 3.9.
.venv\Scripts\python -m pip --version >nul 2>nul
if not %errorlevel%==0 (
  echo pip in .venv does not run. Reinstalling pip for Python 3.9 ...
  powershell -NoProfile -Command "Invoke-WebRequest https://bootstrap.pypa.io/pip/3.9/get-pip.py -OutFile get-pip.py"
  .venv\Scripts\python get-pip.py
  del get-pip.py
)
.venv\Scripts\python -m pip install -r requirements.txt
if not %errorlevel%==0 (
  echo ============================================================
  echo Package install FAILED. The app cannot run yet.
  echo Check the internet connection and the message above, then run this script again.
  echo ============================================================
  pause
  exit /b 1
)
echo.
rem Local models (needed for the Agent): bge-m3 (question understanding, 1.2GB), qwen3:1.7b (explanations, 1.4GB),
rem qwen2.5:7b (question agent and expert-mode analyst, 4.7GB). Without qwen2.5:7b the question agent is off.
where ollama >nul 2>nul
if %errorlevel%==0 (
  echo Downloading local models with Ollama. This needs internet once.
  ollama pull bge-m3
  ollama pull qwen3:1.7b
  ollama pull qwen2.5:7b
  rem Check again and retry once for any model that is still missing.
  for %%m in (bge-m3 qwen3:1.7b qwen2.5:7b) do (
    ollama list | findstr /b /c:"%%m" >nul || ollama pull %%m
  )
  .venv\Scripts\python -m app.check_env
) else (
  echo ============================================================
  echo Ollama was not found. The app still runs, but the question agent is OFF
  echo and question understanding is less accurate.
  echo Install Ollama from https://ollama.com/download , open a NEW command window,
  echo then run this script again.
  echo ============================================================
)
pause
rem Packages installed. A missing Ollama only shows the notice above, so finish as success (2026-11-19: 'where ollama' left errorlevel 1).
exit /b 0
