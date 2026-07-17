"""Cutoff-safe replay over immutable projections only."""

from datetime import datetime

from trading_desk.operations.fingerprints import fingerprint
from trading_desk.operations.models import RecordProjection, ReplayTimeline


def build_replay(records: tuple[RecordProjection, ...], cutoff_at: datetime) -> ReplayTimeline:
    visible = tuple(
        sorted(
            (item for item in records if item.effective_at <= cutoff_at),
            key=lambda item: (item.effective_at, item.journal_record_id),
        )
    )
    fields = {"cutoff_at": cutoff_at, "events": visible}
    return ReplayTimeline(
        cutoff_at=cutoff_at,
        events=visible,
        timeline_fingerprint=fingerprint(fields),
    )
