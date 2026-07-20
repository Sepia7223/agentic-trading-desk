# Runbook — Disaster Recovery

Scope: recover the IG Demo trading desk after a process crash, host restart,
corrupt local state, or partial broker response. This procedure is DEMO-only;
it never enables live trading and never infers an order outcome from local intent.

## Objectives

- **RPO (recovery point):** at most one backup interval of lost durable state.
  The backup cadence must be at least as frequent as the RPO
  (`resilience.objectives.assess_objectives` enforces this relationship).
- **RTO (recovery time):** bounded by the objective configured for the host;
  an unmeasured recovery is reported not-met, never assumed satisfied.

## Recovery order (fail-closed)

1. **Preflight.** Run the startup preflight (`resilience.run_preflight`). It
   evaluates clock drift, timezone, disk, memory, connectivity, and journal/state
   integrity. Any unknown reading fails closed.
   - Integrity failure (journal or state fingerprint mismatch) ⇒
     `RECOVERY_REQUIRED`. Stop and go to **Corrupt state** below.
   - Any critical failure (clock, timezone, disk, connectivity) ⇒ `HALTED`;
     new entries stay blocked.
2. **Acquire exclusive ownership.** `resilience.ProcessLockStore.acquire`. If a
   fresh, live lock is held elsewhere, do not start. A stale lock (expired
   heartbeat or known-dead owner) is taken over and an incident is recorded.
3. **Reconcile first.** Read authoritative broker positions and balances. New
   entries remain blocked until reconciliation returns `SUCCEEDED`
   (`resilience.evaluate_recovery`). Protective lifecycle monitoring runs as soon
   as connectivity is healthy, ahead of any new-entry work.
4. **Resume.** Only when preflight is healthy **and** reconciliation succeeded
   does the recovery gate reach `ENTRIES_ENABLED`. Any mismatch or unavailable
   authoritative state keeps the desk `PROTECTIVE_ONLY`.

## Corrupt state

- Corrupt journal or state is **quarantined, not overwritten**. Restore from the
  last fingerprint-verified backup (`resilience.BackupService.restore`), which
  refuses if the backup digests do not verify and copies any corrupt live file to
  a timestamped `.corrupt` quarantine file before writing.
- Record a `CORRUPT_STATE_QUARANTINED` incident. Restoration preserves
  fingerprints and journal hash-chain lineage byte-for-byte.

## Partial / ambiguous broker responses

- An ambiguous mutation is **never retried** (`resilience.plan_retry` returns
  `halt_required`). Halt, reconcile against authoritative broker state, and
  require a human-cleared halt release before any further mutation.
- Read-only operations retry under a bounded, capped backoff budget only.

## Restart with active confirmed positions

- Protective lifecycle monitoring resumes first. New entries stay blocked through
  the `RECONCILING` phase until authoritative reconciliation of the open
  positions succeeds.

## Evidence

Produce sanitized evidence (preflight report, incident records, restore outcome,
recovery decision) for the incident log. No credentials or raw broker payloads
are included; incident detail keys that look like secrets are rejected at the
model boundary.
