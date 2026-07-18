"""Canonical fingerprints for context records and configuration."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel


def _primitive(value: object) -> Any:
    if isinstance(value, BaseModel):
        return _primitive(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported context fingerprint value: {type(value).__name__}")


def fingerprint(value: object) -> str:
    payload = json.dumps(_primitive(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
