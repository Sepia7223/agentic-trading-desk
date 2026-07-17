"""Typed bounded-scheduler failures."""


class SchedulerStateError(RuntimeError):
    """Raised when persisted scheduler state is malformed or inconsistent."""
