"""Exact allowlist for controlled IG Demo position opening and confirmation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from trading_desk.execution.errors import ExecutionPolicyViolation

OPEN_POSITION_VERSION = 2
CLOSE_POSITION_VERSION = 1
DEAL_CONFIRMATION_VERSION = 1
DEAL_REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,30}\Z")


class ExecutionOperation(StrEnum):
    OPEN_POSITION = "open_position"
    CLOSE_POSITION = "close_position"
    DEAL_CONFIRMATION = "deal_confirmation"


@dataclass(frozen=True, slots=True)
class AllowedExecutionRequest:
    method: str
    path_pattern: re.Pattern[str]
    version: int


EXECUTION_ENDPOINT_ALLOWLIST = {
    ExecutionOperation.OPEN_POSITION: AllowedExecutionRequest(
        "POST", re.compile(r"/positions/otc\Z"), OPEN_POSITION_VERSION
    ),
    ExecutionOperation.CLOSE_POSITION: AllowedExecutionRequest(
        "DELETE", re.compile(r"/positions/otc\Z"), CLOSE_POSITION_VERSION
    ),
    ExecutionOperation.DEAL_CONFIRMATION: AllowedExecutionRequest(
        "GET",
        re.compile(r"/confirms/[A-Za-z0-9_-]{1,30}\Z"),
        DEAL_CONFIRMATION_VERSION,
    ),
}


def validate_deal_reference(value: str) -> str:
    if not isinstance(value, str) or DEAL_REFERENCE_PATTERN.fullmatch(value) is None:
        raise ExecutionPolicyViolation("deal reference contains unsupported characters")
    return value


def enforce_execution_policy(
    operation: ExecutionOperation,
    method: str,
    path: str,
    version: int,
) -> AllowedExecutionRequest:
    _validate_relative_path(path)
    allowed = EXECUTION_ENDPOINT_ALLOWLIST.get(operation)
    normalized_method = method.upper()
    if (
        allowed is None
        or allowed.method != normalized_method
        or allowed.version != version
        or allowed.path_pattern.fullmatch(path) is None
    ):
        raise ExecutionPolicyViolation("operation is outside the execution endpoint allowlist")
    return allowed


def _validate_relative_path(path: str) -> None:
    if not isinstance(path, str) or not path.startswith("/") or not path:
        raise ExecutionPolicyViolation("execution path must be relative")
    parsed = urlsplit(path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or path.startswith("//")
        or path.endswith("/")
        or "//" in path
        or ".." in path
        or "%" in path
        or "\\" in path
        or "?" in path
        or "#" in path
    ):
        raise ExecutionPolicyViolation("execution path contains forbidden manipulation")
