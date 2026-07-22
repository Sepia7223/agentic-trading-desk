# Milestone 18 — Release Candidate Hardening

## Objective

Convert the accepted Demo trading desk into a stable release candidate by eliminating known technical debt, enforcing consistent cross-domain contracts, completing security and quality gates, and proving reproducible installation and operation.

## Scope

### Canonical identity and fingerprints

Replace divergent strategy, Risk, and backtest canonicalizers with one versioned canonical fingerprint library. Migration must preserve historical identities and explicitly distinguish legacy fingerprints from canonical-v2 fingerprints.

### Backtest and runtime consistency

- Remove or wire all dead validated machinery.
- Prove strategy rules, target handling, ambiguity rules, costs, macro inclusion, and staleness behavior are consistent between research, backtest, Paper, and Demo paths where intended.
- Document every intentional environment difference.

### Configuration and errors

- Establish one authoritative configuration composition.
- Remove contradictory defaults.
- Normalize domain-specific configuration errors at adapter boundaries.
- Validate startup configuration before any broker session is created.

### Module boundaries

- Replace private underscore-helper imports across domains with public contracts.
- Enforce dependency direction through automated architecture tests.
- Remove unused compatibility paths only after migration evidence.

### Repository hygiene

- remove stray `.test-tmp*`, caches, generated files, and workstation artifacts;
- strengthen `.gitignore` and cleanliness checks;
- ensure artifacts are intentional, immutable, and documented;
- verify no secrets or sensitive broker data exist in history introduced by project work.

### Static typing and CI

- strengthen mypy coverage and typed boundaries;
- run complete Python and frontend suites in CI;
- pin toolchain versions and lock dependencies;
- produce software bill of materials and dependency-vulnerability report;
- document accepted residual warnings and advisories.

### Performance and capacity

Measure and set budgets for:

- completed-bar cycle latency;
- historical validation duration;
- memory and disk growth;
- journal replay and Operations API latency;
- startup reconciliation duration;
- frontend bundle and page responsiveness.

Optimization cannot change deterministic outputs or safety ordering.

### Documentation and installation

Provide:

- clean-host installation procedure;
- Mini-PC service setup;
- environment variable reference;
- backup, restore, upgrade, and rollback runbooks;
- operator checklist;
- troubleshooting matrix;
- architecture and data-flow diagrams aligned with code.

## Release gates

- zero unresolved critical or high-severity correctness findings;
- zero known authority bypasses;
- zero committed secrets;
- complete backend and frontend CI;
- reproducible clean-host build;
- successful backup/restore and rollback rehearsal;
- deterministic replay of a certified campaign;
- dependency risk disposition;
- accepted performance budgets;
- final documentation review.

## Definition of Done

The release candidate is reproducible, fully tested, consistently configured, fingerprint-compatible, operationally documented, free of known blocking technical debt, and independently accepted for long-running IG Demo operation.
