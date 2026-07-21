"""Post-submission order lifecycle: the checklist's missing final section.

The pre-trade pipeline ends at approval; this module governs everything after
transmission, fail-closed:

  submitted -> (partial) fills -> protection confirmed        -> PROTECTED
            -> unfilled past timeout                          -> CANCEL
            -> partial fill past timeout                      -> CANCEL REMAINDER
                                                                 + PROTECT FILLED
            -> protection rejected / not confirmed in time    -> CANCEL REMAINDER
                                                                 + CLOSE POSITION
                                                                 + INCIDENT LOCK

The incident lock may only be cleared by a human. Fill quality is measured
against the modeled cost so execution-model drift is detected instead of
silently absorbed. Pure logic: the caller supplies events; no broker I/O here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class OrderPhase(StrEnum):
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED_UNPROTECTED = "FILLED_UNPROTECTED"
    PROTECTED = "PROTECTED"
    CANCELLED = "CANCELLED"
    INCIDENT = "INCIDENT"


class LifecycleAction(StrEnum):
    WAIT = "WAIT"
    SUBMIT_PROTECTION = "SUBMIT_PROTECTION"
    CANCEL_REMAINDER = "CANCEL_REMAINDER"
    CLOSE_UNPROTECTED_POSITION = "CLOSE_UNPROTECTED_POSITION"
    ACTIVATE_INCIDENT_LOCK = "ACTIVATE_INCIDENT_LOCK"
    RECORD_FILL_QUALITY_BREACH = "RECORD_FILL_QUALITY_BREACH"


class LifecyclePolicy(_Frozen):
    """Timeouts and tolerances; change only by written decision."""

    entry_fill_timeout_seconds: int = Field(default=120, gt=0)
    protection_confirm_timeout_seconds: int = Field(default=30, gt=0)
    fill_cost_tolerance_bps: Decimal = Field(default=Decimal("10"), ge=0)


class OrderSnapshot(_Frozen):
    """Caller-maintained view of one working order and its protection."""

    submitted_at: datetime
    quantity: Decimal = Field(gt=0)
    filled_quantity: Decimal = Field(ge=0)
    first_fill_at: datetime | None = None
    protection_submitted: bool = False
    protection_confirmed: bool = False
    protection_rejected: bool = False
    modeled_cost_bps: Decimal = Field(default=Decimal("0"), ge=0)
    realized_cost_bps: Decimal | None = None


class LifecycleDecision(_Frozen):
    phase: OrderPhase
    actions: tuple[LifecycleAction, ...]
    detail: str


def evaluate_order(
    order: OrderSnapshot, now: datetime, policy: LifecyclePolicy | None = None
) -> LifecycleDecision:
    """Decide the required actions for one order snapshot, fail-closed."""

    p = policy or LifecyclePolicy()
    age = (now - order.submitted_at).total_seconds()
    filled = order.filled_quantity
    actions: list[LifecycleAction] = []

    # fill-quality drift detection (advisory action, never blocks safety flow)
    quality_breach = (
        order.realized_cost_bps is not None
        and order.realized_cost_bps > order.modeled_cost_bps + p.fill_cost_tolerance_bps
    )
    if quality_breach:
        actions.append(LifecycleAction.RECORD_FILL_QUALITY_BREACH)

    # 1) protection explicitly rejected with exposure on: full incident path
    if order.protection_rejected and filled > 0:
        actions += [
            LifecycleAction.CANCEL_REMAINDER,
            LifecycleAction.CLOSE_UNPROTECTED_POSITION,
            LifecycleAction.ACTIVATE_INCIDENT_LOCK,
        ]
        return LifecycleDecision(
            phase=OrderPhase.INCIDENT,
            actions=tuple(actions),
            detail="protection rejected with exposure on: close + incident lock",
        )

    # 2) nothing filled
    if filled == 0:
        if age > p.entry_fill_timeout_seconds:
            actions.append(LifecycleAction.CANCEL_REMAINDER)
            return LifecycleDecision(
                phase=OrderPhase.CANCELLED,
                actions=tuple(actions),
                detail=f"unfilled after {int(age)}s: cancel",
            )
        return LifecycleDecision(
            phase=OrderPhase.SUBMITTED,
            actions=tuple(actions) or (LifecycleAction.WAIT,),
            detail="working, within fill timeout",
        )

    # 3) some or all filled: exposure exists -> protection is mandatory
    if order.protection_confirmed:
        if filled < order.quantity and age > p.entry_fill_timeout_seconds:
            actions.append(LifecycleAction.CANCEL_REMAINDER)
            return LifecycleDecision(
                phase=OrderPhase.PROTECTED,
                actions=tuple(actions),
                detail="partial past timeout: keep protected fill, cancel rest",
            )
        return LifecycleDecision(
            phase=OrderPhase.PROTECTED,
            actions=tuple(actions) or (LifecycleAction.WAIT,),
            detail="filled and protected",
        )

    if not order.protection_submitted:
        actions.append(LifecycleAction.SUBMIT_PROTECTION)
        return LifecycleDecision(
            phase=OrderPhase.FILLED_UNPROTECTED,
            actions=tuple(actions),
            detail="exposure on without protection submitted: submit now",
        )

    # protection submitted but unconfirmed
    ref = order.first_fill_at or order.submitted_at
    unprotected_for = (now - ref).total_seconds()
    if unprotected_for > p.protection_confirm_timeout_seconds:
        actions += [
            LifecycleAction.CANCEL_REMAINDER,
            LifecycleAction.CLOSE_UNPROTECTED_POSITION,
            LifecycleAction.ACTIVATE_INCIDENT_LOCK,
        ]
        return LifecycleDecision(
            phase=OrderPhase.INCIDENT,
            actions=tuple(actions),
            detail=(
                f"protection unconfirmed {int(unprotected_for)}s "
                "with exposure on: close + incident lock"
            ),
        )
    phase = (
        OrderPhase.PARTIALLY_FILLED if filled < order.quantity else OrderPhase.FILLED_UNPROTECTED
    )
    return LifecycleDecision(
        phase=phase,
        actions=tuple(actions) or (LifecycleAction.WAIT,),
        detail="awaiting protection confirmation within timeout",
    )
