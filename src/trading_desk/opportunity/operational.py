"""Operational read-only evidence composition for governed opportunity scans."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from trading_desk.context.models import (
    ContextQuality,
    ContextTimeframe,
    LiquidityState,
    MarketContextSnapshot,
    SessionState,
    VolatilityState,
)
from trading_desk.context.operational import ObservableMarketQuote, completed_market_data
from trading_desk.context.provider import CandidateContextProvider
from trading_desk.ig.models import HistoricalPricePage, MarketDetails, PriceResolution
from trading_desk.opportunity.config import MarketDefinition
from trading_desk.opportunity.fingerprints import fingerprint
from trading_desk.opportunity.models import (
    CandidateEvidence,
    StrategyFamily,
    default_strategy_policies,
)
from trading_desk.router.engine import StrategyRouter
from trading_desk.router.models import RouteStatus
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.data_validation import market_data_from_ig_page
from trading_desk.strategy.models import (
    StrategyAction,
    StrategyBarResolution,
    StrategyContext,
    TradeCandidate,
)
from trading_desk.strategy.pipeline import RegimeAwareStrategyPipeline


class ReadOnlyOpportunityMarketData(Protocol):
    async def get_market_details(self, epic: str) -> MarketDetails: ...

    async def get_historical_prices(
        self,
        epic: str,
        resolution: PriceResolution | str = PriceResolution.DAY,
        max_points: int | None = None,
        page_number: int = 1,
    ) -> HistoricalPricePage: ...


class OperationalEvaluationDiagnostic(BaseModel):
    """Sanitized read-only evidence about one operational evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_id: str
    epic: str
    timeframe: ContextTimeframe
    market_status: str | None = None
    quote_valid: bool = False
    bars_retrieved: int = 0
    invalid_bars: int = 0
    latest_completed_bar: datetime | None = None
    context_outcome: str = "NOT_EVALUATED"
    route_outcome: str = "NOT_EVALUATED"
    candidates_created: int = 0
    rejection_reason: str | None = None


class OperationalOpportunityEvidenceProvider:
    """Build candidate evidence without Risk, execution, or broker mutation authority."""

    def __init__(
        self,
        market_data: ReadOnlyOpportunityMarketData,
        context_provider: CandidateContextProvider,
        *,
        holding_epics: tuple[str, ...] = (),
        router: StrategyRouter | None = None,
        strategy_configuration: StrategyConfiguration | None = None,
        maximum_history_points: int = 500,
    ) -> None:
        if maximum_history_points < 220:
            raise ValueError("operational opportunity history requires at least 220 points")
        self._market_data = market_data
        self._context_provider = context_provider
        self._holding_epics = frozenset(holding_epics)
        self._router = router or StrategyRouter()
        self._strategy_configuration = strategy_configuration or StrategyConfiguration()
        self._pipeline = RegimeAwareStrategyPipeline(self._strategy_configuration)
        self._maximum_history_points = maximum_history_points
        self._details_cache_cycle: datetime | None = None
        self._details_cache: dict[str, MarketDetails] = {}
        self._diagnostics: list[OperationalEvaluationDiagnostic] = []
        self.strategy_evaluations_per_request = 4
        self.supports_scheduled_cutoff = True

    def set_holding_epics(self, epics: tuple[str, ...]) -> None:
        self._holding_epics = frozenset(epics)

    @property
    def diagnostics(self) -> tuple[OperationalEvaluationDiagnostic, ...]:
        return tuple(self._diagnostics)

    async def evaluate(
        self,
        market: MarketDefinition,
        timeframe: ContextTimeframe,
        cycle_timestamp: datetime,
        *,
        completed_bar_timestamp: datetime | None = None,
    ) -> tuple[CandidateEvidence, ...]:
        now = _utc(cycle_timestamp)
        details = await self._market_details(market.epic, now)
        if details.epic != market.epic or details.bid is None or details.offer is None:
            self._record_diagnostic(
                market,
                timeframe,
                market_status=details.market_status.value,
                rejection_reason="MARKET_DETAILS_OR_QUOTE_INCOMPLETE",
            )
            return ()
        if details.bid <= 0 or details.offer <= 0 or details.bid > details.offer:
            self._record_diagnostic(
                market,
                timeframe,
                market_status=details.market_status.value,
                rejection_reason="INVALID_BID_OFFER",
            )
            return ()
        resolution, strategy_resolution = _resolutions(timeframe)
        page = await self._market_data.get_historical_prices(
            market.epic,
            resolution=resolution,
            max_points=self._maximum_history_points,
            page_number=1,
        )
        bars_retrieved = len(page.bars)
        invalid_bars = sum(1 for item in page.bars if not item.valid_for_strategy)
        build = market_data_from_ig_page(
            page,
            epic=details.epic,
            instrument_name=details.instrument_name,
            market_status=details.market_status.value,
            data_retrieval_time=now,
            bar_resolution=strategy_resolution,
        )
        if build.data is None:
            self._record_diagnostic(
                market,
                timeframe,
                market_status=details.market_status.value,
                quote_valid=True,
                bars_retrieved=bars_retrieved,
                invalid_bars=invalid_bars,
                rejection_reason="HISTORICAL_DATA_INVALID",
            )
            return ()
        try:
            completed = completed_market_data(build.data, now, timeframe)
        except ValueError:
            self._record_diagnostic(
                market,
                timeframe,
                market_status=details.market_status.value,
                quote_valid=True,
                bars_retrieved=bars_retrieved,
                invalid_bars=invalid_bars,
                rejection_reason="COMPLETED_BAR_VALIDATION_FAILED",
            )
            return ()
        if completed_bar_timestamp is not None:
            cutoff = _utc(completed_bar_timestamp)
            indexes = [
                index for index, timestamp in enumerate(completed.timestamps) if timestamp <= cutoff
            ]
            if not indexes or completed.timestamps[indexes[-1]] != cutoff:
                self._record_diagnostic(
                    market,
                    timeframe,
                    market_status=details.market_status.value,
                    quote_valid=True,
                    bars_retrieved=bars_retrieved,
                    invalid_bars=invalid_bars,
                    latest_completed_bar=(
                        completed.timestamps[-1] if completed.timestamps else None
                    ),
                    rejection_reason="SCHEDULED_CUTOFF_UNAVAILABLE",
                )
                return ()
            completed = completed.sliced_through(indexes[-1]).model_copy(
                update={"data_retrieval_time": now}
            )
        if len(completed.timestamps) < self._strategy_configuration.minimum_bars_required:
            self._record_diagnostic(
                market,
                timeframe,
                market_status=details.market_status.value,
                quote_valid=True,
                bars_retrieved=bars_retrieved,
                invalid_bars=invalid_bars,
                latest_completed_bar=(completed.timestamps[-1] if completed.timestamps else None),
                rejection_reason="INSUFFICIENT_COMPLETED_HISTORY",
            )
            return ()
        spread = details.offer - details.bid
        midpoint = (details.offer + details.bid) / Decimal("2")
        spread_bps = spread / midpoint * Decimal("10000")
        strategy_context = StrategyContext(
            holding=details.epic in self._holding_epics,
            macro_score=None,
            current_spread=float(spread),
            current_spread_bps=float(spread_bps),
            market_status=details.market_status.value,
            current_time=now,
            account_exposure_summary=(f"authoritative open epic count: {len(self._holding_epics)}"),
        )
        preliminary = self._pipeline.analyze_latest(
            completed,
            strategy_context,
            inherited_findings=build.findings,
        )
        context = self._context_provider.build_context(
            completed,
            preliminary,
            evaluation_timestamp=now,
            timeframe=timeframe,
            quote=ObservableMarketQuote(
                epic=details.epic,
                bid=details.bid,
                ask=details.offer,
                market_status=details.market_status.value,
                observed_at=now,
            ),
        )
        if context is None or context.context_quality is not ContextQuality.VALID:
            context_outcome = "UNAVAILABLE" if context is None else context.context_quality.value
            context_reasons = (
                () if context is None else tuple(item.value for item in context.reason_codes)
            )
            self._record_diagnostic(
                market,
                timeframe,
                market_status=details.market_status.value,
                quote_valid=True,
                bars_retrieved=bars_retrieved,
                invalid_bars=invalid_bars,
                latest_completed_bar=completed.timestamps[-1],
                context_outcome=context_outcome,
                rejection_reason=(
                    "CONTEXT_UNAVAILABLE"
                    if not context_reasons
                    else "CONTEXT_" + "+".join(context_reasons)
                ),
            )
            return ()
        routed = self._router.route_candidate(context, completed, preliminary)
        if (
            routed.decision.route_status is not RouteStatus.STRATEGY_SELECTED
            or routed.candidate is None
            or routed.candidate.action is not StrategyAction.LONG_CANDIDATE
        ):
            self._record_diagnostic(
                market,
                timeframe,
                market_status=details.market_status.value,
                quote_valid=True,
                bars_retrieved=bars_retrieved,
                invalid_bars=invalid_bars,
                latest_completed_bar=completed.timestamps[-1],
                context_outcome=context.context_quality.value,
                route_outcome=routed.decision.route_status.value,
                rejection_reason="ROUTER_NO_EXECUTABLE_LONG_CANDIDATE",
            )
            return ()
        if routed.decision.selected_strategy_id != "trend-regime-v1":
            self._record_diagnostic(
                market,
                timeframe,
                market_status=details.market_status.value,
                quote_valid=True,
                bars_retrieved=bars_retrieved,
                invalid_bars=invalid_bars,
                latest_completed_bar=completed.timestamps[-1],
                context_outcome=context.context_quality.value,
                route_outcome=routed.decision.route_status.value,
                rejection_reason="ROUTER_SELECTED_NON_EXECUTABLE_STRATEGY",
            )
            return ()
        self._record_diagnostic(
            market,
            timeframe,
            market_status=details.market_status.value,
            quote_valid=True,
            bars_retrieved=bars_retrieved,
            invalid_bars=invalid_bars,
            latest_completed_bar=completed.timestamps[-1],
            context_outcome=context.context_quality.value,
            route_outcome=routed.decision.route_status.value,
            candidates_created=1,
        )
        return (
            _candidate_evidence(
                market,
                timeframe,
                now,
                details,
                context,
                routed.candidate,
                page,
                routed.decision.decision_fingerprint,
            ),
        )

    async def _market_details(self, epic: str, cycle_timestamp: datetime) -> MarketDetails:
        if self._details_cache_cycle != cycle_timestamp:
            self._details_cache_cycle = cycle_timestamp
            self._details_cache.clear()
            self._diagnostics.clear()
        details = self._details_cache.get(epic)
        if details is None:
            details = await self._market_data.get_market_details(epic)
            self._details_cache[epic] = details
        return details

    def _record_diagnostic(
        self,
        market: MarketDefinition,
        timeframe: ContextTimeframe,
        **values: object,
    ) -> None:
        self._diagnostics.append(
            OperationalEvaluationDiagnostic.model_validate(
                {
                    "instrument_id": market.instrument_id,
                    "epic": market.epic,
                    "timeframe": timeframe,
                    **values,
                }
            )
        )


def _candidate_evidence(
    market: MarketDefinition,
    timeframe: ContextTimeframe,
    now: datetime,
    details: MarketDetails,
    context: MarketContextSnapshot,
    candidate: TradeCandidate,
    page: HistoricalPricePage,
    router_fingerprint: str,
) -> CandidateEvidence:
    assert details.bid is not None and details.offer is not None
    entry = details.offer
    atr = context.atr
    if atr <= 0:
        raise ValueError("positive ATR is required for opportunity evidence")
    stop_distance = max(atr, (details.offer - details.bid) * Decimal("3"))
    stop = entry - stop_distance
    target = entry + stop_distance * Decimal("2")
    if stop <= 0:
        raise ValueError("protective stop evidence is invalid")
    confidence = _decimal(candidate.regime_probabilities[0].probability)
    selected_probability = max(
        (
            _decimal(item.probability)
            for item in candidate.regime_probabilities
            if item.regime is candidate.current_regime
        ),
        default=Decimal("0"),
    )
    signal_strength = min(
        Decimal("1"),
        max(
            Decimal("0"),
            Decimal(candidate.baseline_trend_score + candidate.baseline_momentum_score + 4)
            / Decimal("8"),
        ),
    )
    confidence = max(confidence, selected_probability)
    win_probability = min(Decimal("0.70"), Decimal("0.50") + confidence / Decimal("5"))
    policy = next(
        item for item in default_strategy_policies() if item.family is StrategyFamily.TREND_REGIME
    )
    evidence_ids = tuple(
        dict.fromkeys(
            (
                fingerprint(details),
                fingerprint(page),
                context.context_id,
                context.context_fingerprint,
                router_fingerprint,
                candidate.configuration_fingerprint,
                *(item.source_fingerprint for item in context.source_evidence),
            )
        )
    )
    liquidity = {
        LiquidityState.HIGH: Decimal("1"),
        LiquidityState.NORMAL: Decimal("0.8"),
        LiquidityState.LOW: Decimal("0.3"),
    }.get(context.liquidity_state, Decimal("0"))
    volatility = {
        VolatilityState.LOW: Decimal("0.8"),
        VolatilityState.NORMAL: Decimal("1"),
        VolatilityState.HIGH: Decimal("0.5"),
    }.get(context.volatility_state, Decimal("0"))
    session = (
        Decimal("0")
        if context.session in {SessionState.CLOSED, SessionState.UNKNOWN}
        else Decimal("1")
    )
    return CandidateEvidence(
        created_at=now,
        cycle_id=fingerprint({"timestamp": now, "market": market, "timeframe": timeframe}),
        instrument_id=market.instrument_id,
        epic=market.epic,
        asset_class="FOREX",
        timeframe=timeframe,
        completed_bar_timestamp=context.data_cutoff_timestamp,
        strategy=policy,
        market_context_id=context.context_id,
        market_context_fingerprint=context.context_fingerprint,
        regime=candidate.current_regime.value,
        regime_confidence=selected_probability,
        entry_reference_price=entry,
        proposed_stop=stop,
        proposed_target=target,
        expected_holding_period=timedelta(seconds=timeframe.seconds * 12),
        signal_strength=signal_strength,
        signal_confidence=confidence,
        estimated_win_probability=win_probability,
        estimated_loss_probability=Decimal("1") - win_probability,
        estimated_average_gain=target - entry,
        estimated_average_loss=entry - stop,
        current_bid=details.bid,
        current_ask=details.offer,
        spread_observed_at=now,
        liquidity_score=liquidity,
        volatility_score=volatility,
        session_score=session,
        event_risk_score=(Decimal("0") if not context.reason_codes else Decimal("0.5")),
        data_quality_score=(
            Decimal("1") if context.context_quality is ContextQuality.VALID else Decimal("0.6")
        ),
        uncertainty_score=_decimal(candidate.regime_uncertainty),
        correlation_groups=market.correlation_groups,
        evidence_ids=evidence_ids,
    )


def _resolutions(
    timeframe: ContextTimeframe,
) -> tuple[PriceResolution, StrategyBarResolution]:
    mapping = {
        ContextTimeframe.MINUTE_5: (PriceResolution.MINUTE_5, StrategyBarResolution.MINUTE_5),
        ContextTimeframe.MINUTE_15: (
            PriceResolution.MINUTE_15,
            StrategyBarResolution.MINUTE_15,
        ),
        ContextTimeframe.HOUR: (PriceResolution.HOUR, StrategyBarResolution.HOUR),
    }
    try:
        return mapping[timeframe]
    except KeyError:
        raise ValueError("opportunity timeframe has no read-only IG resolution") from None


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("operational opportunity timestamps must be UTC")
    return value.astimezone(UTC)
