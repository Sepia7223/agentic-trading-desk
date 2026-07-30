"""Stage orchestration for governed Milestone 12 historical validation.

Turns the chronological harness output into the framework's evidence models:
stage-bounded trade sets, walk-forward windows, gate evaluations, a
tamper-evident final-test lock, and sealed artifact packages.

The final-test partition is technically protected: simulation for the
DEVELOPMENT and VALIDATION stages refuses to read bars past the validation
end, and the FINAL_TEST stage refuses to run without a pre-existing,
fingerprint-verified lock document created after gate review.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.strategy.baseline import evaluate_baseline
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import (
    StrategyAction,
    StrategyBarResolution,
    StrategyContext,
    StrategyMarketData,
)
from trading_desk.strategy.pipeline import RegimeAwareStrategyPipeline
from trading_desk.strategy.validation import (
    StressResult,
    ValidationGates,
    ValidationMetrics,
    ValidationReport,
    ValidationStage,
    ValidationTrade,
    calculate_metrics,
    cost_stress,
    evaluate_gates,
    execution_stress,
    regime_distribution,
    robustness_stress,
)
from trading_desk.strategy.validation_runner import (
    HistoricalBar,
    SimulationCosts,
    ValidationRunnerError,
    _decimal,
    bars_market_data,
)


class OrchestrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class StageBoundaries(OrchestrationModel):
    """Chronological, non-overlapping stage boundaries for one dataset."""

    schema_version: Literal["validation-stages-v1"] = "validation-stages-v1"
    development_start: datetime
    development_end: datetime
    validation_start: datetime
    validation_end: datetime
    final_test_start: datetime
    final_test_end: datetime
    walk_forward_window_count: int = Field(default=7, ge=2, le=24)

    @field_validator(
        "development_start",
        "development_end",
        "validation_start",
        "validation_end",
        "final_test_start",
        "final_test_end",
    )
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("stage boundaries must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        sequence = (
            self.development_start,
            self.development_end,
            self.validation_start,
            self.validation_end,
            self.final_test_start,
            self.final_test_end,
        )
        if any(left >= right for left, right in zip(sequence, sequence[1:], strict=False)):
            raise ValueError("stage boundaries must be strictly chronological")
        return self

    def walk_forward_windows(self) -> tuple[tuple[datetime, datetime], ...]:
        span = self.validation_end - self.validation_start
        step = span / self.walk_forward_window_count
        windows: list[tuple[datetime, datetime]] = []
        for index in range(self.walk_forward_window_count):
            start = self.validation_start + step * index
            end = (
                self.validation_end
                if index == self.walk_forward_window_count - 1
                else self.validation_start + step * (index + 1)
            )
            windows.append((start, end))
        return tuple(windows)

    def stage_range(self, stage: ValidationStage) -> tuple[datetime, datetime]:
        return {
            ValidationStage.DEVELOPMENT: (self.development_start, self.development_end),
            ValidationStage.VALIDATION: (self.validation_start, self.validation_end),
            ValidationStage.FINAL_TEST: (self.final_test_start, self.final_test_end),
        }[stage]


class FinalTestLock(OrchestrationModel):
    """Tamper-evident record created after validation review and before TEST.

    Mirrors the frozen-selection pattern of the backtest subsystem: the
    final-test simulation refuses to run unless this document exists, its
    fingerprint verifies, and its dataset and configuration identities match
    the run being requested.
    """

    schema_version: Literal["final-test-lock-v1"] = "final-test-lock-v1"
    lock_id: str = Field(min_length=64, max_length=64)
    dataset_fingerprint: str = Field(min_length=64, max_length=64)
    boundaries: StageBoundaries
    strategy_ids: tuple[str, ...]
    configuration_fingerprints: tuple[tuple[str, str], ...]
    validation_report_ids: tuple[tuple[str, str], ...]
    locked_at: datetime
    locked_by: str

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"lock_id"}))
        if self.lock_id != expected:
            raise ValueError("final-test lock fingerprint mismatch")
        return self


def create_final_test_lock(**values: object) -> FinalTestLock:
    draft_fields: dict[str, Any] = {**values, "lock_id": "0" * 64}
    draft = FinalTestLock.model_construct(**draft_fields)
    fields = draft.model_dump(mode="python", exclude={"lock_id"})
    return FinalTestLock.model_validate({**fields, "lock_id": fingerprint(fields)})


def write_lock(lock: FinalTestLock, path: Path) -> None:
    if path.exists():
        raise ValidationRunnerError("final-test lock already exists and is immutable")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(lock.model_dump_json(indent=2) + "\n", encoding="utf-8")


def read_lock(path: Path) -> FinalTestLock:
    if not path.is_file():
        raise ValidationRunnerError("final-test lock is required before TEST evaluation")
    return FinalTestLock.model_validate_json(path.read_text(encoding="utf-8"))


def trades_in_range(
    trades: tuple[ValidationTrade, ...], start: datetime, end: datetime
) -> tuple[ValidationTrade, ...]:
    return tuple(item for item in trades if start <= item.entry_at < end)


def build_walk_forward(
    strategy_id: str,
    trades: tuple[ValidationTrade, ...],
    boundaries: StageBoundaries,
    parameter_fingerprint: str,
) -> tuple[tuple[datetime, datetime, datetime, datetime, tuple[ValidationTrade, ...], str], ...]:
    """One definition per window; training is all history before the window.

    Strategy parameters are the frozen version-1 configurations: no
    per-window re-optimization is performed, so every window carries the same
    parameter fingerprint and parameter instability is honestly zero.
    """

    definitions = []
    for start, end in boundaries.walk_forward_windows():
        definitions.append(
            (
                boundaries.development_start,
                start - timedelta(seconds=1),
                start,
                end,
                trades_in_range(trades, start, end),
                parameter_fingerprint,
            )
        )
    return tuple(definitions)


WALK_FORWARD_WINDOW_GATE = "WALK_FORWARD_WINDOWS"
WALK_FORWARD_CONSISTENCY_GATE = "WALK_FORWARD_CONSISTENCY"
PARAMETER_INSTABILITY_GATE = "PARAMETER_INSTABILITY"
COST_SENSITIVITY_GATE = "COST_STRESS_SENSITIVITY"
REGIME_COVERAGE_GATE = "REGIME_COVERAGE"
RISK_ADJUSTED_RETURN_GATE = "RISK_ADJUSTED_RETURN"


def evaluate_extended_gates(
    metrics: ValidationMetrics,
    gates: ValidationGates,
    *,
    walk_forward_profitable_fraction: Decimal | None,
    walk_forward_window_count: int,
    parameter_instability: Decimal,
    cost_results: tuple[StressResult, ...],
    trades: tuple[ValidationTrade, ...],
) -> tuple[str, ...]:
    """Predetermined pass/fail gates beyond the base metric gates."""

    failed = list(evaluate_gates(metrics, gates))
    if walk_forward_window_count < gates.minimum_walk_forward_windows:
        failed.append(WALK_FORWARD_WINDOW_GATE)
    if (
        walk_forward_profitable_fraction is None
        or walk_forward_profitable_fraction < gates.minimum_profitable_window_fraction
    ):
        failed.append(WALK_FORWARD_CONSISTENCY_GATE)
    if parameter_instability > gates.maximum_parameter_instability:
        failed.append(PARAMETER_INSTABILITY_GATE)
    base = metrics.expectancy
    doubled = next(
        (
            item.metrics.expectancy
            for item in cost_results
            if item.cost_multiplier == Decimal("2.00")
        ),
        None,
    )
    if base is None or base <= 0 or doubled is None:
        failed.append(COST_SENSITIVITY_GATE)
    else:
        sensitivity = (base - doubled) / base
        if doubled <= 0 or sensitivity > gates.maximum_cost_sensitivity:
            failed.append(COST_SENSITIVITY_GATE)
    if len(regime_distribution(trades)) < gates.minimum_regime_coverage:
        failed.append(REGIME_COVERAGE_GATE)
    if metrics.sharpe_ratio is None or metrics.sharpe_ratio <= 0:
        failed.append(RISK_ADJUSTED_RETURN_GATE)
    return tuple(dict.fromkeys(failed))


def build_report(
    *,
    strategy_id: str,
    strategy_version: str,
    stage: ValidationStage,
    dataset_fingerprint: str,
    boundaries: StageBoundaries,
    configuration_fingerprint: str,
    trades: tuple[ValidationTrade, ...],
    rejection_count: int,
    candidate_count: int,
    failed_gates: tuple[str, ...],
    gates: ValidationGates,
    data_quality_findings: tuple[str, ...],
    final_test_locked_before_evaluation: bool,
    created_at: datetime,
) -> ValidationReport:
    start, end = boundaries.stage_range(stage)
    metrics = calculate_metrics(
        trades, rejection_count=rejection_count, candidate_count=candidate_count
    )
    fields = {
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "stage": stage,
        "dataset_fingerprint": dataset_fingerprint,
        "dataset_start": start,
        "dataset_end": end,
        "configuration_fingerprint": configuration_fingerprint,
        "metrics": metrics,
        "required_gates": gates,
        "failed_gates": failed_gates,
        "data_quality_findings": data_quality_findings,
        "final_test_locked_before_evaluation": final_test_locked_before_evaluation,
        "created_at": created_at,
    }
    return ValidationReport.model_validate({**fields, "validation_report_id": fingerprint(fields)})


def simulate_trend_regime_day(
    bars: tuple[HistoricalBar, ...],
    *,
    epic: str,
    instrument: str,
    costs: SimulationCosts,
    evaluation_start: datetime,
    evaluation_end: datetime,
    configuration: StrategyConfiguration | None = None,
    rolling_window: int | None = None,
    protective_stop_fraction: Decimal = Decimal("0.05"),
    maximum_holding_bars: int = 20,
    trade_prefix: str = "trend-regime-day",
) -> tuple[ValidationTrade, ...]:
    """Replay the accepted trend/regime strategy on daily bars.

    Used only for portfolio-contribution and ablation analysis; the exit
    policy mirrors the accepted backtest engine (exhaustion, strategy exit,
    maximum holding period, protective stop, forced end-of-data liquidation)
    with the shared Milestone 12 cost policy so the four strategies are
    directly comparable. The strategy itself refits at every evaluated bar
    through the real pipeline over an expanding history window — the fitting
    policy of its accepted backtest lineage (``rolling_window`` bounds the
    window only when explicitly provided). Trade monetary values are recorded
    as fractions of entry notional, matching the portfolio harness.
    """

    config = configuration or StrategyConfiguration()
    pipeline = RegimeAwareStrategyPipeline(config)
    trades: list[ValidationTrade] = []
    position: dict[str, object] | None = None
    pending_regime: str | None = None
    pending = False
    exit_pending: str | None = None

    def market_data(index: int) -> StrategyMarketData:
        start = 0 if rolling_window is None else max(0, index + 1 - rolling_window)
        selected = bars[start : index + 1]
        return bars_market_data(
            selected,
            epic=epic,
            instrument=instrument,
            resolution=StrategyBarResolution.DAY,
            retrieval_time=selected[-1].timestamp,
        )

    def close(index: int, exit_bid: Decimal, exit_mid: Decimal, exit_at: datetime) -> None:
        nonlocal position, exit_pending
        assert position is not None
        entry_mid = position["entry_mid"]
        assert isinstance(entry_mid, Decimal)
        entry_at = position["entry_at"]
        assert isinstance(entry_at, datetime)
        slippage = (exit_mid * costs.slippage_bps / Decimal("10000")).quantize(
            Decimal("0.00000001")
        )
        held_days = Decimal(str(max((exit_at - entry_at).total_seconds(), 0.0) / 86400.0))
        entry_half_spread = position["entry_half_spread"]
        assert isinstance(entry_half_spread, Decimal)
        entry_slippage = position["entry_slippage"]
        assert isinstance(entry_slippage, Decimal)
        quantum = Decimal("0.00000001")
        trades.append(
            ValidationTrade(
                trade_id=f"{trade_prefix}-{len(trades) + 1:05d}",
                strategy_id="trend-regime-v1",
                instrument_id=instrument,
                timeframe="DAY",
                regime=str(position["regime"]),
                entry_at=entry_at,
                exit_at=exit_at,
                gross_pnl=((exit_mid - entry_mid) / entry_mid).quantize(quantum),
                spread_cost=(
                    (entry_half_spread + max(exit_mid - exit_bid, Decimal("0"))) / entry_mid
                ).quantize(quantum),
                slippage_cost=((entry_slippage + slippage) / entry_mid).quantize(quantum),
                commission_cost=costs.commission_per_fill * 2,
                funding_cost=(costs.funding_fraction_per_day * held_days).quantize(quantum),
                turnover=((entry_mid + exit_mid) / entry_mid).quantize(quantum),
            )
        )
        position = None
        exit_pending = None

    last_index: int | None = None
    for index, bar in enumerate(bars):
        if bar.timestamp > evaluation_end:
            break
        last_index = index
        day_end = bar.timestamp + timedelta(days=1)

        if position is None and pending:
            pending = False
            entry_mid = _decimal(bar.open_mid)
            position = {
                "entry_at": bar.timestamp,
                "entry_mid": entry_mid,
                "entry_half_spread": max(_decimal(bar.open_ask) - entry_mid, Decimal("0")),
                "entry_slippage": (entry_mid * costs.slippage_bps / Decimal("10000")).quantize(
                    Decimal("0.00000001")
                ),
                "stop": entry_mid * (Decimal("1") - protective_stop_fraction),
                "regime": pending_regime or "UNKNOWN",
                "bars_held": 0,
            }
        elif position is not None:
            position["bars_held"] = int(position["bars_held"]) + 1  # type: ignore[call-overload]
            stop = position["stop"]
            assert isinstance(stop, Decimal)
            half_spread = max((_decimal(bar.open_ask) - _decimal(bar.open_bid)) / 2, Decimal("0"))
            if exit_pending is not None:
                open_bid = _decimal(bar.open_bid)
                close(index, open_bid, open_bid + half_spread, day_end)
            elif _decimal(bar.low_bid) <= stop:
                fill = min(stop, _decimal(bar.open_bid))
                close(index, fill, fill + half_spread, day_end)

        if index + 1 < config.minimum_bars_required:
            continue
        data = market_data(index)
        holding = position is not None
        context = StrategyContext(
            holding=holding,
            macro_score=None,
            current_spread=data.spreads[-1],
            current_spread_bps=data.spread_bps[-1],
            market_status=data.market_status,
            current_time=data.timestamps[-1],
        )
        if holding and position is not None and exit_pending is None:
            baseline = evaluate_baseline(data, context)
            reason = None
            if len(baseline.exhaustion_flags) >= 2:
                reason = "EXHAUSTION"
            elif baseline.original_decision.startswith("EXIT"):
                reason = "STRATEGY_EXIT"
            elif int(position["bars_held"]) >= maximum_holding_bars:  # type: ignore[call-overload]
                reason = "MAXIMUM_HOLDING_PERIOD"
            if reason is not None:
                exit_pending = reason
        elif not holding and not pending and bar.timestamp >= evaluation_start:
            try:
                candidate = pipeline.analyze_latest(data, context)
            except (ValueError, ArithmeticError):
                continue
            if candidate.action is StrategyAction.LONG_CANDIDATE:
                pending = True
                pending_regime = candidate.current_regime.value

    if position is not None and last_index is not None:
        final_bar = bars[last_index]
        exit_mid = _decimal(final_bar.close_mid)
        close(
            last_index,
            _decimal(final_bar.close_bid),
            exit_mid,
            final_bar.timestamp + timedelta(days=1),
        )
    return tuple(trades)


def serialize_trades(trades: tuple[ValidationTrade, ...], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(item.model_dump_json() for item in trades) + "\n"
    path.write_text(content, encoding="utf-8")
    return fingerprint(content)


def load_trades(path: Path) -> tuple[ValidationTrade, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return tuple(ValidationTrade.model_validate_json(line) for line in lines if line.strip())


@dataclass(frozen=True)
class StressBundle:
    """The complete stress evidence for one strategy's validation trades."""

    cost: tuple[StressResult, ...]
    execution: StressResult
    robustness: tuple[StressResult, ...]


def stress_bundle(
    strategy_id: str, trades: tuple[ValidationTrade, ...], execution_degradation: Decimal
) -> StressBundle:
    return StressBundle(
        cost=cost_stress(trades, strategy_id),
        execution=execution_stress(trades, strategy_id, execution_degradation),
        robustness=robustness_stress(trades, strategy_id),
    )


def dataset_manifest_document(
    *,
    summary_path: Path,
    boundaries: StageBoundaries,
    costs: SimulationCosts,
    approved_by: str,
    approved_at: datetime,
    timeframes: tuple[str, ...],
    notes: tuple[str, ...],
) -> dict[str, object]:
    """Committed, fingerprinted description of the approved dataset."""

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    pair_documents = {}
    for pair, info in sorted(summary["pairs"].items()):
        bars = {name: value for name, value in info["bars"].items() if not name.startswith("_")}
        pair_documents[pair] = {
            "minute_coverage": info["bars"].get("_minute_coverage"),
            "files": bars,
        }
    document: dict[str, object] = {
        "schema_version": "validation-dataset-manifest-v1",
        "source": summary["source"],
        "source_base_url": summary["base_url"],
        "retrieved_at": summary["retrieved_at"],
        "coverage_start": summary["coverage_start"],
        "coverage_end": summary["coverage_end"],
        "minute_coverage_start": summary.get("minute_coverage_start"),
        "series_provenance": summary.get("series_provenance"),
        "timezone": summary["timezone"],
        "price_fields": "bid and ask OHLC from native bid and ask candle archives",
        "midpoint_definition": "midpoint = (bid + ask) / 2 per OHLC field",
        "completed_bar_convention": (
            "bars are labeled by UTC period start and become evaluable at period "
            "start plus one timeframe interval; the unfinished current bar is never used"
        ),
        "boundary_convention": "stage boundaries are inclusive start, exclusive end, UTC",
        "duplicate_policy": (
            "duplicate timestamps are structurally impossible; loading fails closed"
        ),
        "invalid_bar_policy": (
            "non-finite, non-positive, or bid-above-ask records are dropped and counted "
            "at aggregation; zero-tick flat filler records (closed-market padding with "
            "zero volume and zero range) are excluded to preserve live-feed parity; "
            "loaders fail closed on residual violations"
        ),
        "macro_scoring": (
            "macro-sentiment scoring is explicitly excluded from every frozen strategy "
            "version in this validation round; the new families do not consume macro "
            "input and the accepted trend strategy is simulated with macro_score=None"
        ),
        "staleness_policy": (
            "historical evaluation timestamps equal completed-bar end, so staleness "
            "gates observe zero age by construction; session, spread, liquidity, and "
            "event gates operate on simulated values"
        ),
        "spread_source": "real Dukascopy bid/ask quotes; no synthetic spread model",
        "missing_bar_policy": (
            "minutes present in only one side are dropped; windows without any shared "
            "minute are omitted; crossed bid/ask bars are dropped and counted"
        ),
        "cost_assumptions": {
            "slippage_bps": str(costs.slippage_bps),
            "commission_per_fill": str(costs.commission_per_fill),
            "funding_fraction_per_day": str(costs.funding_fraction_per_day),
        },
        "timeframes": timeframes,
        "boundaries": json.loads(boundaries.model_dump_json()),
        "pairs": pair_documents,
        "raw_data_committed": False,
        "approved_by": approved_by,
        "approved_at": approved_at.isoformat(),
        "notes": notes,
    }
    document["dataset_fingerprint"] = fingerprint(document)
    return document
