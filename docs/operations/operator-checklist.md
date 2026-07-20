# Operator Checklist

Routine checks for running the IG Demo trading desk. DEMO-only; none of these
steps enables live trading.

## Before start (daily / after any change)

- [ ] `.env` present with Demo credentials; `OPERATING_MODE=READ_ONLY` (or the
      governed mode the current milestone authorizes).
- [ ] Host clock synced to UTC (preflight fails closed on drift/timezone).
- [ ] Free disk and memory above the budgets in
      `docs/release/performance-budgets.md`.
- [ ] Latest verified backup exists and is recent enough to meet the RPO.
- [ ] No other desk instance is running (the process lock enforces this, but
      confirm before a manual start).

## At start

- [ ] Startup preflight reports HEALTHY (or a known, accepted DEGRADED with
      entries blocked). Integrity checks verify the journal and state.
- [ ] Exclusive process lock acquired by this host.
- [ ] Reconciliation against the broker reaches SUCCEEDED before the recovery
      gate enables new entries; protective monitoring is active first.

## During operation

- [ ] Operations Center health endpoint reports READ ONLY / DISABLED live
      trading and the expected system status.
- [ ] No unresolved CRITICAL incidents; review any STALE_LOCK / CORRUPT_STATE /
      RECONCILIATION_MISMATCH incidents.
- [ ] Completed-bar cycle latency and API latency within budget.
- [ ] Journal and state disk growth on trend (no runaway).

## Backups

- [ ] Scheduled backup ran within the RPO window and verified
      (`resilience.BackupService.verify` reports no mismatches).
- [ ] A restore rehearsal has been performed recently
      (`docs/runbooks/disaster-recovery.md`).

## Before shutdown / migration

- [ ] New-entry work quiesced; no in-flight ambiguous mutation pending.
- [ ] Process lock released (or left to stale-takeover if the host is down).
- [ ] Fresh verified backup taken if migrating
      (`docs/runbooks/laptop-to-minipc-migration.md`).

## Change management

- [ ] CI green on the deployed commit (backend + frontend + Playwright + secret /
      authority / cleanliness / architecture scans).
- [ ] Dependency-risk disposition reviewed for any new advisory
      (`docs/release/dependency-risk-disposition.md`).
