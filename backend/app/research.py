from __future__ import annotations

import itertools
import math
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from app.backtest import run_backtest
from app.config import DB_PATH
from app.data.service import DataBundle, MarketDataService
from app.models import (
    BacktestRequest,
    ResearchCandidate,
    ResearchExperiment,
    ResearchJob,
    ResearchRequest,
    ResearchResult,
    WalkForwardWindow,
)
from app.strategies import get_strategy
from app.strategies.catalog import default_params


class ResearchCancelled(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _expand_experiment(experiment: ResearchExperiment) -> list[dict[str, Any]]:
    if experiment.custom_strategy is not None:
        return [{}]
    strategy = get_strategy(experiment.strategy_id)
    definitions = {parameter.key: parameter for parameter in strategy.parameters}
    params = default_params(experiment.strategy_id)
    params.update(experiment.base_params)
    keys = list(experiment.parameter_grid)
    for key in [*experiment.base_params, *keys]:
        if key not in definitions:
            raise ValueError(f"策略 {experiment.strategy_id} 不包含参数 {key}")
    for key, values in experiment.parameter_grid.items():
        definition = definitions[key]
        for value in values:
            if definition.kind == "boolean" and not isinstance(value, bool):
                raise ValueError(f"参数 {key} 必须是布尔值")
            if definition.kind in {"number", "integer"}:
                number = float(value)
                if definition.minimum is not None and number < definition.minimum:
                    raise ValueError(f"参数 {key} 低于最小值")
                if definition.maximum is not None and number > definition.maximum:
                    raise ValueError(f"参数 {key} 高于最大值")
    if not keys:
        return [params]
    output = []
    for values in itertools.product(*(experiment.parameter_grid[key] for key in keys)):
        candidate = dict(params)
        candidate.update(dict(zip(keys, values, strict=True)))
        output.append(candidate)
    return output


def _subset(bundle: DataBundle, start: int, end: int) -> DataBundle:
    return DataBundle(
        asset=bundle.asset,
        frame=bundle.frame.iloc[start:end].copy(),
        source=bundle.source,
        source_note=bundle.source_note,
        fetched_at=bundle.fetched_at,
        cache_hit=bundle.cache_hit,
        is_stale=bundle.is_stale,
    )


def _backtest_request(
    request: ResearchRequest, experiment: ResearchExperiment, params: dict[str, Any]
) -> BacktestRequest:
    return BacktestRequest(
        symbol=request.symbol,
        asset_class=request.asset_class,
        interval=request.interval,
        adjustment=request.adjustment,
        data_source=request.data_source,
        strategy_id=experiment.strategy_id,
        custom_strategy=experiment.custom_strategy,
        params=params,
        initial_capital=request.initial_capital,
        commission_rate=request.commission_rate,
        slippage_rate=request.slippage_rate,
        spread_rate=request.spread_rate,
        max_position=request.max_position,
        max_participation_rate=request.max_participation_rate,
        persist=False,
    )


def _run_metrics(
    request: ResearchRequest,
    bundle: DataBundle,
    experiment: ResearchExperiment,
    params: dict[str, Any],
) -> dict[str, float | int | None]:
    result = run_backtest(
        _backtest_request(request, experiment, params), bundle, include_details=False
    )
    return result.metrics


def _objective(metrics: dict[str, float | int | None], key: str) -> float:
    value = _finite(metrics.get(key))
    return value if value is not None else -1e100


def _candidate_warnings(
    train: dict[str, float | int | None],
    test: dict[str, float | int | None],
    combinations: int,
    param_count: int,
) -> tuple[list[str], float | None, float | None, float]:
    warnings: list[str] = []
    train_sharpe = _finite(train.get("sharpe"))
    test_sharpe = _finite(test.get("sharpe"))
    degradation = None
    if train_sharpe is not None and train_sharpe > 0 and test_sharpe is not None:
        degradation = 1 - test_sharpe / train_sharpe
        if degradation > 0.5:
            warnings.append("样本外Sharpe相对样本内下降超过50%")
    if train_sharpe is not None and abs(train_sharpe) > 3:
        warnings.append("样本内Sharpe绝对值超过3，存在明显过拟合风险")
    trades = int(test.get("round_trip_count") or 0)
    if trades < 30:
        warnings.append(f"样本外完整交易仅{trades}笔，统计功效不足")
    observations = max(int(test.get("trade_count") or 0), 1)
    if observations / max(param_count, 1) < 20:
        warnings.append("每个参数对应的样本不足20个")
    raw_p = _finite(test.get("return_p_value"))
    adjusted_p = min(1.0, raw_p * combinations) if raw_p is not None else None
    if adjusted_p is not None and adjusted_p > 0.05:
        warnings.append("经Bonferroni多重测试修正后收益不显著")
    retention = 0.0
    if train_sharpe is not None and train_sharpe > 0 and test_sharpe is not None:
        retention = min(1.0, max(0.0, test_sharpe / train_sharpe))
    oos_quality = min(1.0, max(0.0, ((test_sharpe or 0) + 0.5) / 2.0))
    trade_quality = min(1.0, trades / 30)
    significance = 1.0 - adjusted_p if adjusted_p is not None else 0.0
    score = 100 * (0.4 * oos_quality + 0.25 * retention + 0.2 * trade_quality + 0.15 * significance)
    return warnings, degradation, adjusted_p, round(score, 2)


def run_research(
    job_id: str,
    request: ResearchRequest,
    bundle: DataBundle,
    cancelled: threading.Event,
    progress: Callable[[float, str], None],
) -> ResearchResult:
    frame = bundle.frame
    if len(frame) < 160:
        raise ValueError("策略研究至少需要160根K线")
    split = int(len(frame) * (1 - request.holdout_ratio))
    split = min(max(split, 80), len(frame) - 40)
    train_bundle = _subset(bundle, 0, split)
    test_bundle = _subset(bundle, split, len(frame))
    expanded = [(experiment, _expand_experiment(experiment)) for experiment in request.experiments]
    total_combinations = sum(len(combinations) for _, combinations in expanded)
    total_work = total_combinations
    if request.walk_forward.enabled:
        total_work += total_combinations * request.walk_forward.max_windows
    completed = 0
    candidates: list[ResearchCandidate] = []
    chosen: list[tuple[ResearchExperiment, dict[str, Any], dict[str, float | int | None]]] = []

    for experiment, combinations in expanded:
        scored: list[tuple[float, dict[str, Any], dict[str, float | int | None]]] = []
        for params in combinations:
            if cancelled.is_set():
                raise ResearchCancelled()
            try:
                metrics = _run_metrics(request, train_bundle, experiment, params)
                scored.append((_objective(metrics, request.objective), params, metrics))
            except ValueError:
                pass
            completed += 1
            progress(min(0.9, completed / max(total_work, 1)), f"正在评估 {experiment.strategy_id}")
        if not scored:
            raise ValueError(f"策略 {experiment.strategy_id} 没有可用的参数组合")
        scored.sort(key=lambda item: item[0], reverse=True)
        _, best_params, best_train = scored[0]
        best_test = _run_metrics(request, test_bundle, experiment, best_params)
        chosen.append((experiment, best_params, best_train))
        for _, params, train_metrics in scored:
            is_best = params == best_params
            test_metrics = best_test if is_best else {}
            warnings: list[str] = []
            degradation = adjusted_p = None
            score = 0.0
            if is_best:
                warnings, degradation, adjusted_p, score = _candidate_warnings(
                    train_metrics,
                    best_test,
                    len(combinations),
                    len(experiment.parameter_grid) or len(experiment.base_params) or 1,
                )
            candidates.append(
                ResearchCandidate(
                    strategy_id=experiment.strategy_id,
                    params=params,
                    train_metrics=train_metrics,
                    test_metrics=test_metrics,
                    objective_train=_finite(train_metrics.get(request.objective)),
                    objective_test=_finite(best_test.get(request.objective)) if is_best else None,
                    sharpe_degradation=degradation,
                    adjusted_p_value=adjusted_p,
                    robustness_score=score,
                    warnings=warnings,
                )
            )

    windows: list[WalkForwardWindow] = []
    wf = request.walk_forward
    research_warnings = [
        "参数只在训练窗口中选择，测试窗口仅用于样本外评估。",
        "所有信号仍在K线收盘后生成，并在下一根K线开盘成交。",
    ]
    if wf.enabled:
        for experiment, combinations in expanded:
            window_count = 0
            start = 0
            while (
                start + wf.train_bars + wf.test_bars <= len(frame) and window_count < wf.max_windows
            ):
                if cancelled.is_set():
                    raise ResearchCancelled()
                train = _subset(bundle, start, start + wf.train_bars)
                test_start = start + wf.train_bars
                test = _subset(bundle, test_start, test_start + wf.test_bars)
                scored = []
                for params in combinations:
                    try:
                        metrics = _run_metrics(request, train, experiment, params)
                        scored.append((_objective(metrics, request.objective), params, metrics))
                    except ValueError:
                        pass
                    completed += 1
                    progress(min(0.96, completed / max(total_work, 1)), "Walk-forward滚动验证")
                if scored:
                    _, params, train_metrics = max(scored, key=lambda item: item[0])
                    test_metrics = _run_metrics(request, test, experiment, params)
                    windows.append(
                        WalkForwardWindow(
                            strategy_id=experiment.strategy_id,
                            train_start=int(train.frame.index[0].timestamp()),
                            train_end=int(train.frame.index[-1].timestamp()),
                            test_start=int(test.frame.index[0].timestamp()),
                            test_end=int(test.frame.index[-1].timestamp()),
                            params=params,
                            train_sharpe=_finite(train_metrics.get("sharpe")),
                            test_sharpe=_finite(test_metrics.get("sharpe")),
                            test_return=_finite(test_metrics.get("total_return")),
                            trades=int(test_metrics.get("round_trip_count") or 0),
                        )
                    )
                start += wf.step_bars
                window_count += 1
        if not windows:
            research_warnings.append("K线数量不足以生成Walk-forward窗口，请缩短训练或测试长度。")

    best_candidates = [candidate for candidate in candidates if candidate.test_metrics]
    best_candidates.sort(key=lambda item: item.robustness_score, reverse=True)
    for rank, candidate in enumerate(best_candidates, 1):
        candidate.rank = rank
    remaining = [candidate for candidate in candidates if not candidate.test_metrics]
    candidates = best_candidates + remaining
    test_sharpes = [window.test_sharpe for window in windows if window.test_sharpe is not None]
    test_returns = [window.test_return for window in windows if window.test_return is not None]
    summary: dict[str, float | int | bool | None] = {
        "holdout_bars": len(test_bundle.frame),
        "walk_forward_windows": len(windows),
        "average_oos_sharpe": _finite(np.mean(test_sharpes)) if test_sharpes else None,
        "worst_oos_sharpe": _finite(min(test_sharpes)) if test_sharpes else None,
        "profitable_window_ratio": _finite(np.mean(np.array(test_returns) > 0))
        if test_returns
        else None,
        "is_robust": bool(
            test_sharpes
            and np.mean(test_sharpes) > 0.5
            and test_returns
            and np.mean(np.array(test_returns) > 0) >= 0.6
        ),
    }
    progress(1.0, "研究完成")
    return ResearchResult(
        job_id=job_id,
        symbol=request.symbol,
        interval=request.interval,
        objective=request.objective,
        data_source=bundle.source,
        tested_combinations=total_combinations,
        candidates=candidates,
        walk_forward=windows,
        summary=summary,
        warnings=research_warnings,
        created_at=_now(),
    )


class ResearchService:
    def __init__(
        self, data_service: MarketDataService, path: Path = DB_PATH, max_workers: int = 2
    ) -> None:
        self.data_service = data_service
        self.path = path
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="research")
        self.cancel_events: dict[str, threading.Event] = {}
        self.lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS research_jobs (
                    id TEXT PRIMARY KEY,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL,
                    message TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "UPDATE research_jobs SET status='failed', "
                "error='服务重启导致任务中断', updated_at=? "
                "WHERE status IN ('queued','running')",
                (_now().isoformat(),),
            )

    def _update(self, job_id: str, **values: Any) -> None:
        values["updated_at"] = _now().isoformat()
        fields = ", ".join(f"{key}=?" for key in values)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE research_jobs SET {fields} WHERE id=?",  # noqa: S608 - fixed keys
                (*values.values(), job_id),
            )

    def submit(self, request: ResearchRequest) -> ResearchJob:
        job_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO research_jobs VALUES (?, ?, NULL, 'queued', 0, ?, NULL, ?, ?)",
                (
                    job_id,
                    request.model_dump_json(),
                    "已加入研究队列",
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        event = threading.Event()
        with self.lock:
            self.cancel_events[job_id] = event
        self.executor.submit(self._execute, job_id, request, event)
        return self.get(job_id)

    def _execute(self, job_id: str, request: ResearchRequest, cancelled: threading.Event) -> None:
        try:
            self._update(job_id, status="running", progress=0.01, message="正在读取行情")
            bundle = self.data_service.fetch(
                request.symbol,
                request.asset_class,
                request.interval,
                None,
                None,
                request.adjustment,
                request.data_source,
            )

            def report(value: float, message: str) -> None:
                self._update(job_id, progress=float(value), message=message)

            result = run_research(job_id, request, bundle, cancelled, report)
            self._update(
                job_id,
                status="completed",
                progress=1.0,
                message="研究完成",
                result_json=result.model_dump_json(),
            )
        except ResearchCancelled:
            self._update(job_id, status="cancelled", message="任务已取消")
        except Exception as exc:
            self._update(job_id, status="failed", message="研究失败", error=str(exc))
        finally:
            with self.lock:
                self.cancel_events.pop(job_id, None)

    def get(self, job_id: str) -> ResearchJob:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM research_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        result = (
            ResearchResult.model_validate_json(row["result_json"]) if row["result_json"] else None
        )
        return ResearchJob(
            id=row["id"],
            status=row["status"],
            progress=row["progress"],
            message=row["message"],
            result=result,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def cancel(self, job_id: str) -> ResearchJob:
        job = self.get(job_id)
        if job.status in {"completed", "failed", "cancelled"}:
            return job
        with self.lock:
            event = self.cancel_events.get(job_id)
        if event is not None:
            event.set()
        self._update(job_id, message="正在取消")
        return self.get(job_id)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
