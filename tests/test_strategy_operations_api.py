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
