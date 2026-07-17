"""Persistent bounded scheduler planning deterministic actions only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import ContextTimeframe
from trading_desk.scheduler.clock import cadence_boundary, completed_bar_boundary
from trading_desk.scheduler.config import SchedulerConfiguration
from trading_desk.scheduler.errors import SchedulerStateError
from trading_desk.scheduler.models import (
    ScheduledAction,
    ScheduledActionType,
    SchedulerCycle,
    SchedulerState,
)


class JsonSchedulerStateStore:
    """Explicit-path local state; callers decide where runtime data lives."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> SchedulerState:
        if not self.path.exists():
            return SchedulerState()
        try:
            return SchedulerState.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SchedulerStateError("scheduler state could not be validated") from exc

    def save(self, state: SchedulerState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.path)


class DeterministicScheduler:
    def __init__(self, config: SchedulerConfiguration | None = None) -> None:
        self.config = config or SchedulerConfiguration()

    def plan_cycle(
        self,
        now: datetime,
        state: SchedulerState,
        *,
        execution_halted: bool = False,
    ) -> SchedulerCycle:
        if now.tzinfo is None:
            raise ValueError("scheduler timestamp must be timezone-aware")
        now = now.astimezone(UTC)
        completed = set(state.completed_action_ids)
        actions: list[ScheduledAction] = []
        cadence = (
            (ScheduledActionType.MARKET_HEALTH, self.config.health_interval_seconds),
            (ScheduledActionType.EXECUTION_STATE_VERIFICATION, self.config.health_interval_seconds),
            (ScheduledActionType.ECONOMIC_CALENDAR, self.config.calendar_interval_seconds),
            (
                ScheduledActionType.POSITION_RECONCILIATION,
                self.config.reconciliation_interval_seconds,
            ),
        )
        for action_type, interval in cadence:
            due = cadence_boundary(now, interval)
            action = _action(action_type, due)
            if action.action_id not in completed:
                actions.append(action)
        if not execution_halted:
            for timeframe in self.config.strategy_timeframes:
                boundary = completed_bar_boundary(now, timeframe)
                action = _action(
                    ScheduledActionType.STRATEGY_BAR,
                    boundary,
                    timeframe=timeframe,
                    completed_bar_timestamp=boundary,
                )
                if action.action_id not in completed:
                    actions.append(action)
        actions = sorted(actions, key=lambda item: (item.due_timestamp, item.action_type.value))[
            : self.config.maximum_actions_per_cycle
        ]
        fields = {
            "evaluated_at": now,
            "actions": tuple(actions),
            "execution_halted": execution_halted,
            "configuration_fingerprint": self.config.configuration_fingerprint,
        }
        return SchedulerCycle.model_validate({"cycle_id": fingerprint(fields), **fields})

    def apply(self, state: SchedulerState, cycle: SchedulerCycle) -> SchedulerState:
        action_ids = tuple(
            dict.fromkeys((*state.completed_action_ids, *(a.action_id for a in cycle.actions)))
        )
        bars = dict(state.last_completed_bars)
        for action in cycle.actions:
            if action.timeframe and action.completed_bar_timestamp:
                bars[action.timeframe] = action.completed_bar_timestamp
        return SchedulerState(
            completed_action_ids=action_ids[-10000:],
            last_completed_bars=tuple(sorted(bars.items(), key=lambda item: item[0].value)),
            updated_at=cycle.evaluated_at,
        )


def _action(
    action_type: ScheduledActionType,
    due: datetime,
    *,
    timeframe: ContextTimeframe | None = None,
    completed_bar_timestamp: datetime | None = None,
) -> ScheduledAction:
    fields = {
        "action_type": action_type,
        "due_timestamp": due,
        "timeframe": timeframe,
        "completed_bar_timestamp": completed_bar_timestamp,
    }
    return ScheduledAction.model_validate({"action_id": fingerprint(fields), **fields})
