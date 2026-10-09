#!/usr/bin/env bash
# One command: install, test, backtest, then run the engine + dashboard.
# Usage: ./start.sh "https://script.google.com/macros/s/XXXX/exec"
set -e
cd "$(dirname "$0")"
[ -n "$1" ] && export IQLAB_SHEETS_WEBHOOK="$1"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
python -m pytest -q tests
python -m iqlab backtest --session-only || echo "backtest skipped (no data feed)"
echo "Dashboard: http://localhost:8765  |  next: open Claude in this folder and type: start trading session"
python -m iqlab run
