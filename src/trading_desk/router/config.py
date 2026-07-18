"""Immutable deterministic strategy-selection policy."""

from pydantic import BaseModel, ConfigDict

from trading_desk.router.fingerprints import fingerprint


class RouterConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_priority: tuple[str, ...] = (
        "post-news-continuation",
        "trend-pullback-v1",
        "trend-regime-v1",
        "volatility-breakout",
        "range-mean-reversion",
    )
    reject_ambiguous_priority: bool = False

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)
