# Laptop → Mini-PC Migration — COMPLETED (2026-07-22, via SSH)

The working environment — code, datasets, live paper-trading state, and the
daily job — was migrated from the laptop to the mini PC over SSH. This document
records the final state (the original draft assumed a Windows mini PC; the
machine runs **Linux**, so the actual layout below supersedes it —
`setup_minipc.ps1` is retained only as a Windows fallback).

## The mini PC (authoritative machine)

- Host: `gusanio@10.0.0.8` (HP ProDesk 400 G4, Ubuntu, Python 3.12,
  timezone America/Curaçao). SSH key: laptop's `~/.ssh/id_ed25519_minipc`.
- Layout (mirrors the laptop):
  - `~/agentic-trading-desk` — main clone (+ shared `.venv`)
  - `~/agentic-trading-desk-m12` — worktree on
    `feature/multi-regime-strategy-portfolio` (the active branch)
- Data, inside the worktree:
  - `data/validation → ~/agentic-trading-desk/data/validation` (symlink; 586 MB
    Dukascopy FX — was already on the machine; symlinked, not duplicated,
    because the disk is ~96% full)
  - `data/pit/` (54 MB — PIT universe, stock bars, coverage, EDGAR events)
  - `data/stocks/` (13 MB) · `data/paper/` (**live paper state** — cash,
    queued orders, journal; transferred intact and verified)
- Verification performed ON the mini PC: full test suite **1,070 passed**; one
  end-to-end pipeline session against a scratch state (`--paper-dir`), proving
  quotes + news gate + validation on Linux without touching the live state
  (the market was open at migration time, so the real session was left to the
  scheduled run).
- Daily job: **cron** `30 18 * * 1-5 ~/agentic-trading-desk-m12/scripts/run_paper_session.sh`
  (logs append to `data/paper/session.log`).

## The laptop (retired from operation)

- All branches pushed to origin (including the orphan
  `feature/regime-aware-strategy`).
- The scheduled task `AgenticDesk-PaperTrade` is **deleted** — the one-machine
  rule: paper sessions run ONLY on the mini PC; two machines would silently
  fork the state.
- The laptop's `data/` copies and `Documents\minipc-migration\` archive are
  now redundant backups; safe to delete when disk space is wanted.

## Operating the mini PC

    ssh -i ~/.ssh/id_ed25519_minipc gusanio@10.0.0.8       # from the laptop
    crontab -l                                             # inspect the job
    tail -50 ~/agentic-trading-desk-m12/data/paper/session.log
    # kill switches (same file semantics as before):
    touch ~/agentic-trading-desk-m12/data/paper/KILL_GLOBAL
    rm    ~/agentic-trading-desk-m12/data/paper/INCIDENT_LOCK   # human-only

Known constraints: disk ~96% full (9.6 GB free — monitor); pushing to GitHub
from the mini PC needs credentials not yet configured (pulls are anonymous
HTTPS and work; sessions never push).
