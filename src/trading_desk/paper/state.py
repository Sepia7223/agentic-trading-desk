"""Restart-safe paper-trading state + operable kill switches.

Everything the daily session needs to survive a restart lives in one JSON file:
positions, cash, queued orders, equity history, realized-trade outcomes
(consecutive-loss tracking), idempotency keys, and the daily anchor values the
account checks need. A JSONL journal records every event append-only.

Kill switches are FILES a human can create/delete with no tooling:
    data/paper/KILL_GLOBAL     -> global kill switch active
    data/paper/KILL_STRATEGY   -> strategy kill switch active
    data/paper/INCIDENT_LOCK   -> incident lock (created by the lifecycle
                                  layer on protection failure; only a human
                                  deletes it)
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from trading_desk.paper.broker import PaperOrder, Position

GLOBAL_KILL_FILE = "KILL_GLOBAL"
STRATEGY_KILL_FILE = "KILL_STRATEGY"
INCIDENT_LOCK_FILE = "INCIDENT_LOCK"


class PaperState(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    cash: Decimal
    start_equity: Decimal
    positions: dict[str, Position] = Field(default_factory=dict)
    queued_orders: list[PaperOrder] = Field(default_factory=list)
    equity_by_day: dict[str, Decimal] = Field(default_factory=dict)
    peak_equity: Decimal = Decimal("0")
    day_start_equity: Decimal = Decimal("0")
    day_start_date: str = ""
    trades_today: int = 0
    consecutive_losses: int = 0
    seen_idempotency_keys: list[str] = Field(default_factory=list)
    last_session: str = ""

    def roll_day(self, session: date, equity: Decimal) -> None:
        key = session.isoformat()
        if self.day_start_date != key:
            self.day_start_date = key
            self.day_start_equity = equity
            self.trades_today = 0
        self.equity_by_day[key] = equity
        self.peak_equity = max(self.peak_equity, equity)
        self.last_session = key

    def daily_loss_fraction(self, equity: Decimal) -> Decimal:
        if self.day_start_equity <= 0:
            return Decimal("0")
        loss = (self.day_start_equity - equity) / self.day_start_equity
        return max(loss, Decimal("0"))

    def drawdown_fraction(self, equity: Decimal) -> Decimal:
        if self.peak_equity <= 0:
            return Decimal("0")
        dd = (self.peak_equity - equity) / self.peak_equity
        return max(dd, Decimal("0"))

    def record_round_trip(self, pnl: Decimal) -> None:
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0


def state_path(root: Path) -> Path:
    return root / "paper_state.json"


def load_state(root: Path, start_equity: Decimal) -> PaperState:
    path = state_path(root)
    if path.exists():
        return PaperState.model_validate_json(path.read_text(encoding="utf-8"))
    return PaperState(
        cash=start_equity,
        start_equity=start_equity,
        peak_equity=start_equity,
        day_start_equity=start_equity,
    )


def save_state(root: Path, state: PaperState) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = state_path(root).with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(indent=1), encoding="utf-8")
    tmp.replace(state_path(root))


def journal(root: Path, record: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "journal.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def kill_switch_active(root: Path, name: str) -> bool:
    return (root / name).exists()


def activate_incident_lock(root: Path, reason: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / INCIDENT_LOCK_FILE).write_text(reason, encoding="utf-8")
