# Regime-Aware Deterministic Strategy

## Scope

This design produces explainable long-only analysis. Its complete action set is
`LONG_CANDIDATE`, `WATCH`, and `NO_TRADE`. It has no order, position sizing,
account switching, scheduling, AI, or broker mutation capability.

## Pipeline

1. Convert normalized IG bars into midpoint OHLC series while preserving invalid-bar findings.
2. Validate chronology, freshness, prices, bid/ask consistency, gaps, market status,
   spread, bar count, and known holding state.
3. Run the unchanged three-pillar indicator and score engine.
4. Filter close prices with a local-linear Kalman model.
5. Fit a causal three-state diagonal Gaussian HMM.
6. Apply mandatory gates. No weighted score can override a failed gate.

## Kalman Model

The hidden state contains level and slope:

```text
x_t = [level_t, slope_t]^T
F   = [[1, 1], [0, 1]]
H   = [1, 0]
x_t = F x_(t-1) + w_t,     w_t ~ N(0, Q)
y_t = H x_t + v_t,         v_t ~ N(0, R)
```

Prediction and update equations are:

```text
x^-_t = F x_(t-1)
P^-_t = F P_(t-1) F^T + Q
e_t   = y_t - H x^-_t
S_t   = H P^-_t H^T + R
K_t   = P^-_t H^T S_t^-1
x_t   = x^-_t + K_t e_t
P_t   = (I-K_tH)P^-_t(I-K_tH)^T + K_t R K_t^T
```

The Joseph covariance update is used for numerical stability. Every covariance is
symmetrized and checked for finite, non-negative eigenvalues. Defaults are level
process noise `1e-3`, slope process noise `1e-5`, observation noise `1e-2`, and
unit initial variances. Initialization is `level_0 = first close`, `slope_0 = 0`,
and `P_0 = diag(1, 1)`. At least 30 observations are required. Normalized price
deviation is `(last_price - filtered_level) / sqrt(level_variance + R)`.
The dimensionless slope and uncertainty used by generic gates are respectively
`filtered_slope / abs(filtered_level)` and
`slope_uncertainty / abs(filtered_level)`.

## HMM Features

At index `t`, features use observations through `t` only:

- log return: `log(close_t / close_(t-1))`;
- realized volatility: root mean square of returns in the trailing 20-bar window;
- normalized Kalman slope: `filtered_slope_t / abs(filtered_level_t)`;
- level distance: `(close_t - filtered_level_t) / level_uncertainty_t`;
- rolling drawdown: `close_t / max(close in trailing window) - 1`.

The feature scaler is fit only on the explicit training window ending at the signal
cutoff. A three-state diagonal-covariance `hmmlearn` Gaussian HMM then fits that same
window with 200 maximum iterations, tolerance `1e-3`, covariance floor `1e-6`, and
random seed 42. The 20-bar feature window is removed before sample counting: at least
120 usable feature rows and 10 posterior-weighted observations per state are required.
Zero-variance or excessive standardized features fail closed. There is no retry with
relaxed constraints.

Dependencies are deliberately narrow: NumPy implements explicit matrix and array
calculations; SciPy supplies established numerical primitives used by the modeling
stack; scikit-learn provides the training-window standardizer; hmmlearn provides the
established Gaussian HMM implementation. No trading framework is used.

## State Mapping

Raw HMM indices are arbitrary. For every hidden state, posterior-weighted means are
calculated for log return, realized volatility, and normalized Kalman slope. These
three columns are standardized across states. The bull score is:

```text
z(return) - z(volatility) + z(slope)
```

All six one-to-one assignments are scored using bull, bear, and transitional
statistics. Assignment ordering is deterministic, but the best assignment must beat
the runner-up by the configured `0.20` margin. Exact ties, near ties, conflicting
statistics without adequate separation, and low-occupancy states fail closed rather
than receiving forced labels. Safe per-state numerical summaries are retained.

`hmmlearn.predict_proba` produces smoothed posteriors. The signal uses only the final
row at the current cutoff and records the method as `endpoint_smoothed_posterior`.
Because the input is sliced at the cutoff first, that endpoint has no observations
after signal time. It is not described as a filtered probability. Probabilities are
remapped to semantic regimes. Uncertainty is
Shannon entropy normalized by `log(3)`. Defaults require selected probability at
least `0.60` and normalized entropy no greater than `0.65`.

## Leakage Protection

The pipeline analyzes the latest point of supplied data or an explicit cutoff. At a
cutoff, it slices first, resets evaluation time, and then reruns the baseline, Kalman
filter, feature scaler, HMM fit, mapping, and gates. Walk-forward analysis repeats
this independently for each cutoff. No API fits on a future-inclusive dataset and
then emits historical decisions.

Regression tests append extreme future values and prove that a previously calculated
cutoff result is unchanged. Other tests compare scaler statistics to the cutoff
feature matrix and verify causal rolling features.

## Mandatory Long Gates

A `LONG_CANDIDATE` requires all of these conditions:

- valid, sufficiently long, fresh, ordered, finite market data;
- `TRADEABLE` market status and relative spread no greater than 10 basis points,
  where `spread_bps = 10,000 * (ask - bid) / midpoint`;
- known and flat holding state;
- ready, finite Kalman output with positive slope, bounded slope uncertainty, and
  normalized price deviation inside `[-2.0, 1.0]`;
- ready `BULL_LOW_VOL` regime, probability at least `0.60`, and entropy at most `0.65`;
- baseline trend and momentum scores each at least `1`;
- a fresh deterministic rebound or legacy re-entry trigger;
- no death-cross and no relentless-bearish condition.

An existing holding may produce `WATCH` when data and models are valid. All other
states produce `NO_TRADE`. Rejection output lists every failed gate.

Macro context is optional by default. Missing macro is recorded as `UNKNOWN` and is
not silently converted to zero. When `require_macro_confirmation` is enabled, macro
must be present and non-adverse. Holding semantics are fixed: unknown means
`NO_TRADE`, flat evaluates entry gates, and holding can only yield `WATCH` or
`NO_TRADE`.

## Signal Timing And Staleness

The signal and data-cutoff timestamps equal completed bar `t`. Every result records
`NEXT_VALID_BAR`; when cadence is known, the earliest eligible timestamp is strictly
later than the signal timestamp. Signals using a completed bar are actionable no
earlier than the next valid market bar.

Staleness is resolution-aware. Daily bars allow 36 hours plus a configurable 48-hour
grace when the interval crosses a weekend. Intraday bars use a multiple of their
cadence. Unknown cadence fails closed. Holiday and instrument-session calendars are
deferred to a later milestone.

## Reproducibility

Configuration is immutable Pydantic data. Its fingerprint is SHA-256 over UTF-8
encoded JSON with sorted keys, compact separators, and non-finite values forbidden.
Every candidate includes this fingerprint plus baseline, Kalman, HMM, signal-engine,
schema, NumPy, SciPy, scikit-learn, and hmmlearn version identifiers. The guarantee is
reproducibility within a pinned software environment and deterministic configuration,
not universal bit-for-bit equality across operating systems or BLAS implementations.

Named deterministic variants are `BASELINE_ONLY`, `BASELINE_KALMAN`, `BASELINE_HMM`,
and `BASELINE_KALMAN_HMM`. The last is the default. Disabled components contribute no
signal gates; the HMM-only variant builds its trend and distance features directly
from its causal rolling price window rather than from Kalman output.

## Assumptions And Limitations

- The time-step transition is one bar; irregular gaps are rejected rather than scaled.
- HMM fitting uses the available expanding window through the cutoff, not a fixed-size
  rolling training window.
- Daily analysis is the initial CLI integration even though the IG adapter can return
  hourly resolutions.
- Regime labels are statistical interpretations, not ground truth.
- Basis-point spread normalization is portable across price scales but does not model
  instrument-specific tick sizes, liquidity, or session effects.
- Holiday-aware staleness requires a reviewed market-calendar integration later.
- Legacy rebound semantics are preserved, including two rebound flags unless the
  original decision is `RE-ENTRY`.
- Long-only operation avoids introducing short-sale borrow, asymmetric risk, and exit
  semantics before those controls have separate designs and reviews.
