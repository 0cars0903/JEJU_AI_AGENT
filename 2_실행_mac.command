#!/bin/sh
# Start the app (http://localhost:8501). Runs scripts/run_mac.sh from this folder.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "============================================================"
  echo "The app is not installed yet. Run 1_설치_mac.command first, then run this file again."
  echo "============================================================"
  exit 1
fi
sh scripts/run_mac.sh
