#!/bin/sh
# Retrains the question-type classifier from the [OK]/[Change] feedback saved on this PC.
# Keeps the new model only when the 300-question check score is the same or higher. Needs Ollama (bge-m3).
PYTHONWARNINGS=ignore .venv/bin/python tools/retrain.py
