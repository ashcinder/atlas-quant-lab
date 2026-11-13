from app.cloud_proofs import CloudProofService, cloud_proof_router
from contextlib import asynccontextmanager
import json
import re
from datetime import UTC, datetime
from threading import BoundedSemaphore

from fastapi import FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.demo_accounts_api import router as demo_accounts_router
from app.auth import parse_session
from app.exchange_accounts import router as exchange_account_router
from fastapi.exceptions import RequestValidationError
from app.backtest import run_backtest, run_portfolio_backtest
from app.catalog import find_asset, search_assets
from app.config import ALLOWED_ORIGINS, APP_NAME, APP_VERSION, STATIC_DIR
from app.data import MarketDataService
from app.data.providers import NoMarketData, ProviderError
from app.execution_api import execution_router
from app.fundamentals import FundamentalsService
from app.indicators import calculate_indicators, serialize_indicators
from app.journal.router import _origin_ok
from app.journal.router import router as journal_router
from app.journal.router import store as journal_store
from app.journal.scheduler import JournalScheduler
from app.models import (
    AlertNotification,
    AlertRule,
    AlertRuleCreate,
    BacktestRequest,
    BacktestResult,
    CustomStrategyRecord,
    CustomStrategySpec,
    FundamentalsResponse,
    MarketDataResponse,
    PortfolioBacktestRequest,
    PortfolioResult,
    ResearchJob,
    ResearchRequest,
    RunSummary,
)
from app.quantjudge import QuantJudgeStore
from app.quantjudge_models import (
    AnchorRequest,
    ChainTransactionAttach,
    PerformanceReportCreate,
    QuantAgentCreate,
    SubscriptionCreate,
)
from app.research import ResearchService
from app.bkc_payments import bkc_router
from app.storage import RunStore
from app.lab_strategies import LAB_OWNER_HEADER, LabStrategyStore, lab_strategy_router
from app.sector_backtests import router as sector_backtest_router
from app.strategies import list_strategies
from app.strategy_projects import (
    ProjectArtifactLink,
    ProjectConflictError,
    ProjectFreezeRequest,
    ProjectGateError,
    StrategyProjectCreate,
    StrategyProjectStore,
    StrategyProjectUpdate,
)
from app.strategy_studio import (
    MAX_ARCHIVE_BYTES,
    StrategyPackageError,
    StrategyStudioStore,
    studio_spec,
    validate_workflow,
    workflow_templates,
)
from app.strategy_studio_models import StrategyWorkflow, WorkflowSaveRequest
from app.supervisor_client import SupervisorRPCError
from app.workspace import AlertMonitor, WorkspaceStore
from app.zkp import (
    MAX_RECEIPT_BYTES,
    ZkProofError,
    ZkProofStore,
    ZkVerifierUnavailable,
    make_market_dataset,
)
from app.zkp_models import ZkReportPublishCreate
from app.zkp_api import proof_inspection_router
from app.strategy_code_api import router as strategy_code_router
from app.cloud_ai import router as cloud_ai_router, get_config as cloud_ai_config, CloudGuard
from app.trading_api import ManualTradeSyncScheduler, router as trading_router
from app.strategy_runtime import StrategyRuntimeScheduler, StrategyRuntimeStore, runtime_router
from app.work_limits import expensive_request, work_limits
from app.compute_mode import browser_compute_enabled
from app.market_publication import MarketPublication
from app.browser_compute import browser_router
from app.private_compute import PrivateCompute
from app.public_artifacts import PublicArtifacts, public_artifact_router

data_service = MarketDataService()
market_history_slots = BoundedSemaphore(2)
fundamentals_service = FundamentalsService()
run_store = RunStore()
lab_strategy_store = LabStrategyStore()
workspace_store = WorkspaceStore()
research_service = ResearchService(data_service)
alert_monitor = AlertMonitor(workspace_store, data_service)
journal_scheduler = JournalScheduler(journal_store)
quantjudge_store = QuantJudgeStore(seed_demo=False)
zk_proof_store = ZkProofStore()
quantjudge_store.bind_proof_store(zk_proof_store)
strategy_studio_store = StrategyStudioStore()
strategy_project_store = StrategyProjectStore()
strategy_runtime_store = StrategyRuntimeStore(data_service)
strategy_runtime_scheduler = StrategyRuntimeScheduler(strategy_runtime_store)
manual_trade_sync_scheduler = ManualTradeSyncScheduler()
cloud_proof_service = CloudProofService(strategy_runtime_store, run_store, zk_proof_store)
market_publications = MarketPublication()
strategy_runtime_store.publications = market_publications
private_compute = PrivateCompute(strategy_runtime_store, market_publications)
strategy_runtime_store.private_compute = private_compute
public_artifacts = PublicArtifacts(quantjudge_store, zk_proof_store, market_publications.objects)


@asynccontextmanager
async def lifespan(_: FastAPI):
    cloud_proof_service.start()
    if not browser_compute_enabled():
        alert_monitor.start()
    journal_scheduler.start()
    if not browser_compute_enabled():
        strategy_runtime_scheduler.start()
    manual_trade_sync_scheduler.start()
    yield
    cloud_proof_service.stop()
    manual_trade_sync_scheduler.stop()
    strategy_runtime_scheduler.stop()
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
app.include_router(execution_router(strategy_studio_store, zk_proof_store))
app.include_router(strategy_code_router)
app.include_router(cloud_ai_router)
app.include_router(exchange_account_router)
app.include_router(trading_router)
app.include_router(demo_accounts_router(strategy_runtime_store))
app.include_router(runtime_router(strategy_runtime_store))
app.include_router(bkc_router(strategy_runtime_store, run_store))
app.include_router(cloud_proof_router(cloud_proof_service))
app.include_router(proof_inspection_router(zk_proof_store))
app.include_router(browser_router(strategy_runtime_store, market_publications, run_store, private_compute, workspace_store, lab_strategy_store))
app.include_router(lab_strategy_router(lab_strategy_store, run_store))
app.include_router(sector_backtest_router)
app.include_router(public_artifact_router(public_artifacts))
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


@app.exception_handler(RequestValidationError)
async def invalid_request_fields(_request, error):
    # Pydantic errors contain raw input by default, including submitted keys.
    return JSONResponse({"detail": [{"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]} for item in error.errors()]}, status_code=422)


@app.exception_handler(ValueError)
async def invalid_value(_request, error):
    return JSONResponse({"error": str(error)}, status_code=400)


@app.middleware("http")
async def require_atlas_user(request: Request, call_next):
    public_market_file = request.method in {'GET', 'HEAD'} and re.fullmatch(r'/api/v1/(?:market/files/[a-f0-9]{64}\.json|public-artifacts/[a-f0-9]{64}\.(?:json|r0))', request.url.path) is not None
    if (
        request.method != "OPTIONS"
        and request.url.path.startswith("/api/v1/")
        and request.url.path != "/api/v1/health"
        and not public_market_file
        and not (request.method == "POST" and request.url.path == "/api/v1/private-runner/signals")
    ):
        if not _origin_ok(request):
            return JSONResponse({"error": "来源不被允许"}, status_code=403)
        user = parse_session(request, journal_store.find_session_user)
        if user is None:
            return JSONResponse({"error": "需要登录"}, status_code=401, headers={"X-Atlas-Session-Required": "1"})
        expected_lab_owner = request.headers.get(LAB_OWNER_HEADER)
        if expected_lab_owner is not None and expected_lab_owner != user.id:
            return JSONResponse({"error": "当前登录账号已改变。请刷新工作台后重试。"}, status_code=403,
                                headers={"Cache-Control": "no-store"})
        request.state.user = user
    retired_package_upload = request.method == 'POST' and re.fullmatch(
        r'/api/v1/quantjudge/agents/[^/]+/packages', request.url.path
    ) is not None
    if (
        request.url.path.startswith('/api/')
        and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}
        and not retired_package_upload
    ):
        if not _origin_ok(request):
            return JSONResponse({"error": "来源不被允许"}, status_code=403)
        multipart_upload = request.method == 'POST' and re.fullmatch(
            r'/api/v1/quantjudge/agents/[^/]+/zk-proofs', request.url.path
        ) is not None
        content_type = request.headers.get('content-type', '').split(';')[0].strip()
        body_limit = (16 * 1024 * 1024 if request.url.path == '/api/v1/compute/runs' else MAX_RECEIPT_BYTES + 1024 * 1024 if multipart_upload else 4_000_000)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > body_limit:
                return JSONResponse({"error": "请求体超过大小限制"}, status_code=413)
        if body and content_type != 'application/json' and not (multipart_upload and content_type == 'multipart/form-data'):
            return JSONResponse({"error": "请使用 application/json"}, status_code=415)
        request._body = bytes(body)
    owner = None
    if expensive_request(request.method, request.url.path):
        user = getattr(request.state, "user", None)
        if user is not None:
            owner = user.id
            try:
                work_limits.acquire(owner)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    try:
        response = await call_next(request)
    finally:
        if owner is not None:
            work_limits.release(owner)
    if request.url.path.startswith("/api/") and not public_market_file:
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
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


@app.get("/api/v1/market/chart", response_model=MarketDataResponse)
def crypto_chart(
    symbol: str = Query(min_length=1, max_length=64),
    interval: str = Query(pattern="^(1m|5m|15m|1h|4h|1d|1wk)$"),
    adjustment: str = Query(default="auto", pattern="^(auto|raw|forward|backward)$"),
    before: int | None = Query(default=None, gt=0, le=253402300799),
):
    """Read one live Binance chart page without changing published backtest data."""
    asset = find_asset(symbol, "crypto")
    if asset.asset_class != "crypto":
        raise HTTPException(400, "此图表接口仅支持加密货币")
    if not market_history_slots.acquire(blocking=False):
        raise HTTPException(429, "行情请求较多，请稍后重试")
    now = datetime.now(UTC)
    try:
        try:
            end = datetime.fromtimestamp(before - 0.001, UTC) if before is not None else None
            frame = data_service.providers["binance"].fetch_bars(asset, interval, None, end, adjustment)
        except NoMarketData as exc:
            if before is None:
                raise HTTPException(502, "币安未返回该交易对的行情") from exc
            frame = None
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
    finally:
        market_history_slots.release()
    bars = []
    if frame is not None:
        import math
        for index, row in frame.iterrows():
            bar = {"time": int(index.timestamp()), "open": float(row.open), "high": float(row.high),
                   "low": float(row.low), "close": float(row.close), "volume": float(row.volume)}
            if not all(math.isfinite(bar[key]) for key in ("open", "high", "low", "close", "volume")) or min(bar["open"], bar["high"], bar["low"], bar["close"]) <= 0 or bar["volume"] < 0 or bar["high"] < max(bar["open"], bar["close"]) or bar["low"] > min(bar["open"], bar["close"]):
                raise HTTPException(502, "交易所返回了无效K线")
            if before is None or bar["time"] < before:
                bars.append(bar)
    return MarketDataResponse(asset=asset, interval=interval, adjustment=adjustment, source="binance",
        source_note="币安实时图表；历史回测使用已发布数据", fetched_at=int(now.timestamp()),
        last_bar_time=bars[-1]["time"] if bars else int((end or now).timestamp()),
        cache_hit=False, is_stale=False, bars=bars, indicators={})


@app.get("/api/v1/market/bars", response_model=MarketDataResponse)
def market_bars(
    symbol: str = "BTC-USD",
    asset_class: str = "crypto",
    interval: str = Query(default="1d", pattern="^(1m|5m|15m|1h|4h|1d|1wk)$"),
    source: str = Query(default="auto", pattern="^(auto|yahoo|binance|demo)$"),
    provider: str | None = Query(default=None, pattern="^(binance|yahoo|sina|tencent)$"),
    adjustment: str = Query(default="auto", pattern="^(auto|raw|forward|backward)$"),
    refresh: bool = False,
    start: datetime | None = None,
    end: datetime | None = None,
):
    if browser_compute_enabled():
        raise HTTPException(410, '行情请通过数据清单和不可变分块下载；指标在浏览器计算')
    bounded_window = start is not None or end is not None
    if provider is not None and not bounded_window:
        raise HTTPException(status_code=422, detail="锁定行情来源时必须提供历史窗口")
    if bounded_window:
        if start is None or end is None:
            raise HTTPException(status_code=422, detail="历史窗口必须同时提供开始和结束时间")
        start = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
        end = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
        if start >= end:
            raise HTTPException(status_code=422, detail="开始时间必须早于结束时间")
        interval_seconds = {
            "1m": 60,
            "5m": 5 * 60,
            "15m": 15 * 60,
            "1h": 60 * 60,
            "4h": 4 * 60 * 60,
            "1d": 24 * 60 * 60,
            "1wk": 7 * 24 * 60 * 60,
        }[interval]
        if (end - start).total_seconds() >= 5_000 * interval_seconds:
            raise HTTPException(status_code=422, detail="单次历史窗口最多包含5000个K线周期")
        if not market_history_slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="历史行情请求较多，请稍后重试")
    try:
        try:
            bundle = data_service.fetch(
                symbol,
                asset_class,
                interval,
                start,
                end,
                adjustment,
                source,
                refresh,
                **(
                    {
                        "minimum_bars": 1,
                        "provider_hint": provider,
                        "cache_history": False,
                    }
                    if bounded_window
                    else {}
                ),
            )
        except NoMarketData as exc:
            if not bounded_window:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            asset = find_asset(symbol, asset_class)
            if asset.asset_class == "unknown":
                asset.asset_class = asset_class
            boundary = int(end.timestamp())
            return MarketDataResponse(
                asset=asset,
                interval=interval,
                adjustment=adjustment,
                source=provider or source,
                source_note=f"{provider or source} 在该历史区间没有行情",
                fetched_at=boundary,
                last_bar_time=boundary,
                bars=[],
                indicators={},
            )
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if bounded_window:
            market_history_slots.release()
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


@app.get("/api/v1/market/fundamentals", response_model=FundamentalsResponse)
def market_fundamentals(
    symbol: str,
    asset_class: str = "equity",
    refresh: bool = False,
):
    return fundamentals_service.fetch(symbol, asset_class, refresh)


@app.post("/api/v1/backtests", response_model=BacktestResult)
def create_backtest(request: BacktestRequest, http_request: Request):
    if browser_compute_enabled():
        raise HTTPException(410, '普通回测已迁到浏览器；保密订阅策略请使用按需执行接口')
    supplied_program=None
    if request.release_id:
        strategy_id,snapshot=strategy_runtime_store.backtest_release(http_request.state.user.id,request.release_id)
        supplied_program=snapshot.get('python_program')
        from app.models import CustomStrategySpec
        request=request.model_copy(update={'strategy_id':strategy_id,'params':snapshot.get('params',{}),'python_source':None,'custom_strategy':CustomStrategySpec.model_validate(snapshot['custom_strategy']) if snapshot.get('custom_strategy') else None})
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
        cloud_config = cloud_ai_config(http_request) if request.execution_pipeline and any(stage.enabled for stage in request.execution_pipeline.ai_stages) else None
        result = run_backtest(request, bundle, supplied_program=supplied_program, supplied_ai_guard=CloudGuard(cloud_config) if cloud_config else None)
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
    if browser_compute_enabled():
        raise HTTPException(410, '组合回测已迁到浏览器，不提供服务器回退计算')
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
    if browser_compute_enabled():
        raise HTTPException(410, '参数研究已迁到浏览器，不提供服务器批量研究')
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


@app.get("/api/v1/strategy-projects")
def list_strategy_projects(http_request: Request):
    return strategy_project_store.list(http_request.state.user.id)


@app.post("/api/v1/strategy-projects", status_code=status.HTTP_201_CREATED)
def create_strategy_project(request: StrategyProjectCreate, http_request: Request):
    return strategy_project_store.create(request, http_request.state.user.id)


@app.get("/api/v1/strategy-projects/{project_id}")
def get_strategy_project(project_id: str, http_request: Request):
    try:
        return strategy_project_store.get(project_id, http_request.state.user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="策略项目不存在") from exc


@app.patch("/api/v1/strategy-projects/{project_id}")
def update_strategy_project(project_id: str, request: StrategyProjectUpdate, http_request: Request):
    try:
        return strategy_project_store.update(project_id, request, http_request.state.user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="策略项目不存在") from exc
    except ProjectConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/strategy-projects/{project_id}/artifacts")
def link_strategy_project_artifact(
    project_id: str, request: ProjectArtifactLink, http_request: Request,
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    try:
        return strategy_project_store.link_artifact(project_id, request, http_request.state.user.id, developer_token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="策略项目不存在") from exc
    except ProjectConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProjectGateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/strategy-projects/{project_id}/freeze")
def freeze_strategy_project(project_id: str, request: ProjectFreezeRequest, http_request: Request):
    try:
        return strategy_project_store.freeze(project_id, request, http_request.state.user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="策略项目不存在") from exc
    except ProjectConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProjectGateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    if browser_compute_enabled():
        raise HTTPException(410, '提醒条件在浏览器计算，请提交当前账号的提醒观察值')
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
@app.get("/api/v1/quantjudge/overview")
def quantjudge_overview():
    return quantjudge_store.overview()


@app.get("/api/v1/quantjudge/agents")
def list_quant_agents(
    category: str | None = None,
    report_type: str | None = Query(default=None, pattern="^(backtest|live)$"),
    q: str = Query(default="", max_length=100),
):
    return quantjudge_store.list_agents(category=category, report_type=report_type, query=q)


@app.post("/api/v1/quantjudge/agents", status_code=status.HTTP_201_CREATED)
def create_quant_agent(request: QuantAgentCreate):
    return quantjudge_store.create_agent(request)


@app.get("/api/v1/quantjudge/agents/{agent_id}")
def get_quant_agent(agent_id: str):
    try:
        return quantjudge_store.get_agent(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc


@app.post(
    "/api/v1/quantjudge/agents/{agent_id}/reports",
    status_code=status.HTTP_201_CREATED,
)
def publish_quant_report(
    agent_id: str,
    request: PerformanceReportCreate,
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    try:
        result = quantjudge_store.publish_report(agent_id, request, developer_token)
        return published_distribution(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def published_distribution(result):
    try:
        result["distribution"] = {"status": "ready", **public_artifacts.publish_report(result["id"])}
    except (ValueError, KeyError, OSError, ZkProofError, ZkVerifierUnavailable):
        # The report is already committed. A CDN failure must not invite creating
        # another report or charging again; export can be retried independently.
        result["distribution"] = {"status": "pending", "message": "报告已发布，公共文件分发尚未就绪，可单独重试"}
    return result


@app.post("/api/v1/quantjudge/reports/{report_id}/distribution")
def retry_report_distribution(report_id: str, developer_token: str | None = Header(default=None, alias="X-Developer-Token")):
    try:
        with quantjudge_store._connect() as db:
            report = db.execute("SELECT agent_id FROM qj_reports WHERE id=?", (report_id,)).fetchone()
        if report is None:
            raise KeyError(report_id)
        quantjudge_store._assert_token(report["agent_id"], developer_token)
        return {"status": "ready", **public_artifacts.publish_report(report_id)}
    except PermissionError:
        raise HTTPException(403, "仅报告作者可以重新发布公共制品") from None
    except KeyError:
        raise HTTPException(404, "报告不存在") from None


@app.get("/api/v1/quantjudge/zkp/profiles")
def list_zkp_profiles():
    try:
        return zk_proof_store.profiles()
    except ZkVerifierUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/v1/quantjudge/zkp/market-datasets")
def create_zkp_market_dataset(
    symbol: str = Query(default="BTC-USD", min_length=1, max_length=40),
    asset_class: str = Query(default="crypto", min_length=1, max_length=40),
    interval: str = Query(default="1d", pattern="^(1m|5m|15m|1h|4h|1d|1wk)$"),
    source: str = Query(default="auto", pattern="^(auto|yahoo|binance)$"),
    adjustment: str = Query(default="raw", pattern="^(auto|raw|forward|backward)$"),
    refresh: bool = False,
    start: datetime | None = None,
    end: datetime | None = None,
):
    try:
        from app.zkp_dataset import validate_period, closed_frame
        validate_period(start, end)
        if browser_compute_enabled():
            manifest = market_publications.lookup(dict(symbol=symbol, asset_class=asset_class, interval=interval, adjustment=adjustment, data_source=source))
            if manifest is None:
                raise HTTPException(409, "证明行情尚未由独立发布器登记")
            bundle = market_publications.bundle(manifest["dataset_id"], start, end)
        else:
            bundle = data_service.fetch(
                symbol, asset_class, interval, start, end, adjustment, source, refresh,
                minimum_bars=3
            )
        frame = closed_frame(bundle.frame, interval, start, end)
        dataset = make_market_dataset(
            source=bundle.source,
            symbol=bundle.asset.symbol,
            interval=interval,
            adjustment=adjustment,
            bars=[
                {
                    "time": int(index.timestamp()),
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                }
                for index, row in frame.iterrows()
            ],
        )
        record = zk_proof_store.register_market_dataset(
            dataset,
            fetched_at=bundle.fetched_at or bundle.frame.index[-1].to_pydatetime().astimezone(UTC),
        )
        return {
            **record,
            "dataset": dataset,
            "download_url": f"/api/v1/quantjudge/zkp/market-datasets/{record['market_data_hash']}",
            "limitation": (
                "市场数据根由平台从公开数据源获取并登记；当前数据源未提供可独立验证的签名。"
            ),
        }
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ZkProofError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/quantjudge/zkp/database-history")
def create_database_history(symbol: str = "BTC-USD", interval: str = Query(default="1d", pattern="^(1m|5m|15m|1h|4h|1d|1wk)$")):
    """Freeze all closed Binance candles already stored for this instrument."""
    from app.catalog import find_asset
    from app.zkp_dataset import closed_frame
    try:
        asset = find_asset(symbol, "crypto")
        frame = data_service.store.full_history("binance", asset.symbol, interval)
        if frame.empty:
            raise ZkProofError("数据库尚无此标的与周期的行情，请先在行情页面加载历史数据")
        frame = closed_frame(frame, interval)
        dataset = make_market_dataset(source="binance:database-snapshot", symbol=asset.symbol,
            interval=interval, adjustment="raw", bars=[{"time":int(t.timestamp()),
            "open":v.open,"high":v.high,"low":v.low,"close":v.close,"volume":v.volume}
            for t,v in frame.iterrows()])
        record = zk_proof_store.register_market_dataset(dataset, fetched_at=datetime.now(UTC),
            trust_model="platform_database_full_history_snapshot")
        return {**record,"scope":"database_full_history","bar_count":len(frame),
            "period_start":frame.index[0].isoformat(),"period_end":frame.index[-1].isoformat()}
    except (ZkProofError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/v1/quantjudge/zkp/market-datasets/{market_hash}")
def download_zkp_market_dataset(market_hash: str):
    try:
        _, path = zk_proof_store.market_dataset(market_hash)
        content = path.read_bytes()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="市场数据集不存在") from exc
    except ZkProofError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{market_hash}.json"'},
    )


@app.post(
    "/api/v1/quantjudge/agents/{agent_id}/zk-proofs",
    status_code=status.HTTP_201_CREATED,
)
async def upload_zk_proof(
    agent_id: str,
    proof_profile: str = Query(min_length=3, max_length=100),
    file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency declaration
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    receipt = await file.read(MAX_RECEIPT_BYTES + 1)
    try:
        return zk_proof_store.register_receipt(agent_id, proof_profile, receipt, developer_token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ZkVerifierUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ZkProofError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/quantjudge/zk-proofs/{proof_id}")
def get_zk_proof(proof_id: str):
    try:
        return zk_proof_store.get(proof_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ZKP 证明不存在") from exc


@app.get("/api/v1/quantjudge/zk-proofs/{proof_id}/receipt")
def download_zk_receipt(proof_id: str):
    try:
        distribution = public_artifacts.for_proof(proof_id)
        if distribution and distribution.get("receipt_url"):
            # Only receipts deliberately published with a verified public report.
            return RedirectResponse(distribution["receipt_url"], status_code=307)
        path = zk_proof_store.receipt_path(proof_id)
        content = path.read_bytes()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ZKP 证明不存在") from exc
    except ZkProofError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{proof_id}.r0"'},
    )


@app.post(
    "/api/v1/quantjudge/agents/{agent_id}/reports/zkp",
    status_code=status.HTTP_201_CREATED,
)
def publish_zkp_report(
    agent_id: str,
    request: ZkReportPublishCreate,
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    try:
        result = quantjudge_store.publish_zk_report(agent_id, request.proof_id, developer_token)
        return published_distribution(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 或 ZKP 证明不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (ValueError, ZkProofError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/quantjudge/reports/{report_id}/verify")
def verify_quant_report(report_id: str, refresh_chain: bool = True):
    try:
        return quantjudge_store.verify_report(report_id, refresh_chain=refresh_chain)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="证明回执不存在") from exc


@app.post("/api/v1/quantjudge/reports/{report_id}/anchor")
def anchor_quant_report(
    report_id: str,
    request: AnchorRequest,
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    try:
        return quantjudge_store.submit_anchor(
            report_id, request.signed_raw_transaction, developer_token
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="证明回执不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SupervisorRPCError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.put("/api/v1/quantjudge/reports/{report_id}/chain-transaction")
def attach_quant_report_transaction(
    report_id: str,
    request: ChainTransactionAttach,
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    try:
        return quantjudge_store.attach_transaction(
            report_id, request.transaction_hash, developer_token
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="证明回执不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/api/v1/quantjudge/agents/{agent_id}/subscriptions", status_code=status.HTTP_201_CREATED)
def subscribe_quant_agent(agent_id: str, request: SubscriptionCreate, http_request: Request):
    try:
        raise HTTPException(410, "旧版沙盒订阅已关闭，请在可运行策略中使用 BKC 订阅具体版本")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc


@app.get("/api/v1/quantjudge/subscriptions")
def list_quant_subscriptions(http_request: Request, investor_alias: str = Query(min_length=2, max_length=60)):
    return quantjudge_store.list_subscriptions(investor_alias, http_request.state.user.id)


@app.get("/api/v1/quantjudge/chain/status")
def quantjudge_chain_status():
    return quantjudge_store.chain_status()


@app.get("/api/v1/quantjudge/studio/spec")
def quantjudge_studio_spec():
    return studio_spec()


@app.get("/api/v1/quantjudge/studio/templates")
def quantjudge_workflow_templates():
    return workflow_templates()


@app.post("/api/v1/quantjudge/studio/workflows/validate")
def validate_quant_workflow(workflow: StrategyWorkflow):
    return validate_workflow(workflow)


@app.get("/api/v1/quantjudge/agents/{agent_id}/packages")
def list_quant_strategy_packages(
    agent_id: str,
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    try:
        return strategy_studio_store.list_packages(agent_id, developer_token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post(
    "/api/v1/quantjudge/agents/{agent_id}/packages",
    status_code=status.HTTP_201_CREATED,
)
async def upload_quant_strategy_package(
    agent_id: str,
    file: UploadFile = File(...),
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    content = await file.read(MAX_ARCHIVE_BYTES + 1)
    try:
        return strategy_studio_store.upload_package(
            agent_id, file.filename or "strategy.qstrategy", content, developer_token
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except StrategyPackageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/quantjudge/agents/{agent_id}/packages/{package_id}/download")
def download_quant_strategy_package(
    agent_id: str,
    package_id: str,
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    try:
        content = strategy_studio_store.download_package(agent_id, package_id, developer_token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="策略包不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{package_id}.qstrategy"'},
    )


@app.get("/api/v1/quantjudge/agents/{agent_id}/workflows")
def list_quant_workflows(
    agent_id: str,
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    try:
        return strategy_studio_store.list_workflows(agent_id, developer_token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/api/v1/quantjudge/agents/{agent_id}/workflows/{workflow_id}")
def get_quant_workflow(
    agent_id: str,
    workflow_id: str,
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    try:
        return strategy_studio_store.get_workflow(agent_id, workflow_id, developer_token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.put("/api/v1/quantjudge/agents/{agent_id}/workflows/{workflow_id}")
def save_quant_workflow(
    agent_id: str,
    workflow_id: str,
    request: WorkflowSaveRequest,
    developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
):
    if workflow_id not in {request.workflow.id, f"{agent_id}:{request.workflow.id}"}:
        raise HTTPException(status_code=422, detail="路径中的工作流 ID 与内容不一致")
    try:
        return strategy_studio_store.save_workflow(
            agent_id, request.workflow, request.change_note, developer_token
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except StrategyPackageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
