from pathlib import Path

STRATEGY_ROOT = Path("src/trading_desk/strategy")


def test_portfolio_strategies_have_no_external_authority() -> None:
    prohibited = (
        "trading_desk.ig",
        "trading_desk.execution",
        "trading_desk.risk",
        "httpx",
        "requests",
        "openai",
        "api_key",
        "password",
        "position_size",
        "place_order",
        "create_order",
        "execute_order",
        "short_candidate",
        "random.choice",
    )
    portfolio_files = (
        STRATEGY_ROOT / "contracts.py",
        STRATEGY_ROOT / "portfolio_configuration.py",
        STRATEGY_ROOT / "portfolio_registry.py",
        *(
            STRATEGY_ROOT / name / "evaluator.py"
            for name in ("trend_pullback", "volatility_breakout", "range_mean_reversion")
        ),
    )
    for path in portfolio_files:
        source = path.read_text(encoding="utf-8").lower()
        assert not [value for value in prohibited if value in source], path


def test_no_dashboard_strategy_mutation_routes_exist() -> None:
    source = Path("src/trading_desk/api/app.py").read_text(encoding="utf-8").lower()
    for route in ("promote", "activate", "disable-strategy", "clear-breaker", "parameters"):
        assert f'@app.post("/api/v1/strategies/{route}' not in source
        assert f'@app.patch("/api/v1/strategies/{route}' not in source
