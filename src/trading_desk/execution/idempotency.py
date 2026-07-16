"""Replay protection with exportable state for restart persistence."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from trading_desk.execution.models import ExecutionRequest


class IdempotencySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_ids: tuple[str, ...] = ()
    request_fingerprints: tuple[str, ...] = ()
    consumed_intent_ids: tuple[str, ...] = ()
    deal_references: tuple[str, ...] = ()


class ExecutionIdempotencyStore:
    def __init__(self, snapshot: IdempotencySnapshot | None = None) -> None:
        state = snapshot or IdempotencySnapshot()
        self._request_ids = set(state.request_ids)
        self._request_fingerprints = set(state.request_fingerprints)
        self._consumed_intent_ids = set(state.consumed_intent_ids)
        self._deal_references = set(state.deal_references)

    def is_duplicate(self, request: ExecutionRequest) -> bool:
        return (
            request.execution_request_id in self._request_ids
            or request.request_fingerprint in self._request_fingerprints
        )

    def intent_consumed(self, approved_intent_id: str) -> bool:
        return approved_intent_id in self._consumed_intent_ids

    def reserve_submission(self, request: ExecutionRequest) -> bool:
        if self.is_duplicate(request) or self.intent_consumed(request.approved_intent_id):
            return False
        self._request_ids.add(request.execution_request_id)
        self._request_fingerprints.add(request.request_fingerprint)
        self._consumed_intent_ids.add(request.approved_intent_id)
        return True

    def record_deal_reference(self, deal_reference: str) -> bool:
        if deal_reference in self._deal_references:
            return False
        self._deal_references.add(deal_reference)
        return True

    def snapshot(self) -> IdempotencySnapshot:
        return IdempotencySnapshot(
            request_ids=tuple(sorted(self._request_ids)),
            request_fingerprints=tuple(sorted(self._request_fingerprints)),
            consumed_intent_ids=tuple(sorted(self._consumed_intent_ids)),
            deal_references=tuple(sorted(self._deal_references)),
        )
