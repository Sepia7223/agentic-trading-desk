# Agentic Trading Desk

Safety-first automated trading application foundation, adapted from the original
MIT-licensed Claude + Robinhood MCP Agentic Trading Desk.

The broker integration supports authenticated read-only IG Demo access plus a
separate, disabled-by-default controlled boundary for opening one long Demo
market position. It contains no live, closure, amendment, working-order,
deletion, or account-switching capability.

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
- `operating_mode`: `READ_ONLY` by default; `CONTROLLED_EXECUTION` is explicit
- `live_trading_allowed`: `false`
- `automatic_execution_enabled`: `false`

Unknown broker, position, market, risk, approval, confirmation, or reconciliation
state results in no submission or a reconciliation-required state. The existing
broker protocol remains read-only. Mutation exists only behind the dedicated
execution port and exact IG Demo allowlist.

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
  ai/                       disabled-by-default sanitized advisory analysis and research
  execution/                controlled preflight, confirmation, idempotency, and reconciliation
  journal/                  append-only SQLite evidence, reviews, retrieval, backup, and export
  operations/               immutable monitoring projections, health, alerts, replay, and search
  api/                      versioned GET-only FastAPI and sanitized WebSocket endpoints
frontend/                   React/TypeScript local Operations Center
scripts/                    backwards-compatible CLI wrappers
tests/                      unit and regression tests
docs/original-claude-skill.md
```

## Trading Desk Operations Center

Milestone 9 adds a disabled-by-default, local, journal-first supervision UI. It
binds only to loopback, receives a `ReadOnlyJournal`, and exposes versioned GET
endpoints plus a sanitized server-to-client WebSocket. It has no broker, risk,
portfolio, execution, journal-write, halt-clearing, or AI operational authority.

Build the frontend and start the server against an explicit local journal:

```powershell
Set-Location frontend
npm ci
npm run build
Set-Location ..
python -m trading_desk.cli operations run --host 127.0.0.1 --port 8000 --journal .trading-desk/journal.db
```

Open `http://127.0.0.1:8000`. Every page keeps these boundaries visible:

```text
Environment: IG DEMO
Live trading: DISABLED
Dashboard authority: READ ONLY
```

Validated views cover system health, market context, strategy routing,
deterministic lineage-based why-no-trade reconstruction, risk gates, joined
execution lifecycles, current Paper portfolio state, reconciled Demo positions,
closed trades, backend-computed performance and costs, AI advisory records,
alerts, journal state, cutoff-safe replay, bounded search, sanitized JSONL/CSV/
Markdown downloads, and redacted configuration. Typed WebSocket events
invalidate the displayed REST projections so live screens refresh without an
operator page reload. Runtime sources that are not supplied are shown as
`UNKNOWN`.

The performance view includes realized and unrealized P&L, equity and drawdown,
daily P&L, spread/slippage/commission/funding attribution, exposure, turnover,
and deterministic breakdowns by available instrument, strategy, regime,
session, volatility, event, and environment evidence. JavaScript displays these
backend projections and does not recalculate trading results.

Still prohibited are dashboard order submission, closure or amendment, risk or
strategy changes, halt clearing, journal rewriting, AI control, live trading,
production-host access, and remote unauthenticated access.

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
`Live trading: DISABLED`. The Paper Portfolio remains unable to call any broker
or execution adapter.

## AI Analyst

Milestone 6 adds a provider-neutral advisory analysis layer. It explains
deterministic signals and risk decisions, reviews paper trades and portfolio
summaries, interprets precomputed historical evidence, and creates append-only
structured analysis records for human review.

AI analysis and network providers are disabled by default. The implementation
contains a protocol and deterministic fake provider only; it does not call the
OpenAI API or require an API key. Strict sanitization rejects credentials,
authorization data, raw broker responses, local paths, unsafe questions,
oversized requests, and future historical records before provider invocation.

```powershell
python -m trading_desk.cli ai explain-signal --record-id <record-id>
python -m trading_desk.cli ai explain-risk --decision-id <decision-id>
python -m trading_desk.cli ai review-trade --trade-id <trade-id>
python -m trading_desk.cli ai daily-review --date YYYY-MM-DD
```

The default commands return `DISABLED` without loading broker configuration.
Every response is structured, fingerprinted, source-linked, and carries the
mandatory advisory statement. AI cannot approve, size, execute, mutate, or
override deterministic systems, and provider failure cannot block them.

## Controlled IG Demo Execution

Milestone 7 adds a dedicated execution subsystem for one long `MARKET`
position opening through `POST /positions/otc` version 2. It uses
only `https://demo-api.ig.com/gateway/deal`; confirmation lookup is
`GET /confirms/{dealReference}` version 1. The existing read-only IG allowlist
and broker protocol remain unchanged.

Execution is disabled by default. Submission requires `CONTROLLED_EXECUTION`,
the explicit `--enable-execution` CLI switch, an intact unexpired approved
intent, fresh account and market state, a second Risk Engine approval, a bound
operator confirmation in the default manual mode, acceptable price/spread
drift, and unused idempotency keys. Quantity is rounded down and may only stay
equal or decrease.

Submission is attempted once. A timeout, malformed acknowledgement, unknown
confirmation, or confirmation mismatch is potentially executed and requires
reconciliation; it is never retried automatically. Automated tests use mocks
only.

A separate `AUTOMATED_DEMO` mode is implemented for bounded observation. It is
disabled by default and requires both `--enable-execution` and
`--enable-automatic-demo-execution`. The initial policy permits one order per
cycle and day, one open Demo position, a 0.1% risk fraction, 1% notional,
0.5% daily loss, 1% drawdown, a one-hour cooldown, long market orders only,
and a protective stop. State is fingerprinted, hash-linked, and locked against
concurrent runners. Any unresolved submission latches a halt.

```powershell
python -m trading_desk.cli execution automated-demo-smoke `
  --epic CS.D.EURUSD.CFD.IP --max-orders 1 `
  --enable-execution --enable-automatic-demo-execution --initialize-state

python -m trading_desk.cli execution automated-demo-run `
  --epic CS.D.EURUSD.CFD.IP --cycles 24 --interval-seconds 3600 `
  --max-orders-per-day 1 --enable-execution `
  --enable-automatic-demo-execution
```

The manual mode retains request-bound confirmation. Automated mode replaces it
only with stricter immutable Demo policy authorization and dual switches. It
never forces a trade: `WATCH`, `NO_TRADE`, and risk rejection are safe cycle
results. Operational validation remains pending until a naturally eligible
signal is confirmed and reconciled in IG Demo.

Every execution command prints `Environment: IG DEMO`,
`Mode: CONTROLLED EXECUTION`, and `Live trading: DISABLED`. Manual commands
also print `Automatic execution: DISABLED` and `Operator confirmation:
REQUIRED`; automated commands identify the explicit Demo policy boundary.

## Durable Trade Journal

Milestone 8 adds a local SQLite evidence store around the existing immutable
Strategy, Risk, Paper Portfolio, Demo Execution, and AI records. The journal is
append-only: records are sequence ordered and SHA-256 fingerprint chained,
source parents are linked, batches are transactional, and corrections create
new amendment records while preserving originals. There is no update or hard
delete operation.

The database path is always explicit. Startup applies the supported schema
migration, enables foreign keys and WAL, verifies the chain and payloads, and
enters recovery-read-only mode after unrecoverable integrity findings. Reviews,
queries, normalized-distance comparisons, backups, and exports are deterministic
and cutoff bounded. Raw provider responses, credentials, OAuth values,
authorization headers, and broker access are prohibited.

Schema version 2 also stores a record-count and chain-head anchor and installs
SQLite guards that reject direct record updates and deletes. These controls detect
local corruption and straightforward mutation; they are not a substitute for a
future keyed signature and independently controlled WORM anchor.

```powershell
python -m trading_desk.cli journal init --database journal.db
python -m trading_desk.cli journal status --database journal.db
python -m trading_desk.cli journal verify --database journal.db
python -m trading_desk.cli journal query --database journal.db --record-type RISK_DECISION
python -m trading_desk.cli journal lineage --database journal.db --source-id <source-id>
python -m trading_desk.cli journal daily-review --database journal.db --date 2026-07-16
python -m trading_desk.cli journal backup --database journal.db --destination backups
python -m trading_desk.cli journal export --database journal.db --format jsonl --output export.jsonl
```

Every command prints `Mode: JOURNAL`, `Trading authority: NONE`,
`Broker access: DISABLED`, `Mutation of source records: DISABLED`, and
`Live trading: DISABLED`. JSONL, selected-field CSV, and Markdown exports carry
schema, configuration, query, count, timestamp, and checksum metadata.
Similarity is deterministic structured comparison, not machine learning.
Semantic vector search, autonomous learning, cloud persistence, and journal-led
strategy, risk, portfolio, or execution changes remain future and prohibited.

## Market Context And Strategy Routing

Milestone 7.5 was applied after Milestone 8 in repository history. It adds a
deterministic, cutoff-safe Market Context Engine, validated-strategy registry,
capital-preservation route, UTC/DST-aware session classifier, structured event
windows, and completed-bar scheduler. New context and router evidence uses the
existing durable append-only journal record taxonomy.

Validated capability is deliberately narrow: the existing trend/regime strategy
is the only executable strategy. Range mean reversion, volatility breakout, and
post-news continuation are `RESEARCH_ONLY`; the router can evaluate and journal
them but cannot send them to Risk or execution. AI has no strategy-selection
authority. A missing, stale, conflicting, illiquid, event-blocked, or otherwise
invalid context routes to capital preservation.

Operational strategy and automated Demo paths require an authoritative
`CandidateContextProvider`. When none is configured, candidate actions are
suppressed with `MARKET_CONTEXT_UNAVAILABLE`; the system does not infer missing
events, liquidity, news, or holiday state.

Context classification uses only observations available through the explicit
cutoff. Session windows use IANA time zones for London, New York, and Tokyo;
completed-bar identities derive from UTC boundaries rather than process sleep
timing. Context-aware historical expectancy is grouped by strategy, session,
overlap, liquidity, volatility, trend, event state, weekday, spread bucket,
instrument, and timeframe, with sample-size flags and no automatic promotion.

Still prohibited are forced trades, AI-selected strategies, research-strategy
execution, live trading, online learning, and automatic parameter changes.

### Authoritative Operational Context

Automated Demo commands require explicit local JSON economic and holiday calendars.
They are parsed before credentials or network access. Missing, malformed, stale, or
out-of-coverage sources fail closed; an empty implicit calendar is never treated as
`NO_EVENT`. The economic file contains `source_identifier`, UTC `as_of`, UTC
`coverage_start`, UTC `coverage_end`, and strict `EconomicEvent` entries. The holiday
file contains `source_identifier`, UTC `as_of`, date coverage, and entries with
`date`, `name`, `currencies`, `financial_centres`, and `HOLIDAY` or `THIN` impact.

```powershell
python -m trading_desk.cli execution automated-demo-smoke `
  --epic CS.D.EURUSD.CFD.IP `
  --economic-calendar C:\secure-local-data\economic-calendar.json `
  --holiday-calendar C:\secure-local-data\holiday-calendar.json `
  --context-timeframe DAY `
  --context-max-age-seconds 345600 `
  --max-orders 1 `
  --enable-execution `
  --enable-automatic-demo-execution `
  --initialize-state
```

The runner discards the unfinished current bar before strategy analysis. The context
then combines the current read-only IG quote, completed history, causal volatility,
existing Kalman/HMM output, DST-aware sessions, and authoritative calendar snapshots.
Every source contributes an identifier, UTC timestamp, and fingerprint. The provider
has no mutation adapter, Risk approval, AI direction authority, or forced-trade path.
Real operational validation remains pending until a natural order is submitted,
confirmed, and reconciled in IG Demo.

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
Paper Portfolio accounting remains local simulation only. Controlled IG Demo
execution is a separate, explicitly enabled, operator-confirmed boundary.

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
`docs/original-claude-skill.md` for upstream attribution and reference. The MIT
license remains in `LICENSE`.

## Validated in Milestone 10

The disabled-by-default lifecycle engine monitors confirmed long IG Demo positions,
uses bid-side liquidation prices, applies deterministic exit precedence, performs an
exact fresh-state preflight, and permits one full offsetting `SELL` close request.
Stop, target, strategy invalidation, maximum holding, account-risk, and emergency
exits are supported. Confirmation and read-only position reconciliation are required
before closure is recorded. Ambiguous or mismatched outcomes are never retried and
persist an automatic lifecycle halt.

Lifecycle evidence is written to the append-only SQLite journal and projected through
the GET-only Operations Center Lifecycle view. Deterministic post-trade reviews and
separate Paper-versus-Demo comparisons are analytical records only. Automated tests
use mocked IG transport; a real Demo close remains separately authorized operational
validation.

The close confirmation `confirmed_at` value is the local UTC time when the adapter
observed the IG response. It is not represented as an exchange timestamp or an
authoritative broker execution timestamp.

```bash
python -m trading_desk.cli lifecycle config-check
python -m trading_desk.cli lifecycle inspect --snapshot position.json
python -m trading_desk.cli lifecycle evaluate --snapshot position.json --risk risk.json
```

Mutation commands additionally require both lifecycle enable switches, fresh Demo
credentials, a current broker position match, persistent state, and a durable journal.
Live trading, production hosts, shorts, partial closes, amendments, working orders,
account switching, ambiguous-close retry, AI-triggered exits, and dashboard-triggered
exits remain prohibited.

## Milestone 11 Opportunity Engine

The disabled-by-default Opportunity Engine scans a strict six-market FOREX universe
(`EUR/USD`, `GBP/USD`, `USD/JPY`, `AUD/USD`, `USD/CAD`, and `EUR/JPY`) on completed
5-minute, 15-minute, and 1-hour bars. It creates immutable long-only candidates,
includes spread, slippage, uncertainty, liquidity, and event costs, calculates net
expected value, suppresses duplicates/correlation, and ranks at most three candidates
for Risk per cycle. Commission and funding default to zero until an authoritative
source can express them in the same price units as the candidate evidence.

The operational provider reads IG Demo market details and historical prices, removes
the unfinished bar, builds authoritative market context, invokes the Strategy Router,
and emits fingerprinted evidence only for an executable strategy. The scheduler stores
the last evaluated completed bar, rotates fairly when capacity is bounded, performs
bounded catch-up, and runs lifecycle monitoring independently from entry cadence.
Authoritative broker positions are loaded before duplicate, correlation, concentration,
concurrency, and re-entry filters. Unknown exposure fails closed before Risk.

Only `trend-regime-v1` is both `BACKTEST_VALIDATED` and
`DEMO_EXPLORATION_ENABLED`. Trend pullback, volatility breakout, and range mean
reversion remain `RESEARCH_ONLY` and cannot reach Risk. Risk remains the sole
approval and quantity authority. Only controlled IG Demo execution can open a
position, and only the lifecycle subsystem can close one.

```bash
python -m trading_desk.cli opportunity validate-config
python -m trading_desk.cli opportunity scan-once --enable-opportunity-engine \
  --economic-calendar economic-calendar.json --holiday-calendar holidays.json
python -m trading_desk.cli opportunity rank-once --enable-opportunity-engine \
  --economic-calendar economic-calendar.json --holiday-calendar holidays.json
python -m trading_desk.cli opportunity diagnostics
python -m trading_desk.cli demo-exploration status
python -m trading_desk.cli demo-campaign start --enable-demo-campaign
python -m trading_desk.cli demo-campaign status
python -m trading_desk.cli demo-campaign report
```

`scan-once` and `rank-once` are read-only and never submit to Risk or execution.
`demo-exploration run-cycle` and `run` additionally require all three explicit flags:
`--enable-opportunity-engine`, `--enable-demo-exploration`, and `--enable-execution`.
The continuous runner uses an exclusive process lock and persists scheduler, ledger,
campaign, lifecycle, and halt state under the configured local paths.

Demo Exploration and the 30-day campaign are disabled by default and technically
DEMO-only. The 100/250 closed-trade objectives and the 20,000-to-40,000 stretch
objective are diagnostics/reporting only. They cannot force a trade, lower a
threshold, increase size, bypass Risk, or enable Live. The Operations Center adds
GET-only Opportunity, Activity, Strategy, Instrument, Regime, Inactivity, and Demo
Campaign views backed by journal and campaign evidence. Campaign start records the
authoritative preferred Demo account balance and equity; the 20,000 value is only a
reporting reference. Submitted-order counts use a UTC trading-date boundary and
survive restart. Automated tests use deterministic or mocked broker inputs; no real IG
Demo scan, order, or close was performed for this correction.
