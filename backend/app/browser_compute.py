"""Browser computation I/O. Saving a report never attests its correctness."""
import json
import math
import sys
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.compute_mode import browser_compute_enabled
from app.lab_strategies import LabBacktestSettings, require_lab_owner
from app.models import BacktestResult, PortfolioResult, ResearchResult


def safe_program(value):
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, dict):
        return {key: safe_program(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_program(item) for item in value]
    return value


def capability(runtime, owner: str, release_id: str | None, purpose: str = "backtest"):
    if not release_id:
        return {"execution_location": "browser", "available": True, "strategy_version": None}
    with runtime._connect() as db:
        release = runtime._release_for(db, release_id)
        if release["owner_id"] != owner and not db.execute("SELECT 1 FROM strategy_subscriptions WHERE owner_id=? AND release_id=? AND status='active'", (owner, release_id)).fetchone():
            raise HTTPException(403, "只能使用自己开发或已订阅的策略")
    snapshot = json.loads(release["snapshot"])
    strategy_id = release["strategy_id"]
    if release["source_kind"] == "multi_python":
        return {"execution_location": "server_private", "available": False,
                "strategy_version": release["content_hash"],
                "unavailable_reason": "多股版本请从策略实验室回测或从交易账户启动多股模拟"}
    if snapshot.get("execution_mode", "candles") != "candles":
        return {"execution_location": "server_private", "available": purpose == "runtime", "strategy_version": release["content_hash"],
                "release_id": release_id, "unavailable_reason": "实时报价联调与作者签名信号仅用于按需运行，不提供历史回测"}
    result = {"execution_location": "server_private", "available": True,
              "strategy_version": release["content_hash"], "release_id": release_id}
    if release["owner_id"] == owner or snapshot.get("source_visibility") == "public":
        result.update(execution_location="browser", strategy=safe_program({
            "strategy_id": strategy_id, "params": snapshot.get("params", {}),
            "custom_strategy": snapshot.get("custom_strategy"), "python_program": snapshot.get("python_program"),
        }))
    elif sys.platform != "linux":
        result.update(available=False, unavailable_reason="保密策略需要支持资源隔离的Linux执行服务")
    return result


class CompileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(max_length=16_384)


class BrowserRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["single", "portfolio", "research"]
    request: dict
    result: dict
    dataset_ids: list[str] = Field(min_length=1, max_length=24)
    engine_version: Literal["browser-ts/v1"]
    strategy_version: str | None = Field(default=None, max_length=128)
    lab_strategy_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="after")
    def report_only(self):
        forbidden = {"proof_status", "verified", "verification_claims", "compute", "execution_location", "zk_proof_id", "receipt", "owner_id", "evidence"}
        if forbidden.intersection(self.result) or forbidden.intersection(self.request):
            raise ValueError("浏览器结果不能提交证明状态、身份或执行来源")
        return self


class PrivateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: str = Field(max_length=64)
    dataset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    settings: dict = Field(default_factory=dict)


class AIReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    stage: Literal["market", "entry", "buy_size", "sell_size", "risk", "execution"]
    side: Literal["buy", "sell"]
    closed_bars: list[dict] = Field(max_length=60)
    signal: str = Field(max_length=1024)
    scale: float = Field(ge=0, le=1)
    authority: Literal["advisory", "veto", "reduce_only"]
    instructions: str = Field(default="", max_length=2000)
    timeout_ms: int = Field(default=30_000, ge=100, le=60_000)


class RuntimeSignalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    dataset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    bar_time: int = Field(gt=0)
    target: float = Field(ge=0, le=1)
    reason: str = Field(default="浏览器策略信号", max_length=300)


class AlertObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    value: float
    triggered: bool


def browser_router(runtime, publications, runs, private_compute, workspace=None, lab_strategies=None):
    router = APIRouter(prefix="/api/v1")

    @router.get("/compute/identity")
    def identity(request: Request):
        return {"owner_id": request.state.user.id, "session_scope": getattr(request.state, "session_id_hash", "")}

    @router.get("/compute/capabilities")
    def capabilities(request: Request, release_id: str | None = Query(default=None, max_length=64), purpose: Literal["backtest", "runtime"] = "backtest"):
        return {**capability(runtime, request.state.user.id, release_id, purpose),
                "compute_mode": "browser" if browser_compute_enabled() else "legacy",
                "engine_version": "browser-ts/v1", "heartbeat_seconds": 15, "lease_seconds": 45,
                "proof_generation": "author_local"}

    @router.post("/compute/compile")
    def compile_source(body: CompileInput):
        from app.python_strategy import compile_program
        return {"python_program": safe_program(compile_program(body.source))}

    @router.get("/market/manifest")
    def market_manifest(symbol: str, asset_class: str = "crypto", interval: str = "1d", adjustment: str = "auto", data_source: str = "auto", start: str | None = None, end: str | None = None):
        manifest = publications.lookup(dict(symbol=symbol, asset_class=asset_class, interval=interval, adjustment=adjustment, data_source=data_source))
        if manifest is None:
            return JSONResponse({"status": "preparing", "message": "行情尚未发布，请等待独立采集任务；不会在回测请求中临时抓取数据"}, status_code=202)
        return {"status": "ready", **manifest}

    @router.get("/market/datasets/{identifier}")
    def dataset_manifest(identifier: str):
        try:
            return {"status": "ready", **publications.manifest(identifier)}
        except KeyError:
            raise HTTPException(404, "行情版本不存在") from None

    @router.get("/market/files/{digest}.json")
    def public_file(digest: str):
        try:
            publications.objects.read("public", digest)
            path = publications.objects.path("public", digest)
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "公共行情对象不存在或完整性检查失败") from None
        return FileResponse(path, media_type="application/json", headers={"Cache-Control": "public, max-age=31536000, immutable", "Access-Control-Allow-Origin": "*", "ETag": f'"{digest}"'})

    @router.post("/compute/runs", status_code=201)
    def save_browser_run(body: BrowserRunInput, request: Request):
        owner = request.state.user.id
        if body.lab_strategy_id:
            require_lab_owner(request)
            if lab_strategies is None:
                raise HTTPException(404, "代码策略库不可用")
            lab_strategies.require_owned(owner, body.lab_strategy_id)
            source = body.request.get("python_source")
            if (body.mode != "single" or body.request.get("strategy_id") != "python_bounded"
                    or body.request.get("release_id") or not isinstance(source, str)
                    or not source.strip() or len(source) > 16_384 or "\0" in source):
                raise HTTPException(422, "策略历史只接受受限 Python 单标的回测")
            try:
                settings = LabBacktestSettings.model_validate({
                    key: body.request[key] for key in LabBacktestSettings.model_fields if key in body.request
                })
            except ValidationError:
                raise HTTPException(422, "回测设置无效") from None
            if settings.symbol is None:
                raise HTTPException(422, "回测缺少标的")
            try:
                source_sha256 = sha256(source.encode("utf-8")).hexdigest()
            except UnicodeEncodeError:
                raise HTTPException(422, "源码必须为 UTF-8 文本") from None
            body.request["lab_snapshot"] = {
                "source_sha256": source_sha256,
                "settings": settings.model_dump(mode="json"),
            }
        if body.request.get("release_id"):
            permission = capability(runtime, owner, body.request["release_id"])
            if permission["execution_location"] != "browser" or permission["strategy_version"] != body.strategy_version:
                raise HTTPException(403, "该策略版本不允许上传浏览器执行结果")
        for identifier in body.dataset_ids:
            try:
                publications.manifest(identifier)
            except KeyError:
                raise HTTPException(422, "结果引用了未登记的行情版本") from None
        result_model = {"single": BacktestResult, "portfolio": PortfolioResult, "research": ResearchResult}[body.mode]
        result = result_model.model_validate(body.result).model_dump(mode="json")
        if body.lab_strategy_id and (
            result["strategy"]["id"] != "python_bounded"
            or result["asset"]["symbol"] != settings.symbol
            or result["asset"]["asset_class"] != settings.asset_class
            or result["interval"] != settings.interval
        ):
            raise HTTPException(422, "回测结果与策略或标的设置不匹配")
        result["run_id"] = str(uuid4())
        result["created_at"] = datetime.now(UTC).isoformat()
        if body.mode == "research":
            result["job_id"] = "brj_" + uuid4().hex
        result["compute"] = {"execution_location": "browser", "proof_status": "unverified", "engine_version": body.engine_version,
                             "dataset_ids": body.dataset_ids, "strategy_version": body.strategy_version,
                             "period_start": result["equity"][0]["time"] if result.get("equity") else None,
                             "period_end": result["equity"][-1]["time"] if result.get("equity") else None}
        # Price history belongs to immutable datasets, not every saved result.
        if body.mode == "single":
            result["bars"] = []
        runs.save_computed(owner, body.mode, body.request, result, publications.objects,
                           lab_strategy_id=body.lab_strategy_id)
        if body.mode == "research":
            digest = publications.objects.put("private", result)
            with runs._connect() as db:
                db.execute("INSERT INTO research_jobs (id,owner_id,request_json,result_json,status,progress,message,error,created_at,updated_at) VALUES (?,?,?,?,'completed',1,'浏览器研究已保存（未证明）',NULL,?,?)", (result["job_id"], owner, json.dumps(body.request, ensure_ascii=False), json.dumps({"_object_sha256": digest}), result["created_at"], result["created_at"]))
        return result

    @router.post("/compute/private-backtests")
    def private_backtest(body: PrivateInput, request: Request):
        if capability(runtime, request.state.user.id, body.release_id)["execution_location"] != "server_private":
            raise HTTPException(409, "自有或公开策略请在浏览器执行，不提供服务器回退")
        result = private_compute.backtest(request.state.user.id, body.release_id, body.dataset_id, body.settings)
        result["run_id"] = str(uuid4())
        result["created_at"] = datetime.now(UTC).isoformat()
        runs.save_computed(request.state.user.id, "single", {"release_id": body.release_id, "strategy_id": body.release_id,
                           "symbol": result["asset"]["symbol"], **body.settings}, {**result, "bars": []}, publications.objects)
        return result

    @router.post("/compute/ai-review")
    def ai_review(body: AIReviewInput, request: Request):
        from app.cloud_ai import CloudGuard, get_config
        config = get_config(request)
        if config is None:
            raise HTTPException(409, "请先配置当前会话的 AI 服务")
        evidence = {"stage": body.stage, "side": body.side, "closed_bars": body.closed_bars, "signal": body.signal}
        weight, receipt = CloudGuard(config).review(evidence, body.scale, body.authority, instructions=body.instructions, timeout_ms=body.timeout_ms)
        return {"scale": weight, "status": receipt["status"]}

    @router.post("/compute/runtime/{identifier}/heartbeat")
    def runtime_heartbeat(identifier: str, request: Request):
        from app.browser_runtime import heartbeat
        return heartbeat(runtime, request.state.user.id, identifier)

    @router.post("/compute/runtime/{identifier}/signal")
    def runtime_signal(identifier: str, body: RuntimeSignalInput, request: Request):
        return runtime.tick(request.state.user.id, identifier, body.model_dump())

    @router.post("/compute/alerts/{identifier}/observations")
    def alert_observation(identifier: str, body: AlertObservation, request: Request):
        from datetime import timedelta
        if workspace is None:
            raise HTTPException(503, "提醒记录服务不可用")
        owner = request.state.user.id
        # Ownership and cooldown are authoritative even though the condition is
        # evaluated in the browser and carries no verification claim.
        alert = next((item for item in workspace.list_alerts(owner) if item.id == identifier), None)
        if alert is None:
            raise HTTPException(404, "提醒不存在")
        if not alert.enabled:
            raise HTTPException(409, "提醒已停用")
        now = datetime.now(UTC)
        cooldown_ok = alert.last_triggered_at is None or now - alert.last_triggered_at >= timedelta(minutes=alert.cooldown_minutes)
        notification = None
        if body.triggered and cooldown_ok:
            notification = workspace.add_notification(alert, f"{alert.symbol} 提醒条件触发（浏览器计算，未证明）", body.value, owner)
            workspace.update_alert_state(identifier, body.value, now, now)
        else:
            workspace.update_alert_state(identifier, body.value, now)
        return {"notification": notification}

    return router
