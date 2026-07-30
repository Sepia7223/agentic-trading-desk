#!/usr/bin/env bash
# Daily paper-trading session wrapper (Linux/cron).
# Cron entry (weekdays 18:30 local, after the US close):
#   30 18 * * 1-5 /home/gusanio/agentic-trading-desk-m12/scripts/run_paper_session.sh
# Self-updates from git before running, and publishes the session outputs
# (journal, state, confidence ledger/sidecar) so the dashboard can read
# them from the repository on any machine.
set -u
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a  # load Alpaca creds (gitignored)
git pull --ff-only origin feature/multi-regime-strategy-portfolio >/dev/null 2>&1 || true
PY="$HOME/agentic-trading-desk/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p data/paper
PYTHONPATH="src:scripts" "$PY" scripts/paper_trade.py >> data/paper/session.log 2>&1
git add data/paper/journal.jsonl data/paper/paper_state.json \
  data/paper/confidence_calibration.jsonl data/paper/confidence_positions.json \
  >/dev/null 2>&1 || true
git diff --cached --quiet || {
  git commit -m "paper session: $(date +%F)" >/dev/null 2>&1 || true
  git push origin feature/multi-regime-strategy-portfolio >/dev/null 2>&1 || true
}
