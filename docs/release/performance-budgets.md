# Performance and Capacity Budgets

Budgets for the IG Demo trading desk running long-lived on a Mini PC. These are
ceilings, not targets to optimize toward. **Optimization must never change
deterministic outputs or safety ordering** — a change that alters a fingerprint,
a decision, or the exit/authority precedence is a correctness change, not a
performance change, and is out of scope for tuning.

## Budgets

| Dimension | Budget | Measurement point | Notes |
|---|---|---|---|
| Completed-bar cycle latency | ≤ 2.0 s per instrument per completed bar | scheduler cycle start → journaled decision | intraday cadence has ample headroom vs. bar interval |
| Historical validation duration | ≤ 8 h per strategy-timeframe unit | validation CLI run | the governed unit size chosen in M12/M15 |
| Memory growth | ≤ 1.5 GB steady-state RSS; no unbounded growth over 72 h | host monitor | bounded trailing windows; no per-cycle accumulation |
| Disk growth | ≤ 200 MB/week journal + state | host monitor | append-only journal; backups rotate |
| Journal replay | ≤ 5 s to replay 50k records to a cutoff | `service.replay` | bounded by `maximum_replay_records` |
| Operations API latency | ≤ 300 ms p95 per GET projection | API access log | read-only projections over cached records |
| Startup reconciliation | ≤ 30 s from process start to `ENTRIES_ENABLED` | preflight → recovery gate | reconciliation-first; protective monitoring earlier |
| Frontend bundle | ≤ 2.0 MB main JS (gzipped served) | `frontend/dist` | current build ≈ 1.38 MB uncompressed main chunk |
| Frontend page responsiveness | ≤ 2.5 s Largest Contentful Paint on the Mini PC | dashboard load | static assets served locally |

## Method

- Latency and duration budgets are wall-clock on the target Mini PC (Ubuntu
  24.04), not a developer laptop.
- Memory and disk are observed over a ≥ 72 h soak; the pass criterion is a flat
  trend, not just an instantaneous value.
- The reconciliation-startup budget is measured from process start to the
  recovery gate reaching `ENTRIES_ENABLED` (see the resilience recovery gate);
  a host that never reconciles never enables entries, by design.

## Guardrail

Any optimization PR must show, in addition to the improved metric, that the
affected deterministic outputs (fingerprints, decisions, replay results) are
byte-for-byte unchanged. The canonical fingerprint and replay-determinism tests
are the mechanical check for this.
