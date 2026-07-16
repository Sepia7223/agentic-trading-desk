# Agentic Trading Desk

Safety-first automated trading application foundation, adapted from the original
MIT-licensed Claude + Robinhood MCP Agentic Trading Desk.

The current adapter supports authenticated, strictly read-only access to the IG
REST demo API. It does not call the OpenAI API and contains no order preview,
validation, placement, amendment, closure, deletion, or account-switching code.

## Project Documentation

- [Engineering Blueprint](docs/00_ENGINEERING_BLUEPRINT.md)
- [System Architecture](docs/01_SYSTEM_ARCHITECTURE.md)
- [Roadmap](docs/02_ROADMAP.md)
- [IG Integration](docs/03_IG_INTEGRATION.md)
- [Strategy Engine](docs/04_STRATEGY_ENGINE.md)
- [Mathematics](docs/05_MATHEMATICS.md)
- [Backtesting](docs/06_BACKTESTING.md)
- [Risk Engine](docs/07_RISK_ENGINE.md)
- [AI Architecture](docs/08_AI_ARCHITECTURE.md)
- [Deployment](docs/09_DEPLOYMENT.md)
- [Development Standards](docs/10_DEVELOPMENT_STANDARDS.md)
- [Architectural Decisions](docs/11_ARCHITECTURAL_DECISIONS.md)
- [Glossary](docs/12_GLOSSARY.md)
- [Trade Journal and Memory](docs/13_TRADE_JOURNAL_AND_MEMORY.md)

## Roles

- **Codex** is the software development tool used to modify and maintain this
  repository.
- **OpenAI API** is the eventual runtime AI analysis provider. It will receive
  sanitized strategy outputs and context, not broker credentials.
- **IG demo** is the eventual broker environment. The default environment is
  always demo, and configuration accepts only the exact IG demo REST base URL.
- **Deterministic strategy calculations** remain local Python code. Indicators,
  score pillars, macro scoring, and decision flags are calculated by code, not
  by a language model.
- **Hard-coded risk controls** remain outside model control. The model must not
  choose position size or bypass risk limits.

## Current Safety Posture

- `broker_environment`: `DEMO`
- `operating_mode`: `READ_ONLY`
- `live_trading_allowed`: `false`
- `automatic_execution_enabled`: `false`

Unknown broker, position, market, or risk state must result in no trade. Order
execution is intentionally absent in this milestone.

The broker protocol and IG adapter are read-only and contain no order preview,
validation, or execution methods. Those concerns require separate interfaces
and are outside this milestone.

## Project Layout

```text
src/trading_desk/
  cli.py                    read-only command-line interface
  config.py                 immutable safety-first configuration models
  ig/                       strict IG demo models, policy, errors, and adapter
  ports/                    abstract protocols for future integrations
  strategy/
    configuration.py        immutable deterministic model and gate settings
    data_validation.py      typed fail-closed market-data validation
    indicators.py           EMA, RSI, MACD, TRIX, Bollinger calculations
    kalman.py               explicit local-linear Kalman trend filter
    macro_pillar.py         cross-asset macro-sentiment pillar
    pipeline.py             cutoff-safe strategy orchestration
    regime.py               causal three-state Gaussian HMM
    score.py                three-pillar scoring and decision flags
    signal_engine.py        mandatory long-only signal gates
  risk/                     deterministic approval, sizing, exposure, and decision records
  portfolio/                local-only paper positions, fills, accounting, and event replay
scripts/                    backwards-compatible CLI wrappers
tests/                      unit and regression tests
docs/original-claude-skill.md
```

## Paper Portfolio

Milestone 5 adds a deterministic local paper portfolio. It can consume only an
untampered, unexpired `APPROVED` Risk Decision and its immutable approved intent.
It never increases approved quantity and has no IG, HTTP, credential, AI, or
broker-execution dependency.

Long entries fill from ask plus configured adverse slippage. Open positions are
marked and closed from bid, the liquidation side. Commissions and UTC-daily
funding are itemized with `Decimal`; cash, equity, exposure, realized P&L, and
unrealized P&L are reconstructed from a fingerprint-chained append-only event
ledger. Duplicate approvals are rejected. Missing or non-tradeable quotes never
fabricate fills, and an uncloseable end-of-data position remains unresolved and
unrealized.

Local commands use JSON files and never load broker settings:

```powershell
python -m trading_desk.cli portfolio create --timestamp 2026-07-15T12:00:00+00:00 --output events.json
python -m trading_desk.cli portfolio state --events events.json
python -m trading_desk.cli portfolio replay --events events.json
```

The `open`, `mark`, and `close` subcommands require explicit typed JSON inputs
and UTC timestamps. Every portfolio command prints `Mode: PAPER`,
`Execution: SIMULATED ONLY`, `Broker connectivity: DISABLED`, and
`Live trading: DISABLED`. SQLite persistence and all real execution remain
unavailable.

## Strategy Framework

The deterministic strategy layer preserves the original three-pillar framework:

- **Trend**: price versus EMA20, EMA20/EMA50/EMA200 structure, and EMA200 slope.
- **Momentum**: RSI-14 using Wilder smoothing, MACD histogram, and TRIX versus
  signal.
- **Macro-Sentiment**: cross-asset regime score using RSP/SPY, 10Y-2Y,
  HYG/LQD, IWM/SPY, SPY/TLT, XLY/XLP, and SPY-TLT correlation.

Bollinger Bands are computed as a supporting exhaustion signal and do not feed
directly into the numeric momentum score.

## Regime-Aware Analysis

Milestone 3 adds a deterministic pipeline:

```text
normalized IG prices -> validation -> three-pillar baseline -> Kalman trend
                     -> three-state HMM -> mandatory gates -> candidate or no trade
```

The Kalman model uses the local-linear state `x_t = [level_t, slope_t]` with
`x_t = [[1, 1], [0, 1]] x_(t-1) + w_t` and price observation
`y_t = [1, 0] x_t + v_t`. Process and observation covariance values come from
immutable typed configuration. The implementation exposes every prediction,
innovation, filtered state, and uncertainty.

The diagonal Gaussian HMM has exactly three states. Its causal features are log
return, rolling realized volatility, normalized Kalman slope, normalized
distance from Kalman level, and rolling drawdown. Hidden indices map after
fitting to `BULL_LOW_VOL`, `TRANSITIONAL`, and `BEAR_HIGH_VOL` using
state-weighted return, volatility, and slope statistics. Ambiguous mappings,
insufficient usable history, low state occupancy, fitting warnings, failed
convergence, invalid model matrices, weak probability, or high entropy fail closed.
The signal uses the endpoint smoothed posterior at each explicit cutoff.

Every historical evaluation has an explicit cutoff. Prices, Kalman state,
rolling features, scaler statistics, HMM fit, state mapping, and decision use
only observations at or before that cutoff. Walk-forward analysis refits each
cutoff independently, so appended future bars cannot alter an earlier result.

A `LONG_CANDIDATE` requires all configured gates to pass: valid and fresh
tradeable data, known flat holding state, spread at or below the configured
basis-point limit, a confident bull
low-volatility regime, positive sufficiently certain Kalman slope, acceptable
price deviation, minimum baseline trend and momentum, a fresh rebound trigger,
and no death-cross or relentless-bearish condition. Transitional, bear, or
uncertain regimes produce `NO_TRADE`. An existing holding can produce `WATCH`;
there are no exit instructions.

Every result includes a SHA-256 fingerprint of canonical, sorted strategy
configuration JSON and deterministic component and numerical package versions.
Signals based on completed bar `t` record `NEXT_VALID_BAR` and cannot be treated
as executable at bar `t`. Daily staleness supports a configurable weekend grace;
unknown cadence fails closed. Macro context is optional and explicitly `UNKNOWN`
when absent, unless macro confirmation is configured as mandatory. Supported
ablation variants are `BASELINE_ONLY`, `BASELINE_KALMAN`, `BASELINE_HMM`, and the
default `BASELINE_KALMAN_HMM`. Reproducibility is guaranteed only within a pinned
software environment and deterministic configuration. See
`docs/regime-aware-strategy.md` for equations, assumptions, and limitations.

## CLI Usage

The legacy script paths still work as wrappers:

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
python -m ruff format .
python -m ruff check .
python -m mypy
python -m pytest
```

Python 3.12+ is required.

## IG Demo Credentials

Create or use an IG demo account, then generate an API key from the API-key or
account settings area of the IG demo web application. Keep the demo identifier,
password, and API key local. The adapter accepts only this canonical gateway:

```text
https://demo-api.ig.com/gateway/deal
```

Demo/live separation is enforced by exact URL-component validation of that
gateway and by the immutable `DEMO` and `READ_ONLY` runtime boundary. The
adapter never infers demo status from a loose hostname substring or a
user-provided environment label.

The adapter uses OAuth session v3 exclusively. `X-IG-API-KEY` identifies the
application, while the demo identifier and password establish the user session.
A successful response must contain the required client and account identity plus
an OAuth access token, refresh token, Bearer token type, and positive finite
expiry duration. The body may omit an explicit environment field because the
request destination is already technically restricted to the exact demo gateway;
an explicit non-demo environment fails closed.

Authenticated read-only requests send `Authorization: Bearer <access token>`,
`IG-ACCOUNT-ID`, and the API key. OAuth values remain private in memory and are
never included in models, logs, exceptions, or CLI output. Access-token expiry is
calculated with a monotonic clock and a five-second default safety margin. An
expired token blocks the request before transport. Automatic refresh is not
implemented; each CLI command creates a fresh session and logs out with
`DELETE /session` when finished.

Create a local, untracked configuration from the placeholder template:

```bash
cp .env.example .env
```

On PowerShell:

```powershell
Copy-Item .env.example .env
```

Replace the placeholder values only in `.env`. Git ignores that file. Never
paste credentials or session tokens into Codex, chat, GitHub, screenshots,
issues, logs, test fixtures, or command output.

## Read-Only Commands

```bash
ig-trader config-check
ig-trader ig accounts
ig-trader ig positions
ig-trader ig search-market "EUR/USD"
ig-trader ig market CS.D.EURUSD.CFD.IP
ig-trader ig prices CS.D.EURUSD.CFD.IP --resolution DAY --max-points 20
ig-trader strategy analyze CS.D.EURUSD.CFD.IP
ig-trader strategy walk-forward CS.D.EURUSD.CFD.IP --start-index 220 --end-index 240
```

`DAY`, `HOUR`, and `HOUR_4` are supported price resolutions. Price requests
return one page only. Every command starts with:

```text
Environment: DEMO
Mode: READ_ONLY
Execution: UNAVAILABLE
```

Output is a typed summary rather than a raw IG response. Historical bars with
missing close bid or ask values remain visible but are excluded from the
strategy-ready close series. Account IDs are redacted to at most their final
four characters.

Market details intentionally use `GET /markets/{epic}` version 3. Its
`snapshot.updateTime` value is normalized as a timezone-naive time-of-day; the
adapter does not invent a calendar date or claim a UTC timezone that IG did not
provide. Market-details retrieval remains strictly read-only.

Common safe errors include missing `IG_IDENTIFIER`, `IG_PASSWORD`, or
`IG_API_KEY`; rejected non-demo URLs; invalid or expired sessions; insufficient
authorization; exhausted API allowance; and response-validation failures. Error
messages include only status, IG error code, request ID, and operation name.
They never include credentials, session tokens, login bodies, or full headers.

There are no commands or adapter methods for orders, working orders, position
changes, position closure, or active-account switching.

Example strategy output is summarized and never includes raw broker data:

```text
Environment: DEMO
Mode: READ_ONLY
Execution: UNAVAILABLE
Baseline: trend=2 momentum=1 macro=1 total=4
Kalman: level=1.082 slope=0.0012 slope uncertainty=0.0004
Regime: BULL_LOW_VOL | BULL_LOW_VOL=0.812, TRANSITIONAL=0.151, BEAR_HIGH_VOL=0.037
Action: LONG_CANDIDATE
```

Candidate output is analysis only. It contains no quantity, position size,
leverage, monetary risk, order type, stop, or limit, and cannot execute a trade.

## Deterministic Risk Engine

Milestone 4 adds a local, fail-closed authority between strategy candidates and
the future Paper Portfolio:

```text
strategy candidate -> explicit risk candidate -> ordered risk gates
                   -> RiskDecision -> optional expiring ApprovedTradeIntent
```

The caller must inject complete, timestamped account and market snapshots. The
engine does not call IG, load credentials, use HTTP, read `.env`, use AI, or
infer missing state. Unknown holding, P&L, exposure, position-count, quote,
dealing-rule, account, or market state rejects.

Sizing uses `Decimal` only:

```text
risk budget   = account equity * per-trade risk fraction
risk per unit = abs(entry - stop) * value per price unit
raw quantity  = risk budget / risk per unit
```

Quantity is constrained by available capital, configured and market size
rules, and projected gross, instrument, and asset-class exposure, then rounded
down to a compatible increment. Daily realized/total losses, drawdown,
consecutive losses, open-position counts, freshness, spread, market status,
entry/stop direction, and the kill switch are mandatory gates. The same inputs,
configuration, and explicit evaluation timestamp produce the same canonical
decision fingerprint.

An approved intent contains no broker operation and expires deterministically.
Paper Portfolio accounting is available as local simulation only; broker
execution remains unavailable.

## Leakage-Controlled Backtesting

Milestone 3.5 provides local CSV/Parquet simulation for the four deterministic variants.
Data is split chronologically into non-overlapping TRAIN, VALIDATION, and untouched
TEST periods. Every evaluated signal refits from an expanding or explicitly bounded rolling
history through its cutoff; no future scaler, Kalman, HMM, mapping, benchmark, fill,
trade, or equity information is reused.
Variant comparison is restricted to VALIDATION and contains no test metrics. It can
freeze one selected variant and immutable configuration into a tamper-evident artifact.
Only the separate final-test command can release TEST, and it evaluates that frozen
variant after verifying dataset, split, and configuration fingerprints.

Default fills use the next valid bar's ask for long entry and bid for exit, plus adverse
slippage. Spread, slippage, fixed/proportional commission, funding, and reserved stop
premium are itemized once per trade. The common temporary exit policy uses legacy
baseline exits/exhaustion, a simulation stop, maximum holding period, or forced
end-of-data liquidation at the latest valid tradeable quote after entry. If no eligible
quote exists, the position remains explicitly unresolved and its P&L is not treated as
realized. A `NEXT_CLOSE` entry cannot use that fill bar's earlier high or low for a
stop or target. Intrabar ambiguity defaults to `ADVERSE_FIRST`.

```bash
python -m trading_desk.cli backtest run --data data/eurusd_daily.parquet \
  --epic CS.D.EURUSD.CFD.IP --variant BASELINE_KALMAN_HMM \
  --train-end 2021-12-31 --validation-end 2023-12-31 --test-end 2025-12-31

python -m trading_desk.cli backtest compare --data data/eurusd_daily.parquet \
  --epic CS.D.EURUSD.CFD.IP --train-end 2021-12-31 \
  --validation-end 2023-12-31 --test-end 2025-12-31 \
  --variants BASELINE_ONLY BASELINE_KALMAN BASELINE_HMM BASELINE_KALMAN_HMM \
  --freeze-variant BASELINE_KALMAN_HMM \
  --selection-rationale "Selected from validation evidence" \
  --selection-output frozen-selection.json

python -m trading_desk.cli backtest final-test \
  --data data/eurusd_daily.parquet \
  --selection frozen-selection.json
```

Local commands print `Mode: BACKTEST`, `Execution: SIMULATED ONLY`, and
`Live trading: DISABLED`. They do not load IG credentials or authenticate. JSON, trade
CSV, and Markdown exports contain typed summaries, not raw datasets or account data.
See `docs/backtesting-methodology.md` for formulas and limitations.

**A profitable backtest is evidence for further testing, not proof of a profitable
live strategy.**

## Attribution

The original Claude-specific skill has been preserved at
`docs/original-claude-skill.md` for attribution and reference. The MIT license
and original attribution remain in `LICENSE`.
