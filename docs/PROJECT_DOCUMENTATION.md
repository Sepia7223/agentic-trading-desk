# Project Documentation Map

This repository is the authoritative source for architecture, milestone specifications, implementation evidence, operational certification, and independent reviews.

## Directory structure

- `docs/00_...` through `docs/13_...`: accepted architecture and engineering reference documents. These paths remain stable to avoid breaking existing references.
- `docs/milestones/`: implementation specifications and acceptance criteria for each project milestone.
- `docs/reviews/`: independent milestone reviews, findings, dispositions, and final verdicts.
- `docs/operations/`: operational runbooks, certification procedures, migration guidance, and incident records.
- `artifacts/`: immutable generated validation and certification evidence. Artifacts are evidence, not specifications.

## Authority order

When documents conflict, use this order:

1. Accepted architecture decisions and explicit safety prohibitions.
2. The active milestone specification in `docs/milestones/`.
3. Accepted independent review disposition in `docs/reviews/`.
4. Implementation documentation and generated artifacts.
5. PR descriptions and chat transcripts.

## Working method

1. A milestone specification is committed before implementation begins.
2. Implementation occurs on a dedicated branch based on the accepted predecessor SHA.
3. The PR references the exact milestone document and starting SHA.
4. Automated evidence is generated without weakening safety or validation gates.
5. Independent review findings are committed under `docs/reviews/`.
6. A milestone is complete only after an explicit `ACCEPTED`, `CERTIFIED`, or equivalent verdict.

## Safety baseline

- IG Demo only unless a future milestone explicitly authorizes a separate readiness assessment.
- No Live trading path may be enabled by implication, environment drift, UI mutation, AI output, or strategy state.
- Risk remains final quantity authority.
- Execution remains sole broker mutation authority.
- Strategy, portfolio, journal, AI, dashboards, and research tooling cannot submit, amend, retry, or close broker orders.
- No forced trades, synthetic operational certification, automatic strategy promotion, or hidden threshold reduction.
