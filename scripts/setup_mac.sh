#!/bin/sh
# Run once. Creates .venv and installs packages. Needs Python 3.9 and internet.
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
# Local models: bge-m3 (question understanding, 1.2GB), qwen3:1.7b (explanations, 1.4GB), qwen2.5:7b (expert-mode tool agent, 4.7GB).
if command -v ollama >/dev/null 2>&1; then
  echo "Downloading local models with Ollama. This needs internet once."
  ollama pull bge-m3
  ollama pull qwen3:1.7b
  ollama pull qwen2.5:7b
else
  echo "Ollama was not found. The app still works, but question understanding is less accurate."
  echo "Install Ollama from https://ollama.com/download , then run this script again."
fi
