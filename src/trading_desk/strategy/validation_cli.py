"""Research CLI for governed Milestone 12 historical strategy validation.

Every command is local and read-only with respect to the trading system: no
broker adapter, credential, journal-write, risk, or execution import. The
output is immutable, fingerprinted evidence for human promotion review.

Typical flow (per approved dataset):

1. ``manifest``       — freeze the governed dataset manifest.
2. ``simulate``       — one pair: development + validation stages only.
3. ``simulate-trend`` — one pair: accepted trend strategy on daily bars.
4. ``report``         — aggregate evidence, evaluate predetermined gates.
5. ``lock``           — create the immutable final-test lock.
6. ``final-simulate`` — one pair: locked final-test stage (requires lock).
7. ``final-report``   — final-test reports (requires lock).
8. ``seal``           — write the sealed per-strategy artifact packages with
   an explicit human promotion decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trading_desk.strategy.artifacts import build_artifact_package
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.donchian_breakout import DonchianBreakoutEvaluator
from trading_desk.strategy.models import StrategyBarResolution
from trading_desk.strategy.portfolio_configuration import (
    DonchianBreakoutConfiguration,
    RangeMeanReversionConfiguration,
    TrendPullbackConfiguration,
    VolatilityBreakoutConfiguration,
)
from trading_desk.strategy.range_mean_reversion import RangeMeanReversionEvaluator
from trading_desk.strategy.trend_pullback import TrendPullbackEvaluator
from trading_desk.strategy.validation import (
    ValidationGates,
    ValidationStage,
    ValidationTrade,
    calculate_metrics,
    portfolio_ablation,
    portfolio_contribution,
    walk_forward_validate,
)
from trading_desk.strategy.validation_orchestration import (
    StageBoundaries,
    build_report,
    build_walk_forward,
    create_final_test_lock,
    dataset_manifest_document,
    evaluate_extended_gates,
    load_trades,
    read_lock,
    serialize_trades,
    simulate_trend_regime_day,
    stress_bundle,
    trades_in_range,
    write_lock,
)
from trading_desk.strategy.validation_runner import (
    CausalContextBuilder,
    SimulatedStrategy,
    SimulationCosts,
    load_bars,
    simulate_strategies,
)
from trading_desk.strategy.volatility_breakout import VolatilityBreakoutEvaluator

PAIR_EPICS: dict[str, tuple[str, str]] = {
    "EURUSD": ("CS.D.EURUSD.CFD.IP", "EUR/USD"),
    "GBPUSD": ("CS.D.GBPUSD.CFD.IP", "GBP/USD"),
    "USDJPY": ("CS.D.USDJPY.CFD.IP", "USD/JPY"),
    "AUDUSD": ("CS.D.AUDUSD.CFD.IP", "AUD/USD"),
    "USDCAD": ("CS.D.USDCAD.CFD.IP", "USD/CAD"),
    "EURJPY": ("CS.D.EURJPY.CFD.IP", "EUR/JPY"),
}

TIMEFRAME_RESOLUTIONS: dict[str, StrategyBarResolution] = {
    "MINUTE_15": StrategyBarResolution.MINUTE_15,
    "HOUR": StrategyBarResolution.HOUR,
}

STRATEGY_IDS = ("trend-pullback-v1", "volatility-breakout", "range-mean-reversion")

DEFAULT_BOUNDARIES = StageBoundaries(
    development_start=datetime(2019, 7, 1, tzinfo=UTC),
    development_end=datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC),
    validation_start=datetime(2022, 1, 1, tzinfo=UTC),
    validation_end=datetime(2025, 6, 30, 23, 59, 59, tzinfo=UTC),
    final_test_start=datetime(2025, 7, 1, tzinfo=UTC),
    final_test_end=datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
    walk_forward_window_count=7,
)

# Trades record returns as fractions of entry notional, so one uniform
# execution-stress degradation applies to every instrument: one basis point
# of notional (about one pip on the governed majors).
EXECUTION_DEGRADATION = Decimal("0.0001")

# Context-model configuration for intraday historical validation. The default
# hmm_covariance_floor (1e-6) is calibrated for DAY-scale features; intraday
# log-return and volatility feature variances sit orders of magnitude lower,
# so the regime model can never become ready on 5m/15m/1h windows with the
# default. The floor still rejects genuinely constant features. This explicit
# configuration is fingerprinted into every report; the accepted trend/regime
# strategy simulation keeps the unmodified default configuration.
INTRADAY_CONTEXT_CONFIGURATION = StrategyConfiguration(hmm_covariance_floor=1e-12)
INTRADAY_CONTEXT_WINDOW = 300


def _strategies() -> tuple[SimulatedStrategy, ...]:
    pullback = TrendPullbackConfiguration()
    breakout = VolatilityBreakoutConfiguration()
    ranging = RangeMeanReversionConfiguration()
    donchian = DonchianBreakoutConfiguration()
    return (
        SimulatedStrategy(
            evaluator=TrendPullbackEvaluator(pullback),
            maximum_holding_bars=pullback.maximum_holding_bars,
            configuration_fingerprint=pullback.fingerprint,
        ),
        SimulatedStrategy(
            evaluator=VolatilityBreakoutEvaluator(breakout),
            maximum_holding_bars=breakout.maximum_holding_bars,
            configuration_fingerprint=breakout.fingerprint,
        ),
        SimulatedStrategy(
            evaluator=RangeMeanReversionEvaluator(ranging),
            maximum_holding_bars=ranging.maximum_holding_bars,
            configuration_fingerprint=ranging.fingerprint,
        ),
        SimulatedStrategy(
            evaluator=DonchianBreakoutEvaluator(donchian),
            maximum_holding_bars=donchian.maximum_holding_bars,
            configuration_fingerprint=donchian.fingerprint,
        ),
    )


def strategy_configuration_fingerprints() -> dict[str, str]:
    return {
        "trend-pullback-v1": TrendPullbackConfiguration().fingerprint,
        "volatility-breakout": VolatilityBreakoutConfiguration().fingerprint,
        "range-mean-reversion": RangeMeanReversionConfiguration().fingerprint,
        "donchian-breakout": DonchianBreakoutConfiguration().fingerprint,
        "trend-regime-v1": StrategyConfiguration().fingerprint,
    }


def _costs() -> SimulationCosts:
    return SimulationCosts()


def _boundaries(path: str | None) -> StageBoundaries:
    if path is None:
        return DEFAULT_BOUNDARIES
    return StageBoundaries.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _trades_path(evidence: Path, stage: str, pair: str, timeframe: str) -> Path:
    return evidence / "trades" / stage / f"{pair}_{timeframe}.jsonl"


def _run_simulate(args: argparse.Namespace) -> int:
    boundaries = _boundaries(args.boundaries)
    epic, instrument = PAIR_EPICS[args.pair]
    evidence = Path(args.evidence)
    final_stage = bool(args.final_test)
    if final_stage:
        lock = read_lock(Path(args.lock))
        if lock.boundaries != boundaries:
            raise SystemExit("final-test lock boundaries do not match the requested run")
        evaluation_start = boundaries.final_test_start
        evaluation_end = boundaries.final_test_end
        stage_label = "final_test"
    else:
        evaluation_start = boundaries.development_start
        evaluation_end = boundaries.validation_end
        stage_label = "development_validation"
    started = datetime.now(tz=UTC)
    for timeframe in args.timeframes:
        resolution = TIMEFRAME_RESOLUTIONS[timeframe]
        bars = load_bars(Path(args.bars_root) / f"{args.pair}_{timeframe}.csv", epic=epic)
        builder = CausalContextBuilder(
            epic=epic,
            instrument=instrument,
            resolution=resolution,
            strategy_configuration=INTRADAY_CONTEXT_CONFIGURATION,
            window_size=INTRADAY_CONTEXT_WINDOW,
        )
        results = simulate_strategies(
            _strategies(),
            bars,
            builder=builder,
            costs=_costs(),
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
            trade_prefix=f"{args.pair}-{timeframe}",
        )
        all_trades: list[ValidationTrade] = []
        counters = {}
        for outcome in results:
            all_trades.extend(outcome.trades)
            counters[outcome.strategy_id] = {
                "candidate_count": outcome.candidate_count,
                "rejection_count": outcome.rejection_count,
                "evaluation_count": outcome.evaluation_count,
                "forced_exit_count": outcome.forced_exit_count,
                "session_closed_skips": outcome.session_closed_skips,
                "trade_count": len(outcome.trades),
                "rejection_reasons": dict(outcome.rejection_reasons),
            }
        ordered = tuple(sorted(all_trades, key=lambda item: (item.entry_at, item.trade_id)))
        path = _trades_path(evidence, stage_label, args.pair, timeframe)
        digest = serialize_trades(ordered, path)
        counts_path = path.with_suffix(".counts.json")
        counts_path.write_text(
            json.dumps(
                {
                    "pair": args.pair,
                    "timeframe": timeframe,
                    "stage": stage_label,
                    "bars": len(bars),
                    "trades_fingerprint": digest,
                    "started_at": started.isoformat(),
                    "finished_at": datetime.now(tz=UTC).isoformat(),
                    "counters": counters,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"{args.pair} {timeframe} {stage_label}: {len(ordered)} trades -> {path}")
    return 0


def _run_simulate_trend(args: argparse.Namespace) -> int:
    boundaries = _boundaries(args.boundaries)
    epic, instrument = PAIR_EPICS[args.pair]
    evidence = Path(args.evidence)
    if args.final_test:
        read_lock(Path(args.lock))
        evaluation_start = boundaries.final_test_start
        evaluation_end = boundaries.final_test_end
        stage_label = "final_test"
    else:
        evaluation_start = boundaries.development_start
        evaluation_end = boundaries.validation_end
        stage_label = "development_validation"
    bars = load_bars(Path(args.bars_root) / f"{args.pair}_DAY.csv", epic=epic)
    trades = simulate_trend_regime_day(
        bars,
        epic=epic,
        instrument=instrument,
        costs=_costs(),
        evaluation_start=evaluation_start,
        evaluation_end=evaluation_end,
        trade_prefix=f"{args.pair}-DAY-trend-regime",
    )
    path = _trades_path(evidence, stage_label, args.pair, "DAY_TREND")
    digest = serialize_trades(trades, path)
    print(f"{args.pair} DAY trend-regime {stage_label}: {len(trades)} trades ({digest[:12]})")
    return 0


def _load_stage_trades(evidence: Path, stage: str) -> dict[str, tuple[ValidationTrade, ...]]:
    by_strategy: dict[str, list[ValidationTrade]] = {}
    stage_dir = evidence / "trades" / stage
    if not stage_dir.is_dir():
        raise SystemExit(f"no simulated evidence found under {stage_dir}")
    for path in sorted(stage_dir.glob("*.jsonl")):
        for trade in load_trades(path):
            by_strategy.setdefault(trade.strategy_id, []).append(trade)
    return {
        name: tuple(sorted(values, key=lambda item: (item.entry_at, item.trade_id)))
        for name, values in by_strategy.items()
    }


def _counters_total(evidence: Path, stage: str, strategy_id: str) -> tuple[int, int]:
    rejections = candidates = 0
    for path in sorted((evidence / "trades" / stage).glob("*.counts.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        entry = payload.get("counters", {}).get(strategy_id)
        if entry:
            rejections += entry["rejection_count"]
            candidates += entry["candidate_count"]
    return rejections, candidates


def _run_report(args: argparse.Namespace) -> int:
    boundaries = _boundaries(args.boundaries)
    evidence = Path(args.evidence)
    manifest = json.loads(Path(args.dataset_manifest).read_text(encoding="utf-8"))
    dataset_fingerprint = manifest["dataset_fingerprint"]
    fingerprints = strategy_configuration_fingerprints()
    gates = ValidationGates()
    created = datetime.now(tz=UTC)
    by_strategy = _load_stage_trades(evidence, "development_validation")
    reports_dir = evidence / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {}
    for strategy_id in STRATEGY_IDS:
        trades = by_strategy.get(strategy_id, ())
        development = trades_in_range(
            trades, boundaries.development_start, boundaries.development_end
        )
        validation = trades_in_range(trades, boundaries.validation_start, boundaries.validation_end)
        rejections, candidates = _counters_total(evidence, "development_validation", strategy_id)
        walk_forward = walk_forward_validate(
            strategy_id,
            build_walk_forward(strategy_id, validation, boundaries, fingerprints[strategy_id]),
        )
        stresses = stress_bundle(strategy_id, validation, EXECUTION_DEGRADATION)
        validation_metrics = calculate_metrics(
            validation, rejection_count=rejections, candidate_count=candidates
        )
        failed = evaluate_extended_gates(
            validation_metrics,
            gates,
            walk_forward_profitable_fraction=walk_forward.profitable_window_fraction,
            walk_forward_window_count=len(walk_forward.windows),
            parameter_instability=walk_forward.parameter_instability,
            cost_results=stresses.cost,
            trades=validation,
        )
        development_report = build_report(
            strategy_id=strategy_id,
            strategy_version="1.0.0",
            stage=ValidationStage.DEVELOPMENT,
            dataset_fingerprint=dataset_fingerprint,
            boundaries=boundaries,
            configuration_fingerprint=fingerprints[strategy_id],
            trades=development,
            rejection_count=0,
            candidate_count=0,
            failed_gates=(),
            gates=gates,
            data_quality_findings=(),
            final_test_locked_before_evaluation=False,
            created_at=created,
        )
        validation_report = build_report(
            strategy_id=strategy_id,
            strategy_version="1.0.0",
            stage=ValidationStage.VALIDATION,
            dataset_fingerprint=dataset_fingerprint,
            boundaries=boundaries,
            configuration_fingerprint=fingerprints[strategy_id],
            trades=validation,
            rejection_count=rejections,
            candidate_count=candidates,
            failed_gates=failed,
            gates=gates,
            data_quality_findings=(),
            final_test_locked_before_evaluation=False,
            created_at=created,
        )
        document = {
            "development_report": json.loads(development_report.model_dump_json()),
            "validation_report": json.loads(validation_report.model_dump_json()),
            "walk_forward": json.loads(walk_forward.model_dump_json()),
            "cost_stress": [json.loads(item.model_dump_json()) for item in stresses.cost],
            "execution_stress": json.loads(stresses.execution.model_dump_json()),
            "robustness": [json.loads(item.model_dump_json()) for item in stresses.robustness],
        }
        out = reports_dir / f"{strategy_id}.json"
        out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary[strategy_id] = {
            "validation_trades": len(validation),
            "development_trades": len(development),
            "expectancy": str(validation_metrics.expectancy),
            "profit_factor": str(validation_metrics.profit_factor),
            "maximum_drawdown": str(validation_metrics.maximum_drawdown),
            "profitable_window_fraction": str(walk_forward.profitable_window_fraction),
            "failed_gates": list(failed),
            "validation_report_id": validation_report.validation_report_id,
        }
        print(f"{strategy_id}: trades={len(validation)} failed_gates={list(failed)}")
    (reports_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


def _run_lock(args: argparse.Namespace) -> int:
    boundaries = _boundaries(args.boundaries)
    evidence = Path(args.evidence)
    manifest = json.loads(Path(args.dataset_manifest).read_text(encoding="utf-8"))
    summary = json.loads((evidence / "reports" / "summary.json").read_text(encoding="utf-8"))
    fingerprints = strategy_configuration_fingerprints()
    lock = create_final_test_lock(
        dataset_fingerprint=manifest["dataset_fingerprint"],
        boundaries=boundaries,
        strategy_ids=tuple(STRATEGY_IDS),
        configuration_fingerprints=tuple((name, fingerprints[name]) for name in STRATEGY_IDS),
        validation_report_ids=tuple(
            (name, summary[name]["validation_report_id"]) for name in STRATEGY_IDS
        ),
        locked_at=datetime.now(tz=UTC),
        locked_by=args.locked_by,
    )
    write_lock(lock, Path(args.lock))
    print(f"final-test lock created: {lock.lock_id}")
    return 0


def _run_final_report(args: argparse.Namespace) -> int:
    boundaries = _boundaries(args.boundaries)
    evidence = Path(args.evidence)
    lock = read_lock(Path(args.lock))
    manifest = json.loads(Path(args.dataset_manifest).read_text(encoding="utf-8"))
    if lock.dataset_fingerprint != manifest["dataset_fingerprint"]:
        raise SystemExit("final-test lock does not match the dataset manifest")
    fingerprints = strategy_configuration_fingerprints()
    gates = ValidationGates()
    created = datetime.now(tz=UTC)
    by_strategy = _load_stage_trades(evidence, "final_test")
    reports_dir = evidence / "reports"
    summary: dict[str, object] = {}
    for strategy_id in STRATEGY_IDS:
        trades = by_strategy.get(strategy_id, ())
        rejections, candidates = _counters_total(evidence, "final_test", strategy_id)
        metrics = calculate_metrics(trades, rejection_count=rejections, candidate_count=candidates)
        failed = tuple(
            item
            for item in (
                "POSITIVE_EXPECTANCY"
                if metrics.expectancy is None or metrics.expectancy <= 0
                else None,
            )
            if item is not None
        )
        report = build_report(
            strategy_id=strategy_id,
            strategy_version="1.0.0",
            stage=ValidationStage.FINAL_TEST,
            dataset_fingerprint=lock.dataset_fingerprint,
            boundaries=boundaries,
            configuration_fingerprint=fingerprints[strategy_id],
            trades=trades,
            rejection_count=rejections,
            candidate_count=candidates,
            failed_gates=failed,
            gates=gates,
            data_quality_findings=(),
            final_test_locked_before_evaluation=True,
            created_at=created,
        )
        out = reports_dir / f"{strategy_id}.final_test.json"
        out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        summary[strategy_id] = {
            "final_test_trades": len(trades),
            "expectancy": str(metrics.expectancy),
            "profit_factor": str(metrics.profit_factor),
            "net_return": str(metrics.net_return),
            "maximum_drawdown": str(metrics.maximum_drawdown),
            "final_report_id": report.validation_report_id,
        }
        print(f"{strategy_id}: final-test trades={len(trades)} expectancy={metrics.expectancy}")
    (reports_dir / "final_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


def _run_manifest(args: argparse.Namespace) -> int:
    boundaries = _boundaries(args.boundaries)
    document = dataset_manifest_document(
        summary_path=Path(args.download_summary),
        boundaries=boundaries,
        costs=_costs(),
        approved_by=args.approved_by,
        approved_at=datetime.now(tz=UTC),
        timeframes=tuple(args.timeframes) + ("DAY",),
        notes=(
            "Scheduled economic events and holiday calendars were not simulated: no "
            "authoritative historical calendar source was approved for this dataset. "
            "Session, liquidity, spread, volatility, trend, range, compression, and "
            "breakout context states are fully simulated from the price series.",
            "Weekend and holiday closures are represented by the absence of bars and "
            "by the DST-aware session classifier.",
            "HMM regime parameters are refitted every 120 completed bars on a "
            "400-bar trailing window; between refits the latest strictly-older fit "
            "is reused (bounded-stale, causal).",
            "MINUTE_5 bars are generated and fingerprinted but were not simulated in "
            "this validation round; MINUTE_5 remains unvalidated for the new "
            "strategy families.",
        ),
    )
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"dataset manifest written: {document['dataset_fingerprint']}")
    return 0


def _run_portfolio(args: argparse.Namespace) -> int:
    evidence = Path(args.evidence)
    by_strategy = _load_stage_trades(evidence, "development_validation")
    boundaries = _boundaries(args.boundaries)
    all_validation: list[ValidationTrade] = []
    for trades in by_strategy.values():
        all_validation.extend(
            trades_in_range(trades, boundaries.validation_start, boundaries.validation_end)
        )
    combined = tuple(sorted(all_validation, key=lambda item: (item.entry_at, item.trade_id)))
    contributions = {
        strategy_id: json.loads(portfolio_contribution(strategy_id, combined).model_dump_json())
        for strategy_id in STRATEGY_IDS
    }
    scenarios = [json.loads(item.model_dump_json()) for item in portfolio_ablation(combined)]
    document = {
        "validation_trades": len(combined),
        "strategies_present": sorted({item.strategy_id for item in combined}),
        "contributions": contributions,
        "ablation_scenarios": scenarios,
    }
    out = evidence / "reports" / "portfolio.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"portfolio evidence written for {len(combined)} trades -> {out}")
    return 0


_DECISION_STATES = {
    "PROMOTE_TO_BACKTEST_VALIDATED": "BACKTEST_VALIDATED",
    "PROMOTE_TO_DEMO_EXPLORATION": "DEMO_EXPLORATION_ENABLED",
    "REMAIN_RESEARCH_ONLY": "RESEARCH_ONLY",
    "DISABLE": "DISABLED",
}


def _run_seal(args: argparse.Namespace) -> int:
    evidence = Path(args.evidence)
    manifest = json.loads(Path(args.dataset_manifest).read_text(encoding="utf-8"))
    strategy_id = args.strategy
    report_document = json.loads(
        (evidence / "reports" / f"{strategy_id}.json").read_text(encoding="utf-8")
    )
    final_path = evidence / "reports" / f"{strategy_id}.final_test.json"
    final_document = (
        json.loads(final_path.read_text(encoding="utf-8"))
        if final_path.is_file()
        else {"status": "NOT_RUN", "reason": "final test requires passed validation gates"}
    )
    portfolio_document = json.loads(
        (evidence / "reports" / "portfolio.json").read_text(encoding="utf-8")
    )
    failed_gates = tuple(report_document["validation_report"]["failed_gates"])
    if args.decision in {"PROMOTE_TO_BACKTEST_VALIDATED", "PROMOTE_TO_DEMO_EXPLORATION"}:
        if failed_gates:
            raise SystemExit(
                f"failed validation gates prohibit promotion: {', '.join(failed_gates)}"
            )
        if not final_path.is_file():
            raise SystemExit("promotion requires completed locked final-test evidence")
    configurations = {
        "trend-pullback-v1": TrendPullbackConfiguration(),
        "volatility-breakout": VolatilityBreakoutConfiguration(),
        "range-mean-reversion": RangeMeanReversionConfiguration(),
    }
    configuration = configurations[strategy_id]
    decided_at = datetime.now(tz=UTC)
    promotion = {
        "approver": args.approver,
        "automatic_promotion": False,
        "decision": args.decision,
        "previous_state": "RESEARCH_ONLY",
        "new_state": _DECISION_STATES[args.decision],
        "decided_at": decided_at.isoformat(),
        "failed_gates": list(failed_gates),
        "validation_report_id": report_document["validation_report"]["validation_report_id"],
        "final_test_report_id": final_document.get("validation_report_id"),
        "notes": args.notes,
    }
    summary_lines = [
        f"# {strategy_id} {args.version} validation summary",
        "",
        f"- Decision: {args.decision} (approver: {args.approver}, automatic: false)",
        f"- Validation trades: {report_document['validation_report']['metrics']['trade_count']}",
        f"- Failed gates: {', '.join(failed_gates) if failed_gates else 'none'}",
        f"- Dataset fingerprint: {manifest['dataset_fingerprint']}",
        f"- Sealed at: {decided_at.isoformat()}",
    ]
    documents: dict[str, object] = {
        "configuration.json": json.loads(configuration.model_dump_json())
        | {"configuration_fingerprint": configuration.fingerprint},
        "dataset_manifest.json": manifest,
        "development_results.json": report_document["development_report"],
        "validation_results.json": report_document["validation_report"],
        "final_test_results.json": final_document,
        "walk_forward_results.json": report_document["walk_forward"],
        "cost_stress_results.json": {
            "cost": report_document["cost_stress"],
            "execution": report_document["execution_stress"],
        },
        "robustness_results.json": report_document["robustness"],
        "portfolio_results.json": portfolio_document,
        "promotion_decision.json": promotion,
        "summary.md": "\n".join(summary_lines),
    }
    target = Path(args.artifacts_root) / f"{strategy_id}-{args.version}"
    sealed = build_artifact_package(
        target,
        strategy_id=strategy_id,
        strategy_version=args.version,
        dataset_fingerprint=manifest["dataset_fingerprint"],
        configuration_fingerprint=configuration.fingerprint,
        documents=documents,
        created_at=decided_at,
    )
    print(f"sealed {strategy_id}: artifact {sealed.artifact_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="validation-cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    manifest = commands.add_parser("manifest", help="Freeze the governed dataset manifest")
    manifest.add_argument("--download-summary", required=True)
    manifest.add_argument("--output", required=True)
    manifest.add_argument("--approved-by", required=True)
    manifest.add_argument("--boundaries")
    manifest.add_argument("--timeframes", nargs="*", default=list(TIMEFRAME_RESOLUTIONS))
    manifest.set_defaults(handler=_run_manifest)

    simulate = commands.add_parser("simulate", help="Simulate portfolio strategies for one pair")
    simulate.add_argument("--pair", required=True, choices=sorted(PAIR_EPICS))
    simulate.add_argument("--bars-root", required=True)
    simulate.add_argument("--evidence", required=True)
    simulate.add_argument("--timeframes", nargs="*", default=list(TIMEFRAME_RESOLUTIONS))
    simulate.add_argument("--boundaries")
    simulate.add_argument("--final-test", action="store_true")
    simulate.add_argument("--lock")
    simulate.set_defaults(handler=_run_simulate)

    trend = commands.add_parser(
        "simulate-trend", help="Simulate the accepted trend strategy on daily bars"
    )
    trend.add_argument("--pair", required=True, choices=sorted(PAIR_EPICS))
    trend.add_argument("--bars-root", required=True)
    trend.add_argument("--evidence", required=True)
    trend.add_argument("--boundaries")
    trend.add_argument("--final-test", action="store_true")
    trend.add_argument("--lock")
    trend.set_defaults(handler=_run_simulate_trend)

    report = commands.add_parser("report", help="Aggregate evidence and evaluate gates")
    report.add_argument("--evidence", required=True)
    report.add_argument("--dataset-manifest", required=True)
    report.add_argument("--boundaries")
    report.set_defaults(handler=_run_report)

    lock = commands.add_parser("lock", help="Create the immutable final-test lock")
    lock.add_argument("--evidence", required=True)
    lock.add_argument("--dataset-manifest", required=True)
    lock.add_argument("--lock", required=True)
    lock.add_argument("--locked-by", required=True)
    lock.add_argument("--boundaries")
    lock.set_defaults(handler=_run_lock)

    final = commands.add_parser("final-report", help="Final-test reports (requires lock)")
    final.add_argument("--evidence", required=True)
    final.add_argument("--dataset-manifest", required=True)
    final.add_argument("--lock", required=True)
    final.add_argument("--boundaries")
    final.set_defaults(handler=_run_final_report)

    portfolio = commands.add_parser(
        "portfolio", help="Portfolio contribution and ablation evidence"
    )
    portfolio.add_argument("--evidence", required=True)
    portfolio.add_argument("--boundaries")
    portfolio.set_defaults(handler=_run_portfolio)

    seal = commands.add_parser(
        "seal", help="Seal one strategy's artifact package with a human decision"
    )
    seal.add_argument("--evidence", required=True)
    seal.add_argument("--dataset-manifest", required=True)
    seal.add_argument("--artifacts-root", required=True)
    seal.add_argument("--strategy", required=True, choices=STRATEGY_IDS)
    seal.add_argument("--version", default="1.0.0")
    seal.add_argument("--decision", required=True, choices=sorted(_DECISION_STATES))
    seal.add_argument("--approver", required=True)
    seal.add_argument("--notes", default="")
    seal.set_defaults(handler=_run_seal)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = args.handler
    return int(handler(args))


if __name__ == "__main__":
    sys.exit(main())
