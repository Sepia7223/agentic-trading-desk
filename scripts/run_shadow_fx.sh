#!/usr/bin/env bash
# Nightly forward paper log for the six FX pairs (forward-testing FAILED-backtest
# strategies at ZERO risk). Cron entry (weekdays 19:50, after the DTC shadow):
#   50 19 * * 1-5 /home/gusanio/agentic-trading-desk-m12/scripts/run_shadow_fx.sh
set -u
cd "$(dirname "$0")/.."
git pull --ff-only origin feature/multi-regime-strategy-portfolio >/dev/null 2>&1 || true
PY="$HOME/agentic-trading-desk/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p data/shadow
PYTHONPATH="src:scripts" "$PY" scripts/shadow_fx_forward.py >> data/shadow/shadow_fx.log 2>&1
git add data/shadow/fx_forward.jsonl >/dev/null 2>&1 || true
git diff --cached --quiet || {
  git commit -m "shadow evidence: $(date +%F) fx-forward" >/dev/null 2>&1 || true
  git push origin feature/multi-regime-strategy-portfolio >/dev/null 2>&1 || true
}
