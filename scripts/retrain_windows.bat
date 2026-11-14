@echo off
rem Retrains the question-type classifier from the [OK]/[Change] feedback saved on this PC.
rem Keeps the new model only when the 300-question check score is the same or higher. Needs Ollama (bge-m3).
set PYTHONWARNINGS=ignore
.venv\Scripts\python tools\retrain.py
pause
