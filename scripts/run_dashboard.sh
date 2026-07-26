#!/usr/bin/env bash
# Operations Center dashboard server (mini PC).
# Serves the built frontend + read-only API on 0.0.0.0:8000.
# Cron entry for boot persistence:
#   @reboot /home/gusanio/agentic-trading-desk-m12/scripts/run_dashboard.sh
set -u
cd "$(dirname "$0")/.."
PY="$HOME/agentic-trading-desk/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p data/operations
# single instance: kill a previous server if it is still bound
pkill -f "trading_desk.cli operations run" 2>/dev/null || true
sleep 1
PYTHONPATH=src nohup "$PY" -m trading_desk.cli operations run \
  --host 0.0.0.0 --port 8000 \
  --journal data/operations/journal.db \
  >> data/operations/server.log 2>&1 &
echo "dashboard starting on :8000 (pid $!)"
