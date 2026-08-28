from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.backtest import run_backtest, run_portfolio_backtest
from app.catalog import search_assets
from app.config import APP_NAME, APP_VERSION
from app.data import MarketDataService
from app.data.providers import ProviderError
from app.indicators import calculate_indicators, serialize_indicators
from app.models import (
    AlertNotification,
    AlertRule,
    AlertRuleCreate,
    BacktestRequest,
    BacktestResult,
    CustomStrategyRecord,
    CustomStrategySpec,
    MarketDataResponse,
    PortfolioBacktestRequest,
    PortfolioResult,
    ResearchJob,
    ResearchRequest,
    RunSummary,
)
from app.research import ResearchService
from app.storage import RunStore
from app.strategies import list_strategies
from app.workspace import AlertMonitor, WorkspaceStore

data_service = MarketDataService()
run_store = RunStore()
workspace_store = WorkspaceStore()
research_service = ResearchService(data_service)
alert_monitor = AlertMonitor(workspace_store, data_service)


@asynccontextmanager
async def lifespan(_: FastAPI):
    alert_monitor.start()
    yield
    alert_monitor.stop()
    research_service.shutdown()


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1_000, compresslevel=5)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "name": APP_NAME, "version": APP_VERSION}


@app.get("/api/v1/assets/search")
def assets_search(q: str = "", limit: int = Query(default=30, ge=1, le=100)):
    return search_assets(q, limit)


@app.get("/api/v1/strategies")
def strategies(mode: str | None = Query(default=None, pattern="^(single|portfolio)$")):
    return list_strategies(mode)


@app.get("/api/v1/market/bars", response_model=MarketDataResponse)
def market_bars(
    symbol: str = "BTC-USD",
    asset_class: str = "crypto",
    interval: str = Query(default="1d", pattern="^(15m|1h|4h|1d|1wk)$"),
    source: str = Query(default="auto", pattern="^(auto|yahoo|binance|demo)$"),
    adjustment: str = Query(default="auto", pattern="^(auto|raw|forward|backward)$"),
    refresh: bool = False,
):
    try:
        bundle = data_service.fetch(
            symbol, asset_class, interval, None, None, adjustment, source, refresh
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MarketDataResponse(
        asset=bundle.asset,
        interval=interval,
        adjustment=adjustment,
        source=bundle.source,
        source_note=bundle.source_note,
        fetched_at=int((bundle.fetched_at or bundle.frame.index[-1]).timestamp()),
        last_bar_time=int(bundle.frame.index[-1].timestamp()),
        cache_hit=bundle.cache_hit,
        is_stale=bundle.is_stale,
        bars=[
            {
                "time": int(index.timestamp()),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for index, row in bundle.frame.iterrows()
        ],
        indicators=serialize_indicators(calculate_indicators(bundle.frame)),
    )


@app.post("/api/v1/backtests", response_model=BacktestResult)
def create_backtest(request: BacktestRequest):
    try:
        bundle = data_service.fetch(
            request.symbol,
            request.asset_class,
            request.interval,
            request.start,
            request.end,
            request.adjustment,
            request.data_source,
        )
        result = run_backtest(request, bundle)
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if request.persist:
        run_store.save("single", request.model_dump(mode="json"), result.model_dump(mode="json"))
    return result


@app.post("/api/v1/portfolio/backtests", response_model=PortfolioResult)
def create_portfolio_backtest(request: PortfolioBacktestRequest):
    try:
        bundles = [
            data_service.fetch(
                asset.symbol,
                asset.asset_class,
                request.interval,
                request.start,
                request.end,
                "auto",
                request.data_source,
            )
            for asset in request.assets
        ]
        converted_bundles = []
        for bundle in bundles:
            converted = data_service.convert_to_base_currency(
                bundle,
                request.base_currency,
                request.interval,
                request.start,
                request.end,
                request.data_source,
            )
            converted_bundles.append(converted)
        bundles = converted_bundles
        result = run_portfolio_backtest(request, bundles)
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if request.persist:
        run_store.save("portfolio", request.model_dump(mode="json"), result.model_dump(mode="json"))
    return result


@app.get("/api/v1/runs", response_model=list[RunSummary])
def list_runs(limit: int = Query(default=50, ge=1, le=200)):
    return run_store.list(limit)


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str):
    result = run_store.get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="回测记录不存在")
    return result


@app.delete("/api/v1/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: str):
    if not run_store.delete(run_id):
        raise HTTPException(status_code=404, detail="回测记录不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/api/v1/research/jobs",
    response_model=ResearchJob,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_research_job(request: ResearchRequest):
    try:
        return research_service.submit(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/research/jobs/{job_id}", response_model=ResearchJob)
def get_research_job(job_id: str):
    try:
        return research_service.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="研究任务不存在") from exc


@app.delete("/api/v1/research/jobs/{job_id}", response_model=ResearchJob)
def cancel_research_job(job_id: str):
    try:
        return research_service.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="研究任务不存在") from exc


@app.get("/api/v1/custom-strategies", response_model=list[CustomStrategyRecord])
def list_custom_strategies():
    return workspace_store.list_custom_strategies()


@app.put("/api/v1/custom-strategies/{strategy_id}", response_model=CustomStrategyRecord)
def save_custom_strategy(strategy_id: str, spec: CustomStrategySpec):
    if strategy_id != spec.id:
        raise HTTPException(status_code=422, detail="路径中的策略ID与内容不一致")
    try:
        return workspace_store.save_custom_strategy(spec)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/v1/custom-strategies/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_strategy(strategy_id: str):
    if not workspace_store.delete_custom_strategy(strategy_id):
        raise HTTPException(status_code=404, detail="自定义策略不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/alerts", response_model=list[AlertRule])
def list_alerts():
    return workspace_store.list_alerts()


@app.post("/api/v1/alerts", response_model=AlertRule, status_code=status.HTTP_201_CREATED)
def create_alert(rule: AlertRuleCreate):
    return workspace_store.create_alert(rule)


@app.put("/api/v1/alerts/{alert_id}", response_model=AlertRule)
def update_alert(alert_id: str, rule: AlertRuleCreate):
    updated = workspace_store.update_alert(alert_id, rule)
    if updated is None:
        raise HTTPException(status_code=404, detail="提醒规则不存在")
    return updated


@app.delete("/api/v1/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(alert_id: str):
    if not workspace_store.delete_alert(alert_id):
        raise HTTPException(status_code=404, detail="提醒规则不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/alerts/evaluate", response_model=list[AlertNotification])
def evaluate_alerts():
    return alert_monitor.evaluate_all()


@app.get("/api/v1/notifications", response_model=list[AlertNotification])
def list_notifications(limit: int = Query(default=100, ge=1, le=500)):
    return workspace_store.list_notifications(limit)


@app.post("/api/v1/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_notifications_read():
    workspace_store.mark_notifications_read()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
