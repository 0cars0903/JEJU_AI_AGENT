#!/bin/sh
# Run once. Creates .venv and installs packages. Needs Python 3.9 and internet.
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
echo "Optional local LLM: install Ollama, then run: ollama pull qwen3:1.7b"
