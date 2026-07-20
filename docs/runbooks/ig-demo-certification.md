# Runbook — Full IG Demo Operational Certification

How an operator drives and records the full IG Demo operational certification.
DEMO-only. Certification observes a **naturally occurring** bounded Demo trade
end-to-end; it never forces a trade, weakens a gate, or fabricates evidence.

## What the tooling does (and does not) do

- `GET /api/v1/certification-status` (or `OperationsService.certification_status`)
  computes the deterministic verdict from authoritative journal records:
  - **FAILED** if any defect is recorded (unresolved halt, close-blocked,
    execution failure — safety/consistency/reconciliation/authority/duplicate).
  - **CERTIFIED** only when all seventeen required items are observed.
  - **PARTIALLY_CERTIFIED** otherwise — including the normal case where markets
    were closed or no candidate appeared. That is an explicit non-defect.
- The two restart checkpoints (`RESTART_WITH_ACTIVE_POSITION`,
  `FINAL_RESTART_NO_DUPLICATE_MUTATION`) are **operator-recorded**; the collector
  never infers them from records.
- The tooling cannot and will not manufacture the natural trade. Reaching
  CERTIFIED requires the real operational run below.

## Prerequisites (do not proceed without all of these)

- Milestones 12–16 accepted by review.
- At least one strategy explicitly `DEMO_EXPLORATION_ENABLED`.
- Portfolio, Risk, execution, lifecycle, reconciliation, persistence, and
  Operations controls enabled only through their documented authorization
  sequence.
- No unresolved state corruption, ambiguity halt, or campaign safety halt.
- A live IG Demo market window (an instrument in the governed universe is open).

## Procedure

1. **Preflight and start.** Bring the desk up (see `installation.md`). Confirm
   startup preflight HEALTHY, exclusive lock acquired, and read-only
   reconciliation succeeded. Software/read-only certification items begin
   populating from real records.
2. **Let opportunity flow naturally.** Do not lower any threshold, spread,
   expected-value, regime, Risk, portfolio, or timing gate to force a candidate.
   If none appears in the window, stop and continue certification another day —
   this is legitimate and yields PARTIALLY_CERTIFIED, not FAILED.
3. **Governed entry.** When a candidate is naturally accepted and submitted to
   Risk, Risk approves and sizes a **bounded** Demo quantity. One controlled IG
   Demo order is submitted. An ambiguous outcome is never retried — halt,
   reconcile, and record the incident instead.
4. **Confirmation and durable state.** Record confirmation, broker
   reconciliation, and durable journal/campaign/portfolio/execution state.
5. **Restart with the position active.** Restart the process while the confirmed
   position remains open. Record the `RESTART_WITH_ACTIVE_POSITION` checkpoint
   (operator evidence). Confirm lifecycle monitoring resumes and no duplicate
   mutation occurs.
6. **Natural or governed close.** Let the position close naturally or by
   documented lifecycle policy. Record close confirmation and reconciliation.
7. **Attribution.** Confirm realized P&L and attribution reconcile to the
   authoritative records (`/api/v1/portfolio-analytics`).
8. **Final restart.** Restart once more; confirm no duplicate mutation. Record the
   `FINAL_RESTART_NO_DUPLICATE_MUTATION` checkpoint.
9. **Verdict and evidence.** Read `/api/v1/certification-status`. When all
   seventeen items are observed with no defect, the verdict is CERTIFIED. Seal the
   sanitized evidence package (environment/config fingerprints, masked account
   reference, decisions, sanitized request hash and confirmation reference,
   reconciliation outcomes, restart checkpoints, attribution, incidents,
   Operations projections, and the final verdict) via the certification renderer.

## Rules (non-negotiable)

- No forced trade or synthetic candidate.
- No gate weakened to obtain evidence.
- No mutation retried after an ambiguous outcome.
- Only bounded Demo quantity approved by Risk may be submitted.
- Live remains unavailable.
