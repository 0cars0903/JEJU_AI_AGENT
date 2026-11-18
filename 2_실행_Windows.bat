@echo off
rem Start the app (http://localhost:8501). Runs scripts\run_windows.bat from this folder.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo ============================================================
  echo The app is not installed yet. First run the setup file in this folder
  echo (the file name starting with 1_ and ending with _Windows.bat), then run this file again.
  echo ============================================================
  pause
  exit /b 1
)
call scripts\run_windows.bat
