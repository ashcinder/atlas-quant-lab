from contextlib import asynccontextmanager
import json
import re
from datetime import UTC

from fastapi import FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.auth import parse_session
from app.exchange_accounts import router as exchange_account_router
from fastapi.exceptions import RequestValidationError
from app.backtest import run_backtest, run_portfolio_backtest
from app.catalog import search_assets
from app.config import ALLOWED_ORIGINS, APP_NAME, APP_VERSION, STATIC_DIR
from app.data import MarketDataService
from app.data.providers import ProviderError
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
from app.storage import RunStore
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
from app.execution_api import execution_router
from app.strategy_code_api import router as strategy_code_router
from app.cloud_ai import router as cloud_ai_router, get_config as cloud_ai_config, CloudGuard

data_service = MarketDataService()
fundamentals_service = FundamentalsService()
run_store = RunStore()
workspace_store = WorkspaceStore()
research_service = ResearchService(data_service)
alert_monitor = AlertMonitor(workspace_store, data_service)
journal_scheduler = JournalScheduler(journal_store)
quantjudge_store = QuantJudgeStore()
zk_proof_store = ZkProofStore()
quantjudge_store.bind_proof_store(zk_proof_store)
strategy_studio_store = StrategyStudioStore()
strategy_project_store = StrategyProjectStore()


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
app.include_router(execution_router(strategy_studio_store, zk_proof_store))
app.include_router(strategy_code_router)
app.include_router(cloud_ai_router)
app.include_router(exchange_account_router)
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
    if (
        request.method != "OPTIONS"
        and request.url.path.startswith("/api/v1/")
        and request.url.path != "/api/v1/health"
    ):
        if not _origin_ok(request):
            return JSONResponse({"error": "来源不被允许"}, status_code=403)
        user = parse_session(request, journal_store.find_session_user)
        if user is None:
            return JSONResponse({"error": "需要登录"}, status_code=401, headers={"X-Atlas-Session-Required": "1"})
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
        body_limit = MAX_RECEIPT_BYTES + 1024 * 1024 if multipart_upload else 4_000_000
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > body_limit:
                return JSONResponse({"error": "请求体超过大小限制"}, status_code=413)
        if body and content_type != 'application/json' and not (multipart_upload and content_type == 'multipart/form-data'):
            return JSONResponse({"error": "请使用 application/json"}, status_code=415)
        request._body = bytes(body)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
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


@app.get("/api/v1/market/fundamentals", response_model=FundamentalsResponse)
def market_fundamentals(
    symbol: str,
    asset_class: str = "equity",
    refresh: bool = False,
):
    return fundamentals_service.fetch(symbol, asset_class, refresh)


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
        cloud_config = cloud_ai_config(http_request) if request.execution_pipeline and any(stage.enabled for stage in request.execution_pipeline.ai_stages) else None
        result = run_backtest(request, bundle, supplied_ai_guard=CloudGuard(cloud_config) if cloud_config else None)
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
        return quantjudge_store.publish_report(agent_id, request, developer_token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


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
    interval: str = Query(default="1d", pattern="^(15m|1h|4h|1d|1wk)$"),
    source: str = Query(default="auto", pattern="^(auto|yahoo|binance)$"),
    adjustment: str = Query(default="raw", pattern="^(auto|raw|forward|backward)$"),
    refresh: bool = False,
):
    try:
        bundle = data_service.fetch(
            symbol, asset_class, interval, None, None, adjustment, source, refresh
        )
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
                for index, row in bundle.frame.iterrows()
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
        return quantjudge_store.publish_zk_report(agent_id, request.proof_id, developer_token)
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
        return quantjudge_store.subscribe(agent_id, request, http_request.state.user.id)
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
    status_code=status.HTTP_410_GONE,
)
def upload_quant_strategy_package(agent_id: str):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="策略代码上传已停用，请使用图形化策略画布创建和配置策略。",
    )


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
    if workflow_id != request.workflow.id:
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
