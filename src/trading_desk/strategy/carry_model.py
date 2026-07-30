"""Policy-rate carry proxy for FX research (offline, non-authoritative).

Real broker swap/rollover income is dominated by the short-term interest-rate
differential between the two currencies of a pair. This module encodes the
central-bank policy-rate path for each currency as a month-resolution step
function (public record; approximate to +/-0.25%) and derives a per-day carry
fraction for a LONG position in a pair.

Scope: RESEARCH ONLY. This is a *proxy* for carry, not a broker swap feed. It
grants no lifecycle/Demo/Risk/execution/Live authority and is deliberately kept
out of the Milestone 12 validation harness and its predetermined gates. It exists
so research can answer "does modelling carry income change the cost-robustness of
a positive-carry strategy?" without asserting a promotable cost model. A promotion
that depends on carry must use a real, dated, broker-sourced swap series.

Convention: for a LONG on BASE/QUOTE you earn BASE's rate and pay QUOTE's rate,
so gross annual carry = r_base - r_quote (percent). A conservative broker markup
(``markup_annual``) is subtracted from the favourable side (brokers keep a spread
on the tom-next rate), and the result is spread over a 360-day year.

Sources (policy rate paths, decision-month resolution): Federal Reserve target
range upper bound; Bank of Japan policy-rate balance; ECB deposit facility rate;
Bank of England Bank Rate; Reserve Bank of Australia cash rate; Bank of Canada
overnight rate. Encoded from the public rate-decision history 2019-01..2025-06.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

# Per-currency policy-rate path: (effective_date, rate_percent), ascending.
# Month-resolution; rate is the level in effect from that date until the next.
POLICY_RATES: dict[str, tuple[tuple[date, Decimal], ...]] = {
    "USD": (
        (date(2019, 1, 1), Decimal("2.50")),
        (date(2019, 8, 1), Decimal("2.25")),
        (date(2019, 9, 19), Decimal("2.00")),
        (date(2019, 10, 31), Decimal("1.75")),
        (date(2020, 3, 16), Decimal("0.25")),
        (date(2022, 3, 17), Decimal("0.50")),
        (date(2022, 5, 5), Decimal("1.00")),
        (date(2022, 6, 16), Decimal("1.75")),
        (date(2022, 7, 28), Decimal("2.50")),
        (date(2022, 9, 22), Decimal("3.25")),
        (date(2022, 11, 3), Decimal("4.00")),
        (date(2022, 12, 15), Decimal("4.50")),
        (date(2023, 2, 2), Decimal("4.75")),
        (date(2023, 3, 23), Decimal("5.00")),
        (date(2023, 5, 4), Decimal("5.25")),
        (date(2023, 7, 27), Decimal("5.50")),
        (date(2024, 9, 19), Decimal("5.00")),
        (date(2024, 11, 8), Decimal("4.75")),
        (date(2024, 12, 19), Decimal("4.50")),
    ),
    "JPY": (
        (date(2019, 1, 1), Decimal("-0.10")),
        (date(2024, 3, 19), Decimal("0.10")),
        (date(2024, 7, 31), Decimal("0.25")),
        (date(2025, 1, 24), Decimal("0.50")),
    ),
    "EUR": (
        (date(2019, 1, 1), Decimal("-0.40")),
        (date(2019, 9, 18), Decimal("-0.50")),
        (date(2022, 7, 27), Decimal("0.00")),
        (date(2022, 9, 14), Decimal("0.75")),
        (date(2022, 11, 2), Decimal("1.50")),
        (date(2022, 12, 21), Decimal("2.00")),
        (date(2023, 2, 8), Decimal("2.50")),
        (date(2023, 3, 22), Decimal("3.00")),
        (date(2023, 5, 10), Decimal("3.25")),
        (date(2023, 6, 21), Decimal("3.50")),
        (date(2023, 8, 2), Decimal("3.75")),
        (date(2023, 9, 20), Decimal("4.00")),
        (date(2024, 6, 12), Decimal("3.75")),
        (date(2024, 9, 18), Decimal("3.50")),
        (date(2024, 10, 23), Decimal("3.25")),
        (date(2024, 12, 18), Decimal("3.00")),
        (date(2025, 2, 5), Decimal("2.75")),
        (date(2025, 3, 12), Decimal("2.50")),
        (date(2025, 4, 23), Decimal("2.25")),
        (date(2025, 6, 11), Decimal("2.00")),
    ),
    "GBP": (
        (date(2019, 1, 1), Decimal("0.75")),
        (date(2020, 3, 19), Decimal("0.10")),
        (date(2021, 12, 16), Decimal("0.25")),
        (date(2022, 2, 3), Decimal("0.50")),
        (date(2022, 3, 17), Decimal("0.75")),
        (date(2022, 5, 5), Decimal("1.00")),
        (date(2022, 6, 16), Decimal("1.25")),
        (date(2022, 8, 4), Decimal("1.75")),
        (date(2022, 9, 22), Decimal("2.25")),
        (date(2022, 11, 3), Decimal("3.00")),
        (date(2022, 12, 15), Decimal("3.50")),
        (date(2023, 2, 2), Decimal("4.00")),
        (date(2023, 3, 23), Decimal("4.25")),
        (date(2023, 5, 11), Decimal("4.50")),
        (date(2023, 6, 22), Decimal("5.00")),
        (date(2023, 8, 3), Decimal("5.25")),
        (date(2024, 8, 1), Decimal("5.00")),
        (date(2024, 11, 7), Decimal("4.75")),
        (date(2025, 2, 6), Decimal("4.50")),
        (date(2025, 5, 8), Decimal("4.25")),
    ),
    "AUD": (
        (date(2019, 1, 1), Decimal("1.50")),
        (date(2019, 6, 4), Decimal("1.25")),
        (date(2019, 7, 2), Decimal("1.00")),
        (date(2019, 10, 1), Decimal("0.75")),
        (date(2020, 3, 19), Decimal("0.25")),
        (date(2020, 11, 3), Decimal("0.10")),
        (date(2022, 5, 3), Decimal("0.35")),
        (date(2022, 6, 7), Decimal("0.85")),
        (date(2022, 7, 5), Decimal("1.35")),
        (date(2022, 8, 2), Decimal("1.85")),
        (date(2022, 9, 6), Decimal("2.35")),
        (date(2022, 10, 4), Decimal("2.60")),
        (date(2022, 11, 1), Decimal("2.85")),
        (date(2022, 12, 6), Decimal("3.10")),
        (date(2023, 2, 7), Decimal("3.35")),
        (date(2023, 3, 7), Decimal("3.60")),
        (date(2023, 5, 2), Decimal("3.85")),
        (date(2023, 6, 6), Decimal("4.10")),
        (date(2023, 11, 7), Decimal("4.35")),
        (date(2025, 2, 18), Decimal("4.10")),
        (date(2025, 5, 20), Decimal("3.85")),
    ),
    "CAD": (
        (date(2019, 1, 1), Decimal("1.75")),
        (date(2020, 3, 27), Decimal("0.25")),
        (date(2022, 3, 2), Decimal("0.50")),
        (date(2022, 4, 13), Decimal("1.00")),
        (date(2022, 6, 1), Decimal("1.50")),
        (date(2022, 7, 13), Decimal("2.50")),
        (date(2022, 9, 7), Decimal("3.25")),
        (date(2022, 10, 26), Decimal("3.75")),
        (date(2022, 12, 7), Decimal("4.25")),
        (date(2023, 1, 25), Decimal("4.50")),
        (date(2023, 6, 7), Decimal("4.75")),
        (date(2023, 7, 12), Decimal("5.00")),
        (date(2024, 6, 5), Decimal("4.75")),
        (date(2024, 7, 24), Decimal("4.50")),
        (date(2024, 9, 4), Decimal("4.25")),
        (date(2024, 10, 23), Decimal("3.75")),
        (date(2024, 12, 11), Decimal("3.25")),
        (date(2025, 1, 29), Decimal("3.00")),
        (date(2025, 3, 12), Decimal("2.75")),
    ),
}

# pair -> (base, quote). A LONG on the pair earns base, pays quote.
PAIR_CURRENCIES: dict[str, tuple[str, str]] = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"),
    "AUDUSD": ("AUD", "USD"),
    "USDCAD": ("USD", "CAD"),
    "EURJPY": ("EUR", "JPY"),
}

_DAYS_PER_YEAR = Decimal("360")


def policy_rate(currency: str, on_date: date) -> Decimal:
    """Policy rate (percent) in effect for ``currency`` on ``on_date``."""

    schedule = POLICY_RATES[currency]
    rate = schedule[0][1]
    for effective, value in schedule:
        if effective <= on_date:
            rate = value
        else:
            break
    return rate


def annual_carry_percent(
    pair: str, on_date: date, markup_annual: Decimal = Decimal("1.00")
) -> Decimal:
    """Net annual carry (percent) for a LONG on ``pair``, after a broker markup.

    gross = r_base - r_quote; the markup is a haircut applied against the trader
    (subtracted from a credit, added to a debit) to stay conservative.
    """

    base, quote = PAIR_CURRENCIES[pair]
    # The markup is always a haircut against the trader: it shrinks a credit and
    # deepens a debit, so it is subtracted from the gross differential either way.
    gross = policy_rate(base, on_date) - policy_rate(quote, on_date)
    return gross - markup_annual


def daily_carry_fraction(
    pair: str, on_date: date, markup_annual: Decimal = Decimal("1.00")
) -> Decimal:
    """Per-day carry as a fraction of notional for a LONG on ``pair``.

    Positive = income (credit) accrues per day held; negative = a financing debit.
    """

    return annual_carry_percent(pair, on_date, markup_annual) / Decimal("100") / _DAYS_PER_YEAR
