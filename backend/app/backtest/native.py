"""Optional real Python engines, isolated from the API's Python dependencies."""
import json
import os
import subprocess
from tempfile import TemporaryDirectory
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request

from app.backtest.engine import serialize_bars
from app.backtest.metrics import calculate_metrics, drawdown_series, regime_metrics
from app.catalog import find_asset
from app.config import DATA_DIR, ROOT_DIR
from app.evaluation import build_evaluation
from app.indicators import calculate_indicators, serialize_indicators
from app.models import BacktestRequest, BacktestResult, EquityPoint, Trade
from app.backtest.strategy_plan import definition
from app.storage import DeletedLabComparison

PYTHON = Path(os.environ.get('ATLAS_ENGINE_PYTHON', ROOT_DIR / '.engine-venv/bin/python'))
BUNDLE = Path(os.environ.get('ATLAS_RQALPHA_BUNDLE', DATA_DIR / 'rqalpha/bundle'))
WORKER = ROOT_DIR / 'engine_workers/native.py'
MAX_NATIVE_BARS = 1_000_000
MAX_LONG_VNPY_BARS = 5_000_000
LONG_REPORT_THRESHOLD = 100_000
REPORT_POINTS = 6_000
REPORT_TRADE_LIMIT = 12_000
NATIVE_TIMEOUT = 600


def engine_status():
    versions, error = {}, None
    if PYTHON.is_file():
        try:
            result = subprocess.run([str(PYTHON), '-c',
                'import json; from importlib.metadata import version; import rqalpha; import vnpy_ctastrategy.backtesting; print(json.dumps({n:version(n) for n in ("rqalpha","vnpy","vnpy_ctastrategy")}))'],
                capture_output=True, text=True, timeout=20)
            versions = json.loads(result.stdout) if result.returncode == 0 else {}
            if not versions: error = 'Python 引擎依赖无法导入，请检查独立运行环境'
        except (OSError, subprocess.SubprocessError, ValueError): error = 'Python 引擎环境探测失败'
    else: error = '尚未安装独立 Python 引擎环境'
    bundle_ready = (BUNDLE / 'instruments.pk').is_file() and (BUNDLE / 'stocks.h5').is_file()
    return [dict(id='atlas', name='当前引擎 · 浏览器', available=True, version='browser-ts/v1', description='现有策略、市场及风控功能'),
        dict(id='vnpy', name='vn.py CTA', available='vnpy' in versions, version=versions.get('vnpy'),
             description='BTC/USDT 或 A股全周期 · 内置/自定义/Python · 本地已发布数据', reason=error),
        dict(id='rqalpha', name='RQAlpha', available='rqalpha' in versions and bundle_ready, version=versions.get('rqalpha'),
             description='A股 · 内置/自定义/Python · HF全周期 / bundle日线', reason=error or (None if bundle_ready else '尚未下载 RQAlpha 日线 bundle'))]


def validate_native(r):
    if r.backtest_engine not in {'vnpy', 'rqalpha'}: raise ValueError('请选择外部回测引擎')
    from app.backtest.strategy_plan import validate_strategy
    validate_strategy(r)
    if r.adjustment != 'auto' and not (r.data_source == 'huggingface' and r.adjustment == 'raw'): raise ValueError('外部引擎请使用自动复权；价格口径由各框架决定并记录在结果中')
    if r.execution_model == 'unified':
        from app.backtest.unified import unified_market_source, validate_unified
        validate_unified(r.model_dump(mode='json'))
        unified_market_source(r)
    cn = r.asset_class == 'equity' and r.symbol.endswith(('.SS', '.SZ'))
    hf = r.data_source == 'huggingface'
    if r.daily_action_version and (not cn or r.interval != '1d' or r.data_source != 'auto' or r.execution_model != 'native'):
        raise ValueError('分红送转校正适用于自动来源的沪深 A 股日线独立撮合')
    if hf and not cn:
        raise ValueError('Hugging Face 数据源仅支持项目沪深A股')
    if r.backtest_engine == 'rqalpha':
        if not cn or (not hf and r.interval != '1d'):
            raise ValueError('RQAlpha 支持A股Hugging Face全周期，或自动来源的bundle日线')
        if r.data_source not in {'auto', 'huggingface'}:
            raise ValueError('RQAlpha 请选择自动或Hugging Face来源')
    elif not ((r.symbol == 'BTC-USD' and r.asset_class == 'crypto') or (cn and (hf or r.interval == '1d'))):
        raise ValueError('vn.py 支持BTC-USD、A股日线或Hugging Face全周期')
    if r.backtest_engine == 'vnpy' and r.asset_class == 'crypto' and r.data_source not in {'auto','binance'}:
        raise ValueError('vn.py BTC 回测仅接受 Binance 已发布数据')
    if r.backtest_engine == 'vnpy' and cn and r.data_source not in {'auto','huggingface'}:
        raise ValueError('vn.py A股请选择自动或Hugging Face来源')


def normalize(r, raw, source, note, frame=None, account=None):
    if frame is None:
        bars, snapshots = raw['bars'], raw['snapshots']
        if len(bars) < 40 or len(bars) != len(snapshots):
            raise ValueError('原生引擎输出不足40根或账户记录不完整')
        if any(bar['time'] != snapshot['time'] for bar, snapshot in zip(bars, snapshots)):
            raise ValueError('原生引擎行情与账户时间不一致')
        frame = pd.DataFrame(bars).set_index('time')
        frame.index = pd.to_datetime(frame.index, unit='s', utc=True)
        account = np.array([(p['equity'], p['exposure']) for p in snapshots])
    if account.shape != (len(frame), 2) or not np.isfinite(account).all():
        raise ValueError('原生引擎账户记录不完整')
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing: raise ValueError('引擎返回乱序行情')
    equity = pd.Series(account[:, 0], index=frame.index)
    exposure = pd.Series(account[:, 1], index=frame.index)
    research_close = pd.Series(raw['research_closes'], index=frame.index) if 'research_closes' in raw else frame.close
    benchmark = r.initial_capital * research_close / research_close.iloc[0]
    fills = raw['fills']
    for fill in fills:
        fill['notional'] = fill['price'] * fill['quantity']
    metrics,warnings = calculate_metrics(equity,benchmark,fills,exposure,r.interval,r.asset_class,r.initial_capital,exchange=find_asset(r.symbol,r.asset_class).exchange)
    regimes=regime_metrics(equity,research_close,r.interval,r.asset_class,exchange=find_asset(r.symbol,r.asset_class).exchange)
    dd=drawdown_series(equity)
    long = len(frame) > LONG_REPORT_THRESHOLD
    chart = frame.tail(3200) if long else frame
    positions = np.linspace(0, len(frame)-1, REPORT_POINTS, dtype=int) if long else range(len(frame))
    selected_fills = enumerate(fills)
    if long:
        warnings.append(f'绩效按全部 {len(frame):,} 根 K 线计算。报告保留首尾和定距净值点，行情展示最近 3,200 根。')
        if len(fills) > REPORT_TRADE_LIMIT:
            warnings.append('成交统计使用全部成交，报告明细展示首笔和最近 12,000 笔。')
            from itertools import chain
            selected_fills = chain([(0, fills[0])], enumerate(fills[-REPORT_TRADE_LIMIT:], len(fills)-REPORT_TRADE_LIMIT))
    trades = [Trade.model_validate({**t, 'id': i+1, 'reason': t.get('reason', f'{r.backtest_engine} · {r.strategy_id}')})
              for i, t in selected_fills]
    first, last = (int(frame.index[i].timestamp()) for i in (0, -1))
    return BacktestResult(run_id=str(uuid4()),created_at=datetime.now(UTC),asset=find_asset(r.symbol,r.asset_class),
        interval=r.interval,adjustment='raw',bar_count=len(frame),
        backtest_engine=r.backtest_engine,execution_model=r.execution_model,execution_contract=raw.get('execution_contract'),daily_action_version=r.daily_action_version,engine_version=raw['version'],strategy=definition(r),
        data_source=source,valuation_currency='USDT' if r.backtest_engine=='vnpy' and r.asset_class=='crypto' else 'CNY',source_note=note,
        bars=serialize_bars(chart),indicators=serialize_indicators(calculate_indicators(chart).tail(3000)),trades=trades,
        equity=[EquityPoint(time=int(frame.index[i].timestamp()),equity=float(equity.iloc[i]),benchmark=float(benchmark.iloc[i]),drawdown=float(dd.iloc[i]),exposure=float(exposure.iloc[i])) for i in positions],
        metrics=metrics,regime_metrics=regimes,evaluation=build_evaluation(metrics,period={'start':first,'end':last,'observation_count':len(frame)-1},regime_metrics=regimes),
        warnings=[f'实际执行框架：{r.backtest_engine} {raw["version"]}；未生成当前引擎的 Proof。',*raw['warnings'],*warnings])


def execute_worker(r, payload, source, note, frame=None, account_path=None):
    try:
        process=subprocess.run([str(PYTHON),str(WORKER)],input=json.dumps(payload),text=True,capture_output=True,timeout=NATIVE_TIMEOUT,cwd=DATA_DIR)
    except subprocess.TimeoutExpired: raise ValueError('外部引擎运行超过600秒，请缩短区间') from None
    except OSError: raise ValueError('无法启动 Python 回测引擎') from None
    try: raw=json.loads(process.stdout)
    except ValueError: raise ValueError('原生引擎没有返回有效结果，请检查引擎环境') from None
    if process.returncode or raw.get('error'): raise ValueError(f'{r.backtest_engine} 执行失败：{str(raw.get("error","未知错误"))[:500]}')
    account = np.load(account_path, mmap_mode='r') if account_path else None
    return normalize(r,raw,source,note,frame,account)


def run_long_vnpy(r, frame, dataset_id, payload, source, note):
    from app.backtest.strategy_plan import portable_targets, validate_plan_market

    stamps = frame.index.as_unit('s').asi8
    if r.portable_plan:
        validate_plan_market(r.portable_plan, dataset_id, int(stamps[0]), int(stamps[-1]))
        targets = np.minimum(portable_targets(r.portable_plan, len(frame)), r.max_position)
    else:
        targets = None
    with TemporaryDirectory(prefix='atlas-vnpy-', dir=os.environ.get('TRINE_COMPARISON_WORKSPACE')) as directory:
        history_path = Path(directory) / 'ohlcv.npy'
        account_path = Path(directory) / 'account.npy'
        np.save(history_path, np.column_stack([stamps, frame[['open','high','low','close','volume']].to_numpy()]))
        payload.update(history_path=str(history_path), account_path=str(account_path))
        if targets is not None:
            targets_path = Path(directory) / 'targets.npy'
            np.save(targets_path, targets)
            payload['targets_path'] = str(targets_path)
            payload['request']['portable_plan'] = None
        return execute_worker(r, payload, source, note, frame, account_path)


def run_native(r, publications):
    validate_native(r)
    if r.execution_pipeline:
        p=r.execution_pipeline
        r=r.model_copy(update={'max_position':min(r.max_position,p.max_position),'commission_rate':p.commission_rate,'slippage_rate':p.slippage_rate,'max_participation_rate':p.max_participation_rate})
    status=next(s for s in engine_status() if s['id']==r.backtest_engine)
    if not status['available']: raise ValueError(status.get('reason') or '引擎尚未就绪')
    published = r.backtest_engine == 'vnpy' or r.data_source == 'huggingface' or r.strategy_id == 'python_portable' or r.execution_model == 'unified'
    manifest = None
    if published or not r.start or not r.end:
        manifest=publications.lookup(r.model_dump(mode='json',exclude={'base_currency'}))
    if published and not manifest:
        raise ValueError('所选周期尚无本地已发布行情，请先发布该周期数据')
    if manifest:
        start = r.start or datetime.fromtimestamp(manifest['start'], UTC)
        end = r.end or datetime.fromtimestamp(manifest['end'], UTC)
        if manifest['source'] in {'binance', 'binance:cache'}:
            from app.zkp_dataset import SECONDS
            closed = datetime.fromtimestamp(manifest['fetched_at'] - SECONDS[r.interval], UTC)
            end = min(end, closed)
        if start >= end:
            raise ValueError('所选区间没有足够的有效 K 线')
        r = r.model_copy(update={'start':start, 'end':end})
    payload={'engine':r.backtest_engine,'request':r.model_dump(mode='json'),'bundle_path':str(BUNDLE)}
    source,note='rqalpha-bundle','RQAlpha 原生中国股票数据包；数据范围以 bundle 为准。'
    if manifest:
        if r.execution_model == 'unified':
            from app.backtest.unified import unified_market_source
            if manifest['source'] != unified_market_source(r) or manifest['adjustment'] != 'raw':
                raise ValueError('统一研究口径需要已发布的不复权行情')
        parts=[p for p in manifest['chunks'] if p['end']>=r.start.timestamp() and p['start']<=r.end.timestamp()]
        long_vnpy = r.backtest_engine == 'vnpy' and r.execution_model == 'native' and not r.daily_action_version and not r.custom_strategy and r.python_source is None
        if long_vnpy and r.strategy_id == 'sma_cross':
            from app.strategies.catalog import validate_params
            params = validate_params(r.strategy_id, r.params)
            long_vnpy = params['confirm_bars'] == 1 and params['min_gap'] == 0 and params['trend_filter'] == 0
        else:
            long_vnpy = long_vnpy and r.strategy_id == 'python_portable'
        limit = MAX_LONG_VNPY_BARS if long_vnpy else MAX_NATIVE_BARS
        # Boundary chunks can include up to 2*chunk_size out-of-range bars.
        if sum(p['count'] for p in parts[1:-1]) > limit:
            raise ValueError(f'当前引擎与策略组合最多支持 {limit:,} 根 K 线，请选择更短的时间区间')
        bundle=publications.bundle(manifest['dataset_id'],r.start,r.end)
        if len(bundle.frame) > limit:
            raise ValueError(f'本次选中 {len(bundle.frame):,} 根 K 线，当前引擎与策略组合最多支持 {limit:,} 根')
        if len(bundle.frame)<40: raise ValueError('至少需要40根K线才能回测')
        if (r.data_source == 'huggingface' and bundle.source != 'hf-ohlcv') or bundle.source == 'hf-unverified': raise ValueError('请先重新发布规范化的Hugging Face数据')
        source,note=bundle.source,f'{bundle.source_note or ""} dataset_id={manifest["dataset_id"]}'
        if long_vnpy and len(bundle.frame) > LONG_REPORT_THRESHOLD:
            return run_long_vnpy(r, bundle.frame, manifest['dataset_id'], payload, source, note)
        payload['bars']=[b.model_dump() for b in serialize_bars(bundle.frame)]
        if r.data_source == 'huggingface':
            daily=publications.lookup({**r.model_dump(mode='json',exclude={'base_currency'}), 'interval':'1d', 'adjustment':'raw'})
            if daily:
                history=publications.bundle(daily['dataset_id']).frame
                before=history.loc[history.index < bundle.frame.index[0].tz_convert('Asia/Shanghai').normalize()]
                payload['previous_daily']=[b.model_dump() for b in serialize_bars(before.tail(2))]
                if r.interval == '1wk':
                    last=bundle.frame.index[-1] + pd.Timedelta(days=6)
                    payload['daily_bars']=[b.model_dump() for b in serialize_bars(history.loc[(history.index >= bundle.frame.index[0]) & (history.index <= last)])]
    if 'bars' not in payload:
        # Bundle OHLCV is loaded in the framework's environment; user source is
        # never imported. All strategy plans are then compiled by trusted code.
        loaded=subprocess.run([str(PYTHON),str(WORKER)],input=json.dumps({**payload,'operation':'load_bundle'}),text=True,capture_output=True,timeout=60,cwd=DATA_DIR)
        if loaded.returncode:raise ValueError('RQAlpha bundle读取失败')
        payload['bars']=json.loads(loaded.stdout)['bars']
        if len(payload['bars'])<40:raise ValueError('至少需要40根K线才能回测')
        manifest={'dataset_id':None}
    if 'bars' in payload:
        from app.backtest.strategy_plan import prepare_plan
        plan=prepare_plan(r,payload['bars'],manifest['dataset_id'])
        if plan is not None: payload['prepared_strategy']=plan
    return execute_worker(r, payload, source, note)


def native_router(publications, runs, drafts=None):
    router=APIRouter(prefix='/api/v1')
    @router.get('/backtest-engines')
    def engines(): return engine_status()
    @router.get('/backtests/daily-actions')
    def daily_actions(
        symbol: str = Query(pattern=r"^[0-9]{6}\.(SS|SZ)$"),
        start: int = Query(ge=0, le=4_102_444_800),
        end: int = Query(ge=0, le=4_102_444_800),
    ):
        if start >= end:
            raise HTTPException(422, '公司行动区间无效')
        if not PYTHON.is_file() or not all((BUNDLE / filename).is_file() for filename in (
            'stocks.h5', 'dividends.h5', 'split_factor.h5', 'ex_cum_factor.h5',
        )):
            raise HTTPException(503, '本地 RQAlpha 分红送转数据不可用')
        try:
            payload = {'operation': 'daily_actions', 'request': {'symbol': symbol, 'from': start, 'to': end}, 'bundle_path': str(BUNDLE)}
            process = subprocess.run([str(PYTHON), str(WORKER)], input=json.dumps(payload), text=True,
                                     capture_output=True, timeout=10, cwd=DATA_DIR)
            result = json.loads(process.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise HTTPException(503, '无法读取本地 RQAlpha 分红送转数据') from None
        if process.returncode:
            raise HTTPException(422, str(result.get('error', '分红送转数据不可用'))[:200])
        return result

    @router.post('/backtests/native',response_model=BacktestResult)
    def backtest(body:BacktestRequest, request:Request):
        if request.headers.get('X-Atlas-Lab-Owner'):
            from app.lab_strategies import require_lab_owner
            require_lab_owner(request)
        payload = body.model_dump(mode='json')
        if body.lab_strategy_id:
            from app.lab_strategies import require_lab_owner, single_run_snapshot
            if drafts is None:
                raise HTTPException(503, "策略库不可用")
            payload['lab_snapshot'] = single_run_snapshot(drafts, require_lab_owner(request), body.lab_strategy_id, payload)
        try: result=run_native(body,publications)
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        if body.persist:
            try:
                runs.save(request.state.user.id, 'single', payload, result.model_dump(mode='json'), lab_strategy_id=body.lab_strategy_id)
            except DeletedLabComparison as exc:
                raise HTTPException(409, str(exc)) from exc
        return result
    return router
