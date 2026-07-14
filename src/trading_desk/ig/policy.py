"""Central read-only operation and path policy for the IG demo adapter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from trading_desk.ig.errors import ReadOnlyPolicyViolation

LOGIN_VERSION = 3
LOGOUT_VERSION = 1
ACCOUNTS_VERSION = 1
POSITIONS_VERSION = 2
MARKET_SEARCH_VERSION = 1
MARKET_DETAILS_VERSION = 3
HISTORICAL_PRICES_VERSION = 3

EPIC_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}\Z")


class Operation(StrEnum):
    LOGIN = "login"
    LOGOUT = "logout"
    ACCOUNTS = "accounts"
    POSITIONS = "positions"
    MARKET_SEARCH = "market_search"
    MARKET_DETAILS = "market_details"
    HISTORICAL_PRICES = "historical_prices"


@dataclass(frozen=True, slots=True)
class AllowedRequest:
    method: str
    path_pattern: re.Pattern[str]
    version: int
    requires_session: bool


_EXACT_SESSION = re.compile(r"/session\Z")
_EXACT_ACCOUNTS = re.compile(r"/accounts\Z")
_EXACT_POSITIONS = re.compile(r"/positions\Z")
_EXACT_MARKETS = re.compile(r"/markets\Z")
_MARKET_DETAILS = re.compile(r"/markets/([A-Za-z0-9][A-Za-z0-9._:-]{0,79})\Z")
_HISTORICAL_PRICES = re.compile(r"/prices/([A-Za-z0-9][A-Za-z0-9._:-]{0,79})\Z")

READ_ONLY_ENDPOINT_ALLOWLIST: dict[Operation, AllowedRequest] = {
    Operation.LOGIN: AllowedRequest("POST", _EXACT_SESSION, LOGIN_VERSION, False),
    Operation.LOGOUT: AllowedRequest("DELETE", _EXACT_SESSION, LOGOUT_VERSION, True),
    Operation.ACCOUNTS: AllowedRequest("GET", _EXACT_ACCOUNTS, ACCOUNTS_VERSION, True),
    Operation.POSITIONS: AllowedRequest("GET", _EXACT_POSITIONS, POSITIONS_VERSION, True),
    Operation.MARKET_SEARCH: AllowedRequest("GET", _EXACT_MARKETS, MARKET_SEARCH_VERSION, True),
    Operation.MARKET_DETAILS: AllowedRequest("GET", _MARKET_DETAILS, MARKET_DETAILS_VERSION, True),
    Operation.HISTORICAL_PRICES: AllowedRequest(
        "GET", _HISTORICAL_PRICES, HISTORICAL_PRICES_VERSION, True
    ),
}


def validate_epic(epic: str) -> str:
    if not isinstance(epic, str) or not EPIC_PATTERN.fullmatch(epic):
        raise ReadOnlyPolicyViolation("EPIC is empty or contains unsupported characters")
    return epic


def validate_search_term(search_term: str) -> str:
    if not isinstance(search_term, str):
        raise ReadOnlyPolicyViolation("market search term must be text")
    normalized = search_term.strip()
    if not normalized or len(normalized) > 100:
        raise ReadOnlyPolicyViolation("market search term must contain 1 to 100 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ReadOnlyPolicyViolation("market search term contains control characters")
    return normalized


def enforce_read_only_policy(
    operation: Operation,
    method: str,
    path: str,
    version: int,
) -> AllowedRequest:
    """Reject anything outside the named operation allowlist before transport."""

    _validate_relative_path(path)
    allowed = READ_ONLY_ENDPOINT_ALLOWLIST.get(operation)
    normalized_method = method.upper()
    if (
        allowed is None
        or normalized_method != allowed.method
        or version != allowed.version
        or allowed.path_pattern.fullmatch(path) is None
    ):
        raise ReadOnlyPolicyViolation(
            f"operation {operation.value!r} does not allow {normalized_method} {path!r} v{version}"
        )
    return allowed


def _validate_relative_path(path: str) -> None:
    if not isinstance(path, str) or not path or not path.startswith("/"):
        raise ReadOnlyPolicyViolation("IG path must be a non-empty relative API path")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc:
        raise ReadOnlyPolicyViolation("absolute IG URLs are forbidden")
    if (
        path.startswith("//")
        or path.endswith("/")
        or "//" in path
        or ".." in path
        or "%" in path
        or "\\" in path
        or "?" in path
        or "#" in path
        or parsed.query
        or parsed.fragment
    ):
        raise ReadOnlyPolicyViolation("IG path contains forbidden path manipulation")
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise ReadOnlyPolicyViolation("IG path contains control characters")
