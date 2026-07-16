"""Canonical, secret-rejecting serialization and SHA-256 fingerprints."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, SecretBytes, SecretStr

_FORBIDDEN_KEYS = (
    "password",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "x-security-token",
    "cst",
)
_RAW_DATA_KEYS = frozenset(
    {
        "raw_provider_response",
        "raw_response",
        "raw_login_response",
        "http_headers",
        "request_headers",
        "response_headers",
        "authentication_body",
    }
)
_IDENTIFIER_KEYS = frozenset({"account_id", "preferred_account_id", "active_account_id"})
_SECRET_VALUE = re.compile(
    r"(?i)(?:\bbearer\s+\S+|\b(?:cst|x-security-token|api[_ -]?key|password|"
    r"access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*\S+)"
)
_MACHINE_PATH = re.compile(
    r"(?:\b[A-Za-z]:[\\/]|\\\\[^\\\s]+[\\/][^\s]+|(?:^|\s)~[\\/]|"
    r"(?:^|\s)/(?:Users|home|etc|var|tmp)(?:/|\b))"
)


def reject_secret_fields(value: object, path: str = "payload") -> None:
    """Reject secret objects and keys before persistence or export."""
    if isinstance(value, (SecretStr, SecretBytes)):
        raise ValueError(f"secret value is prohibited at {path}")
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        raise ValueError(f"secret-like value is prohibited at {path}")
    if isinstance(value, BaseModel):
        reject_secret_fields(value.model_dump(mode="python"), path)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(token.replace("-", "_") in normalized for token in _FORBIDDEN_KEYS):
                raise ValueError(f"secret-bearing field is prohibited at {path}.{key}")
            if normalized in _IDENTIFIER_KEYS:
                raise ValueError(f"full account identifier is prohibited at {path}.{key}")
            reject_secret_fields(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for index, item in enumerate(value):
            reject_secret_fields(item, f"{path}[{index}]")


def reject_machine_paths(value: object, path: str = "payload") -> None:
    """Keep local filesystem paths out of historical evidence."""
    if isinstance(value, Path):
        raise ValueError(f"filesystem path is prohibited at {path}")
    if isinstance(value, str) and _MACHINE_PATH.search(value):
        raise ValueError(f"filesystem path is prohibited at {path}")
    if isinstance(value, BaseModel):
        reject_machine_paths(value.model_dump(mode="python"), path)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            reject_machine_paths(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for index, item in enumerate(value):
            reject_machine_paths(item, f"{path}[{index}]")


def reject_raw_provider_data(value: object, path: str = "payload") -> None:
    if isinstance(value, BaseModel):
        reject_raw_provider_data(value.model_dump(mode="python"), path)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _RAW_DATA_KEYS:
                raise ValueError(f"raw provider data is prohibited at {path}.{key}")
            reject_raw_provider_data(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for index, item in enumerate(value):
            reject_raw_provider_data(item, f"{path}[{index}]")


def to_primitive(value: object) -> Any:
    """Convert supported values to deterministic JSON primitives."""
    if isinstance(value, BaseModel):
        return to_primitive(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return to_primitive(value.value)
    if isinstance(value, Decimal):
        return {"__decimal__": format(value, "f")}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): to_primitive(item)
            for key, item in sorted(value.items(), key=lambda x: str(x[0]))
        }
    if isinstance(value, (list, tuple)):
        return [to_primitive(item) for item in value]
    if isinstance(value, (set, frozenset)):
        converted = [to_primitive(item) for item in value]
        return sorted(converted, key=lambda item: json.dumps(item, sort_keys=True))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported journal value type: {type(value).__name__}")


def canonical_json(value: object) -> str:
    reject_secret_fields(value)
    return json.dumps(
        to_primitive(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sanitize_export_value(value: object) -> Any:
    """Redact unsafe historical values as a second boundary before export."""
    primitive = to_primitive(value)
    return _sanitize_export_primitive(primitive)


def _sanitize_export_primitive(value: Any) -> Any:
    if isinstance(value, str):
        if _SECRET_VALUE.search(value) or _MACHINE_PATH.search(value):
            return "[REDACTED]"
        return value
    if isinstance(value, list):
        return [_sanitize_export_primitive(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_export_primitive(item) for key, item in value.items()}
    return value


def decode_primitive(value: Any) -> Any:
    if isinstance(value, list):
        return [decode_primitive(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"__decimal__"}:
            return Decimal(value["__decimal__"])
        if set(value) == {"__datetime__"}:
            return datetime.fromisoformat(value["__datetime__"])
        if set(value) == {"__date__"}:
            return date.fromisoformat(value["__date__"])
        return {key: decode_primitive(item) for key, item in value.items()}
    return value


def decode_json(value: str) -> Any:
    return decode_primitive(json.loads(value))
