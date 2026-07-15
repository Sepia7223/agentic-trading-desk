# Agentic Trading Desk Development Guide

This repository is being adapted into a safety-first quantitative trading application. Codex is the development tool for changing the codebase. The OpenAI API is a future runtime analysis provider and must not receive broker credentials.

## Mandatory Reading Order

Before architectural or behavioral work, every human or AI contributor must read:

1. `docs/00_ENGINEERING_BLUEPRINT.md`
2. `docs/01_SYSTEM_ARCHITECTURE.md`
3. `docs/02_ROADMAP.md`
4. The subsystem-specific document relevant to the task
5. `docs/10_DEVELOPMENT_STANDARDS.md`
6. `docs/11_ARCHITECTURAL_DECISIONS.md`

For work involving trade evidence, review, memory, or AI learning, also read `docs/13_TRADE_JOURNAL_AND_MEMORY.md`.

> A milestone is not complete until implementation, tests, architecture, and affected documentation are aligned.

## Non-Negotiable Safety Constraints

- Default broker environment is always `DEMO`.
- Default operating mode is always `READ_ONLY`.
- Live trading is technically disabled.
- Automatic execution is technically disabled.
- Unknown broker, position, market, model, journal, portfolio, or risk state must result in no trade.
- A language model must never control final position size or bypass deterministic risk limits.
- Never use an IG production host. The only broker base URL is `https://demo-api.ig.com/gateway/deal`.
- Do not add real credentials or secrets.
- Do not inspect `.env`.
- Do not implement execution unless a separately reviewed milestone explicitly authorizes it.
- Do not allow any AI provider to access IG credentials or raw authorization data.
- Strategy, AI, workflow, dashboard, backtest, and journal modules may not call IG directly.

## Development Procedure

- Inspect the branch, base commit, `git status`, relevant source, tests, and documentation before editing.
- Preserve unrelated user changes.
- Keep changes focused and use typed, narrow interfaces.
- Use strict or frozen models where appropriate and fail closed on invalid state.
- Add or update tests with every behavioral change.
- Keep planned, validated, and future capabilities clearly separated.
- Record significant architectural changes in `docs/11_ARCHITECTURAL_DECISIONS.md`.
- Update the roadmap and affected specifications before declaring a milestone complete.

## Quantitative Rules

- Preserve chronology and prevent future-data leakage.
- Do not assume same-bar execution.
- Keep final test periods untouched during strategy selection.
- Use realistic spread, slippage, commission, and funding assumptions.
- Compare complex strategies against simple controls and ablations.
- Use deterministic seeds and canonical configuration fingerprints.
- Do not promote AI-generated research directly into trading behavior.

## IG Read-Only Boundary

Every IG request must pass through the central allowlist. The current complete allowed operation surface is:

- `POST /session` version 3: OAuth login.
- `DELETE /session` version 1: logout.
- `GET /accounts` version 1: account review.
- `GET /positions` version 2: open-position review.
- `GET /markets` version 1: market search.
- `GET /markets/{epic}` version 3: market details.
- `GET /prices/{epic}` version 3: one page of historical prices.

All other methods, paths, versions, hosts, and absolute URLs must fail before HTTP transport. Never add order, working-order, confirmation, position-mutation, account-switching, or live-host behavior without an explicitly approved milestone.

## Session Safety

- Use OAuth session v3 only.
- Keep access and refresh tokens in private in-memory `SecretStr` fields only.
- Clear tokens, expiry, and account state after logout attempts, failed login, or detected expiry.
- Never persist or expose tokens through representations, logs, exceptions, CLI output, screenshots, tests, AI prompts, or journal records.
- Do not retry login or refresh OAuth tokens automatically unless separately designed and reviewed.
- Use a monotonic clock for expiry and fail before transport at the safety margin.

## Required Verification

```bash
python -m ruff format --check .
python -m ruff check .
python -m mypy
python -m pytest
git diff --check
```

If checks cannot be run, report that explicitly rather than claiming success.
