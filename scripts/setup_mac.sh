#!/bin/sh
# Run once. Creates .venv and installs packages. Needs Python 3.9 and internet.
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
# Local models (needed for the Agent): bge-m3 (question understanding, 1.2GB), qwen3:1.7b (explanations, 1.4GB),
# qwen2.5:7b (question agent and expert-mode analyst, 4.7GB). Without qwen2.5:7b the question agent is off.
if command -v ollama >/dev/null 2>&1; then
  echo "Downloading local models with Ollama. This needs internet once."
  for m in bge-m3 qwen3:1.7b qwen2.5:7b; do ollama pull "$m"; done
  # Check again and retry once for any model that is still missing.
  for m in bge-m3 qwen3:1.7b qwen2.5:7b; do ollama list | grep -q "^$m" || ollama pull "$m"; done
  .venv/bin/python -m app.check_env
else
  echo "============================================================"
  echo "Ollama was not found. The app still runs, but the question agent is OFF"
  echo "and question understanding is less accurate."
  echo "Install Ollama from https://ollama.com/download , open a NEW terminal, then run this script again."
  echo "============================================================"
fi
