#!/usr/bin/env bash
# Nightly forward shadow log for the DTC-CFD challenge sleeve.
# Cron entry (weekdays 19:45 local, after paper session + shortvol shadow):
#   45 19 * * 1-5 /home/gusanio/agentic-trading-desk-m12/scripts/run_shadow_dtc.sh
set -u
cd "$(dirname "$0")/.."
PY="$HOME/agentic-trading-desk/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p data/shadow
PYTHONPATH="src:scripts" "$PY" scripts/shadow_dtc_forward.py >> data/shadow/shadow_dtc.log 2>&1
