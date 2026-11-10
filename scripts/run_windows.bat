@echo off
rem Starts the app at http://localhost:8501
.venv\Scripts\python -m uvicorn app.api:app --host 127.0.0.1 --port 8501
pause
