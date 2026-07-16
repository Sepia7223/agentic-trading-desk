"""Decimal-only simulated fill and cost calculations."""

from decimal import Decimal

from trading_desk.portfolio.config import PaperPortfolioConfiguration

BPS = Decimal("10000")


def entry_fill_price(
    ask: Decimal, configuration: PaperPortfolioConfiguration
) -> tuple[Decimal, Decimal]:
    slippage = ask * configuration.slippage_bps / BPS
    return ask + slippage, slippage


def exit_fill_price(
    bid: Decimal, configuration: PaperPortfolioConfiguration
) -> tuple[Decimal, Decimal]:
    slippage = bid * configuration.slippage_bps / BPS
    return bid - slippage, slippage


def commission(
    fill_price: Decimal, quantity: Decimal, configuration: PaperPortfolioConfiguration
) -> Decimal:
    return configuration.fixed_commission_per_fill + (
        fill_price * quantity * configuration.commission_bps / BPS
    )


def funding_charge(
    entry_price: Decimal,
    quantity: Decimal,
    value_per_price_unit: Decimal,
    elapsed_utc_days: int,
    configuration: PaperPortfolioConfiguration,
) -> Decimal:
    return (
        entry_price
        * quantity
        * value_per_price_unit
        * configuration.funding_bps_per_utc_day
        / BPS
        * elapsed_utc_days
    )
