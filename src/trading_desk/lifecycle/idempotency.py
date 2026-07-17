"""Restart-safe close request replay protection."""

from pydantic import BaseModel, ConfigDict

from trading_desk.lifecycle.models import CloseRequest, ExitDecision


class LifecycleIdempotencySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    consumed_exit_decisions: tuple[str, ...] = ()
    consumed_close_requests: tuple[str, ...] = ()
    request_fingerprints: tuple[str, ...] = ()
    deal_references: tuple[str, ...] = ()


class LifecycleIdempotencyStore:
    def __init__(self, snapshot: LifecycleIdempotencySnapshot | None = None) -> None:
        state = snapshot or LifecycleIdempotencySnapshot()
        self._decisions = set(state.consumed_exit_decisions)
        self._requests = set(state.consumed_close_requests)
        self._fingerprints = set(state.request_fingerprints)
        self._references = set(state.deal_references)

    def duplicate(self, decision: ExitDecision, request: CloseRequest) -> bool:
        return (
            decision.exit_decision_id in self._decisions
            or request.close_request_id in self._requests
            or request.request_fingerprint in self._fingerprints
        )

    def reserve(self, decision: ExitDecision, request: CloseRequest) -> bool:
        if self.duplicate(decision, request):
            return False
        self._decisions.add(decision.exit_decision_id)
        self._requests.add(request.close_request_id)
        self._fingerprints.add(request.request_fingerprint)
        return True

    def record_deal_reference(self, value: str) -> bool:
        if value in self._references:
            return False
        self._references.add(value)
        return True

    def snapshot(self) -> LifecycleIdempotencySnapshot:
        return LifecycleIdempotencySnapshot(
            consumed_exit_decisions=tuple(sorted(self._decisions)),
            consumed_close_requests=tuple(sorted(self._requests)),
            request_fingerprints=tuple(sorted(self._fingerprints)),
            deal_references=tuple(sorted(self._references)),
        )
