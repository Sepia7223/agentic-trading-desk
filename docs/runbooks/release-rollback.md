# Runbook — Release Rollback

Scope: roll a deployed IG Demo desk back to a previously known-good release after
a regression, failed CI in production, or an operational incident. DEMO-only; a
rollback never enables live trading.

## When to roll back

- A release fails startup preflight on the target host.
- Post-deploy reconciliation reports a mismatch that the new release cannot
  resolve safely.
- A regression is detected in protective lifecycle behavior or risk authority.

## Preconditions

- The previous release tag/commit is known and its artifacts are available.
- A fingerprint-verified backup of durable state taken **before** the new release
  exists (state and journal are forward-compatible, but roll back to the matching
  pre-release backup when a schema change is involved).

## Procedure

1. **Halt new entries.** Put the desk into a protective-only posture. Do not
   attempt any mutation while rolling back.
2. **Release ownership.** Release the process lock so the rolled-back process can
   acquire it cleanly.
3. **Check out the known-good release.** Deploy the previous commit/tag. Reinstall
   dependencies deterministically.
4. **Restore matching state if needed.** If the failed release migrated state,
   restore the pre-release fingerprint-verified backup (`BackupService.restore`).
   Restore refuses on any digest mismatch and quarantines corrupt live files
   rather than overwriting them.
5. **Preflight.** Run `run_preflight` on the rolled-back release. All integrity
   checks must verify.
6. **Acquire ownership and reconcile.** Acquire the lock, then reconcile against
   authoritative broker state. New entries stay blocked until reconciliation
   returns `SUCCEEDED`.
7. **Record rollback evidence.** Emit an incident capturing the from/to release
   identifiers and the reason, with sanitized detail only.

## Verification after rollback

- CI on the rolled-back commit is green (backend + frontend + Playwright smoke +
  secret/authority/cleanliness scans).
- The recovery gate reaches `ENTRIES_ENABLED` only after a healthy preflight and a
  succeeded reconciliation.
- RTO/RPO for the rollback are recorded via `assess_objectives`; an unmeasured
  recovery is reported not-met.
