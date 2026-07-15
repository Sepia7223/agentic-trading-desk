"""Safe command-line interface for read-only IG demo inspection."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from trading_desk.backtest.comparison import (
    compare_variants,
    evaluate_final_test,
    freeze_selection,
)
from trading_desk.backtest.configuration import (
    BacktestConfiguration,
    FrozenSelection,
    SplitConfiguration,
)
from trading_desk.backtest.data import load_dataset
from trading_desk.backtest.engine import BacktestEngine
from trading_desk.backtest.reports import export_json, export_markdown, export_trades_csv
from trading_desk.config import AppSettings
from trading_desk.ig import IGDemoClient, PriceResolution
from trading_desk.ig.errors import IGError
from trading_desk.ig.models import (
    Account,
    HistoricalPricePage,
    MarketDetails,
    MarketSearchResult,
    OpenPosition,
)
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.data_validation import market_data_from_ig_page
from trading_desk.strategy.models import (
    StrategyBarResolution,
    StrategyContext,
    StrategyVariant,
    TradeCandidate,
)
from trading_desk.strategy.pipeline import RegimeAwareStrategyPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ig-trader", description="Read-only IG demo tools")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("config-check", help="Validate the local read-only configuration")

    ig_parser = subcommands.add_parser("ig", help="Read-only IG demo operations")
    ig_commands = ig_parser.add_subparsers(dest="ig_command", required=True)
    ig_commands.add_parser("accounts", help="List accounts")
    ig_commands.add_parser("positions", help="List open positions")

    search = ig_commands.add_parser("search-market", help="Search IG markets")
    search.add_argument("search_term")

    market = ig_commands.add_parser("market", help="Show IG market details")
    market.add_argument("epic")

    prices = ig_commands.add_parser("prices", help="Show normalized historical prices")
    prices.add_argument("epic")
    prices.add_argument(
        "--resolution",
        choices=[resolution.value for resolution in PriceResolution],
        default=PriceResolution.DAY.value,
    )
    prices.add_argument("--max-points", type=int, default=20)
    prices.add_argument("--page-number", type=int, default=1)

    strategy_parser = subcommands.add_parser("strategy", help="Deterministic analysis only")
    strategy_commands = strategy_parser.add_subparsers(dest="strategy_command", required=True)
    analyze = strategy_commands.add_parser("analyze", help="Analyze the latest cutoff")
    analyze.add_argument("epic")
    analyze.add_argument("--macro-score", type=int, choices=range(-2, 3))

    walk_forward = strategy_commands.add_parser(
        "walk-forward", help="Refit and evaluate one historical cutoff at a time"
    )
    walk_forward.add_argument("epic")
    walk_forward.add_argument("--start-index", type=int, required=True)
    walk_forward.add_argument("--end-index", type=int, required=True)
    walk_forward.add_argument("--macro-score", type=int, choices=range(-2, 3))

    backtest_parser = subcommands.add_parser("backtest", help="Local simulation only")
    backtest_commands = backtest_parser.add_subparsers(dest="backtest_command", required=True)
    for command_name in ("run", "compare"):
        command = backtest_commands.add_parser(command_name)
        command.add_argument("--data", required=True)
        command.add_argument("--epic", required=True)
        command.add_argument(
            "--resolution",
            choices=[item.value for item in StrategyBarResolution],
            default=StrategyBarResolution.DAY.value,
        )
        command.add_argument("--train-end", required=True)
        command.add_argument("--validation-end", required=True)
        command.add_argument("--test-end", required=True)
    run = backtest_commands.choices["run"]
    run.add_argument(
        "--variant",
        choices=[item.value for item in StrategyVariant],
        default=StrategyVariant.BASELINE_KALMAN_HMM.value,
    )
    run.add_argument("--output-json")
    run.add_argument("--output-csv")
    run.add_argument("--output-markdown")
    compare = backtest_commands.choices["compare"]
    compare.add_argument(
        "--variants",
        nargs="+",
        choices=[item.value for item in StrategyVariant],
        default=[item.value for item in StrategyVariant],
    )
    compare.add_argument("--freeze-variant", choices=[item.value for item in StrategyVariant])
    compare.add_argument("--selection-rationale")
    compare.add_argument("--selection-output")
    final_test = backtest_commands.add_parser("final-test")
    final_test.add_argument("--data", required=True)
    final_test.add_argument("--selection", required=True)
    final_test.add_argument("--output-json")
    final_test.add_argument("--output-csv")
    final_test.add_argument("--output-markdown")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "backtest":
        _print_backtest_header()
        try:
            return _run_backtest_command(args)
        except (OSError, ValidationError, ValueError) as error:
            print(f"Backtest error: {error}", file=sys.stderr)
            return 2
    try:
        settings = AppSettings.from_environment()
    except (ValidationError, ValueError) as error:
        print("Environment: DEMO")
        print("Mode: READ_ONLY")
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    _print_safety_header()
    if args.command == "config-check":
        return _config_check(settings)

    try:
        if args.command == "ig":
            return asyncio.run(_run_ig_command(settings, args))
        if args.command == "strategy":
            return asyncio.run(_run_strategy_command(settings, args))
        raise ValueError("unsupported read-only command")
    except (IGError, ValidationError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


def _print_safety_header() -> None:
    print("Environment: DEMO")
    print("Mode: READ_ONLY")
    print("Execution: UNAVAILABLE")


def _print_backtest_header() -> None:
    print("Mode: BACKTEST")
    print("Execution: SIMULATED ONLY")
    print("Live trading: DISABLED")


def _run_backtest_command(args: argparse.Namespace) -> int:
    if args.backtest_command == "final-test":
        selection = FrozenSelection.model_validate_json(
            Path(args.selection).read_text(encoding="utf-8")
        )
        dataset = load_dataset(args.data, selection.backtest_configuration.resolution)
        final_report = evaluate_final_test(dataset, selection)
        run = final_report.run
        print("Report: FINAL_TEST")
        print(f"Selection: {final_report.selection_identifier}")
        _print_backtest_run(run, "Final test")
        _export_backtest_run(run, args)
        return 0

    resolution = StrategyBarResolution(args.resolution)
    dataset = load_dataset(args.data, resolution)
    splits = SplitConfiguration(
        train_end=_date_boundary(args.train_end),
        validation_end=_date_boundary(args.validation_end),
        test_end=_date_boundary(args.test_end),
    )
    variant = (
        StrategyVariant(args.variant)
        if args.backtest_command == "run"
        else StrategyVariant.BASELINE_KALMAN_HMM
    )
    configuration = BacktestConfiguration(
        dataset_source=Path(args.data).name,
        epic=args.epic,
        resolution=resolution,
        splits=splits,
        variant=variant,
    )
    if args.backtest_command == "run":
        run = BacktestEngine(configuration).run(dataset)
        _print_backtest_run(run, "Validation")
        _export_backtest_run(run, args)
    elif args.backtest_command == "compare":
        variants = tuple(StrategyVariant(value) for value in args.variants)
        runs, comparison = compare_variants(dataset, configuration, variants=variants)
        print(f"Baseline control: {comparison.baseline_variant.value}")
        print("Report: VALIDATION_ONLY")
        for variant_name, validation_return, drawdown, count in zip(
            comparison.variants,
            comparison.validation_net_returns,
            comparison.validation_maximum_drawdowns,
            comparison.validation_trade_counts,
            strict=True,
        ):
            print(
                f"- {variant_name.value}: validation={validation_return:.6f}"
                f" drawdown={drawdown:.6f} trades={count}"
            )
        freeze_values = (
            args.freeze_variant,
            args.selection_rationale,
            args.selection_output,
        )
        if any(freeze_values) and not all(freeze_values):
            raise ValueError(
                "freezing requires --freeze-variant, --selection-rationale, and --selection-output"
            )
        if all(freeze_values):
            selection = freeze_selection(
                runs,
                comparison,
                configuration,
                StrategyVariant(args.freeze_variant),
                selection_rationale=args.selection_rationale,
            )
            Path(args.selection_output).write_text(
                selection.model_dump_json(indent=2),
                encoding="utf-8",
            )
            print(f"Frozen selection: {selection.selection_identifier}")
    else:
        raise ValueError("unsupported backtest command")
    return 0


def _print_backtest_run(run, label: str) -> None:  # type: ignore[no-untyped-def]
    print(f"Variant: {run.variant.value}")
    print(f"Run fingerprint: {run.run_fingerprint}")
    print(f"{label} net return: {run.metrics.net_return:.6f}")
    print(f"Maximum drawdown: {run.metrics.maximum_drawdown:.6f}")
    print(f"Trades: {run.metrics.trade_count}")
    print(f"Unresolved positions: {len(run.unresolved_positions)}")


def _export_backtest_run(run, args: argparse.Namespace) -> None:  # type: ignore[no-untyped-def]
    if args.output_json:
        export_json(run, args.output_json)
    if args.output_csv:
        export_trades_csv(run, args.output_csv)
    if args.output_markdown:
        export_markdown(run, args.output_markdown)


def _date_boundary(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)


def _config_check(settings: AppSettings) -> int:
    credentials = {
        "IG_IDENTIFIER": settings.broker.identifier,
        "IG_PASSWORD": settings.broker.password,
        "IG_API_KEY": settings.broker.api_key,
    }
    missing = [name for name, value in credentials.items() if value is None]
    print(f"IG base URL: {settings.broker.base_url}")
    print(f"Request timeout: {settings.broker.request_timeout_seconds:g}s")
    print(f"Historical point limit: {settings.broker.max_historical_price_points}")
    print(f"OAuth expiry safety margin: {settings.broker.oauth_expiry_safety_margin_seconds:g}s")
    print(f"Credentials configured: {'no' if missing else 'yes'}")
    if missing:
        print(f"Missing: {', '.join(missing)}")
    print("Order execution: unavailable")
    return 0


async def _run_ig_command(settings: AppSettings, args: argparse.Namespace) -> int:
    async with IGDemoClient(settings) as client:
        if args.ig_command == "accounts":
            _print_accounts(await client.get_accounts())
        elif args.ig_command == "positions":
            _print_positions(await client.get_open_positions())
        elif args.ig_command == "search-market":
            _print_market_results(await client.search_markets(args.search_term))
        elif args.ig_command == "market":
            _print_market_details(await client.get_market_details(args.epic))
        elif args.ig_command == "prices":
            page = await client.get_historical_prices(
                args.epic,
                resolution=PriceResolution(args.resolution),
                max_points=args.max_points,
                page_number=args.page_number,
            )
            _print_prices(page)
        else:
            raise ValueError("unsupported read-only command")
    return 0


async def _run_strategy_command(settings: AppSettings, args: argparse.Namespace) -> int:
    strategy_config = StrategyConfiguration()
    requested_points = min(
        settings.broker.max_historical_price_points,
        max(strategy_config.minimum_bars_required, 500),
    )
    async with IGDemoClient(settings) as client:
        market = await client.get_market_details(args.epic)
        positions = await client.get_open_positions()
        page = await client.get_historical_prices(
            market.epic,
            resolution=PriceResolution.DAY,
            max_points=requested_points,
            page_number=1,
        )
    retrieved_at = datetime.now(UTC)
    build = market_data_from_ig_page(
        page,
        epic=market.epic,
        instrument_name=market.instrument_name,
        market_status=market.market_status.value,
        data_retrieval_time=retrieved_at,
        bar_resolution=StrategyBarResolution.DAY,
    )
    if build.data is None:
        print("Action: NO_TRADE")
        for finding in build.findings:
            print(f"- rejection: {finding.code.value}: {finding.message}")
        return 0
    spread = (
        float(market.offer - market.bid)
        if market.bid is not None and market.offer is not None
        else build.data.spreads[-1]
    )
    if market.bid is not None and market.offer is not None:
        midpoint = float((market.bid + market.offer) / 2)
        spread_bps = 10_000.0 * spread / midpoint
    else:
        spread_bps = build.data.spread_bps[-1]
    holding = any(position.market.epic == market.epic for position in positions)
    context = StrategyContext(
        holding=holding,
        macro_score=args.macro_score,
        current_spread=spread,
        current_spread_bps=spread_bps,
        market_status=market.market_status.value,
        current_time=retrieved_at,
        account_exposure_summary=f"open positions reviewed: {len(positions)}",
    )
    pipeline = RegimeAwareStrategyPipeline(strategy_config)
    if args.strategy_command == "analyze":
        candidate = pipeline.analyze_latest(
            build.data,
            context,
            inherited_findings=build.findings,
        )
        _print_strategy_candidate(candidate)
    elif args.strategy_command == "walk-forward":
        candidates = pipeline.walk_forward(
            build.data,
            context,
            start_index=args.start_index,
            end_index=args.end_index,
        )
        print(f"Walk-forward evaluations: {len(candidates)}")
        for candidate in candidates:
            print(
                f"- {candidate.evaluation_timestamp.isoformat()} | {candidate.action.value}"
                f" | {candidate.current_regime.value}"
            )
    else:
        raise ValueError("unsupported strategy command")
    return 0


def _print_accounts(accounts: tuple[Account, ...]) -> None:
    print(f"Accounts: {len(accounts)}")
    for account in accounts:
        preferred = " preferred" if account.preferred else ""
        print(
            f"- {_redact_account_id(account.account_id)} | {account.account_name}"
            f" | {account.account_type.value}"
            f"{preferred} | {account.currency} | balance={_money(account.balance.balance)}"
            f" | available={_money(account.balance.available_funds)}"
        )


def _print_positions(positions: tuple[OpenPosition, ...]) -> None:
    print(f"Open positions: {len(positions)}")
    for position in positions:
        print(
            f"- {position.market.epic} | {position.direction.value} {position.size}"
            f" | open={position.opening_level} | bid={_optional_decimal(position.market.bid)}"
            f" | offer={_optional_decimal(position.market.offer)}"
            f" | status={position.market.market_status.value}"
        )


def _print_market_results(markets: tuple[MarketSearchResult, ...]) -> None:
    print(f"Markets: {len(markets)}")
    for market in markets:
        print(
            f"- {market.epic} | {market.instrument_name} | {market.instrument_type.value}"
            f" | {market.market_status.value} | bid={_optional_decimal(market.bid)}"
            f" | offer={_optional_decimal(market.offer)}"
        )


def _print_market_details(market: MarketDetails) -> None:
    print(f"EPIC: {market.epic}")
    print(f"Instrument: {market.instrument_name}")
    print(f"Type: {market.instrument_type.value}")
    print(f"Status: {market.market_status.value}")
    print(f"Bid/offer: {_optional_decimal(market.bid)} / {_optional_decimal(market.offer)}")
    updated = market.update_time.isoformat() if market.update_time is not None else "unavailable"
    print(f"Updated: {updated}")


def _print_prices(page: HistoricalPricePage) -> None:
    print(
        f"Page: {page.pagination.page_number}/{page.pagination.total_pages}"
        f" | page size={page.pagination.page_size}"
    )
    print(
        f"Allowance: {page.allowance.remaining_allowance}/{page.allowance.total_allowance}"
        f" | resets in {page.allowance.allowance_expiry_seconds}s"
    )
    print(f"Bars: {len(page.bars)} | strategy-ready: {len(page.strategy_ready_closes)}")
    for bar in page.bars:
        close = _optional_decimal(bar.midpoint_close)
        status = "ready" if bar.valid_for_strategy else f"invalid: {bar.validation_reason}"
        print(f"- {bar.timestamp.isoformat()} | midpoint close={close} | {status}")


def _print_strategy_candidate(candidate: TradeCandidate) -> None:
    print(f"EPIC: {candidate.epic}")
    print(f"Variant: {candidate.strategy_variant.value}")
    print(
        f"Signal: {candidate.signal_timestamp.isoformat()}"
        f" | execution policy={candidate.execution_timing_policy.value}"
    )
    print(
        f"Baseline: trend={candidate.baseline_trend_score}"
        f" momentum={candidate.baseline_momentum_score}"
        f" macro={candidate.macro_score} total={candidate.total_baseline_score}"
    )
    print(
        f"Kalman: level={_optional_float(candidate.kalman_level)}"
        f" slope={_optional_float(candidate.kalman_slope)}"
        f" slope uncertainty={_optional_float(candidate.kalman_slope_uncertainty)}"
    )
    print(f"Spread: absolute={candidate.current_spread:.6g} bps={candidate.current_spread_bps:.3f}")
    probabilities = ", ".join(
        f"{item.regime.value}={item.probability:.3f}" for item in candidate.regime_probabilities
    )
    print(
        f"Regime: {candidate.current_regime.value} | {probabilities}"
        f" | uncertainty={candidate.regime_uncertainty:.3f}"
    )
    for gate in candidate.mandatory_gates:
        print(f"Gate {gate.name}: {'PASS' if gate.passed else 'FAIL'}")
    print(f"Action: {candidate.action.value}")
    for reason in candidate.rejection_reasons:
        print(f"- rejection: {reason}")
    print(f"Configuration: {candidate.configuration_fingerprint}")


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _optional_decimal(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _redact_account_id(account_id: str) -> str:
    return "***" if len(account_id) <= 4 else f"***{account_id[-4:]}"


def _optional_float(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.6g}"


if __name__ == "__main__":
    raise SystemExit(main())
