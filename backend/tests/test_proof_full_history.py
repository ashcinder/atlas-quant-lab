from datetime import UTC,datetime
import pandas as pd
from app.data.candle_store import CandleStore

def test_all_history_merges_snapshots_keeps_newest_overlap_and_closed_bars(tmp_path):
    store=CandleStore(tmp_path/'market.db')
    def frame(days,close):
        return pd.DataFrame({'open':close,'high':[v+1 for v in close],'low':[v-1 for v in close],'close':close,'volume':1},index=pd.to_datetime(days,utc=True))
    store.write('binance_BTC-USD_1d_old.csv.gz',frame(['2025-01-01','2025-01-02'],[10,11]),datetime(2025,1,3,tzinfo=UTC))
    store.write('binance_BTC-USD_1d_new.csv.gz',frame(['2025-01-02','2025-01-03'],[12,13]),datetime(2025,1,4,tzinfo=UTC))
    store.write('yahoo_BTC-USD_1d_other.csv.gz',frame(['2024-01-01'],[20]))
    result=store.full_history('binance','BTC-USD','1d')
    assert list(result.close)==[10,12,13]
    assert len(result)==3
