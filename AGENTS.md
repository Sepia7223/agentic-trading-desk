# Agentic Trading Desk Development Guide

This repository is being adapted into a safety-first automated trading application.
Codex is the development tool for changing this codebase. The OpenAI API is a future
runtime analysis provider and must not receive broker credentials.

## Non-Negotiable Safety Constraints

- Default broker environment is always `DEMO`.
- Default operating mode is always `READ_ONLY`.
- Live trading is technically disabled.
- Automatic execution is technically disabled.
- Unknown broker, position, market, or risk state must result in no trade.
- The language model must never control position size or bypass hard-coded risk limits.
- Do not connect to IG during Milestone 1.
- Do not add real credentials or secrets.
- Do not implement order execution during Milestone 1.
- Do not allow any AI provider to access IG credentials.

## Development Rules

- Preserve the existing deterministic indicator, score, and macro-pillar calculations
  unless a defect is explicitly fixed and covered by tests.
- Keep the MIT license and attribution intact.
- Add tests before or alongside behavioral changes.
- Prefer typed boundaries, small modules, and fail-closed behavior.
- Broker and model integrations must depend on abstract ports until concrete clients
  are explicitly introduced in a later milestone.
