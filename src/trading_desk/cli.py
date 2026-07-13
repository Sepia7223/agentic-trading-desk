"""Safe command-line interface for read-only IG demo inspection."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from decimal import Decimal

from pydantic import ValidationError

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
        return asyncio.run(_run_ig_command(settings, args))
    except (IGError, ValidationError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


def _print_safety_header() -> None:
    print("Environment: DEMO")
    print("Mode: READ_ONLY")


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


def _print_accounts(accounts: tuple[Account, ...]) -> None:
    print(f"Accounts: {len(accounts)}")
    for account in accounts:
        preferred = " preferred" if account.preferred else ""
        print(
            f"- {account.account_id} | {account.account_name} | {account.account_type.value}"
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


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _optional_decimal(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
