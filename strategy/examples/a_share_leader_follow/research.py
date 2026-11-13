"""A-share next-session leader limit-up / peer-following research.

Trusted offline research program; does not call a broker or a cloud model.
Run with backend/.engine-venv/bin/python (Python 3.13).
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import inspect
import json
from pathlib import Path
import pickle
import time

import h5py
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

ROOT = Path(__file__).resolve().parents[3]
FEATURES = ['ret1_limit', 'ret5', 'ret20', 'volume_ratio', 'close_location',
            'volatility20', 'ma20_gap', 'prior_touches20', 'industry_momentum',
            'industry_breadth', 'log_adv', 'limit_pct']

@dataclass(frozen=True)
class Parameters:
    version: str = 'leader_peer_v1'
    test_start: str = '2023-01-01'
    test_end: str = '2026-10-30'
    train_years: int = 3
    probability_floor: float = .08
    training_quantile: float = .80
    min_industry_members: int = 5
    min_listing_bars: int = 120
    min_adv: float = 50_000_000
    leader_min_adv: float = 100_000_000
    followers_per_industry: int = 2
    holding_sessions: int = 3
    max_positions: int = 6
    stock_weight: float = .10
    industry_weight: float = .20
    max_gross: float = .60
    max_open_gap: float = .03
    max_adv_fraction: float = .005
    stop_loss: float = .05
    take_profit: float = .08
    capital: float = 1_000_000
    commission: float = .0003
    impact: float = .001
    transfer: float = .00001
    min_commission: float = 5


def metadata(bundle: Path):
    with (bundle/'instruments.pk').open('rb') as handle:
        records=pickle.load(handle)  # Trusted, operator-installed RQAlpha bundle.
    with h5py.File(bundle/'stocks.h5') as stocks:
        codes=set(stocks)
    records=[r for r in records if r.get('type')=='CS' and r['order_book_id'] in codes
             and r['order_book_id'].endswith(('.XSHG','.XSHE'))
             and r.get('industry_code') not in (None,'','Unknown')
             and r.get('industry_name') not in (None,'','未知')]
    return {r['order_book_id']:r for r in records}


def stock_features(raw, st_dates, code, industry, calendar, p):
    frame=pd.DataFrame(raw)
    frame['age']=np.arange(len(frame))
    frame['date']=pd.to_datetime((frame.datetime//1_000_000).astype(str),format='%Y%m%d')
    frame=frame.loc[frame.date>=pd.Timestamp('2019-01-01')].copy()
    if len(frame)<100: return None
    # Native prev_close is the ex-rights reference, unlike a raw close.shift(1).
    frame['ret1']=frame.close/frame.prev_close-1
    valid_price=(frame.close>0)&(frame.prev_close>0)&(frame.volume>0)
    frame['ret1']=frame.ret1.where(valid_price)
    frame['ret5']=(1+frame.ret1).rolling(5,min_periods=5).apply(np.prod,raw=True)-1
    frame['ret20']=(1+frame.ret1).rolling(20,min_periods=20).apply(np.prod,raw=True)-1
    price_index=(1+frame.ret1.fillna(0)).cumprod()
    frame['ma20_gap']=price_index/price_index.rolling(20,min_periods=20).mean()-1
    frame['adv20']=frame.total_turnover.rolling(20,min_periods=20).mean()
    frame['volume_ratio']=frame.volume/frame.volume.rolling(20,min_periods=20).mean()
    frame['close_location']=((frame.close-frame.low)/(frame.high-frame.low).replace(0,np.nan)).fillna(.5)
    frame['volatility20']=frame.ret1.rolling(20,min_periods=20).std()
    frame['limit_pct']=frame.limit_up/frame.prev_close-1
    frame['ret1_limit']=frame.ret1/frame.limit_pct
    frame['touch']=(frame.high>=frame.limit_up-.005)&(frame.limit_up>0)&valid_price
    frame['prior_touches20']=frame.touch.rolling(20,min_periods=20).mean()
    frame['log_adv']=np.log(frame.adv20.clip(lower=1))
    frame['label_date']=frame.date.shift(-1)
    expected=frame.date.map(dict(zip(calendar[:-1],calendar[1:])))
    next_valid=(frame.label_date==expected)&(frame.volume.shift(-1)>0)&(frame.limit_up.shift(-1)>0)
    frame['target_touch']=frame.touch.shift(-1).where(next_valid).astype(float)
    frame['target_sealed']=(frame.close.shift(-1)>=frame.limit_up.shift(-1)-.005).where(next_valid).astype(float)
    # Membership and eligibility use only this date's security state; do not
    # filter today's list by future delisting status or next-day liquidity.
    date_numbers=(frame.datetime//1_000_000).to_numpy()
    st=np.isin(date_numbers,np.asarray(st_dates,dtype=np.int64))
    eligible=valid_price & ~st & (frame.age>=p.min_listing_bars) & (frame.adv20>=p.min_adv)
    eligible &= frame.limit_pct.between(.04,.31)  # Exclude unlimited IPO / invalid bars.
    cols=['date','label_date','ret1','ret1_limit','ret5','ret20','ma20_gap','adv20',
          'volume_ratio','close_location','volatility20','prior_touches20','log_adv',
          'limit_pct','target_touch','target_sealed']
    result=frame.loc[eligible,cols].replace([np.inf,-np.inf],np.nan)
    result=result.dropna(subset=[c for c in cols if c not in ('label_date','target_touch','target_sealed')])
    for col in cols:
        if col not in ('date','label_date'):result[col]=result[col].astype('float32')
    result['symbol']=code; result['industry']=industry
    return result


def prepare(bundle, output, p, refresh=False):
    cache=output/'leader_candidates.pkl'
    manifest=output/'feature_cache_manifest.json'
    signature={'code':hashlib.sha256((inspect.getsource(stock_features)+inspect.getsource(prepare)).encode()).hexdigest(),
        'parameters':{key:getattr(p,key) for key in ['version','min_industry_members','min_listing_bars','min_adv','leader_min_adv','followers_per_industry']},
        'data':{name:[(bundle/name).stat().st_size,(bundle/name).stat().st_mtime_ns]
                for name in ['stocks.h5','st_stock_days.h5','instruments.pk','trading_dates.npy']}}
    meta=metadata(bundle)
    if cache.exists() and manifest.exists() and not refresh and json.loads(manifest.read_text())==signature:
        cached=pd.read_pickle(cache)
        return cached,meta
    calendar=pd.to_datetime(np.load(bundle/'trading_dates.npy').astype('int64').astype(str),format='%Y%m%d')
    pieces=[]; started=time.time()
    with h5py.File(bundle/'stocks.h5') as stocks,h5py.File(bundle/'st_stock_days.h5') as st:
        for i,(code,info) in enumerate(sorted(meta.items()),1):
            part=stock_features(stocks[code][:],st[code][:] if code in st else [],code,info['industry_code'],calendar,p)
            if part is not None and not part.empty:pieces.append(part)
            if i%500==0:print(f'features {i}/{len(meta)} ({time.time()-started:.0f}s)',flush=True)
    panel=pd.concat(pieces,ignore_index=True)
    panel['symbol']=panel.symbol.astype('category');panel['industry']=panel.industry.astype('category')
    keys=['date','industry']; grouped=panel.groupby(keys,observed=True)
    panel['members']=grouped.symbol.transform('size')
    panel['industry_momentum']=grouped.ret20.transform('median')
    panel['industry_breadth']=panel.ret1.gt(0).groupby([panel.date,panel.industry],observed=True).transform('mean').astype('float32')
    panel['leader_score']=.55*grouped.ret20.rank(pct=True)+.30*grouped.adv20.rank(pct=True)+.15*grouped.ret5.rank(pct=True)
    leader_pool=panel.loc[(panel.members>=p.min_industry_members)&(panel.adv20>=p.leader_min_adv)]
    leaders=leader_pool.sort_values(keys+['leader_score','symbol'],ascending=[True,True,False,True]).drop_duplicates(keys).copy()
    # All peer selections are frozen at T close. No T+1 high/close is joined here.
    comparison=leaders[keys+['symbol','ret20']].rename(columns={'symbol':'leader','ret20':'leader_ret20'})
    peers=panel.merge(comparison,on=keys,how='inner')
    peers=peers.loc[(peers.symbol!=peers.leader)&(peers.ret20>=0)&(peers.ma20_gap>0)
                    &(peers.ret1_limit<.6)&(peers.ret1>-.03)&(peers.ret20<=peers.leader_ret20)].copy()
    peers['lag']=peers.leader_ret20-peers.ret20
    pg=peers.groupby(keys,observed=True)
    peers['peer_score']=.5*pg.lag.rank(pct=True)+.3*pg.ret5.rank(pct=True)+.2*pg.adv20.rank(pct=True)
    peers=peers.sort_values(keys+['peer_score','symbol'],ascending=[True,True,False,True]).groupby(keys,observed=True).head(p.followers_per_industry)
    selected={key:group[['symbol','adv20']].to_dict('records') for key,group in peers.groupby(keys,observed=True)}
    leaders['followers']=[selected.get((date,industry),[]) for date,industry in zip(leaders.date,leaders.industry)]
    leaders['candidate']=(leaders.ret20>0)&(leaders.ma20_gap>0)&(leaders.industry_momentum>0)&leaders.followers.map(bool)
    leaders=leaders.sort_values(['date','industry']).reset_index(drop=True)
    leaders.to_pickle(cache)
    manifest.write_text(json.dumps(signature,indent=2))
    print(f'prepared {len(meta)} securities, {len(leaders)} leader-days, {len(panel)} eligible stock-days',flush=True)
    return leaders,meta


def fit_logistic(x,y,penalty=1.0):
    mean=x.mean(axis=0);scale=x.std(axis=0);scale=np.where(scale<1e-6,1,scale)
    z=np.clip((x-mean)/scale,-6,6)
    design=np.column_stack([np.ones(len(z)),z])
    initial=np.zeros(design.shape[1]);rate=np.clip(y.mean(),1e-5,1-1e-5);initial[0]=np.log(rate/(1-rate))
    def objective(beta):
        logit=design@beta
        loss=np.logaddexp(0,logit).sum()-y@logit+penalty*(beta[1:]@beta[1:])/2
        grad=design.T@(expit(logit)-y);grad[1:]+=penalty*beta[1:]
        return loss,grad
    result=minimize(objective,initial,jac=True,method='L-BFGS-B',options={'maxiter':200,'ftol':1e-9})
    if not result.success: raise ValueError('Logistic model did not converge: '+result.message)
    return {'mean':mean.tolist(),'scale':scale.tolist(),'beta':result.x.tolist(),'samples':len(y),'positives':int(y.sum())}


def predict(model,x):
    z=np.clip((x-np.asarray(model['mean']))/np.asarray(model['scale']),-6,6)
    return expit(np.column_stack([np.ones(len(z)),z])@np.asarray(model['beta']))


def walk_forward(leaders,p):
    candidates=leaders.loc[leaders.candidate].copy()
    candidates['probability']=np.nan;candidates['threshold']=np.nan
    audit=[]; models={}
    start=pd.Timestamp(p.test_start);end=pd.Timestamp(p.test_end)
    for month in pd.period_range(start,end,freq='M'):
        boundary=month.start_time
        training=candidates.loc[(candidates.date>=boundary-pd.DateOffset(years=p.train_years))
                    &(candidates.date<boundary)&(candidates.label_date<boundary)&candidates.target_touch.notna()]
        test=candidates.loc[(candidates.date>=max(boundary,start))&(candidates.date<=min(month.end_time,end))]
        if test.empty:continue
        if len(training)<500 or training.target_touch.sum()<20:
            audit.append({'month':str(month),'skipped':'insufficient training labels'});continue
        model=fit_logistic(training[FEATURES].to_numpy(dtype=float),training.target_touch.to_numpy(dtype=float))
        threshold=max(p.probability_floor,float(np.quantile(predict(model,training[FEATURES].to_numpy(dtype=float)),p.training_quantile)))
        candidates.loc[test.index,'probability']=predict(model,test[FEATURES].to_numpy(dtype=float))
        candidates.loc[test.index,'threshold']=threshold
        record={'month':str(month),'train_start':str(training.date.min().date()),'train_end':str(training.date.max().date()),
                'last_training_label':str(training.label_date.max().date()),'test_start':str(test.date.min().date()),
                'train_rows':len(training),'positive_labels':int(training.target_touch.sum()),'threshold':threshold,'test_rows':len(test)}
        assert pd.Timestamp(record['last_training_label'])<boundary
        audit.append(record);models[str(month)]=model
    test=candidates.loc[candidates.date.between(start,end)&candidates.probability.notna()].copy()
    test['selected']=test.probability>=test.threshold
    return test,audit,models


def prediction_metrics(predictions):
    data=predictions.dropna(subset=['target_touch'])
    chosen=data.loc[data.selected]
    def ci(k,n):
        if not n:return [None,None]
        z=1.96;v=k/n;den=1+z*z/n;center=(v+z*z/(2*n))/den
        half=z*np.sqrt(v*(1-v)/n+z*z/(4*n*n))/den
        return [float(center-half),float(center+half)]
    positives=int(chosen.target_touch.sum());n=len(chosen)
    daily=chosen.groupby('date').target_touch.agg(['sum','count'])
    rng=np.random.default_rng(20261112);boot=[]
    if len(daily)>=20:
        for _ in range(1000):
            starts=rng.integers(0,len(daily)-19,size=int(np.ceil(len(daily)/20)))
            indices=np.concatenate([np.arange(s,s+20) for s in starts])[:len(daily)]
            sample=daily.iloc[indices]
            boot.append(float(sample['sum'].sum()/sample['count'].sum()))
    return {'eligible_leader_days':len(data),'selected_leader_days':n,'touch_hits':positives,
        'touch_precision':float(chosen.target_touch.mean()) if n else None,
        'sealed_precision':float(chosen.target_sealed.mean()) if n else None,
        'touch_base_rate':float(data.target_touch.mean()),'precision_wilson_95':ci(positives,n),
        'precision_date_block_95':np.quantile(boot,[.025,.975]).tolist() if boot else None,
        'recall':positives/float(data.target_touch.sum()) if data.target_touch.sum() else None,
        'brier':float(np.mean((data.probability-data.target_touch)**2)),
        'constant_probability_brier':float(np.mean((data.target_touch.mean()-data.target_touch)**2))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,default=ROOT/'backend/.data/rqalpha/bundle')
    parser.add_argument('--output',type=Path,default=ROOT/'.artifacts/a-share-leader-follow')
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    p=Parameters()
    (args.output/'parameters.json').write_text(json.dumps(asdict(p),ensure_ascii=False,indent=2))
    leaders,meta=prepare(args.bundle,args.output,p,args.refresh)
    predictions,audit,models=walk_forward(leaders,p)
    (args.output/'walk_forward.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    (args.output/'models.json').write_text(json.dumps({'features':FEATURES,'models':models},indent=2))
    forecasts=predictions.copy();forecasts['followers']=forecasts.followers.map(json.dumps)
    forecasts.to_csv(args.output/'forecasts.csv.gz',index=False,compression='gzip')
    stats=prediction_metrics(predictions)
    (args.output/'prediction_metrics.json').write_text(json.dumps(stats,indent=2))
    latest=predictions.loc[(predictions.date==predictions.date.max())&predictions.selected]
    plan={'as_of':str(predictions.date.max().date()),'mode':'research_simulation_only',
          'warning':'Historical snapshot; NOT a current next-session trading recommendation.',
          'signals':latest[['symbol','industry','probability','threshold','followers']].to_dict('records')}
    (args.output/'latest_signal_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    print(json.dumps(stats),flush=True)
    if args.prepare_only:return
    from rq_backtest import run_experiments
    run_experiments(args.bundle,args.output,p,predictions,meta)

if __name__=='__main__':main()
