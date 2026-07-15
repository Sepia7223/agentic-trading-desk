# Agentic Trading Desk

Safety-first automated trading application foundation, adapted from the original MIT-licensed Claude + Robinhood MCP Agentic Trading Desk.

The current adapter supports authenticated, strictly read-only access to the IG REST Demo API. It does not call the OpenAI API and contains no order preview, validation, placement, amendment, closure, deletion, confirmation, or account-switching code.

## Roles

- **Codex** is the software development tool used to modify and maintain this repository.
- **OpenAI API** is the eventual runtime AI analysis provider. It will receive sanitized strategy, risk, and journal context, not broker credentials.
- **IG Demo** is the required initial broker environment. Configuration accepts only the exact IG Demo REST base URL.
- **Deterministic strategy calculations** remain local Python code. Indicators, scores, and decision flags are calculated by code, not a language model; planned quantitative models must preserve that boundary.
- **Deterministic risk controls** remain outside model control. A language model must not choose final position size or bypass risk limits.

## Current Safety Posture

- `broker_environment`: `DEMO`
- `operating_mode`: `READ_ONLY`
- `live_trading_allowed`: `false`
- `automatic_execution_enabled`: `false`

Unknown broker, position, market, model, journal, portfolio, or risk state must result in no trade. Order execution is intentionally absent in the current validated milestone.

The broker protocol and IG adapter are read-only and contain no order preview, validation, or execution methods. Those concerns require separate interfaces and are outside the current milestone.

## Project Documentation

The engineering manual is the authoritative reference for project goals, architecture, milestone status, and safety boundaries:

- [Engineering Blueprint](docs/00_ENGINEERING_BLUEPRINT.md)
- [System Architecture](docs/01_SYSTEM_ARCHITECTURE.md)
- [Project Roadmap](docs/02_ROADMAP.md)
- [IG.com Integration](docs/03_IG_INTEGRATION.md)
- [Strategy Engine](docs/04_STRATEGY_ENGINE.md)
- [Mathematics and Quantitative Models](docs/05_MATHEMATICS.md)
- [Leakage-Controlled Backtesting](docs/06_BACKTESTING.md)
- [Deterministic Risk Engine](docs/07_RISK_ENGINE.md)
- [AI Architecture and Governance](docs/08_AI_ARCHITECTURE.md)
- [Deployment and Operations](docs/09_DEPLOYMENT.md)
- [Development Standards](docs/10_DEVELOPMENT_STANDARDS.md)
- [Architecture Decision Records](docs/11_ARCHITECTURAL_DECISIONS.md)
- [Glossary](docs/12_GLOSSARY.md)
- [Trade Journal, Review and Memory](docs/13_TRADE_JOURNAL_AND_MEMORY.md)

Contributors must follow the reading order and milestone governance in [AGENTS.md](AGENTS.md).

## Current Validated Milestones

- Milestone 0 — Planning
- Milestone 1 — Foundation
- Milestone 2 — IG OAuth v3 Demo Read-Only Integration

## Planned and Future Milestones

The next planned milestone is **Milestone 3 — Regime-Aware Strategy Engine**, followed by **Milestone 3.5 — Leakage-Controlled Backtesting**. Deterministic risk, paper portfolio, historical trade memory, runtime AI analysis, Demo execution, and live trading remain planned or future capabilities.

## Project Layout

```text
src/trading_desk/
  cli.py                    read-only command-line interface
  config.py                 immutable safety-first configuration models
  ig/                       strict IG Demo models, policy, errors, and adapter
  ports/                    abstract protocols for future integrations
  strategy/                 deterministic baseline and strategy components
scripts/                    backwards-compatible CLI wrappers
tests/                      unit, regression, and safety tests
docs/                       engineering manual and preserved attribution
```

## Strategy Framework

The deterministic baseline preserves the original three-pillar framework:

- **Trend**: price versus EMA20, EMA20/EMA50/EMA200 structure, and EMA200 slope.
- **Momentum**: RSI-14 using Wilder smoothing, MACD histogram, and TRIX versus signal.
- **Macro-Sentiment**: cross-asset regime score using RSP/SPY, 10Y-2Y, HYG/LQD, IWM/SPY, SPY/TLT, XLY/XLP, and SPY-TLT correlation.

Bollinger Bands are computed as a supporting exhaustion signal and do not feed directly into the numeric momentum score.

The planned Milestone 3 design adds a local-linear Kalman trend estimate, a three-state Gaussian HMM, deterministic state mapping, strict gates, and configuration fingerprints. The Strategy Engine will produce candidates only; it will not execute or size trades.

## CLI Usage

Legacy script paths remain available:

```bash
python scripts/indicators.py input_ticker.json
python scripts/macro_pillar.py macro_input.json --json
python scripts/score.py ticker_input.json --json
```

Installed console scripts are also defined:

```bash
trading-desk-indicators input_ticker.json
trading-desk-macro-pillar macro_input.json --json
trading-desk-score ticker_input.json --json
```

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff format --check .
python -m ruff check .
python -m mypy
python -m pytest
git diff --check
```

Python 3.12+ is required.

## IG Demo Credentials

Create or use an IG Demo account, then generate an API key from the API-key or account settings area of the IG Demo web application. Keep the Demo identifier, password, and API key local. The adapter accepts only this canonical gateway:

```text
https://demo-api.ig.com/gateway/deal
```

Demo/live separation is enforced by exact URL-component validation and by the immutable `DEMO` and `READ_ONLY` runtime boundary. The adapter never infers Demo status from a loose hostname substring or a user-provided label.

The adapter uses OAuth session v3 exclusively. `X-IG-API-KEY` identifies the application, while the Demo identifier and password establish the user session. A successful response must contain required client and account identity plus an OAuth access token, refresh token, Bearer token type, and positive finite expiry duration. An explicit non-Demo environment fails closed.

Authenticated read-only requests send `Authorization: Bearer <access token>`, `IG-ACCOUNT-ID`, and the API key. OAuth values remain private in memory and are never included in models, logs, exceptions, journals, prompts, or CLI output. Expiry is calculated with a monotonic clock and a safety margin. Automatic refresh is not implemented; each CLI command creates a fresh session and logs out with `DELETE /session` when finished.

Create a local, untracked configuration from the placeholder template:

```bash
cp .env.example .env
```

On PowerShell:

```powershell
Copy-Item .env.example .env
```

Replace placeholder values only in `.env`. Git ignores that file. Never paste credentials or session tokens into Codex, chat, GitHub, screenshots, issues, logs, test fixtures, journals, AI prompts, or command output.

## Read-Only Commands

```bash
ig-trader config-check
ig-trader ig accounts
ig-trader ig positions
ig-trader ig search-market "EUR/USD"
ig-trader ig market CS.D.EURUSD.CFD.IP
ig-trader ig prices CS.D.EURUSD.CFD.IP --resolution DAY --max-points 20
```

`DAY`, `HOUR`, and `HOUR_4` are supported price resolutions. Price requests return one page only. Every command starts with:

```text
Environment: DEMO
Mode: READ_ONLY
```

Output is a typed summary rather than a raw IG response. Historical bars with missing close bid or ask values remain visible but are excluded from the strategy-ready close series. Account IDs are redacted to at most their final four characters.

Market details intentionally use `GET /markets/{epic}` version 3. Its `snapshot.updateTime` value is normalized as a timezone-naive time-of-day; the adapter does not invent a calendar date or claim a UTC timezone that IG did not provide.

Common safe errors include missing credentials; rejected non-Demo URLs; invalid or expired sessions; insufficient authorization; exhausted API allowance; and response-validation failures. Diagnostics never include credentials, session tokens, login bodies, full headers, or raw sensitive responses.

There are no commands or adapter methods for orders, working orders, position changes, position closure, confirmations, live hosts, or active-account switching.

## Attribution

The original Claude-specific skill is preserved at `docs/original-claude-skill.md` for attribution and reference. The MIT license and original attribution remain in `LICENSE`.
