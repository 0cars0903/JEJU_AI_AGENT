#!/bin/sh
# Starts the app at http://localhost:8501 and opens it in a private browser window (no browsing history is kept).
# Run again to open a new private window: the running server is reused.
.venv/bin/python -m app.open_browser --if-running http://localhost:8501 && exit 0
.venv/bin/python -m app.check_env
.venv/bin/python -m app.open_browser http://localhost:8501 &
PYTHONWARNINGS=ignore .venv/bin/python -m uvicorn app.api:app --host 127.0.0.1 --port 8501
