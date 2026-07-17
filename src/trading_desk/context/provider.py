"""Provider-neutral authoritative inputs for candidate-time context routing."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from trading_desk.context.classifier import MarketContextEngine
from trading_desk.context.models import (
    ContextTimeframe,
    EconomicEvent,
    MarketContextSnapshot,
    NewsItem,
)
from trading_desk.strategy.models import (
    HMMRegimeResult,
    KalmanTrendResult,
    StrategyMarketData,
    TradeCandidate,
)

if TYPE_CHECKING:
    from trading_desk.context.operational import ObservableMarketQuote


class MarketContextInputs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[EconomicEvent, ...] = ()
    news: tuple[NewsItem, ...] = ()
    holiday: bool = False
    authoritative: bool = False


class CandidateContextProvider(Protocol):
    def build_context(
        self,
        data: StrategyMarketData,
        candidate: TradeCandidate,
        *,
        evaluation_timestamp: datetime,
        timeframe: ContextTimeframe,
        quote: ObservableMarketQuote | None = None,
    ) -> MarketContextSnapshot | None: ...


class DeterministicContextProvider:
    """Build context only when calendar/news completeness is explicitly asserted."""

    def __init__(
        self,
        inputs: MarketContextInputs,
        engine: MarketContextEngine | None = None,
    ) -> None:
        self.inputs = inputs
        self.engine = engine or MarketContextEngine()

    def build_context(
        self,
        data: StrategyMarketData,
        candidate: TradeCandidate,
        *,
        evaluation_timestamp: datetime,
        timeframe: ContextTimeframe,
        quote: ObservableMarketQuote | None = None,
    ) -> MarketContextSnapshot | None:
        if not self.inputs.authoritative:
            return None
        kalman = KalmanTrendResult(
            ready=(
                candidate.kalman_level is not None
                and candidate.kalman_slope is not None
                and candidate.kalman_slope_uncertainty is not None
                and candidate.kalman_normalized_slope is not None
            ),
            current_filtered_level=candidate.kalman_level,
            current_slope=candidate.kalman_slope,
            current_slope_uncertainty=candidate.kalman_slope_uncertainty,
            current_normalized_slope=candidate.kalman_normalized_slope,
            current_normalized_slope_uncertainty=(candidate.kalman_normalized_slope_uncertainty),
            normalized_price_deviation=candidate.normalized_price_deviation,
            observations_used=len(data.timestamps),
        )
        regime = HMMRegimeResult(
            ready=candidate.current_regime.value != "UNKNOWN",
            current_regime=candidate.current_regime,
            probabilities=candidate.regime_probabilities,
            selected_regime_probability=max(
                (item.probability for item in candidate.regime_probabilities), default=0
            ),
            uncertainty=candidate.regime_uncertainty,
            converged=candidate.current_regime.value != "UNKNOWN",
            observations_used=len(data.timestamps),
        )
        return self.engine.classify(
            data,
            kalman,
            regime,
            evaluation_timestamp=evaluation_timestamp,
            timeframe=timeframe,
            events=self.inputs.events,
            news=self.inputs.news,
            holiday=self.inputs.holiday,
        )
