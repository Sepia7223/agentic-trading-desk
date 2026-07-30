#!/usr/bin/env bash
# Operations Center dashboard server (mini PC).
# Governance: the Operations Center binds LOOPBACK ONLY (a reviewed
# security rule; allow_remote_bind is hard-false). Remote access goes
# through an SSH tunnel - see scripts/open_dashboard.ps1.
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
  --port 8000 \
  --journal data/operations/journal.db \
  >> data/operations/server.log 2>&1 &
echo "dashboard starting on 127.0.0.1:8000 (pid $!)"
