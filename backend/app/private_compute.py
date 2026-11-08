"""Bounded execution of immutable subscriber strategies in a separate process."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from fastapi import HTTPException
from pydantic import ValidationError

from app.models import BacktestRequest, BacktestResult, CustomStrategySpec

SETTINGS = frozenset({"start", "end", "initial_capital", "commission_rate", "slippage_rate",
                      "spread_rate", "max_position", "max_participation_rate", "stop_loss", "take_profit"})
MAX_BYTES = 16 * 1024 * 1024


class PrivateCompute:
    def __init__(self, runtime, publications, objects=None):
        self.runtime = runtime
        self.publications = publications
        self._owners: set[str] = set()
        self._owner_lock = threading.Lock()
        self._capacity = threading.BoundedSemaphore(5)
        self._serial = threading.Lock()

    def _release(self, owner, release_id):
        strategy_id, snapshot = self.runtime.backtest_release(owner, release_id)
        with self.runtime._connect() as db:
            release = dict(self.runtime._release_for(db, release_id))
        return strategy_id, snapshot, release

    def _admit(self, owner):
        with self._owner_lock:
            if owner in self._owners or not self._capacity.acquire(blocking=False):
                raise HTTPException(429, "保密计算繁忙；每账号限一项，最多四项等待", headers={"Retry-After": "3"})
            self._owners.add(owner)

    def _finish(self, owner, acquired):
        if acquired:
            self._serial.release()
        with self._owner_lock:
            self._owners.discard(owner)
            self._capacity.release()

    def backtest(self, owner: str, release_id: str, dataset_id: str, settings: dict) -> dict:
        if not isinstance(settings, dict) or set(settings) - SETTINGS:
            raise HTTPException(422, "保密回测仅接受日期、资金和交易成本设置，不接受策略逻辑或批量研究")
        # Check entitlement before admitting work, then again when its queue slot runs.
        self._release(owner, release_id)
        self._admit(owner)
        acquired = False
        try:
            acquired = self._serial.acquire(timeout=60)
            if not acquired:
                raise HTTPException(429, "保密计算等待超时，请稍后重试", headers={"Retry-After": "3"})
            strategy_id, snapshot, release = self._release(owner, release_id)
            try:
                manifest = self.publications.manifest(dataset_id)
                # Dataset identity is registered on the server; never use client bars.
                request = BacktestRequest.model_validate({
                    **settings, "symbol": manifest["asset"]["symbol"],
                    "asset_class": manifest["asset"]["asset_class"],
                    "interval": manifest["interval"], "adjustment": manifest["adjustment"],
                    "data_source": "auto", "strategy_id": strategy_id,
                    "params": snapshot.get("params", {}), "persist": False,
                    "custom_strategy": CustomStrategySpec.model_validate(snapshot["custom_strategy"])
                    if snapshot.get("custom_strategy") else None,
                })
                bundle = self.publications.bundle(dataset_id, request.start, request.end)
                bars = [{"time": int(timestamp.timestamp()),
                         **{key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}}
                        for timestamp, row in bundle.frame.iterrows()]
                body = {"request": request.model_dump(mode="json"),
                        "program": snapshot.get("python_program"),
                        "asset": manifest["asset"], "source": manifest["source"],
                        "source_note": None, "bars": bars}
                encoded = json.dumps(body, allow_nan=False).encode()
                if len(encoded) > MAX_BYTES:
                    raise ValueError("input too large")
            except KeyError as exc:
                raise HTTPException(404, "已登记行情数据集不存在") from exc
            except (ValueError, TypeError, ValidationError) as exc:
                raise HTTPException(422, "保密回测输入或日期区间无效") from exc
            result = self._execute(encoded)
            # A subscription can be revoked while a queued or running task finishes.
            self._release(owner, release_id)
            if release["owner_id"] != owner:
                result["strategy"] = {
                    "id": release_id, "name": release["name"], "category": "订阅策略",
                    "description": "固定版本保密策略", "suitable_for": "按订阅授权执行",
                    "risk_level": "高", "mode": "single", "parameters": [],
                }
                for trade in result["trades"]:
                    trade["reason"] = "保密策略信号"
                result["warnings"] = ["信号在收盘后生成，于下一根K线开盘执行。", "保密策略在平台执行；本结果未获得 ZKP 验证。"]
                result["source_note"] = None
            result.update(execution_location="server_private", proof_status="unverified", compute={
                "engine_version": "python-private/v1", "execution_location": "server_private",
                "proof_status": "unverified", "dataset_ids": [dataset_id], "strategy_version": release_id,
            })
            return result
        finally:
            self._finish(owner, acquired)

    def targets(self, owner, release_id, bundle, initial_cash, schedule_history=None):
        """Internal runtime signals share the same bounded private execution lane."""
        import pandas as pd

        self._release(owner, release_id)
        self._admit(owner)
        acquired = False
        try:
            acquired = self._serial.acquire(timeout=60)
            if not acquired:
                raise HTTPException(429, "保密计算等待超时，请稍后重试", headers={"Retry-After": "3"})
            strategy_id, snapshot, release = self._release(owner, release_id)
            try:
                bars = [{"time": int(timestamp.timestamp()),
                         **{key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}}
                        for timestamp, row in bundle.frame.iterrows()]
                body = {"operation": "targets", "strategy_id": strategy_id, "snapshot": snapshot,
                        "source_kind": release["source_kind"], "bars": bars,
                        "initial_cash": str(initial_cash), "schedule_history": schedule_history}
                encoded = json.dumps(body, allow_nan=False).encode()
                if len(encoded) > MAX_BYTES:
                    raise ValueError("input too large")
            except (ValueError, TypeError, KeyError) as exc:
                raise HTTPException(422, "保密运行行情输入无效") from exc
            result = self._execute(encoded, result_kind="targets")
            if len(result["targets"]) != len(bundle.frame):
                raise HTTPException(422, "保密计算结果长度无效")
            self._release(owner, release_id)
            return (pd.Series(result["targets"], index=bundle.frame.index, dtype=float),
                    pd.Series(result["reasons"], index=bundle.frame.index, dtype=object))
        finally:
            self._finish(owner, acquired)

    def _execute(self, encoded: bytes, result_kind="backtest") -> dict:
        if sys.platform != "linux":
            raise HTTPException(503, "保密策略执行需要支持资源隔离的 Linux 计算服务")
        backend = Path(__file__).resolve().parents[1]
        environment = {"PATH": os.defpath, "PYTHONPATH": str(backend), "PYTHONIOENCODING": "utf-8",
                       "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                       "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}
        # stdout is a bounded file in the child, not an unbounded communicate buffer.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryDirectory(prefix="atlas-private-worker-") as workdir:
            # Importing the shared data configuration must not read API session
            # secrets or create files in the server's live data directory.
            environment.update(ATLAS_DATA_DIR=workdir, ATLAS_SESSION_SECRET=os.urandom(32).hex())
            try:
                process = subprocess.Popen([sys.executable, "-m", "app.private_compute_worker"],
                                           stdin=subprocess.PIPE, stdout=output, stderr=subprocess.DEVNULL,
                                           cwd=backend, env=environment)
            except OSError as exc:
                raise HTTPException(503, "保密计算执行器不可用") from exc
            try:
                process.communicate(input=encoded, timeout=60)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise HTTPException(504, "保密计算超过执行时间限制") from exc
            if process.returncode:
                raise HTTPException(422, "保密计算未完成，请检查数据区间或稍后重试")
            output.seek(0)
            raw = output.read(MAX_BYTES + 1)
        try:
            if len(raw) > MAX_BYTES:
                raise ValueError("output too large")
            result = json.loads(raw)
            if result_kind == "targets":
                values, reasons = result["targets"], result["reasons"]
                if (not isinstance(values, list) or not isinstance(reasons, list) or len(values) != len(reasons)
                        or any(isinstance(value, bool) or not isinstance(value, (int, float))
                               or not math.isfinite(value) or not 0 <= value <= 1 for value in values)
                        or any(not isinstance(reason, str) or len(reason) > 1024 for reason in reasons)):
                    raise ValueError("invalid targets")
                return {"targets": values, "reasons": reasons}
            # Drop unknown output fields and reject malformed/partial worker results.
            return BacktestResult.model_validate(result).model_dump(mode="json")
        except (ValueError, TypeError, KeyError, ValidationError) as exc:
            raise HTTPException(422, "保密计算结果无效") from exc
