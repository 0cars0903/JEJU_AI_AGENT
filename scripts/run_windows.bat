@echo off
rem Starts the app at http://localhost:8501 and opens it in a private browser window (no browsing history is kept).
rem Run again to open a new private window: the running server is reused.
.venv\Scripts\python -m app.open_browser --if-running http://localhost:8501 && exit /b 0
.venv\Scripts\python -m app.check_env
start "" /b .venv\Scripts\python -m app.open_browser http://localhost:8501
.venv\Scripts\python -m uvicorn app.api:app --host 127.0.0.1 --port 8501
pause
