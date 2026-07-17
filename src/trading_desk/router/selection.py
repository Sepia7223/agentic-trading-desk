"""Deterministic priority selection with no AI authority."""

from trading_desk.router.config import RouterConfiguration


def select_strategy(eligible: tuple[str, ...], config: RouterConfiguration) -> str | None:
    if not eligible:
        return None
    if config.reject_ambiguous_priority and len(eligible) > 1:
        return None
    order = {identifier: index for index, identifier in enumerate(config.strategy_priority)}
    return min(eligible, key=lambda identifier: (order.get(identifier, len(order)), identifier))
