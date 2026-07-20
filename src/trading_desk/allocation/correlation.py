"""Deterministic rolling correlation over completed, aligned returns.

Correlation informs portfolio diversification decisions and must never be
guessed: insufficient overlap yields an explicit UNKNOWN outcome that the
engine treats conservatively (reject or defer, per configuration) rather
than a silent default of zero.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.context.fingerprints import fingerprint


class CorrelationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class ReturnSeries(CorrelationModel):
    """Completed-bar fractional close returns for one instrument."""

    epic: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    bar_timestamps: tuple[str, ...]
    returns: tuple[Decimal, ...]

    @model_validator(mode="after")
    def aligned(self) -> Self:
        if len(self.bar_timestamps) != len(self.returns):
            raise ValueError("return series timestamps and values must align")
        if list(self.bar_timestamps) != sorted(set(self.bar_timestamps)):
            raise ValueError("return series timestamps must be unique and ordered")
        return self


class PairCorrelation(CorrelationModel):
    first_epic: str
    second_epic: str
    known: bool
    value: Decimal | None = Field(default=None, ge=-1, le=1)
    overlap: int = Field(ge=0)
    reason: str = ""

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.known and self.value is None:
            raise ValueError("known correlations require a value")
        if not self.known and self.value is not None:
            raise ValueError("unknown correlations cannot carry a value")
        return self


class CorrelationMatrix(CorrelationModel):
    schema_version: Literal["correlation-matrix-v1"] = "correlation-matrix-v1"
    timeframe: str
    lookback: int = Field(ge=10)
    minimum_overlap: int = Field(ge=10)
    pairs: tuple[PairCorrelation, ...]
    matrix_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"matrix_fingerprint"}))
        if self.matrix_fingerprint != expected:
            raise ValueError("correlation matrix fingerprint mismatch")
        return self

    def lookup(self, first_epic: str, second_epic: str) -> PairCorrelation | None:
        for pair in self.pairs:
            if {pair.first_epic, pair.second_epic} == {first_epic, second_epic}:
                return pair
        return None


def _pearson(first: tuple[Decimal, ...], second: tuple[Decimal, ...]) -> Decimal | None:
    count = Decimal(len(first))
    mean_first = sum(first, Decimal(0)) / count
    mean_second = sum(second, Decimal(0)) / count
    centered_first = [value - mean_first for value in first]
    centered_second = [value - mean_second for value in second]
    covariance = sum(
        (a * b for a, b in zip(centered_first, centered_second, strict=True)), Decimal(0)
    )
    variance_first = sum((value * value for value in centered_first), Decimal(0))
    variance_second = sum((value * value for value in centered_second), Decimal(0))
    if variance_first == 0 or variance_second == 0:
        return None
    correlation = covariance / (variance_first.sqrt() * variance_second.sqrt())
    return max(Decimal("-1"), min(Decimal("1"), correlation)).quantize(Decimal("0.0001"))


def build_correlation_matrix(
    series: tuple[ReturnSeries, ...],
    *,
    lookback: int = 120,
    minimum_overlap: int = 40,
) -> CorrelationMatrix:
    """Pairwise rolling correlation on the intersection of completed bars.

    The missing-data policy is alignment by bar timestamp: only bars present
    in both series participate. Fewer overlapping bars than
    ``minimum_overlap`` (or degenerate variance) yields an explicit UNKNOWN
    pair for the engine's conservative fallback.
    """

    timeframes = {item.timeframe for item in series}
    if len(timeframes) > 1:
        raise ValueError("correlation requires one immutable timeframe per matrix")
    pairs: list[PairCorrelation] = []
    ordered = sorted(series, key=lambda item: item.epic)
    for index, first in enumerate(ordered):
        first_map = dict(zip(first.bar_timestamps, first.returns, strict=True))
        for second in ordered[index + 1 :]:
            shared = [stamp for stamp in second.bar_timestamps if stamp in first_map][-lookback:]
            if len(shared) < minimum_overlap:
                pairs.append(
                    PairCorrelation(
                        first_epic=first.epic,
                        second_epic=second.epic,
                        known=False,
                        overlap=len(shared),
                        reason="INSUFFICIENT_OVERLAP",
                    )
                )
                continue
            second_map = dict(zip(second.bar_timestamps, second.returns, strict=True))
            value = _pearson(
                tuple(first_map[stamp] for stamp in shared),
                tuple(second_map[stamp] for stamp in shared),
            )
            if value is None:
                pairs.append(
                    PairCorrelation(
                        first_epic=first.epic,
                        second_epic=second.epic,
                        known=False,
                        overlap=len(shared),
                        reason="DEGENERATE_VARIANCE",
                    )
                )
            else:
                pairs.append(
                    PairCorrelation(
                        first_epic=first.epic,
                        second_epic=second.epic,
                        known=True,
                        value=value,
                        overlap=len(shared),
                    )
                )
    timeframe = ordered[0].timeframe if ordered else "UNSPECIFIED"
    draft = CorrelationMatrix.model_construct(
        timeframe=timeframe,
        lookback=lookback,
        minimum_overlap=minimum_overlap,
        pairs=tuple(pairs),
        matrix_fingerprint="0" * 64,
    )
    fields = draft.model_dump(mode="python", exclude={"matrix_fingerprint"})
    return CorrelationMatrix.model_validate({**fields, "matrix_fingerprint": fingerprint(fields)})
