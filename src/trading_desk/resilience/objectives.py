"""Recovery-time and recovery-point objectives.

The recovery-point objective (RPO) bounds acceptable data loss and can only be
met if the backup cadence is at least as frequent as the objective and the most
recent backup is within the window. The recovery-time objective (RTO) bounds how
long recovery may take; an unmeasured recovery is reported as not-yet-met rather
than assumed satisfied.
"""

from __future__ import annotations

from pydantic import Field

from trading_desk.resilience.diagnostics import ResilienceModel


class RecoveryObjective(ResilienceModel):
    rto_seconds: int = Field(gt=0)
    rpo_seconds: int = Field(gt=0)
    backup_interval_seconds: int = Field(gt=0)


class ObjectiveAssessment(ResilienceModel):
    rpo_met: bool
    rto_met: bool
    cadence_supports_rpo: bool
    reasons: tuple[str, ...]


def assess_objectives(
    objective: RecoveryObjective,
    *,
    last_backup_age_seconds: int | None,
    observed_recovery_seconds: int | None,
) -> ObjectiveAssessment:
    """Assess RPO/RTO against measured backup age and recovery time."""

    reasons: list[str] = []
    cadence_supports_rpo = objective.backup_interval_seconds <= objective.rpo_seconds
    if not cadence_supports_rpo:
        reasons.append("BACKUP_CADENCE_EXCEEDS_RPO")

    if last_backup_age_seconds is None:
        rpo_met = False
        reasons.append("BACKUP_AGE_UNKNOWN")
    else:
        rpo_met = cadence_supports_rpo and last_backup_age_seconds <= objective.rpo_seconds
        if last_backup_age_seconds > objective.rpo_seconds:
            reasons.append("LAST_BACKUP_OLDER_THAN_RPO")

    if observed_recovery_seconds is None:
        rto_met = False
        reasons.append("RECOVERY_TIME_UNMEASURED")
    else:
        rto_met = observed_recovery_seconds <= objective.rto_seconds
        if not rto_met:
            reasons.append("RECOVERY_EXCEEDED_RTO")

    return ObjectiveAssessment(
        rpo_met=rpo_met,
        rto_met=rto_met,
        cadence_supports_rpo=cadence_supports_rpo,
        reasons=tuple(reasons),
    )
