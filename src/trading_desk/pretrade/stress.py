"""Parametric stress calculator: produces the StressReport the pipeline checks.

Computes the six pre-registered adverse scenarios for a POST-TRADE portfolio
snapshot. The v1 model is deliberately parametric and conservative — documented
shock sizes applied to the projected exposures — so it is deterministic,
auditable, and cannot be quietly weakened (parameters change only by written
decision). Shorts receive a larger adverse shock than longs (asymmetric risk).

Scenario definitions (loss expressed as a fraction of equity):
  normal_stop          |net| x daily_vol + gross x spread_vol
                       (the book's residual market exposure moves one normal
                        day against us while the long-short spread also moves)
  double_volatility    2 x normal_stop
  overnight_gap        max_single_name x single_name_gap + |net| x market_gap
  short_squeeze        max_short_name x squeeze_shock (worst single short gaps
                        up hard)
  correlation_spike    gross x correlation_shock (longs fall AND shorts rise
                        together — the hedge stops hedging)
  failed_hedge         (gross / 2) x leg_shock (one whole leg moves adversely
                        with no offset — e.g. hedge leg unexecuted)
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from trading_desk.pretrade.models import StressReport


class StressParameters(BaseModel):
    """Pre-registered shock sizes (fractions). Change only by written decision."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    daily_vol: Decimal = Field(default=Decimal("0.01"), ge=0)
    spread_vol: Decimal = Field(default=Decimal("0.004"), ge=0)
    single_name_gap: Decimal = Field(default=Decimal("0.20"), ge=0)
    market_gap: Decimal = Field(default=Decimal("0.03"), ge=0)
    squeeze_shock: Decimal = Field(default=Decimal("0.40"), ge=0)
    correlation_shock: Decimal = Field(default=Decimal("0.02"), ge=0)
    leg_shock: Decimal = Field(default=Decimal("0.03"), ge=0)


class PortfolioSnapshot(BaseModel):
    """Projected POST-trade exposures (fractions of equity)."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    gross_exposure: Decimal = Field(ge=0)
    net_exposure: Decimal
    max_single_name_weight: Decimal = Field(ge=0)
    max_short_name_weight: Decimal = Field(ge=0)


def compute_stress_report(
    snapshot: PortfolioSnapshot, params: StressParameters | None = None
) -> StressReport:
    p = params or StressParameters()
    abs_net = abs(snapshot.net_exposure)
    normal = abs_net * p.daily_vol + snapshot.gross_exposure * p.spread_vol
    return StressReport(
        normal_stop_loss_fraction=normal,
        double_volatility_loss_fraction=2 * normal,
        overnight_gap_loss_fraction=(
            snapshot.max_single_name_weight * p.single_name_gap + abs_net * p.market_gap
        ),
        short_squeeze_loss_fraction=(snapshot.max_short_name_weight * p.squeeze_shock),
        correlation_spike_loss_fraction=(snapshot.gross_exposure * p.correlation_shock),
        failed_hedge_loss_fraction=(snapshot.gross_exposure / 2 * p.leg_shock),
    )
