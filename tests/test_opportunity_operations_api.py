from test_operations_api import _client


def test_opportunity_operations_routes_are_get_only() -> None:
    endpoints = (
        "/api/v1/opportunities",
        "/api/v1/activity",
        "/api/v1/strategy-leaderboard",
        "/api/v1/instrument-performance",
        "/api/v1/regime-performance",
        "/api/v1/inactivity-diagnostics",
        "/api/v1/demo-campaign",
    )
    with _client() as client:
        for endpoint in endpoints:
            assert client.get(endpoint).status_code in {200, 404}
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                assert client.request(method, endpoint).status_code == 405
