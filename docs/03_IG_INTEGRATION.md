---
current_validated_milestone: 11
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
- 02_ROADMAP.md
document: 03_IG_INTEGRATION
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: IG.com Integration Specification
version: 1.0.0
---

# Purpose

## Milestone 9 Operations Visibility

The dashboard may display sanitized IG Demo connectivity, confirmation, and
reconciliation evidence already present in typed records. It does not receive
IG credentials, OAuth tokens, raw headers, login responses, or an IG adapter.
The canonical Demo gateway remains the only broker host; no production host or
new mutation endpoint was added by Milestone 9.

This document defines every architectural rule governing integration
with IG.com.

It is the authoritative specification for authentication, session
management, market data retrieval, safety boundaries, and future
execution support.

No implementation interacting with IG.com may violate this
specification.

# Current Validated State

Validated through Milestone 7:

-   `POST /session` OAuth authentication, API version 3
-   Exact Demo gateway: `https://demo-api.ig.com/gateway/deal`
-   Read-only operation
-   Accounts retrieval
-   Positions retrieval
-   Market search
-   Market details, API version 3
-   Historical prices, API version 3
-   OAuth token lifecycle
-   Session cleanup
-   Secret redaction
-   Read-only CLI
-   Separate controlled Demo execution adapter
-   `POST /positions/otc`, version 2, for one long market-position opening
-   `GET /confirms/{dealReference}`, version 1, for bounded confirmation
-   One-attempt submission, idempotency, and read-only position reconciliation
-   Disabled-by-default bounded automated Demo observation mode

Not yet implemented:

-   Working orders
-   Position modification
-   Position closure
-   Live account support
-   Unbounded or production automatic execution
-   Account switching

# Design Goals

-   Keep broker logic isolated.
-   Normalize IG responses into domain models.
-   Never expose credentials or tokens.
-   Fail closed on malformed responses.
-   Preserve deterministic behavior.
-   Allow future demo and live execution without redesigning the
    strategy layer.

# Architectural Rules

1.  Only the Broker Layer communicates with IG.com.
2.  Strategy, AI, Risk, and Backtesting never call the IG API directly.
3.  Domain models are passed upward; raw HTTP responses are not.
4.  Secrets must never appear in logs, exceptions, reports, or tests.
5.  Demo and live environments remain explicitly separated.

# Authentication

Current implementation:

-   OAuth v3
-   Bearer token authorization
-   IG account ID header
-   API key
-   Exact canonical Demo gateway validation
-   Private in-memory access and refresh tokens

Requirements:

-   Clear session state on authentication failure.
-   Never persist tokens outside the approved session lifecycle.
-   Do not auto-refresh tokens unless an approved milestone adds that
    capability.

# Read-Only Operations

Validated allowlist:

-   `POST /session`, version 3 -- OAuth login
-   `DELETE /session`, version 1 -- logout
-   `GET /accounts`, version 1
-   `GET /positions`, version 2
-   `GET /markets`, version 1 -- market search
-   `GET /markets/{epic}`, version 3 -- market details
-   `GET /prices/{epic}`, version 3 -- one historical-price page

The read-only allowlist remains unchanged. A separate execution allowlist permits
only `POST /positions/otc` version 2 and `GET /confirms/{dealReference}` version 1.
Deletion, closure, amendment, working-order, account-switching, unsupported
version, absolute URL, redirect, traversal, and production-host operations fail
closed before an unsupported transport call.

All other methods, versions, paths, absolute URLs, alternate hosts,
production hosts, and path-traversal attempts fail before HTTP transport.

# Data Normalization

The Broker Layer converts IG responses into typed internal models.

Normalization includes:

-   market metadata
-   pricing
-   timestamps
-   dealing rules
-   account information

Malformed responses fail closed.

# Error Handling

Errors must be typed and actionable.

Never expose:

-   OAuth tokens
-   API keys
-   Passwords
-   Authorization headers
-   Raw response bodies containing secrets

# Security Rules

-   `.env` is never committed.
-   Credentials are never logged.
-   Demo is the default environment.
-   Live support must be explicitly enabled in a future milestone.
-   Strategy modules may not import broker authentication classes.

# Future Broker Scope

Controlled Demo opening and confirmation are validated only within the narrow
Milestone 7 execution boundary documented below. Position closure, amendment,
working orders, account switching, shorts, and live trading remain future and
require separate design and review.

# Documentation Governance

After every milestone affecting broker behavior:

-   Review this document.
-   Update validated capabilities.
-   Record architectural changes.
-   Update security assumptions.
-   Update endpoint inventory.

A milestone affecting IG integration is not complete until this document
reflects the validated implementation.

## Automated Demo Boundary

The automated runner uses the same exact Demo host and mutation allowlist as
manual controlled execution: `POST /positions/otc` version 2 and
`GET /confirms/{dealReference}` version 1. It may also use the existing
read-only accounts, positions, market-details, and historical-price operations.
Market-details v3 normalizes contract size, lot size, pip value, scaling factor,
currency, minimum size, and stop rules. Missing economics or dealing rules halt
before submission. Redirects, absolute mutation URLs, production hosts, closure,
amendment, working orders, and account switching remain rejected.

## Milestone 8 Journal Separation

The durable journal stores only sanitized typed evidence supplied by upstream
systems. It does not import the IG client or execution adapter, call any IG
endpoint, open `.env`, or persist API keys, passwords, OAuth values,
authorization headers, raw login bodies, or provider responses. Broker facts
are preserved as separate immutable source records; corrections require linked
amendments and evidence. No broker capability changed in Milestone 8.
# Milestone 7.5 Integration Boundary

Market context consumes normalized completed bars and public market state from the
existing IG Demo boundary. It does not add broker endpoints, credentials, hosts, or
HTTP authority. The router cannot call the Demo mutation adapter; any later selected
candidate must still pass the unchanged Risk and controlled Demo execution systems.
Research-only routes never reach either system. Live trading remains prohibited.

The operational provider receives only normalized historical data and an observable
market quote produced by the existing read-only client. It adds no endpoint and cannot
import `IGDemoExecutionAdapter`. Quote timestamps, bid/ask validity, market status, and
the completed-bar cutoff are fingerprinted. Calendar files are loaded locally before
IG authentication, and their contents never enter request headers or broker calls.

## Milestone 10 Demo Close Contract

The centralized mutation policy additionally permits only `DELETE /positions/otc`
version 1 for a full offsetting long-position close and existing
`GET /confirms/{dealReference}` version 1 confirmation. The request contains exact
`dealId`, `SELL`, full `size`, `MARKET`, and `FILL_OR_KILL`. Current positions are
re-read before submission and after confirmation. No production host, redirects,
amendments, working orders, account switching, shorts, or mutation retry is allowed.

## Milestone 11 Broker Boundary

The Opportunity Engine adds no HTTP or broker endpoint. Its six configured epics are
allowlist data, never user-selected mutation targets. Selected candidates still pass
through Risk, the existing canonical Demo gateway preflight, one-attempt controlled
execution, confirmation, reconciliation, and lifecycle. No real Milestone 11 Demo
campaign order was submitted.
