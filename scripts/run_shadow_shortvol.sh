#!/usr/bin/env bash
# Nightly forward shadow log for the short-volume sleeve (after paper session).
# Cron entry (weekdays 19:15 local; FINRA daily file posts ~18:00 ET):
#   15 19 * * 1-5 /home/gusanio/agentic-trading-desk-m12/scripts/run_shadow_shortvol.sh
# Self-updates from git before running, and publishes the append-only
# evidence JSONLs afterwards so cloud evaluations can read them.
set -u
cd "$(dirname "$0")/.."
git pull --ff-only origin feature/multi-regime-strategy-portfolio >/dev/null 2>&1 || true
PY="$HOME/agentic-trading-desk/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p data/shadow
PYTHONPATH="src:scripts" "$PY" scripts/shadow_shortvol_forward.py >> data/shadow/shadow.log 2>&1
git add data/shadow/*.jsonl >/dev/null 2>&1 || true
git diff --cached --quiet || {
  git commit -m "shadow evidence: $(date +%F) shortvol" >/dev/null 2>&1 || true
  git push origin feature/multi-regime-strategy-portfolio >/dev/null 2>&1 || true
}
