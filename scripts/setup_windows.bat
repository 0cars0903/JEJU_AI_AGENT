@echo off
rem Run once. Creates .venv and installs packages. Needs Python 3.9 and internet.
py -3.9 -m venv .venv || python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
echo.
echo Optional local LLM: install Ollama, then run: ollama pull qwen3:1.7b
pause
