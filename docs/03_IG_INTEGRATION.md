---
title: IG.com Integration Specification
document: 03_IG_INTEGRATION
version: 1.0.0
status: Living Document
owner: Agentic Trading Desk Project
current_validated_milestone: "3 (Milestone 3.5 planned)"
review_required_after_every_milestone: true
---

# Purpose

This document governs authentication, session management, market-data retrieval, safety boundaries, and future execution support for IG.com.

# Current Validated State

Validated:

- exact Demo gateway: `https://demo-api.ig.com/gateway/deal`;
- OAuth session v3 only;
- Bearer authorization, account header, and API key handling;
- accounts retrieval;
- positions retrieval;
- market search;
- market details using API version 3;
- one-page historical prices;
- strict typed normalization;
- safe token lifecycle and session cleanup;
- secret redaction and safe diagnostics;
- read-only CLI operations.

Not implemented:

- order placement or preview;
- working orders;
- confirmation polling;
- position changes or closure;
- active-account switching;
- automatic token refresh;
- live-host support;
- automatic execution.

# Architectural Rules

1. Only the broker layer communicates with IG.
2. Strategy, risk, AI, backtesting, journaling, and dashboards cannot call IG directly.
3. Every request passes through a centralized allowlist before transport.
4. Raw broker dictionaries do not leak beyond the adapter boundary.
5. Demo and future live environments remain technically and operationally separate.
6. Unsupported hosts, paths, methods, versions, absolute URLs, and malformed responses fail closed.

# Approved Read-Only Surface

- `POST /session`, version 3 — OAuth login.
- `DELETE /session`, version 1 — logout.
- `GET /accounts`, version 1.
- `GET /positions`, version 2.
- `GET /markets`, version 1.
- `GET /markets/{epic}`, version 3.
- `GET /prices/{epic}`, version 3.

All mutation and execution endpoints remain prohibited until an explicitly reviewed milestone authorizes them.

# Credential and Session Safety

Credentials are loaded from local ignored configuration only. Access and refresh tokens remain private in-memory secret values, never appear in representations or output, and are cleared after logout attempts, failed authentication, or expiry detection. Token expiry uses a monotonic clock with a safety margin.

Do not inspect or commit `.env`. Never paste identifiers, passwords, API keys, OAuth values, login payloads, or authorization headers into source, tests, logs, screenshots, issues, prompts, journals, or reports.

# Data Normalization

IG responses are converted into strict internal models. Account identifiers are redacted in human output. Historical bars missing required close bid or ask values remain observable but are excluded from strategy-ready close series.

Market-details v3 `snapshot.updateTime` is represented as a timezone-naive time-of-day. The adapter must not invent a date or UTC timezone that IG did not provide.

# Future Execution

Demo order execution requires separate ports, policies, confirmation handling, idempotency, reconciliation, risk approval, journal integration, kill switches, and an updated ADR. Live support requires an additional milestone and must not be enabled by merely changing a URL or environment variable.

# Governance

Any change to broker capabilities, endpoints, authentication, session state, or environment policy requires tests, security review, ADR review, and an update to this document before milestone completion.
