"""Canonical secret-free serialization for deterministic risk records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel


def canonicalize(value: object) -> object:
    """Convert supported values into stable JSON-compatible primitives."""
    if isinstance(value, BaseModel):
        return canonicalize(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): canonicalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [canonicalize(item) for item in value]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal cannot be fingerprinted")
        if value.is_zero():
            return "0"
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime cannot be fingerprinted")
        normalized = value.astimezone(UTC).isoformat(timespec="microseconds")
        return normalized.replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, timedelta):
        return canonicalize(Decimal(str(value.total_seconds())))
    if isinstance(value, Enum):
        return canonicalize(value.value)
    if isinstance(value, float):
        raise TypeError("binary floating point is prohibited in risk fingerprints")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json(value: object) -> str:
    return json.dumps(
        canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def model_fingerprint(model: BaseModel, *, exclude: set[str] | None = None) -> str:
    payload: dict[str, Any] = model.model_dump(mode="python", exclude=exclude or set())
    return fingerprint(payload)
