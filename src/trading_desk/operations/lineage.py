"""Deterministic bidirectional linkage over immutable journal projections."""

from trading_desk.operations.models import RecordProjection


def connected_records(
    seed: RecordProjection, records: tuple[RecordProjection, ...]
) -> tuple[RecordProjection, ...]:
    source_ids = {seed.source_record_id}
    atomic_groups = {seed.atomic_group_id} if seed.atomic_group_id else set()
    selected: set[str] = set()
    changed = True
    while changed:
        changed = False
        for record in records:
            linked = (
                record.source_record_id in source_ids
                or bool(source_ids.intersection(record.source_parent_ids))
                or bool(set(record.source_parent_ids).intersection(source_ids))
                or bool(record.atomic_group_id and record.atomic_group_id in atomic_groups)
            )
            if not linked:
                continue
            if record.journal_record_id not in selected:
                selected.add(record.journal_record_id)
                changed = True
            before = len(source_ids)
            source_ids.add(record.source_record_id)
            source_ids.update(record.source_parent_ids)
            if record.atomic_group_id:
                atomic_groups.add(record.atomic_group_id)
            changed = changed or len(source_ids) != before
    return tuple(
        sorted(
            (item for item in records if item.journal_record_id in selected),
            key=lambda item: (item.effective_at, item.journal_record_id),
        )
    )
