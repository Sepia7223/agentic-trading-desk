#!/usr/bin/env bash
# Nightly forward shadow log for the short-volume sleeve (after paper session).
# Cron entry (weekdays 19:15 local; FINRA daily file posts ~18:00 ET):
#   15 19 * * 1-5 /home/gusanio/agentic-trading-desk-m12/scripts/run_shadow_shortvol.sh
set -u
cd "$(dirname "$0")/.."
PY="$HOME/agentic-trading-desk/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p data/shadow
PYTHONPATH="src:scripts" "$PY" scripts/shadow_shortvol_forward.py >> data/shadow/shadow.log 2>&1
