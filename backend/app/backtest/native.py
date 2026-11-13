"""Optional real Python engines, isolated from the API's Python dependencies."""
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, HTTPException, Request

from app.backtest.engine import serialize_bars
from app.backtest.metrics import calculate_metrics, drawdown_series, regime_metrics
from app.catalog import find_asset
from app.config import DATA_DIR, ROOT_DIR
from app.evaluation import build_evaluation
from app.indicators import calculate_indicators, serialize_indicators
from app.models import BacktestRequest, BacktestResult, EquityPoint, Trade
from app.backtest.strategy_plan import definition

PYTHON = Path(os.environ.get('ATLAS_ENGINE_PYTHON', ROOT_DIR / '.engine-venv/bin/python'))
BUNDLE = Path(os.environ.get('ATLAS_RQALPHA_BUNDLE', DATA_DIR / 'rqalpha/bundle'))
WORKER = ROOT_DIR / 'engine_workers/native.py'
MAX_NATIVE_BARS = 1_000_000
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
             description='BTC/USDT 或 A股全周期 · 内置/自定义/Python · 本地已发布数据 · 最多100万根', reason=error),
        dict(id='rqalpha', name='RQAlpha', available='rqalpha' in versions and bundle_ready, version=versions.get('rqalpha'),
             description='A股 · 内置/自定义/Python · HF全周期 / bundle日线', reason=error or (None if bundle_ready else '尚未下载 RQAlpha 日线 bundle'))]


def validate_native(r):
    if r.backtest_engine not in {'vnpy', 'rqalpha'}: raise ValueError('请选择外部回测引擎')
    from app.backtest.strategy_plan import validate_strategy
    validate_strategy(r)
    if not r.start or not r.end: raise ValueError('外部引擎回测必须指定开始和结束日期')
    if r.adjustment != 'auto' and not (r.data_source == 'huggingface' and r.adjustment == 'raw'): raise ValueError('外部引擎请使用自动复权；价格口径由各框架决定并记录在结果中')
    if r.execution_model == 'unified':
        from app.backtest.unified import validate_unified
        validate_unified(r.model_dump(mode='json'))
        if r.data_source != 'huggingface': raise ValueError('统一研究口径请选择Hugging Face已发布行情')
    cn = r.asset_class == 'equity' and r.symbol.endswith(('.SS', '.SZ'))
    hf = r.data_source == 'huggingface'
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


def normalize(r, raw, source, note):
    bars = raw['bars']; snapshots = raw['snapshots']
    if len(bars)<40 or len(bars)!=len(snapshots): raise ValueError('原生引擎输出不足40根或账户记录不完整')
    if any(bar['time'] != snapshot['time'] for bar, snapshot in zip(bars, snapshots)):
        raise ValueError('原生引擎行情与账户时间不一致')
    frame = pd.DataFrame(bars).set_index('time')
    frame.index = pd.to_datetime(frame.index,unit='s',utc=True)
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing: raise ValueError('引擎返回乱序行情')
    equity = pd.Series([p['equity'] for p in snapshots],index=frame.index)
    exposure = pd.Series([p['exposure'] for p in snapshots],index=frame.index)
    benchmark = r.initial_capital*frame.close/frame.close.iloc[0]
    trades = [Trade(id=i+1,reason=t.get('reason',f'{r.backtest_engine} · {r.strategy_id}'),notional=t['price']*t['quantity'],**{k:v for k,v in t.items() if k not in {'id','reason','notional'}}) for i,t in enumerate(raw['fills'])]
    metrics,warnings = calculate_metrics(equity,benchmark,[t.model_dump() for t in trades],exposure,r.interval,r.asset_class,r.initial_capital,exchange=find_asset(r.symbol,r.asset_class).exchange)
    regimes=regime_metrics(equity,frame.close,r.interval,r.asset_class,exchange=find_asset(r.symbol,r.asset_class).exchange)
    dd=drawdown_series(equity)
    return BacktestResult(run_id=str(uuid4()),created_at=datetime.now(UTC),asset=find_asset(r.symbol,r.asset_class),
        interval=r.interval,adjustment='raw',
        backtest_engine=r.backtest_engine,execution_model=r.execution_model,execution_contract=raw.get('execution_contract'),engine_version=raw['version'],strategy=definition(r),
        data_source=source,valuation_currency='USDT' if r.backtest_engine=='vnpy' and r.asset_class=='crypto' else 'CNY',source_note=note,
        bars=serialize_bars(frame),indicators=serialize_indicators(calculate_indicators(frame).tail(3000)),trades=trades,
        equity=[EquityPoint(time=b['time'],equity=float(equity.iloc[i]),benchmark=float(benchmark.iloc[i]),drawdown=float(dd.iloc[i]),exposure=float(exposure.iloc[i])) for i,b in enumerate(bars)],
        metrics=metrics,regime_metrics=regimes,evaluation=build_evaluation(metrics,period={'start':bars[0]['time'],'end':bars[-1]['time'],'observation_count':len(bars)-1},regime_metrics=regimes),
        warnings=[f'实际执行框架：{r.backtest_engine} {raw["version"]}；未生成当前引擎的 Proof。',*raw['warnings'],*warnings])


def run_native(r, publications):
    validate_native(r)
    if r.execution_pipeline:
        p=r.execution_pipeline
        r=r.model_copy(update={'max_position':min(r.max_position,p.max_position),'commission_rate':p.commission_rate,'slippage_rate':p.slippage_rate,'max_participation_rate':p.max_participation_rate})
    status=next(s for s in engine_status() if s['id']==r.backtest_engine)
    if not status['available']: raise ValueError(status.get('reason') or '引擎尚未就绪')
    payload={'engine':r.backtest_engine,'request':r.model_dump(mode='json'),'bundle_path':str(BUNDLE)}
    source,note='rqalpha-bundle','RQAlpha 原生中国股票数据包；数据范围以 bundle 为准。'
    if r.backtest_engine=='vnpy' or r.data_source=='huggingface' or r.strategy_id=='python_portable':
        manifest=publications.lookup(r.model_dump(mode='json',exclude={'base_currency'}))
        if not manifest: raise ValueError('所选周期尚无本地已发布行情，请先发布该周期数据')
        parts=[p for p in manifest['chunks'] if p['end']>=r.start.timestamp() and p['start']<=r.end.timestamp()]
        # Boundary chunks can include up to 2*chunk_size out-of-range bars.
        if sum(p['count'] for p in parts[1:-1])>MAX_NATIVE_BARS: raise ValueError('外部引擎单次最多100万根K线，请缩短回测区间')
        bundle=publications.bundle(manifest['dataset_id'],r.start,r.end)
        if len(bundle.frame)>MAX_NATIVE_BARS: raise ValueError('外部引擎单次最多100万根K线')
        if len(bundle.frame)<40: raise ValueError('至少需要40根K线才能回测')
        if (r.data_source == 'huggingface' and bundle.source != 'hf-ohlcv') or bundle.source == 'hf-unverified': raise ValueError('请先重新发布规范化的Hugging Face数据')
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
        source,note=bundle.source,f'{bundle.source_note or ""} dataset_id={manifest["dataset_id"]}'
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
    try:
        process=subprocess.run([str(PYTHON),str(WORKER)],input=json.dumps(payload),text=True,capture_output=True,timeout=NATIVE_TIMEOUT,cwd=DATA_DIR)
    except subprocess.TimeoutExpired: raise ValueError('外部引擎运行超过600秒，请缩短区间') from None
    except OSError: raise ValueError('无法启动 Python 回测引擎') from None
    try: raw=json.loads(process.stdout)
    except ValueError: raise ValueError('原生引擎没有返回有效结果，请检查引擎环境') from None
    if process.returncode or raw.get('error'): raise ValueError(f'{r.backtest_engine} 执行失败：{str(raw.get("error","未知错误"))[:500]}')
    return normalize(r,raw,source,note)


def native_router(publications, runs):
    router=APIRouter(prefix='/api/v1')
    @router.get('/backtest-engines')
    def engines(): return engine_status()
    @router.post('/backtests/native',response_model=BacktestResult)
    def backtest(body:BacktestRequest, request:Request):
        try: result=run_native(body,publications)
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        if body.persist: runs.save(request.state.user.id,'single',body.model_dump(mode='json'),result.model_dump(mode='json'))
        return result
    return router
