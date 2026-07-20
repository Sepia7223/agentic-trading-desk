from test_operations_api import _client

ENDPOINTS = (
    "/api/v1/strategies/validation-matrix",
    "/api/v1/strategies/performance-comparison",
    "/api/v1/strategies/regime-matrix",
    "/api/v1/strategies/portfolio-contribution",
    "/api/v1/strategies/circuit-breakers",
)


def test_strategy_operations_views_are_sanitized_and_get_only() -> None:
    with _client() as client:
        for endpoint in ENDPOINTS:
            response = client.get(endpoint)
            assert response.status_code == 200
            body = response.text.lower()
            assert "password" not in body
            assert "authorization" not in body
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                assert client.request(method, endpoint).status_code == 405
        matrix = client.get(ENDPOINTS[0]).json()
        states = {item["strategy"]: item["validation_state"] for item in matrix["strategies"]}
        assert states["trend-regime-v1"] == "DEMO_EXPLORATION_ENABLED"
        assert states["trend-pullback-v1"] == "RESEARCH_ONLY"
        assert states["volatility-breakout"] == "RESEARCH_ONLY"
        assert states["range-mean-reversion"] == "RESEARCH_ONLY"


def test_portfolio_allocation_view_is_sanitized_and_get_only() -> None:
    with _client() as client:
        endpoint = "/api/v1/portfolio-allocation"
        response = client.get(endpoint)
        assert response.status_code == 200
        body = response.json()
        assert body["authority"] == "READ_ONLY"
        assert "batches_evaluated" in body
        assert "decisions_by_strategy" in body
        text = response.text.lower()
        assert "password" not in text
        assert "authorization" not in text
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert client.request(method, endpoint).status_code == 405


def test_portfolio_analytics_view_is_reconciled_sanitized_and_get_only() -> None:
    with _client() as client:
        endpoint = "/api/v1/portfolio-analytics"
        response = client.get(endpoint)
        assert response.status_code == 200
        body = response.json()
        assert body["authority"] == "READ_ONLY"
        assert body["convention"]["returns_definition"] == "account_currency_realized_pnl"
        assert "scorecard" in body
        assert "attribution_waterfall" in body
        assert "opportunity_funnel" in body
        assert body["reconciliation"]["reconciled"] in (True, False)
        assert body["completeness"]["currency_basis"] == "ACCOUNT_CURRENCY_UNIFORM"
        text = response.text.lower()
        assert "password" not in text
        assert "authorization" not in text
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert client.request(method, endpoint).status_code == 405
