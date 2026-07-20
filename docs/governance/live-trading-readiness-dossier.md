# Live-Trading Readiness Dossier

**Status:** advisory governance assessment. This document does **not** enable Live
trading and does not authorize any Live work. The system remains Demo-only
regardless of its conclusion.

**Current recommendation: `CONDITIONAL_GO`** — no fundamental engineering blocker,
but multiple human-gated prerequisites are unmet. Live work may be considered only
after every prerequisite and required control below is satisfied and independently
reviewed.

## Evidence inventory

| Domain | Evidence | Status |
|---|---|---|
| Engineering | Deterministic fingerprints (canonical library), authority-boundary + architecture scans, reconciliation-first recovery, backup/restore + rollback runbooks, performance budgets, SBOM + dependency scan | PASS with concerns |
| Strategy & portfolio | Governed validation (M12), overfitting controls (M15), allocation engine (M13), attribution reconciled to authoritative P&L (M14) | CONCERNS — Demo campaign history not yet long enough for cross-regime stability |
| Risk governance | Risk owns approval/sizing; DEMO-only; kill/halt precedence; bounded quantity | CONCERNS — capital-at-risk proposal, hard multi-scope limits, and an independent kill-switch design are not yet ratified |
| Legal & compliance | — | FAIL/PENDING — no jurisdiction, broker-terms, tax, data-licensing, or professional review obtained |
| Security | Secret isolation, secret/authority/cleanliness CI scans, incident sanitization | CONCERNS — dedicated-host posture, credential rotation/revocation, and network-exposure review not yet formalized |

## Unresolved findings by severity

- **HIGH:** none in engineering. Legal/compliance evidence is entirely outstanding
  (blocking for Live, tracked as a prerequisite rather than an engineering defect).
- **MEDIUM:** Demo campaign history length; ratified risk limits; security host
  posture and credential rotation procedures.

## Quantified residual risks

- Strategy performance may be period-dependent until a longer multi-regime Demo
  history is accumulated (impact: unquantified expected edge → treat as zero).
- Operational risk on a single host until dedicated-host and rotation controls are
  formalized (impact: availability + credential exposure).

## Required controls before any Live work

1. Reviewer `ACCEPTED` verdicts on Milestones 12–18.
2. A `CERTIFIED` full IG Demo operational certification (M17 live run).
3. Ratified risk governance: capital-at-risk proposal; hard daily/weekly/campaign/
   strategy/instrument/currency/portfolio limits; an independent kill-switch not
   subject to strategy, AI, or dashboard authority; staged rollout with minimum
   size; human supervision and escalation.
4. Legal and financial review: jurisdiction, broker terms/API usage, tax and
   record-retention obligations, data licensing, operator responsibility.
5. Security hardening: dedicated host, least-privilege secrets, encryption and
   backup protection, access control and audit logging, patching/vulnerability
   management, network-exposure review, credential rotation/revocation.
6. Separate Live infrastructure and credentials (never shared with Demo).
7. An independent safety review of the Live proposal.

## Proposed staged authorization process

1. Complete all required controls; re-run this assessment → target `GO`.
2. New architecture decision record and a new milestone specification for Live.
3. Explicit written legal and financial approval.
4. Minimum-size staged rollout under human supervision, with the kill-switch
   rehearsed before the first order.
5. Independent post-stage review before any size increase.

## Recommendation and approvers

- **Recommendation:** `CONDITIONAL_GO` (advisory only).
- **Named approvers / review dates:** _to be recorded by the human governance
  process; this tooling cannot and does not approve Live activity._

## Mandatory notice

This assessment does not add or enable a Live API host, create a Live execution
adapter, use Live credentials, or submit any Live order. Demo certification is not
financial suitability. Any future Live implementation requires a new architecture
decision, a new milestone specification, explicit legal and financial approval,
separate credentials and infrastructure, and an independent safety review.
