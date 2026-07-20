# Milestone 19 — Live Trading Readiness Assessment

## Status

Optional governance milestone. This milestone does not enable Live trading and does not add a production broker path.

## Objective

Assess whether the release candidate could be considered for a future, separately authorized Live-trading program. Produce a documented go/no-go decision based on engineering, operational, financial, legal, security, and governance evidence.

## Assessment domains

### Engineering

- deterministic behavior and replay;
- authority-boundary integrity;
- reconciliation and ambiguity handling;
- recovery and rollback evidence;
- capacity and performance margins;
- dependency and supply-chain posture;
- configuration and secret isolation;
- observability and incident response.

### Strategy and portfolio evidence

- sufficiently long Demo campaign history;
- performance stability across regimes;
- cost and slippage sensitivity;
- drawdown and concentration behavior;
- strategy degradation and breaker effectiveness;
- portfolio attribution and reconciliation;
- evidence that results are not dependent on a single short period.

### Risk governance

- capital-at-risk proposal;
- hard daily, weekly, campaign, strategy, instrument, currency, and portfolio limits;
- kill-switch design independent of strategy and dashboard authority;
- staged rollout and minimum-size policy;
- human supervision and escalation requirements;
- broker and account restrictions;
- residual-risk acceptance.

### Legal and compliance

- jurisdiction and account permissions;
- broker terms and API usage requirements;
- tax, record-retention, and reporting obligations;
- data licensing;
- operator identity and responsibility;
- required professional legal or financial review.

### Security

- dedicated host posture;
- least-privilege secrets;
- encryption and backup protection;
- access control and audit logging;
- patching and vulnerability management;
- network exposure review;
- credential rotation and revocation procedures.

## Required output

Produce a readiness dossier containing:

- evidence inventory;
- unresolved findings by severity;
- quantified residual risks;
- required controls before any Live work;
- proposed staged authorization process;
- explicit `GO`, `CONDITIONAL_GO`, or `NO_GO` recommendation;
- named human approvers and review dates.

## Mandatory prohibitions

This milestone must not:

- add or enable a Live API host;
- create a Live execution adapter;
- use Live credentials;
- submit any Live order;
- reinterpret Demo certification as financial suitability;
- automatically authorize later implementation;
- permit AI, dashboard, strategy, portfolio, or research tooling to approve Live activity.

## Definition of Done

A complete, evidence-backed readiness dossier is independently reviewed. The system remains Demo-only regardless of the assessment outcome. Any future Live implementation requires a new architecture decision, new milestone specification, explicit legal and financial approval, separate credentials and infrastructure, and an independent safety review.
