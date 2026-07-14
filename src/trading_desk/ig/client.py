"""Authenticated, strictly read-only IG REST demo adapter."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any, NoReturn

import httpx
from pydantic import SecretStr, ValidationError

from trading_desk.config import (
    IG_DEMO_BASE_URL,
    AppSettings,
    BrokerEnvironment,
    OperatingMode,
)
from trading_desk.ig.errors import (
    IGAPIError,
    IGAuthenticationError,
    IGAuthorizationError,
    IGConfigurationError,
    IGRateLimitError,
    IGResponseValidationError,
    IGSessionMissingError,
)
from trading_desk.ig.models import (
    Account,
    AccountBalance,
    AccountType,
    APIAllowanceMetadata,
    AuthenticatedSessionSummary,
    DealingRuleUnit,
    DealingRuleValue,
    Direction,
    HistoricalPriceBar,
    HistoricalPricePage,
    HistoricalPriceValue,
    InstrumentType,
    MarketDetails,
    MarketSearchResult,
    MarketStatus,
    OpenPosition,
    PaginationMetadata,
    PositionMarketSnapshot,
    PriceResolution,
)
from trading_desk.ig.policy import (
    ACCOUNTS_VERSION,
    HISTORICAL_PRICES_VERSION,
    LOGIN_VERSION,
    LOGOUT_VERSION,
    MARKET_DETAILS_VERSION,
    MARKET_SEARCH_VERSION,
    POSITIONS_VERSION,
    Operation,
    enforce_read_only_policy,
    validate_epic,
    validate_search_term,
)

_ALLOWANCE_ERROR_MARKERS = (
    "allowance",
    "exceeded-api-key",
    "exceeded-account-historical-data",
)


class IGDemoClient:
    """Async read-only client whose every request passes through one policy gate."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._validate_runtime_boundary(settings)
        self._broker_settings = settings.broker
        self._cst: SecretStr | None = None
        self._security_token: SecretStr | None = None
        self._client = httpx.AsyncClient(
            base_url=f"{IG_DEMO_BASE_URL}/",
            timeout=httpx.Timeout(settings.broker.request_timeout_seconds),
            transport=transport,
            follow_redirects=False,
        )

    def __repr__(self) -> str:
        authenticated = self._has_session()
        return f"IGDemoClient(environment=DEMO, mode=READ_ONLY, authenticated={authenticated})"

    async def __aenter__(self) -> IGDemoClient:
        try:
            await self.login()
            return self
        except Exception:
            await self.aclose()
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await self.logout()
        except IGAPIError:
            if exc_type is None:
                raise
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        self._clear_session()
        await self._client.aclose()

    async def login(self) -> AuthenticatedSessionSummary:
        identifier = self._required_secret(self._broker_settings.identifier, "IG_IDENTIFIER")
        password = self._required_secret(self._broker_settings.password, "IG_PASSWORD")
        self._required_secret(self._broker_settings.api_key, "IG_API_KEY")
        self._clear_session()

        try:
            response, data = await self._send(
                Operation.LOGIN,
                "POST",
                "/session",
                LOGIN_VERSION,
                json_body={"identifier": identifier, "password": password},
                expect_json=True,
            )
            cst = response.headers.get("CST")
            security_token = response.headers.get("X-SECURITY-TOKEN")
            if not cst or not cst.strip() or not security_token or not security_token.strip():
                raise IGAuthenticationError(
                    "IG login response omitted required session headers",
                    operation=Operation.LOGIN.value,
                    http_status=response.status_code,
                    request_id=_request_id(response),
                )

            try:
                _validate_optional_environment_indicator(data)
            except ValueError:
                raise IGAuthenticationError(
                    "IG login response declared an unsafe environment",
                    operation=Operation.LOGIN.value,
                    http_status=response.status_code,
                    request_id=_request_id(response),
                ) from None

            summary = AuthenticatedSessionSummary(
                account_id=_required_text(data, "currentAccountId", "accountId"),
                client_id=_required_text(data, "clientId"),
                timezone_offset=_optional_int(data.get("timezoneOffset")),
                lightstreamer_endpoint=_optional_text(data.get("lightstreamerEndpoint")),
                environment="DEMO",
            )
            self._cst = SecretStr(cst.strip())
            self._security_token = SecretStr(security_token.strip())
            return summary
        except (IGAPIError, ValidationError, KeyError, TypeError, ValueError) as error:
            self._clear_session()
            if isinstance(error, IGAPIError):
                raise
            self._raise_validation(Operation.LOGIN, "IG login response was malformed")

    async def logout(self) -> None:
        if not self._has_session():
            self._clear_session()
            return
        try:
            await self._send(
                Operation.LOGOUT,
                "DELETE",
                "/session",
                LOGOUT_VERSION,
                expect_json=False,
            )
        finally:
            self._clear_session()

    async def get_accounts(self) -> tuple[Account, ...]:
        _, data = await self._send(
            Operation.ACCOUNTS,
            "GET",
            "/accounts",
            ACCOUNTS_VERSION,
            expect_json=True,
        )
        try:
            raw_accounts = _required_list(data, "accounts")
            return tuple(_parse_account(_mapping(item)) for item in raw_accounts)
        except (ValidationError, KeyError, TypeError, ValueError, InvalidOperation):
            self._raise_validation(Operation.ACCOUNTS, "IG accounts response was malformed")

    async def get_open_positions(self) -> tuple[OpenPosition, ...]:
        _, data = await self._send(
            Operation.POSITIONS,
            "GET",
            "/positions",
            POSITIONS_VERSION,
            expect_json=True,
        )
        try:
            raw_positions = _required_list(data, "positions")
            return tuple(_parse_open_position(_mapping(item)) for item in raw_positions)
        except (ValidationError, KeyError, TypeError, ValueError, InvalidOperation):
            self._raise_validation(Operation.POSITIONS, "IG positions response was malformed")

    async def search_markets(self, search_term: str) -> tuple[MarketSearchResult, ...]:
        normalized_term = validate_search_term(search_term)
        _, data = await self._send(
            Operation.MARKET_SEARCH,
            "GET",
            "/markets",
            MARKET_SEARCH_VERSION,
            params={"searchTerm": normalized_term},
            expect_json=True,
        )
        try:
            raw_markets = _required_list(data, "markets")
            return tuple(_parse_market_search_result(_mapping(item)) for item in raw_markets)
        except (ValidationError, KeyError, TypeError, ValueError, InvalidOperation):
            self._raise_validation(
                Operation.MARKET_SEARCH, "IG market search response was malformed"
            )

    async def get_market_details(self, epic: str) -> MarketDetails:
        normalized_epic = validate_epic(epic)
        _, data = await self._send(
            Operation.MARKET_DETAILS,
            "GET",
            f"/markets/{normalized_epic}",
            MARKET_DETAILS_VERSION,
            expect_json=True,
        )
        try:
            return _parse_market_details(data)
        except (ValidationError, KeyError, TypeError, ValueError, InvalidOperation):
            self._raise_validation(
                Operation.MARKET_DETAILS, "IG market details response was malformed"
            )

    async def get_historical_prices(
        self,
        epic: str,
        resolution: PriceResolution | str = PriceResolution.DAY,
        max_points: int | None = None,
        page_number: int = 1,
    ) -> HistoricalPricePage:
        normalized_epic = validate_epic(epic)
        try:
            normalized_resolution = PriceResolution(resolution)
        except ValueError as error:
            raise IGConfigurationError("resolution must be DAY, HOUR, or HOUR_4") from error

        requested_points = max_points or self._broker_settings.max_historical_price_points
        if not 1 <= requested_points <= self._broker_settings.max_historical_price_points:
            raise IGConfigurationError(
                "max_points exceeds IG_MAX_HISTORICAL_PRICE_POINTS or is below 1"
            )
        if page_number < 1:
            raise IGConfigurationError("page_number must be at least 1")

        _, data = await self._send(
            Operation.HISTORICAL_PRICES,
            "GET",
            f"/prices/{normalized_epic}",
            HISTORICAL_PRICES_VERSION,
            params={
                "resolution": normalized_resolution.value,
                "max": requested_points,
                "pageNumber": page_number,
            },
            expect_json=True,
        )
        try:
            return _parse_historical_price_page(data)
        except (ValidationError, KeyError, TypeError, ValueError, InvalidOperation):
            self._raise_validation(
                Operation.HISTORICAL_PRICES, "IG historical prices response was malformed"
            )

    async def _send(
        self,
        operation: Operation,
        method: str,
        path: str,
        version: int,
        *,
        params: Mapping[str, str | int] | None = None,
        json_body: Mapping[str, object] | None = None,
        expect_json: bool,
    ) -> tuple[httpx.Response, dict[str, Any]]:
        allowed = enforce_read_only_policy(operation, method, path, version)
        api_key = self._required_secret(self._broker_settings.api_key, "IG_API_KEY")
        headers = {
            "X-IG-API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json; charset=UTF-8",
            "Version": str(version),
        }
        if allowed.requires_session:
            if not self._has_session():
                raise IGSessionMissingError(
                    f"operation {operation.value!r} requires an authenticated IG session"
                )
            assert self._cst is not None
            assert self._security_token is not None
            headers["CST"] = self._cst.get_secret_value()
            headers["X-SECURITY-TOKEN"] = self._security_token.get_secret_value()

        try:
            response = await self._client.request(
                method,
                path.lstrip("/"),
                headers=headers,
                params=params,
                json=json_body,
            )
        except httpx.HTTPError:
            raise IGAPIError("IG request failed", operation=operation.value) from None

        self._raise_for_api_error(response, operation)
        if not expect_json:
            return response, {}
        return response, _decode_json_object(response, operation)

    def _raise_for_api_error(self, response: httpx.Response, operation: Operation) -> None:
        error_code: str | None = None
        try:
            payload = response.json()
            if isinstance(payload, dict) and isinstance(payload.get("errorCode"), str):
                error_code = payload["errorCode"]
        except ValueError:
            pass

        if response.is_success and error_code is None:
            return

        request_id = _request_id(response)
        if response.status_code == 401 or operation is Operation.LOGIN:
            raise IGAuthenticationError(
                "IG authentication failed",
                operation=operation.value,
                http_status=response.status_code,
                error_code=error_code,
                request_id=request_id,
            )
        if response.status_code == 403 and _is_allowance_error(error_code):
            raise IGRateLimitError(
                "IG API allowance exhausted",
                operation=operation.value,
                http_status=response.status_code,
                error_code=error_code,
                request_id=request_id,
            )
        if response.status_code == 403:
            raise IGAuthorizationError(
                "IG operation was not authorized",
                operation=operation.value,
                http_status=response.status_code,
                error_code=error_code,
                request_id=request_id,
            )
        raise IGAPIError(
            "IG API returned an error",
            operation=operation.value,
            http_status=response.status_code,
            error_code=error_code,
            request_id=request_id,
        )

    @staticmethod
    def _required_secret(value: SecretStr | None, environment_name: str) -> str:
        if value is None or not value.get_secret_value():
            raise IGConfigurationError(f"missing required configuration: {environment_name}")
        return value.get_secret_value()

    @staticmethod
    def _validate_runtime_boundary(settings: AppSettings) -> None:
        if settings.broker.broker_environment is not BrokerEnvironment.DEMO:
            raise IGConfigurationError("broker environment must be DEMO")
        if settings.safety.operating_mode is not OperatingMode.READ_ONLY:
            raise IGConfigurationError("operating mode must be READ_ONLY")
        if settings.safety.live_trading_allowed:
            raise IGConfigurationError("live trading must remain disabled")
        if settings.safety.automatic_execution_enabled:
            raise IGConfigurationError("automatic execution must remain disabled")
        if settings.broker.base_url != IG_DEMO_BASE_URL:
            raise IGConfigurationError("IG base URL must be the canonical demo endpoint")

    def _has_session(self) -> bool:
        return self._cst is not None and self._security_token is not None

    def _clear_session(self) -> None:
        self._cst = None
        self._security_token = None

    @staticmethod
    def _raise_validation(operation: Operation, message: str) -> NoReturn:
        raise IGResponseValidationError(message, operation=operation.value) from None


def _validate_optional_environment_indicator(data: Mapping[str, Any]) -> None:
    """Reject an explicit non-demo environment; absence is valid for session v2."""

    if "environment" not in data:
        return
    value = data["environment"]
    if not isinstance(value, str) or value.strip().upper() != "DEMO":
        raise ValueError("explicit IG environment indicator is not DEMO")


def _parse_account(raw: Mapping[str, Any]) -> Account:
    balance = _mapping(raw["balance"])
    return Account(
        account_id=_required_text(raw, "accountId"),
        account_name=_required_text(raw, "accountName"),
        account_type=AccountType(_required_text(raw, "accountType")),
        preferred=_required_bool(raw, "preferred"),
        currency=_required_text(raw, "currency"),
        balance=AccountBalance(
            balance=_required_decimal(balance, "balance"),
            deposit=_required_decimal(balance, "deposit"),
            profit_loss=_required_decimal(balance, "profitLoss"),
            available_funds=_required_decimal(balance, "available"),
        ),
    )


def _parse_open_position(raw: Mapping[str, Any]) -> OpenPosition:
    position = _mapping(raw["position"])
    market = _mapping(raw["market"])
    return OpenPosition(
        deal_id=_required_text(position, "dealId"),
        deal_reference=_optional_text(position.get("dealReference")),
        direction=Direction(_required_text(position, "direction")),
        size=_required_decimal(position, "size"),
        opening_level=_required_decimal(position, "level"),
        stop_level=_optional_decimal(position.get("stopLevel")),
        limit_level=_optional_decimal(position.get("limitLevel")),
        controlled_risk=_required_bool(position, "controlledRisk"),
        currency=_required_text(position, "currency"),
        created_at=_required_datetime(position, "createdDateUTC", "createdDate"),
        market=PositionMarketSnapshot(
            epic=_required_text(market, "epic"),
            instrument_name=_required_text(market, "instrumentName"),
            bid=_optional_decimal(market.get("bid")),
            offer=_optional_decimal(market.get("offer")),
            market_status=MarketStatus(_required_text(market, "marketStatus")),
            update_time_utc=_optional_datetime(
                market.get("updateTimeUTC", market.get("updateTime"))
            ),
        ),
    )


def _parse_market_search_result(raw: Mapping[str, Any]) -> MarketSearchResult:
    return MarketSearchResult(
        epic=_required_text(raw, "epic"),
        instrument_name=_required_text(raw, "instrumentName"),
        instrument_type=InstrumentType(_required_text(raw, "instrumentType")),
        market_status=MarketStatus(_required_text(raw, "marketStatus")),
        bid=_optional_decimal(raw.get("bid")),
        offer=_optional_decimal(raw.get("offer")),
        expiry=_optional_text(raw.get("expiry")),
    )


def _parse_market_details(raw: Mapping[str, Any]) -> MarketDetails:
    instrument = _mapping(raw["instrument"])
    snapshot = _mapping(raw["snapshot"])
    dealing_rules = _mapping(raw["dealingRules"])
    return MarketDetails(
        epic=_required_text(instrument, "epic"),
        instrument_name=_required_text(instrument, "name"),
        instrument_type=InstrumentType(_required_text(instrument, "type")),
        expiry=_optional_text(instrument.get("expiry")),
        market_status=MarketStatus(_required_text(snapshot, "marketStatus")),
        bid=_optional_decimal(snapshot.get("bid")),
        offer=_optional_decimal(snapshot.get("offer")),
        update_time_utc=_optional_datetime(
            snapshot.get("updateTimeUTC", snapshot.get("updateTime"))
        ),
        controlled_risk_allowed=_optional_bool(instrument.get("controlledRiskAllowed")),
        min_deal_size=_optional_dealing_rule(dealing_rules.get("minDealSize")),
        min_normal_stop_or_limit_distance=_optional_dealing_rule(
            dealing_rules.get("minNormalStopOrLimitDistance")
        ),
        max_stop_or_limit_distance=_optional_dealing_rule(
            dealing_rules.get("maxStopOrLimitDistance")
        ),
    )


def _parse_historical_price_page(raw: Mapping[str, Any]) -> HistoricalPricePage:
    prices = _required_list(raw, "prices")
    metadata = _mapping(raw["metadata"])
    page_data = _mapping(metadata["pageData"])
    allowance = _mapping(metadata["allowance"])
    bars = tuple(_parse_price_bar(_mapping(price)) for price in prices)
    return HistoricalPricePage(
        bars=bars,
        pagination=PaginationMetadata(
            page_number=_required_int(page_data, "pageNumber"),
            page_size=_required_int(page_data, "pageSize"),
            total_pages=_required_int(page_data, "totalPages"),
        ),
        allowance=APIAllowanceMetadata(
            allowance_expiry_seconds=_required_int(allowance, "allowanceExpiry"),
            remaining_allowance=_required_int(allowance, "remainingAllowance"),
            total_allowance=_required_int(allowance, "totalAllowance"),
        ),
    )


def _parse_price_bar(raw: Mapping[str, Any]) -> HistoricalPriceBar:
    close = _parse_price_value(_mapping(raw["closePrice"]))
    missing_close_parts: list[str] = []
    if close.bid is None:
        missing_close_parts.append("bid")
    if close.ask is None:
        missing_close_parts.append("ask")
    valid = not missing_close_parts
    reason = None
    if missing_close_parts:
        reason = f"close {' and '.join(missing_close_parts)} missing"
    return HistoricalPriceBar(
        timestamp=_required_datetime(raw, "snapshotTimeUTC", "snapshotTime"),
        open=_parse_price_value(_mapping(raw["openPrice"])),
        high=_parse_price_value(_mapping(raw["highPrice"])),
        low=_parse_price_value(_mapping(raw["lowPrice"])),
        close=close,
        last_traded_volume=_optional_decimal(raw.get("lastTradedVolume")),
        valid_for_strategy=valid,
        validation_reason=reason,
    )


def _parse_price_value(raw: Mapping[str, Any]) -> HistoricalPriceValue:
    return HistoricalPriceValue(
        bid=_optional_decimal(raw.get("bid")),
        ask=_optional_decimal(raw.get("ask")),
        last_traded=_optional_decimal(raw.get("lastTraded")),
    )


def _optional_dealing_rule(value: object) -> DealingRuleValue | None:
    if value is None:
        return None
    raw = _mapping(value)
    return DealingRuleValue(
        value=_required_decimal(raw, "value"),
        unit=DealingRuleUnit(_required_text(raw, "unit")),
    )


def _decode_json_object(response: httpx.Response, operation: Operation) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        IGDemoClient._raise_validation(operation, "IG response was not valid JSON")
    if not isinstance(payload, dict):
        IGDemoClient._raise_validation(operation, "IG response was not a JSON object")
    return payload


def _request_id(response: httpx.Response) -> str | None:
    request_id = response.headers.get("X-REQUEST-ID") or response.headers.get("X-CORRELATION-ID")
    return str(request_id) if request_id is not None else None


def _is_allowance_error(error_code: str | None) -> bool:
    if error_code is None:
        return False
    normalized = error_code.lower()
    return any(marker in normalized for marker in _ALLOWANCE_ERROR_MARKERS)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("expected object")
    return value


def _required_list(raw: Mapping[str, Any], key: str) -> list[object]:
    value = raw[key]
    if not isinstance(value, list):
        raise TypeError("expected list")
    return value


def _required_text(raw: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError("required text missing")


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _required_bool(raw: Mapping[str, Any], key: str) -> bool:
    value = raw[key]
    if not isinstance(value, bool):
        raise TypeError("expected bool")
    return value


def _optional_bool(value: object) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise TypeError("expected optional bool")


def _required_decimal(raw: Mapping[str, Any], key: str) -> Decimal:
    value = _optional_decimal(raw[key])
    if value is None:
        raise ValueError("required decimal missing")
    return value


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("bool is not a decimal")
    return Decimal(str(value))


def _required_int(raw: Mapping[str, Any], key: str) -> int:
    value = raw[key]
    if isinstance(value, bool):
        raise TypeError("bool is not an int")
    return int(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError("expected optional int")
    return int(value)


def _required_datetime(raw: Mapping[str, Any], *keys: str) -> datetime:
    for key in keys:
        if key in raw:
            parsed = _optional_datetime(raw[key])
            if parsed is not None:
                return parsed
    raise ValueError("required datetime missing")


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise TypeError("expected datetime string")

    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = _parse_ig_datetime(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_ig_datetime(value: str) -> datetime:
    formats = (
        "%Y/%m/%d %H:%M:%S:%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    )
    for date_format in formats:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    raise ValueError("unsupported datetime")
