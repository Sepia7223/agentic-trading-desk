# Milestone 15 — Governed Strategy Research and Optimization

## Objective

Provide an offline-only research environment for reproducible strategy discovery, parameter analysis, and experiment comparison without granting autonomous promotion or execution authority.

## Scope

Implement:

- immutable experiment specifications;
- reproducible dataset and code fingerprints;
- parameter-grid and sensitivity analysis;
- nested chronological validation;
- multiple-hypothesis and selection-bias reporting;
- experiment registry and lineage;
- benchmark and ablation comparison;
- resource budgets and cancellation;
- research artifact retention;
- explicit handoff into Milestone 12 governance.

## Optimization rules

- Research may search bounded parameter spaces only.
- Search spaces, objectives, constraints, and random seeds are frozen before execution.
- Results are ranked for analysis, not automatically promoted.
- Final-test data is unavailable to optimization.
- Any selected candidate enters the normal strategy versioning and validation process from `RESEARCH_ONLY`.
- Bayesian, evolutionary, or AI-assisted research may be evaluated only as offline suggestion tooling and cannot mutate production or Demo configuration.

## Overfitting controls

Require:

- nested walk-forward or equivalent chronological separation;
- explicit trial count;
- multiple-comparison diagnostics;
- parameter stability surfaces;
- performance degradation from development to validation;
- simple benchmark comparison;
- economic plausibility review;
- rejection of isolated optimum spikes.

## Performance engineering

Address the expensive walk-forward path by introducing evidence-equivalent caching or incremental computation for Kalman, HMM, and other stateful features. Optimized and reference implementations must produce equivalent outputs within declared tolerances. Cache keys include dataset, cutoff, feature version, parameter, and code fingerprints.

## Macro and feature governance

Every research experiment must declare whether macro scoring and staleness gates are included. No injected `None` value may silently disable a declared pillar. Missing required evidence fails the experiment.

## Authority boundaries

Research cannot:

- change strategy lifecycle state;
- change Demo configuration;
- call Risk, Execution, lifecycle, broker, or credentials;
- write to operational state;
- enable Live;
- present synthetic or optimized results as certification.

## Required tests

- experiment reproducibility;
- chronological leakage prevention;
- final-test isolation;
- cache-key correctness and reference equivalence;
- bounded resource enforcement;
- failed and cancelled experiment persistence;
- no automatic promotion;
- no operational dependencies;
- artifact tamper detection.

## Definition of Done

Research runs are reproducible, leakage-resistant, computationally practical, fully fingerprinted, and incapable of changing executable strategy state. Independent review returns `ACCEPTED`.
