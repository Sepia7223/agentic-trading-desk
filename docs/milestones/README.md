# Milestone Specifications

Milestone documents are implementation contracts. They define scope, authority boundaries, prohibited behavior, required evidence, acceptance criteria, and Definition of Done.

## Current roadmap

| Milestone | Title | Status |
|---|---|---|
| 11.5 | IG Demo Operational Certification | Partially certified; natural trade lifecycle evidence remains open |
| 12 | Validated Multi-Regime Strategy Portfolio | Implementation requires corrective validation and accepted lineage |
| 13 | Portfolio Construction and Capital Allocation Engine | Planned |
| 14 | Portfolio Analytics and Performance Attribution | Planned |
| 15 | Governed Strategy Research and Optimization | Planned |
| 16 | Operational Resilience and Disaster Recovery | Planned |
| 17 | Full IG Demo Operational Certification | Planned |
| 18 | Release Candidate Hardening | Planned |
| 19 | Live Trading Readiness Assessment | Optional governance assessment; does not enable Live |

## Required PR metadata

Every milestone PR must identify:

- milestone document path;
- accepted base branch and SHA;
- final head SHA;
- changed authority boundaries;
- safety prohibitions confirmed;
- backend and frontend validation commands;
- operational tests performed and explicitly not performed;
- known limitations;
- generated evidence fingerprints.

## Completion terminology

- `IMPLEMENTED`: software exists, but required evidence may be incomplete.
- `BACKTEST_VALIDATED`: historical evidence gates passed.
- `DEMO_EXPLORATION_ENABLED`: explicit human approval permits bounded Demo entry eligibility.
- `CERTIFIED`: required operational evidence was observed against IG Demo.
- `ACCEPTED`: independent review found the milestone complete.
- `REJECTED`: one or more blocking acceptance criteria remain unsatisfied.
