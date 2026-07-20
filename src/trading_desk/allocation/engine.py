"""Deterministic batch evaluation for portfolio construction.

One batch evaluates all candidates from a scheduling boundary against one
authoritative state snapshot. Reservations created by earlier ranked
candidates constrain later candidates in the same batch, the batch identity
is a pure function of its inputs (so repeated evaluation reproduces the same
decisions and reserves nothing twice), and every candidate leaves with a
durable ACCEPT, REJECT, or DEFER decision.

The engine proposes capital and quantity only. Risk recalculates and owns
the final approved quantity; nothing here touches broker state.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal

from trading_desk.allocation.correlation import CorrelationMatrix
from trading_desk.allocation.models import (
    PortfolioCandidate,
    PortfolioConstraints,
    PortfolioDecision,
    PortfolioDecisionType,
    PortfolioStateSnapshot,
    SizingPolicy,
    StrategyBudget,
    create_decision,
)
from trading_desk.allocation.ranking import RankingComponents, rank_candidates
from trading_desk.context.fingerprints import fingerprint

_QUANTITY_QUANTUM = Decimal("0.01")
_POLICY_PRECEDENCE = (
    SizingPolicy.FIXED_FRACTIONAL_RISK,
    SizingPolicy.VOLATILITY_TARGET,
    SizingPolicy.FIXED_CAPITAL,
)


@dataclass
class _BatchTally:
    """Reservations accumulated by earlier accepted candidates in the batch."""

    positions: int = 0
    capital: Decimal = Decimal("0")
    risk: Decimal = Decimal("0")
    instrument_exposure: dict[str, Decimal] = dataclass_field(default_factory=dict)
    strategy_exposure: dict[str, Decimal] = dataclass_field(default_factory=dict)
    group_exposure: dict[str, Decimal] = dataclass_field(default_factory=dict)
    currency_long: dict[str, Decimal] = dataclass_field(default_factory=dict)
    currency_short: dict[str, Decimal] = dataclass_field(default_factory=dict)
    strategy_positions: dict[str, int] = dataclass_field(default_factory=dict)
    strategy_entries: dict[str, int] = dataclass_field(default_factory=dict)


def batch_identity(
    snapshot: PortfolioStateSnapshot,
    candidates: tuple[PortfolioCandidate, ...],
    constraints: PortfolioConstraints,
) -> str:
    return fingerprint(
        {
            "snapshot": snapshot.snapshot_id,
            "candidates": tuple(sorted(item.candidate_id for item in candidates)),
            "constraints": constraints.fingerprint,
        }
    )


def _lookup(pairs: tuple[tuple[str, Decimal], ...], key: str) -> Decimal:
    for name, value in pairs:
        if name == key:
            return value
    return Decimal("0")


def _entries_lookup(pairs: tuple[tuple[str, int], ...], key: str) -> int:
    for name, value in pairs:
        if name == key:
            return value
    return 0


def _held_correlation(
    candidate: PortfolioCandidate,
    snapshot: PortfolioStateSnapshot,
    matrix: CorrelationMatrix | None,
) -> tuple[Decimal | None, tuple[str, ...]]:
    """Highest known correlation against held instruments, with reasons."""

    reasons: list[str] = []
    highest: Decimal | None = None
    for position in snapshot.confirmed_positions:
        if position.epic == candidate.epic:
            continue
        if matrix is None:
            reasons.append("CORRELATION_EVIDENCE_UNAVAILABLE")
            break
        pair = matrix.lookup(candidate.epic, position.epic)
        if pair is None or not pair.known or pair.value is None:
            reasons.append("CORRELATION_UNKNOWN")
            continue
        if highest is None or pair.value > highest:
            highest = pair.value
    return highest, tuple(dict.fromkeys(reasons))


def _sizing(
    candidate: PortfolioCandidate,
    snapshot: PortfolioStateSnapshot,
    constraints: PortfolioConstraints,
    budget: StrategyBudget,
) -> tuple[SizingPolicy, Decimal, Decimal]:
    """First enabled policy in fixed precedence; returns (policy, capital, quantity)."""

    policy = next(
        (item for item in _POLICY_PRECEDENCE if item in budget.enabled_policies),
        None,
    )
    if policy is None:
        raise ValueError("strategy budget enables no deterministic sizing policy")
    if policy is SizingPolicy.FIXED_CAPITAL:
        capital = budget.fixed_capital_amount
        quantity = capital / candidate.entry_reference
    elif policy is SizingPolicy.FIXED_FRACTIONAL_RISK:
        risk_budget = snapshot.account_equity * budget.maximum_risk_fraction
        quantity = risk_budget / candidate.proposed_risk_distance
        capital = quantity * candidate.entry_reference
    else:
        risk_budget = snapshot.account_equity * constraints.volatility_target_fraction
        quantity = risk_budget / candidate.proposed_risk_distance
        capital = quantity * candidate.entry_reference
    quantity = quantity.quantize(_QUANTITY_QUANTUM, rounding=ROUND_FLOOR)
    capital = (quantity * candidate.entry_reference).quantize(Decimal("0.01"))
    return policy, capital, quantity


def evaluate_batch(
    *,
    candidates: tuple[PortfolioCandidate, ...],
    components: tuple[RankingComponents, ...],
    snapshot: PortfolioStateSnapshot,
    constraints: PortfolioConstraints,
    budgets: tuple[StrategyBudget, ...],
    correlation: CorrelationMatrix | None,
    decided_at: datetime,
) -> tuple[PortfolioDecision, ...]:
    """Evaluate one deterministic batch and return one decision per candidate."""

    batch_id = batch_identity(snapshot, candidates, constraints)
    budget_by_strategy = {item.strategy_id: item for item in budgets}
    ranked = rank_candidates(candidates, components)
    tally = _BatchTally()
    tally.positions = len(snapshot.confirmed_positions) + len(snapshot.pending_reservations)
    for reservation in snapshot.pending_reservations:
        tally.capital += reservation.reserved_capital
        tally.risk += reservation.reserved_risk
    decisions: list[PortfolioDecision] = []

    for entry in ranked:
        candidate = entry.candidate
        reasons: list[str] = []
        binding: list[str] = []
        defer_reasons: list[str] = []

        if not snapshot.state_complete:
            reasons.append("STATE_INCOMPLETE")
        if snapshot.entries_halted:
            reasons.append("ENTRIES_HALTED")
        if not entry.components.eligible:
            reasons.append("CANDIDATE_INELIGIBLE")
        if candidate.net_expected_value <= 0:
            reasons.append("NON_POSITIVE_NET_EXPECTED_VALUE")

        cooldown_until = next(
            (until for epic, until in snapshot.recent_close_cooldowns if epic == candidate.epic),
            None,
        )
        if cooldown_until is not None and cooldown_until > decided_at:
            reasons.append("COOLDOWN_ACTIVE")

        budget = budget_by_strategy.get(candidate.strategy_id)
        if budget is None:
            reasons.append("STRATEGY_BUDGET_MISSING")

        correlation_value, correlation_reasons = _held_correlation(candidate, snapshot, correlation)
        if correlation_reasons:
            reasons.extend(correlation_reasons)
        if (
            correlation_value is not None
            and correlation_value >= constraints.correlation_rejection_threshold
        ):
            reasons.append("CORRELATION_REJECTED")
            binding.append("correlation_rejection_threshold")

        sized: tuple[SizingPolicy, Decimal, Decimal] | None = None
        if not reasons and budget is not None:
            sized = _sizing(candidate, snapshot, constraints, budget)
            policy, capital, quantity = sized
            risk_amount = quantity * candidate.proposed_risk_distance
            equity = snapshot.account_equity

            if quantity <= 0:
                reasons.append("PROPOSED_QUANTITY_BELOW_MINIMUM")

            daily_entries = _entries_lookup(
                snapshot.strategy_daily_entries, candidate.strategy_id
            ) + tally.strategy_entries.get(candidate.strategy_id, 0)
            if daily_entries >= budget.maximum_daily_entries:
                reasons.append("STRATEGY_DAILY_ENTRIES_EXHAUSTED")
                binding.append("maximum_daily_entries")

            strategy_positions = sum(
                1
                for item in snapshot.confirmed_positions
                if item.strategy_id == candidate.strategy_id
            ) + tally.strategy_positions.get(candidate.strategy_id, 0)
            if strategy_positions >= budget.maximum_concurrent_positions:
                defer_reasons.append("STRATEGY_CAPACITY_RESERVED")
                binding.append("maximum_concurrent_positions")

            if tally.positions >= constraints.maximum_concurrent_positions:
                defer_reasons.append("PORTFOLIO_CAPACITY_RESERVED")
                binding.append("maximum_concurrent_positions")

            margin = (capital * constraints.margin_factor).quantize(Decimal("0.01"))
            if margin > snapshot.available_capital - tally.capital:
                defer_reasons.append("INSUFFICIENT_AVAILABLE_CAPITAL")
                binding.append("available_capital")

            if (
                snapshot.daily_deployed_capital + tally.capital + margin
                > equity * constraints.maximum_daily_capital_fraction
            ):
                defer_reasons.append("DAILY_CAPITAL_BUDGET_RESERVED")
                binding.append("maximum_daily_capital_fraction")

            total_risk = tally.risk + risk_amount
            for position in snapshot.confirmed_positions:
                total_risk += position.open_risk
            if total_risk > equity * constraints.maximum_total_risk_fraction:
                reasons.append("TOTAL_RISK_LIMIT")
                binding.append("maximum_total_risk_fraction")

            instrument_exposure = (
                _lookup(snapshot.instrument_exposure, candidate.epic)
                + tally.instrument_exposure.get(candidate.epic, Decimal("0"))
                + capital
            )
            if instrument_exposure > equity * constraints.maximum_instrument_exposure_fraction:
                reasons.append("INSTRUMENT_EXPOSURE_LIMIT")
                binding.append("maximum_instrument_exposure_fraction")

            strategy_exposure = (
                _lookup(snapshot.strategy_allocated_capital, candidate.strategy_id)
                + tally.strategy_exposure.get(candidate.strategy_id, Decimal("0"))
                + capital
            )
            if strategy_exposure > min(
                equity * constraints.maximum_strategy_exposure_fraction,
                budget.maximum_allocated_capital,
            ):
                reasons.append("STRATEGY_EXPOSURE_LIMIT")
                binding.append("maximum_strategy_exposure_fraction")

            group_exposure = (
                _lookup(snapshot.correlation_group_exposure, candidate.correlation_group)
                + tally.group_exposure.get(candidate.correlation_group, Decimal("0"))
                + capital
            )
            if group_exposure > equity * constraints.maximum_correlation_group_exposure_fraction:
                reasons.append("CORRELATION_GROUP_EXPOSURE_LIMIT")
                binding.append("maximum_correlation_group_exposure_fraction")

            long_exposure = (
                _lookup(snapshot.currency_long_exposure, candidate.base_currency)
                + tally.currency_long.get(candidate.base_currency, Decimal("0"))
                + capital
            )
            if long_exposure > equity * constraints.maximum_currency_long_fraction:
                reasons.append("CURRENCY_LONG_EXPOSURE_LIMIT")
                binding.append("maximum_currency_long_fraction")

            short_exposure = (
                _lookup(snapshot.currency_short_exposure, candidate.quote_currency)
                + tally.currency_short.get(candidate.quote_currency, Decimal("0"))
                + capital
            )
            if short_exposure > equity * constraints.maximum_currency_short_fraction:
                reasons.append("CURRENCY_SHORT_EXPOSURE_LIMIT")
                binding.append("maximum_currency_short_fraction")

        idempotency_key = fingerprint({"batch": batch_id, "candidate": candidate.candidate_id})
        common = {
            "idempotency_key": idempotency_key,
            "batch_id": batch_id,
            "candidate_id": candidate.candidate_id,
            "rank": entry.rank,
            "binding_constraints": tuple(dict.fromkeys(binding)),
            "correlation_value": correlation_value,
            "concentration_value": entry.components.concentration_penalty,
            "candidate_fingerprint": fingerprint(candidate.model_dump(mode="python")),
            "state_snapshot_id": snapshot.snapshot_id,
            "configuration_fingerprint": constraints.fingerprint,
            "decided_at": decided_at,
        }
        if reasons:
            decisions.append(
                create_decision(
                    **common,
                    decision=PortfolioDecisionType.REJECT,
                    reason_codes=tuple(dict.fromkeys(reasons + defer_reasons)),
                )
            )
        elif defer_reasons:
            decisions.append(
                create_decision(
                    **common,
                    decision=PortfolioDecisionType.DEFER,
                    reason_codes=tuple(dict.fromkeys(defer_reasons)),
                    defer_expires_at=decided_at
                    + timedelta(seconds=constraints.defer_validity_seconds),
                )
            )
        else:
            assert sized is not None
            policy, capital, quantity = sized
            decisions.append(
                create_decision(
                    **common,
                    decision=PortfolioDecisionType.ACCEPT,
                    proposed_capital=capital,
                    proposed_quantity=quantity,
                    sizing_policy=policy,
                )
            )
            tally.positions += 1
            tally.capital += (capital * constraints.margin_factor).quantize(Decimal("0.01"))
            tally.risk += quantity * candidate.proposed_risk_distance
            tally.instrument_exposure[candidate.epic] = (
                tally.instrument_exposure.get(candidate.epic, Decimal("0")) + capital
            )
            tally.strategy_exposure[candidate.strategy_id] = (
                tally.strategy_exposure.get(candidate.strategy_id, Decimal("0")) + capital
            )
            tally.group_exposure[candidate.correlation_group] = (
                tally.group_exposure.get(candidate.correlation_group, Decimal("0")) + capital
            )
            tally.currency_long[candidate.base_currency] = (
                tally.currency_long.get(candidate.base_currency, Decimal("0")) + capital
            )
            tally.currency_short[candidate.quote_currency] = (
                tally.currency_short.get(candidate.quote_currency, Decimal("0")) + capital
            )
            tally.strategy_positions[candidate.strategy_id] = (
                tally.strategy_positions.get(candidate.strategy_id, 0) + 1
            )
            tally.strategy_entries[candidate.strategy_id] = (
                tally.strategy_entries.get(candidate.strategy_id, 0) + 1
            )

    return tuple(decisions)
