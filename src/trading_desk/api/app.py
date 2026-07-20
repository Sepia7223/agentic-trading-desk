"""Versioned GET-only FastAPI application for local monitoring."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from trading_desk.api.dependencies import OperationsDependencies
from trading_desk.api.websocket import stream_events
from trading_desk.journal.models import JournalRecordType
from trading_desk.operations.config import OperationsConfiguration
from trading_desk.operations.errors import OperationsDisabledError
from trading_desk.operations.events import OperationsEventBus
from trading_desk.operations.exports import OperationsExportFormat, export_records
from trading_desk.operations.service import OperationsService


def create_operations_app(
    service: OperationsService,
    configuration: OperationsConfiguration,
    *,
    event_bus: OperationsEventBus | None = None,
) -> FastAPI:
    if not configuration.enabled:
        raise OperationsDisabledError("Operations Center is disabled")
    dependencies = OperationsDependencies(
        configuration=configuration,
        service=service,
        events=event_bus or OperationsEventBus(configuration),
    )
    app = FastAPI(
        title="Trading Desk Operations Center",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.operations = dependencies

    @app.exception_handler(ValueError)
    async def invalid_query(_: Request, error: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"status": "INVALID_QUERY", "message": str(error)},
        )

    @app.get("/api/v1/health")
    async def health() -> dict[str, object]:
        snapshot = service.snapshot()
        return {
            "status": snapshot.system_status,
            "environment": "IG DEMO",
            "authority": "READ ONLY",
            "live_trading": "DISABLED",
            "snapshot_id": snapshot.snapshot_id,
        }

    @app.get("/api/v1/system")
    async def system():  # type: ignore[no-untyped-def]
        return service.snapshot()

    @app.get("/api/v1/context/latest")
    async def context_latest():  # type: ignore[no-untyped-def]
        return _optional(service.latest(JournalRecordType.MARKET_CONTEXT))

    @app.get("/api/v1/router/latest")
    async def router_latest():  # type: ignore[no-untyped-def]
        return _optional(service.latest(JournalRecordType.ROUTER_DECISION))

    @app.get("/api/v1/risk/latest")
    async def risk_latest():  # type: ignore[no-untyped-def]
        return _optional(service.latest(JournalRecordType.RISK_DECISION))

    @app.get("/api/v1/evaluations")
    async def evaluations(limit: int = 100, offset: int = 0):  # type: ignore[no-untyped-def]
        return service.evaluations(limit=limit, offset=offset)

    @app.get("/api/v1/why-no-trade")
    async def why_no_trade(limit: int = 100):  # type: ignore[no-untyped-def]
        return service.why_no_trade(limit=limit)

    @app.get("/api/v1/portfolio")
    async def portfolio():  # type: ignore[no-untyped-def]
        return service.records(record_type=JournalRecordType.PAPER_PORTFOLIO_EVENT)

    @app.get("/api/v1/positions/open")
    async def open_positions():  # type: ignore[no-untyped-def]
        return service.open_positions()

    @app.get("/api/v1/trades")
    async def trades(limit: int = 100, offset: int = 0):  # type: ignore[no-untyped-def]
        return service.records(
            record_type=JournalRecordType.PAPER_CLOSED_TRADE,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/v1/trades/{trade_id}")
    async def trade_detail(trade_id: str):  # type: ignore[no-untyped-def]
        records = service.evidence_chain(trade_id)
        if not records:
            raise HTTPException(status_code=404, detail="trade evidence is unavailable")
        return records

    @app.get("/api/v1/execution")
    async def execution(limit: int = 100, offset: int = 0):  # type: ignore[no-untyped-def]
        return service.execution_lifecycles(limit=limit, offset=offset)

    @app.get("/api/v1/lifecycle")
    async def lifecycle(limit: int = 100, offset: int = 0):  # type: ignore[no-untyped-def]
        return service.lifecycle(limit=limit, offset=offset)

    @app.get("/api/v1/reviews")
    async def reviews(limit: int = 100, offset: int = 0):  # type: ignore[no-untyped-def]
        return service.records(
            record_type=JournalRecordType.POST_TRADE_REVIEW,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/v1/ai-reviews")
    async def ai_reviews(limit: int = 100, offset: int = 0):  # type: ignore[no-untyped-def]
        return service.records(
            record_type=JournalRecordType.AI_ANALYSIS,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/v1/alerts")
    async def alerts():  # type: ignore[no-untyped-def]
        return service.snapshot().latest_alerts

    @app.get("/api/v1/journal/status")
    async def journal_status():  # type: ignore[no-untyped-def]
        return service.snapshot().journal_status

    @app.get("/api/v1/replay")
    async def replay(cutoff_at: datetime, limit: int | None = None):  # type: ignore[no-untyped-def]
        if not configuration.enable_replay:
            raise HTTPException(status_code=503, detail="replay is disabled")
        return service.replay(cutoff_at=cutoff_at, limit=limit)

    @app.get("/api/v1/search")
    async def search(
        q: str = Query(min_length=1, max_length=128), limit: int = 100, offset: int = 0
    ):  # type: ignore[no-untyped-def]
        return service.search(q, limit=limit, offset=offset)

    @app.get("/api/v1/performance")
    async def performance(limit: int = 500):  # type: ignore[no-untyped-def]
        return service.performance(limit=limit)

    @app.get("/api/v1/opportunities")
    async def opportunities(limit: int = 100):  # type: ignore[no-untyped-def]
        return service.opportunity_records(limit=limit)

    @app.get("/api/v1/activity")
    async def opportunity_activity():  # type: ignore[no-untyped-def]
        return service.opportunity_activity()

    @app.get("/api/v1/strategy-leaderboard")
    async def strategy_leaderboard():  # type: ignore[no-untyped-def]
        return service.opportunity_breakdown("strategy_id")

    @app.get("/api/v1/strategies/validation-matrix")
    async def strategy_validation_matrix():  # type: ignore[no-untyped-def]
        return service.strategy_validation_matrix()

    @app.get("/api/v1/strategies/performance-comparison")
    async def strategy_performance_comparison():  # type: ignore[no-untyped-def]
        return service.strategy_comparison()

    @app.get("/api/v1/strategies/regime-matrix")
    async def strategy_regime_matrix():  # type: ignore[no-untyped-def]
        return service.strategy_regime_matrix()

    @app.get("/api/v1/strategies/portfolio-contribution")
    async def strategy_portfolio_contribution():  # type: ignore[no-untyped-def]
        return service.strategy_portfolio_contribution()

    @app.get("/api/v1/strategies/circuit-breakers")
    async def strategy_circuit_breakers():  # type: ignore[no-untyped-def]
        return service.strategy_circuit_breakers()

    @app.get("/api/v1/portfolio-allocation")
    async def portfolio_allocation():  # type: ignore[no-untyped-def]
        return service.portfolio_allocation()

    @app.get("/api/v1/portfolio-analytics")
    async def portfolio_analytics():  # type: ignore[no-untyped-def]
        return service.portfolio_analytics()

    @app.get("/api/v1/certification-status")
    async def certification_status():  # type: ignore[no-untyped-def]
        return service.certification_status()

    @app.get("/api/v1/instrument-performance")
    async def instrument_performance():  # type: ignore[no-untyped-def]
        return service.opportunity_breakdown("instrument_id")

    @app.get("/api/v1/regime-performance")
    async def regime_performance():  # type: ignore[no-untyped-def]
        return service.opportunity_breakdown("regime")

    @app.get("/api/v1/inactivity-diagnostics")
    async def inactivity_diagnostics(limit: int = 100):  # type: ignore[no-untyped-def]
        return service.inactivity_diagnostics(limit=limit)

    @app.get("/api/v1/demo-campaign")
    async def demo_campaign():  # type: ignore[no-untyped-def]
        return _optional(service.demo_campaign())

    @app.get("/api/v1/configuration")
    async def configuration_view() -> dict[str, object]:
        return service.configuration_view()

    @app.get("/api/v1/exports")
    async def exports(
        format: OperationsExportFormat = OperationsExportFormat.JSONL,
        record_type: JournalRecordType | None = None,
        limit: int = 100,
    ) -> Response:
        if not configuration.enable_exports:
            raise HTTPException(status_code=503, detail="exports are disabled")
        result = service.records(record_type=record_type, limit=limit)
        content, media_type, filename = export_records(result.records, format)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        if not configuration.websocket_enabled:
            await websocket.close(code=1008)
            return
        if dependencies.events.client_count >= configuration.maximum_websocket_clients:
            await websocket.close(code=1013)
            return
        await stream_events(websocket, dependencies.events, service)

    _mount_frontend(app, configuration.frontend_directory)
    return app


def _optional(value: object | None) -> object:
    if value is None:
        return JSONResponse(status_code=404, content={"status": "DATA_UNAVAILABLE"})
    return value


def _mount_frontend(app: FastAPI, directory: Path | None) -> None:
    if directory is None or not directory.is_dir():
        return
    assets = directory / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> FileResponse:
        candidate = directory / path
        if path and candidate.is_file() and candidate.resolve().is_relative_to(directory.resolve()):
            return FileResponse(candidate)
        return FileResponse(directory / "index.html")
