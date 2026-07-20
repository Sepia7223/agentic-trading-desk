# Runbook — Laptop-to-Mini-PC Migration

Scope: move the running IG Demo desk from the laptop to the Mini PC (or any clean
host) without losing journal lineage, without double-owning the process, and
without enabling live trading. DEMO-only throughout.

## Preconditions

- The Mini PC has the runtime installed and passes the startup preflight on its
  own hardware (clock synced to UTC, sufficient disk/memory, broker reachable).
- Secrets are provisioned on the new host out-of-band (never committed, never
  copied through the repository). The desk reads them from the host `.env`, which
  is git-ignored.

## Procedure

1. **Quiesce the source host.** Stop new-entry work on the laptop. Allow
   protective lifecycle monitoring to finish its current cycle. Confirm no
   in-flight ambiguous mutation is pending; if one exists, reconcile and clear it
   before migrating.
2. **Release ownership.** Release the process lock on the laptop
   (`ProcessLockStore.release`). If the laptop is already down, the Mini PC will
   observe an expired heartbeat and take the lock over with a `STALE_LOCK_CLEARED`
   incident — ownership is never inferred, only taken on a stale or dead lock.
3. **Back up durable state.** On the source host, create a fingerprinted backup of
   the journal and all state files (`BackupService.create`). The manifest records
   a SHA-256 per file.
4. **Transfer.** Copy the backup directory and its manifest to the Mini PC over a
   secure channel. Do not transfer `.env`; provision secrets separately.
5. **Restore and verify.** On the Mini PC, restore from the manifest
   (`BackupService.restore`). Restore refuses if any backup digest fails to verify
   and re-verifies every file after writing. Journal hash-chain lineage is
   preserved because bytes are restored exactly.
6. **Preflight on the new host.** Run `run_preflight`. Integrity checks must
   verify the restored journal and state fingerprints.
7. **Acquire ownership on the Mini PC.** `ProcessLockStore.acquire`. Confirm the
   laptop is not still running the desk.
8. **Reconcile before entries.** New entries remain blocked until authoritative
   reconciliation against the broker succeeds (`evaluate_recovery`). Protective
   monitoring resumes first.
9. **Record migration evidence.** Emit a `HOST_MIGRATION` incident with sanitized
   detail (source host, destination host, backup manifest id). No secrets.

## Rollback

If the Mini PC fails preflight or reconciliation, return ownership to the laptop:
restore its state from the same verified backup, re-acquire the lock there, and
reconcile before resuming. The backup is the single source of truth for state;
neither host infers state from the other's memory.
