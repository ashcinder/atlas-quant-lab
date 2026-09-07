from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth import parse_session
from app.backtest import run_backtest, run_portfolio_backtest
from app.catalog import search_assets
from app.config import ALLOWED_ORIGINS, APP_NAME, APP_VERSION, STATIC_DIR
from app.data import MarketDataService
from app.data.providers import ProviderError
from app.indicators import calculate_indicators, serialize_indicators
from app.journal.router import router as journal_router
from app.journal.router import store as journal_store
from app.journal.router import _origin_ok
from app.journal.scheduler import JournalScheduler
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
journal_scheduler = JournalScheduler(journal_store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    alert_monitor.start()
    journal_scheduler.start()
    yield
    alert_monitor.stop()
    journal_scheduler.stop()
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
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(journal_router)


@app.exception_handler(json.JSONDecodeError)
async def invalid_json(_request, _error):
    return JSONResponse({"error": "请求 JSON 格式无效"}, status_code=400)


@app.exception_handler(ValueError)
async def invalid_value(_request, error):
    return JSONResponse({"error": str(error)}, status_code=400)


@app.middleware("http")
async def require_atlas_user(request: Request, call_next):
    if request.url.path.startswith('/api/') and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        if not _origin_ok(request):
            return JSONResponse({"error": "来源不被允许"}, status_code=403)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4_000_000:
                return JSONResponse({"error": "请求不能超过 4 MB"}, status_code=413)
        if body and request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            return JSONResponse({"error": "请使用 application/json"}, status_code=415)
        request._body = bytes(body)
    if (
        request.method != "OPTIONS"
        and request.url.path.startswith("/api/v1/")
        and request.url.path != "/api/v1/health"
    ):
        if not _origin_ok(request):
            return JSONResponse({"error": "来源不被允许"}, status_code=403)
        user = parse_session(request, journal_store.find_session_user)
        if user is None:
            return JSONResponse({"error": "需要登录"}, status_code=401)
        request.state.user = user
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    return response


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
def create_backtest(request: BacktestRequest, http_request: Request):
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
        run_store.save(
            http_request.state.user.id,
            "single",
            request.model_dump(mode="json"),
            result.model_dump(mode="json"),
        )
    return result


@app.post("/api/v1/portfolio/backtests", response_model=PortfolioResult)
def create_portfolio_backtest(request: PortfolioBacktestRequest, http_request: Request):
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
        run_store.save(
            http_request.state.user.id,
            "portfolio",
            request.model_dump(mode="json"),
            result.model_dump(mode="json"),
        )
    return result


@app.get("/api/v1/runs", response_model=list[RunSummary])
def list_runs(http_request: Request, limit: int = Query(default=50, ge=1, le=200)):
    return run_store.list(http_request.state.user.id, limit)


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, http_request: Request):
    result = run_store.get(http_request.state.user.id, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="回测记录不存在")
    return result


@app.delete("/api/v1/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: str, http_request: Request):
    if not run_store.delete(http_request.state.user.id, run_id):
        raise HTTPException(status_code=404, detail="回测记录不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/api/v1/research/jobs",
    response_model=ResearchJob,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_research_job(request: ResearchRequest, http_request: Request):
    try:
        return research_service.submit(http_request.state.user.id, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/research/jobs/{job_id}", response_model=ResearchJob)
def get_research_job(job_id: str, http_request: Request):
    try:
        return research_service.get(http_request.state.user.id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="研究任务不存在") from exc


@app.delete("/api/v1/research/jobs/{job_id}", response_model=ResearchJob)
def cancel_research_job(job_id: str, http_request: Request):
    try:
        return research_service.cancel(http_request.state.user.id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="研究任务不存在") from exc


@app.get("/api/v1/custom-strategies", response_model=list[CustomStrategyRecord])
def list_custom_strategies(http_request: Request):
    return workspace_store.list_custom_strategies(http_request.state.user.id)


@app.put("/api/v1/custom-strategies/{strategy_id}", response_model=CustomStrategyRecord)
def save_custom_strategy(strategy_id: str, spec: CustomStrategySpec, http_request: Request):
    if strategy_id != spec.id:
        raise HTTPException(status_code=422, detail="路径中的策略ID与内容不一致")
    try:
        return workspace_store.save_custom_strategy(spec, http_request.state.user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/v1/custom-strategies/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_strategy(strategy_id: str, http_request: Request):
    if not workspace_store.delete_custom_strategy(strategy_id, http_request.state.user.id):
        raise HTTPException(status_code=404, detail="自定义策略不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/alerts", response_model=list[AlertRule])
def list_alerts(http_request: Request):
    return workspace_store.list_alerts(http_request.state.user.id)


@app.post("/api/v1/alerts", response_model=AlertRule, status_code=status.HTTP_201_CREATED)
def create_alert(rule: AlertRuleCreate, http_request: Request):
    return workspace_store.create_alert(rule, http_request.state.user.id)


@app.put("/api/v1/alerts/{alert_id}", response_model=AlertRule)
def update_alert(alert_id: str, rule: AlertRuleCreate, http_request: Request):
    updated = workspace_store.update_alert(alert_id, rule, http_request.state.user.id)
    if updated is None:
        raise HTTPException(status_code=404, detail="提醒规则不存在")
    return updated


@app.delete("/api/v1/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(alert_id: str, http_request: Request):
    if not workspace_store.delete_alert(alert_id, http_request.state.user.id):
        raise HTTPException(status_code=404, detail="提醒规则不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/alerts/evaluate", response_model=list[AlertNotification])
def evaluate_alerts(http_request: Request):
    return alert_monitor.evaluate_all(http_request.state.user.id)


@app.get("/api/v1/notifications", response_model=list[AlertNotification])
def list_notifications(http_request: Request, limit: int = Query(default=100, ge=1, le=500)):
    return workspace_store.list_notifications(http_request.state.user.id, limit)


@app.post("/api/v1/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_notifications_read(http_request: Request):
    workspace_store.mark_notifications_read(http_request.state.user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# The production build and API share one origin; Vite remains the development server.
if STATIC_DIR.is_dir():
    app.mount('/assets', StaticFiles(directory=STATIC_DIR / 'assets'), name='assets')

    @app.get('/')
    def frontend():
        return FileResponse(STATIC_DIR / 'index.html', headers={'Cache-Control': 'no-cache'})
