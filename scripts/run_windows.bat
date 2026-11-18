@echo off
rem UTF-8 mode: Korean text in files and console works the same on any Windows language setting (2026-11-19).
set PYTHONUTF8=1
rem Starts the app at http://localhost:8501 and opens it in a private browser window (no browsing history is kept).
rem Run again to open a new private window: the running server is reused.
.venv\Scripts\python -m app.open_browser --if-running http://localhost:8501 && exit /b 0
.venv\Scripts\python -m app.check_env
start "" /b .venv\Scripts\python -m app.open_browser http://localhost:8501
rem --no-use-colors: Windows command windows print color codes as text ([32mINFO[0m), 2026-11-16
.venv\Scripts\python -m uvicorn app.api:app --host 127.0.0.1 --port 8501 --no-use-colors
pause
