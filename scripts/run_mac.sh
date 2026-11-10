#!/bin/sh
# Starts the app at http://localhost:8501
PYTHONWARNINGS=ignore .venv/bin/python -m uvicorn app.api:app --host 127.0.0.1 --port 8501
