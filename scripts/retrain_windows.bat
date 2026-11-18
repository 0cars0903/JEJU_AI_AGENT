@echo off
rem UTF-8 mode: Korean text in files and console works the same on any Windows language setting (2026-11-19).
set PYTHONUTF8=1
rem Retrains the question-type classifier from the [OK]/[Change] feedback saved on this PC.
rem Keeps the new model only when the 300-question check score is the same or higher. Needs Ollama (bge-m3).
set PYTHONWARNINGS=ignore
.venv\Scripts\python tools\retrain.py
pause
