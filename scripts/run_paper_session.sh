#!/usr/bin/env bash
# Daily paper-trading session wrapper (Linux/cron).
# Cron entry (weekdays 18:30 local, after the US close):
#   30 18 * * 1-5 /home/gusanio/agentic-trading-desk-m12/scripts/run_paper_session.sh
set -u
cd "$(dirname "$0")/.."
PY="$HOME/agentic-trading-desk/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p data/paper
PYTHONPATH="src:scripts" "$PY" scripts/paper_trade.py >> data/paper/session.log 2>&1
