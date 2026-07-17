"""Typed Demo position lifecycle errors."""


class LifecycleError(RuntimeError):
    """Base lifecycle failure."""


class LifecycleConfigurationError(LifecycleError):
    """Lifecycle configuration violates the Demo-only boundary."""


class LifecyclePolicyViolation(LifecycleError):
    """A close request is outside the exact mutation allowlist."""


class LifecycleStateError(LifecycleError):
    """Persistent lifecycle state is unavailable or invalid."""
