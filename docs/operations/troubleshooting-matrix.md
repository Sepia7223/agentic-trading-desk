# Troubleshooting Matrix

Symptom → likely cause → action. The desk fails closed by design: when in doubt
it blocks new entries and keeps protective monitoring. Never force a mutation to
"unstick" the desk.

| Symptom | Likely cause | Action |
|---|---|---|
| Startup exits immediately; RECOVERY_REQUIRED | journal or state fingerprint mismatch (corrupt state) | Do not overwrite. Restore from last verified backup (`disaster-recovery.md`); the corrupt file is quarantined, not deleted. |
| Startup HALTED; connectivity FAILED | broker gateway unreachable / DNS / network down | Restore connectivity; preflight re-runs. Protective monitoring stays blocked while the endpoint is unreachable. |
| Startup HALTED; clock/timezone FAILED | host clock drift or non-UTC timezone | Sync the clock to UTC; re-run. |
| Desk runs but never opens new entries | reconciliation not SUCCEEDED (NOT_STARTED/IN_PROGRESS/MISMATCH/UNAVAILABLE) | Expected until authoritative reconciliation succeeds. Investigate a persistent MISMATCH before clearing. |
| "cannot acquire lock" / REFUSED_HELD | another live instance owns the desk | Confirm and stop the other instance; do not delete the lock file manually. |
| Lock taken over with STALE_LOCK incident | previous owner's heartbeat expired or it was reported dead | Confirm the prior owner is truly gone; the takeover is safe only then. |
| Ambiguous broker response; desk halted | a mutation's outcome is unknown | Never retried automatically. Reconcile against authoritative broker state, then clear the human halt. |
| Repeated transient read failures | flaky network / gateway throttling | Read-only ops retry under a bounded capped backoff; if the budget exhausts, the read is reported failed, not forced. |
| Disk filling up | journal/state growth or un-rotated backups | Check against the disk budget; rotate backups; investigate any runaway writer. |
| Memory growing over days | unexpected accumulation | Compare against the 72 h soak budget; restart is safe (preflight + reconciliation gate the resume). |
| Operations API slow or 5xx | load or a degraded projection source | Read-only; safe to restart the API process. Backend trading continues independently. |
| Frontend unavailable | frontend build/serve issue | Backend continues safely; the dashboard is read-only and non-authoritative. |
| CI secret scan fails | a credential-like literal or `.env` reached the tree | Remove it from the commit and history; never commit real credentials. |
| CI architecture scan fails | a cross-domain private import or an inverted utility dependency | Route through a public contract; keep the fingerprint/canonical layer at the bottom. |

## Escalation

Any CRITICAL incident, a persistent reconciliation MISMATCH, or a corrupt-state
quarantine requires a human-cleared halt release before the desk resumes new
entries. Capture the sanitized incident evidence (no credentials, no raw broker
payloads) for the record.
