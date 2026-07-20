# Environment Variable Reference

Every environment variable read by `AppSettings.from_environment()`. Placeholders
live in `.env.example`; real values go in a git-ignored `.env`. Configuration is
validated at startup **before any broker session is created** — an inconsistent
composition fails closed.

## Operating mode and safety

| Variable | Default | Values | Notes |
|---|---|---|---|
| `BROKER_ENVIRONMENT` | `DEMO` | `DEMO` | DEMO only; there is no LIVE enum |
| `OPERATING_MODE` | `READ_ONLY` | `READ_ONLY`, `CONTROLLED_EXECUTION` | controlled execution is a governed, opt-in mode |
| `LIVE_TRADING_ALLOWED` | `false` | `false` | pinned false; live trading is not a capability |
| `AUTOMATIC_EXECUTION_ENABLED` | `false` | `false`, `true` | `true` requires `OPERATING_MODE=CONTROLLED_EXECUTION`, else startup fails |

## IG Demo gateway

| Variable | Default | Notes |
|---|---|---|
| `IG_BASE_URL` | IG Demo gateway | Demo gateway URL |
| `IG_IDENTIFIER` | — | Demo account identifier (secret; never committed) |
| `IG_PASSWORD` | — | Demo account password (secret; never committed) |
| `IG_API_KEY` | — | Demo API key (secret; never committed) |
| `IG_REQUEST_TIMEOUT_SECONDS` | `10` | per-request timeout |
| `IG_MAX_HISTORICAL_PRICE_POINTS` | `1000` | history page cap |
| `IG_OAUTH_EXPIRY_SAFETY_MARGIN_SECONDS` | `5` | refresh-ahead margin |

## AI (optional, analysis-only)

| Variable | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | — | optional; AI has no trade authority |
| `OPENAI_MODEL` | — | runtime model id |

## Storage

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///trading_desk.sqlite3` | local journal/state store |

## Handling rules

- Secrets (`IG_*`, `OPENAI_API_KEY`) are read from the environment only. They are
  never fingerprinted, journaled, exported, or committed — the journal
  canonicalizer rejects secret-bearing fields, and CI runs a secret scan.
- Changing `OPERATING_MODE` or the execution flags is an operational decision
  gated by the milestone that authorizes it; defaults are the safe posture.
