"""Causal, host-owned accounting around untrusted Python target proposals.

This is a private research run, never a verified QuantJudge report. The host can
read its uploaded package. Only the independent zkVM flow can create ZKP reports.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from decimal import Decimal
from uuid import uuid4

from app.ai_runtime import LocalAIGuard
from app.execution_models import ExecutionRequest, TargetProposal
from app.sandbox import DockerSandbox, RunnerFailure
from app.strategy_studio import inspect_strategy_package

_slots = threading.BoundedSemaphore(1)
MICROS = 1_000_000


def parameter_values(manifest, supplied: dict) -> dict:
    definitions = {p.key: p for p in manifest.parameters}
    if set(supplied) - definitions.keys():
        raise RunnerFailure("包含策略未声明的参数")
    values = {}
    for key, definition in definitions.items():
        value = supplied.get(key, definition.default)
        kind = definition.kind
        if kind == "integer" and type(value) is not int:
            raise RunnerFailure(f"参数 {key} 必须为整数")
        if kind == "boolean" and type(value) is not bool:
            raise RunnerFailure(f"参数 {key} 必须为布尔值")
        if kind in {"string", "select"} and (not isinstance(value, str) or len(value) > 2000):
            raise RunnerFailure(f"参数 {key} 字符串无效")
        if kind == "select" and value not in definition.options:
            raise RunnerFailure(f"参数 {key} 不在允许的选项中")
        if kind in {"integer", "number"}:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise RunnerFailure(f"参数 {key} 必须为有限数值")
            if definition.minimum is not None and value < definition.minimum:
                raise RunnerFailure(f"参数 {key} 低于下限")
            if definition.maximum is not None and value > definition.maximum:
                raise RunnerFailure(f"参数 {key} 高于上限")
        values[key] = value
    return values


def run_private_strategy(
    archive: bytes,
    dataset: dict,
    request: ExecutionRequest,
    *,
    sandbox_factory=DockerSandbox,
    guard_factory=LocalAIGuard,
) -> dict:
    if not request.acknowledge_host_visibility:
        raise RunnerFailure("请明确确认：本地研究执行可被平台主机读取，不具备 TEE 机密性")
    if not _slots.acquire(blocking=False):
        raise RunnerFailure("隔离执行槽位已占用，请等待当前任务结束")
    try:
        return _execute(archive, dataset, request, sandbox_factory, guard_factory)
    finally:
        _slots.release()


def _execute(archive, dataset, request, sandbox_factory, guard_factory):
    inspection = inspect_strategy_package(archive)
    parameters = parameter_values(inspection.manifest, request.parameters)
    if dataset["interval"] not in inspection.manifest.intervals:
        raise RunnerFailure("该策略包未声明所选 K 线周期")
    bars = dataset["bars"][-request.max_bars :]
    if len(bars) < 3:
        raise RunnerFailure("至少需要三根已登记的 K 线")
    guard = guard_factory() if request.ai_provider else None
    run_id = "qex_" + uuid4().hex
    cash = int(Decimal(str(request.initial_capital)) * MICROS)
    initial, peak, quantity, pending = cash, cash, 0, 0.0
    curve, history, returns, audit = [], [], [], hashlib.sha256(b"ATLASRESEARCH1")
    trade_count = ai_calls = ai_failed = 0
    halted = False
    deadline = time.monotonic() + 180
    with sandbox_factory(archive, parameters) as sandbox:
        for index, bar in enumerate(bars):
            if time.monotonic() >= deadline:
                raise RunnerFailure("研究执行超过总时限")
            opening = bar["open_micros"]
            equity_open = cash + quantity * opening // MICROS
            desired = int(Decimal(str(pending)) * equity_open * MICROS / opening)
            delta = desired - quantity
            # Only previous closed volume is available when placing a next-open order.
            liquidity = (
                int(bars[index - 1]["volume_micros"] * request.max_participation) if index else 0
            )
            delta = max(-liquidity, min(liquidity, delta))
            if delta > 0:
                price = opening * (10000 + request.slippage_bps) // 10000
                affordable = cash * MICROS * 10000 // (price * (10000 + request.commission_bps))
                delta = min(delta, affordable)
                notional = delta * price // MICROS
                cash -= notional + notional * request.commission_bps // 10000
            elif delta < 0:
                delta = max(-quantity, delta)
                price = opening * (10000 - request.slippage_bps) // 10000
                notional = -delta * price // MICROS
                cash += notional - notional * request.commission_bps // 10000
            quantity += delta
            trade_count += int(delta != 0)
            equity = cash + quantity * bar["close_micros"] // MICROS
            if cash < 0 or quantity < 0 or equity <= 0:
                raise RunnerFailure("执行触发资金或仓位不变量错误")
            peak = max(peak, equity)
            drawdown = equity / peak - 1
            if curve:
                returns.append(equity / curve[-1]["equity_micros"] - 1)
            curve.append({"time": bar["time"], "equity_micros": equity})
            history.append(
                {
                    "time": bar["time"],
                    **{
                        key: bar[key + "_micros"] / MICROS
                        for key in ("open", "high", "low", "close", "volume")
                    },
                }
            )
            if index == len(bars) - 1:
                break  # Final close cannot generate a fill within this dataset.
            result = sandbox.exchange(
                {
                    "kind": "step",
                    "run_id": run_id,
                    "time": bar["time"],
                    "symbol": dataset["symbol"],
                    "bars": history,
                    "equity": equity / MICROS,
                    "cash": cash / MICROS,
                    "quantity": quantity / MICROS,
                    "weight": (equity - cash) / equity,
                    "drawdown": drawdown,
                }
            )
            targets = result.get("targets")
            if not isinstance(targets, list) or len(targets) > 1:
                raise RunnerFailure("v1 执行器只允许当前单标的目标仓位")
            proposed = 0.0
            if targets:
                target = TargetProposal.model_validate(targets[0])
                if target.symbol != dataset["symbol"]:
                    raise RunnerFailure("策略请求了未授权标的")
                proposed = target.target_weight
            if guard:
                proposed, record = guard.review(
                    {
                        "time": bar["time"],
                        "drawdown": drawdown,
                        "current_weight": (equity - cash) / equity,
                    },
                    proposed,
                    request.ai_authority,
                )
                ai_calls += 1
                ai_failed += int(record["status"] == "failed_closed")
                audit.update(json.dumps(record, sort_keys=True).encode())
            # Irrevocable final hard gate, outside strategy and AI processes.
            halted = halted or drawdown <= -request.max_drawdown
            pending = 0.0 if halted else min(request.max_position, max(0.0, proposed))
            audit.update(json.dumps([bar["time"], pending, equity, cash, quantity]).encode())
    mean = sum(returns) / len(returns) if returns else 0
    variance = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
    duration_days = max((bars[-1]["time"] - bars[0]["time"]) / 86400, 1)
    annual_periods = len(returns) * 365 / duration_days
    peak, max_dd = initial, 0.0
    for point in curve:
        peak = max(peak, point["equity_micros"])
        max_dd = min(max_dd, point["equity_micros"] / peak - 1)
    return {
        "id": run_id,
        "status": "completed",
        "evidence_level": "sandbox_research",
        "package_hash": inspection.content_hash,
        "market_data_hash": request.market_data_hash,
        "bar_count": len(bars),
        "period_start": bars[0]["time"],
        "period_end": bars[-1]["time"],
        "metrics": {
            "total_return": equity / initial - 1,
            "max_drawdown": max_dd,
            "sharpe": mean / math.sqrt(variance) * math.sqrt(annual_periods) if variance else 0,
            "trade_count": trade_count,
        },
        "final_equity": equity / MICROS,
        "execution_commitment": audit.hexdigest(),
        "ai_calls": ai_calls,
        "ai_failed_closed": ai_failed,
        "tee_verified": False,
        "zk_verified": False,
        "operator_confidential": False,
        "private_details_persisted": False,
        "trading_halted": halted,
        "warnings": [
            "Python 输出为不可信目标仓位；账本与最终风控由平台计算",
            "此结果不是 ZKP / TEE 证明，不能用于创建已验证公开报告",
            "代码仍可能利用内嵌未来知识；因果供数不能证明无过拟合或无预知",
        ],
    }
