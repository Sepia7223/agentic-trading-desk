# Milestone 16 — Operational Resilience and Disaster Recovery

## Objective

Make the IG Demo trading desk recoverable, observable, and safe under process crashes, host restart, network failure, stale data, corrupted local state, partial broker responses, and workstation migration.

## Scope

Implement and certify:

- startup preflight and dependency health;
- durable state backups and restore validation;
- crash-consistent writes;
- reconciliation-first recovery;
- exclusive process ownership and stale-lock handling;
- bounded retry policies for read-only operations;
- no-retry handling for ambiguous broker mutations;
- clock, timezone, disk, memory, and connectivity diagnostics;
- degraded and halted operating states;
- structured incident records;
- release rollback procedure;
- laptop-to-Mini-PC migration runbook;
- recovery-time and recovery-point objectives.

## Failure model

Test at minimum:

- termination before and after durable write;
- termination before and after broker submission;
- confirmation timeout and ambiguous outcome;
- stale or unavailable positions and balances;
- scheduler backlog and missed bars;
- unavailable market details or history;
- corrupt or partially written journal/state files;
- insufficient disk space;
- host clock drift;
- lost network connectivity;
- frontend unavailable while backend continues safely;
- restart with active confirmed positions;
- migration to a clean host with restored secrets and state.

## Recovery rules

- New entries remain blocked until authoritative reconciliation succeeds.
- Protective lifecycle monitoring receives priority over new entry work.
- Ambiguous mutations are never automatically retried.
- Recovery cannot infer a successful order from local intent alone.
- Corrupt state is quarantined and reported; it is not silently overwritten.
- Backup restoration must preserve fingerprints and journal lineage.

## Configuration consistency

Resolve operator-facing drift:

- one authoritative operating-mode composition;
- explicit relationship between `.env`, CLI authorization flags, and in-memory policy;
- no constructor defaults that silently contradict configuration defaults;
- consistent typed configuration errors at adapter boundaries.

## CI and quality gates

Expand CI to run:

- Ruff format and lint;
- mypy with stronger checking, including `check_untyped_defs=true` or equivalent staged enforcement;
- full pytest suite;
- frontend formatting;
- ESLint;
- TypeScript checking;
- Vitest;
- production build;
- Playwright smoke tests;
- secret and authority scans;
- repository cleanliness checks for temporary artifacts.

## Operations evidence

Produce sanitized evidence for backup, restore, crash recovery, reconciliation, active-position restart, host migration, and rollback. No credentials or sensitive raw broker payloads may be committed.

## Definition of Done

The system fails closed, restores deterministically, reconciles before mutation, survives tested crash boundaries, can be migrated to the Mini PC through a documented procedure, runs complete backend and frontend CI, and independent review returns `ACCEPTED`.
