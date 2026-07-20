# Installation — Clean Host and Mini-PC Service

Reproducible installation of the IG Demo trading desk on a clean host, and its
setup as a long-running service on the Mini PC. DEMO-only; live trading is never
enabled by any step here.

## Prerequisites

- Ubuntu 24.04 (Mini PC target) or any POSIX host with Python 3.12 and Node 22.
- Outbound HTTPS to the IG Demo gateway and to PyPI / npm for install.
- Sufficient disk and memory to meet the budgets in
  `docs/release/performance-budgets.md`.

## Clean-host build (reproducible)

```bash
git clone <repo-url> agentic-trading-desk
cd agentic-trading-desk
python3.12 -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[dev]"
# Backend gates — all must pass on a clean checkout:
python -m ruff format --check . && python -m ruff check . && python -m mypy && python -m pytest
# Frontend:
cd frontend && npm ci && npm run build && cd ..
```

A clean-host build is considered reproducible when the commands above succeed on
a fresh checkout with no local state, matching the pinned toolchain in
`pyproject.toml` and `frontend/package-lock.json`.

## Configuration

1. Copy `.env.example` to `.env` and fill in the IG **Demo** credentials.
   Never commit `.env`; it is git-ignored.
2. Leave `OPERATING_MODE=READ_ONLY`, `LIVE_TRADING_ALLOWED=false`, and
   `AUTOMATIC_EXECUTION_ENABLED=false` unless a governed milestone explicitly
   enables controlled execution.
3. Startup validates the configuration **before any broker session is created**;
   an inconsistent composition (e.g. automatic execution without
   `CONTROLLED_EXECUTION`) fails closed at startup. See
   `docs/operations/environment-reference.md`.

## Mini-PC service (systemd)

Create `/etc/systemd/system/trading-desk.service`:

```ini
[Unit]
Description=IG Demo Trading Desk
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=gusanio
WorkingDirectory=/home/gusanio/agentic-trading-desk
EnvironmentFile=/home/gusanio/agentic-trading-desk/.env
ExecStart=/home/gusanio/agentic-trading-desk/.venv/bin/ig-trader run
Restart=on-failure
RestartSec=10
# Startup preflight + exclusive process lock prevent double-ownership on restart.

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now trading-desk.service
sudo systemctl status trading-desk.service
```

The service relies on the resilience layer: startup preflight gates the run,
the exclusive process lock prevents two instances from owning the desk, and
recovery is reconciliation-first (`docs/runbooks/disaster-recovery.md`).

## Upgrade

Follow `docs/runbooks/release-rollback.md` in reverse for forward upgrades: take a
fingerprint-verified backup, deploy the new commit, reinstall deterministically,
run gates, and let startup preflight + reconciliation gate the resume. Roll back
with that runbook if preflight or reconciliation fails.
