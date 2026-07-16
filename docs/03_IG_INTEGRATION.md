---
current_validated_milestone: 5
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

This document defines every architectural rule governing integration
with IG.com.

It is the authoritative specification for authentication, session
management, market data retrieval, safety boundaries, and future
execution support.

No implementation interacting with IG.com may violate this
specification.

# Current Validated State

Validated through Milestones 1--3:

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

Not yet implemented:

-   Order execution
-   Working orders
-   Position modification
-   Live account support
-   Automated execution

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

Execution endpoints are prohibited until the approved execution
milestone.

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

# Future Execution

Future milestones may introduce:

-   Demo order placement
-   Order confirmation
-   Position management
-   Controlled live trading

These features require updates to this document before implementation.

# Documentation Governance

After every milestone affecting broker behavior:

-   Review this document.
-   Update validated capabilities.
-   Record architectural changes.
-   Update security assumptions.
-   Update endpoint inventory.

A milestone affecting IG integration is not complete until this document
reflects the validated implementation.
