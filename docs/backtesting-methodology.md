# Leakage-Controlled Backtesting Methodology

## Scope And Safety

The backtester is a local, deterministic simulation. It consumes normalized CSV or
Parquet bars and has no broker, credential, HTTP, OAuth, account, AI, or order-routing
interface. `SimulatedOrder` and `SimulatedFill` are research records, not broker
instructions. Only one long position and one normalized unit are permitted initially.

A profitable backtest is evidence for further testing, not proof of a profitable live
strategy.

## Dataset Integrity

Each bar requires timezone-aware timestamp, EPIC, resolution, and separate bid/ask
OHLC values. Timestamps must be unique and increasing. Every price must be finite and
positive, bid cannot exceed ask, and bid and ask OHLC relationships must be coherent.
No interpolation or price repair occurs. Daily cadence permits one-, two-, or three-day
intervals for weekends; unexpected cadence fails closed. Non-tradeable bars remain in
history and are recorded, but cannot provide a fill.

The manifest stores the source filename only, SHA-256 of the exact source bytes, row
count, period, resolution, and findings. Absolute paths never enter fingerprints.

## Chronological Splits And Walk Forward

Explicit timezone-aware `TRAIN`, `VALIDATION`, and `TEST` boundaries are strictly
ordered and non-overlapping. TRAIN must contain the full strategy warm-up. Normal
research and variant comparison can evaluate `VALIDATION` only. At an evaluation
cutoff `t`, the strategy
receives only bars through `t`; expanding mode uses all available history and rolling
mode uses the configured trailing window. The scaler, Kalman filter, HMM fit, state
mapping, and signal are rebuilt at each cutoff. Appended future bars cannot alter
stored validation or final-test signals, fills, trades, or equity when the configured boundary is
unchanged.

The final test period is technically inaccessible to normal comparison. A selected
variant and immutable configuration must first be frozen from validation evidence in a
tamper-evident artifact containing dataset identity, split boundaries, fingerprints,
validation metrics, rationale, and explicit final-test authorization. The separate
final-test API checks the artifact and evaluates only that variant. Final-test output
cannot be accepted by the selection API. This milestone has no optimizer, grid search,
Bayesian search, or automatic parameter tuning.

## Execution And Costs

A signal from completed bar `t` is eligible no earlier than a tradeable bar after
`t`. Default long entry is next-valid-bar open ask and default scheduled exit is
next-valid-bar open bid. Research modes may use the next bar close, but never the
signal bar. For `NEXT_CLOSE`, the position becomes active after the fill bar closes;
that bar's earlier high and low are unavailable to stop or target logic. Protective
evaluation starts on the following eligible bar. Adverse slippage is:

```text
entry_fill = ask * (1 + slippage_bps / 10,000)
exit_fill  = bid * (1 - slippage_bps / 10,000)
```

Gross P&L is midpoint movement times fixed quantity. Net P&L subtracts spread impact,
entry and exit slippage, fixed and proportional commissions, overnight funding, and
the reserved guaranteed-stop premium exactly once. Funding is entry midpoint notional
times funding basis points per day times elapsed holding days.

The common temporary exit policy is legacy baseline EXIT, two exhaustion flags,
protective simulation stop, maximum holding bars, or forced end-of-data liquidation at
the most recent valid, tradeable bid after position activation. The forced fill is
explicitly labeled `FORCED_END_OF_DATA_LIQUIDATION`. If no eligible exit quote exists,
the position is recorded as unresolved with no fabricated fill or realized P&L. It is
not production-ready. If stop and favorable target could both be crossed intrabar,
default `ADVERSE_FIRST` assumes the stop occurred first;
`FAVORABLE_FIRST` and `SKIP_AMBIGUOUS_BAR` exist for declared sensitivity runs.

## Variants And Benchmarks

`BASELINE_ONLY`, `BASELINE_KALMAN`, `BASELINE_HMM`, and
`BASELINE_KALMAN_HMM` receive identical bars, splits, costs, timing, quantity, and exit
policy. VALIDATION and untouched TEST results are reported separately only after a
validation-selected variant has been frozen and the final test explicitly released.
Comparison reports contain no test metrics. `BASELINE_ONLY` is the primary strategy
control. Additional controls are cash
with zero return and buy-and-hold entered at the evaluation-period open ask and closed at
the latest eligible evaluation-period bid
with the same slippage, commission, and funding assumptions.

Trades are segmented by the HMM regime known at signal time only. Rejection counts
retain strategy gate failures and fill failures so low or excessive turnover can be
diagnosed without inspecting raw data.

## Metrics

Reports include gross/net return, annualized return when available, equity, peak,
maximum drawdown and duration, trade counts, win rate, average and largest wins/losses,
expectancy, payoff ratio, profit factor, holding period, turnover, exposure, volatility,
downside deviation, Sharpe, Sortino, and Calmar. Undefined ratios use typed unavailable
values rather than zero or infinity. Annualization is resolution-aware and may be
explicitly overridden.

## Fingerprints And Limitations

The run fingerprint hashes canonical sorted JSON containing the strategy fingerprint,
backtest settings, split boundaries, variant, fill and cost rules, fitting policy,
dataset content hash, schema versions, and Python/NumPy/SciPy/scikit-learn/hmmlearn
versions. It excludes paths, credentials, account data, machine identity, and launch
time. Reproducibility is expected within a pinned software environment, not necessarily
bit-for-bit across BLAS implementations.

Known limitations include no holiday calendar, corporate actions, partial fills,
liquidity or market-impact model, short selling, production exits, portfolio-level
risk, or account-equity sizing. Daily weekend cadence and one-unit fills are deliberate
initial simplifications.
