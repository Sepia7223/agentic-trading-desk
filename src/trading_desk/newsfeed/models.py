"""Typed contracts for live news sources."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class NewsItem(_Frozen):
    """One headline from any wire; published_at is its knowledge time."""

    source: str = Field(min_length=1)
    headline: str = Field(min_length=1)
    symbols: tuple[str, ...] = ()
    published_at: datetime | None = None
    url: str = ""
    item_id: str = ""


class HaltNotice(_Frozen):
    """A regulatory trading halt/pause from the exchange feed."""

    symbol: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)  # e.g. T1 (news pending), T2, LUDP
    halted_at: datetime | None = None
    resumed: bool = False

    @property
    def is_news_related(self) -> bool:
        return self.reason_code.upper().startswith("T")


class FilingEvent(_Frozen):
    """An entry from EDGAR's current-filings feed (acceptance-time keyed)."""

    cik: int = Field(ge=1)
    form: str = Field(min_length=1)
    title: str = ""
    accepted: datetime | None = None
    accession: str = ""
