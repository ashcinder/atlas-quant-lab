"""RQAlpha extension for immutable, pre-aggregated HF bars.

Uses RQAlpha's data-source/event-source extension points. Prices and volumes
come exclusively from the selected publication; bundle supplies instrument,
calendar, corporate-action and daily price-limit metadata. No RQData service.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from rqalpha.core.events import Event, EVENT
from rqalpha.data.base_data_source import BaseDataSource
from rqalpha.interface import AbstractEventSource, AbstractMod

PAYLOAD = None  # Set by the trusted worker, in this isolated subprocess only.
FIELDS = ['open', 'high', 'low', 'close', 'volume']
DTYPE = [('datetime', 'u8')] + [(f, 'f8') for f in FIELDS + ['limit_up', 'limit_down', 'total_turnover']]


class PublishedSource(BaseDataSource):
    def __init__(self, config, payload):
        super().__init__(config)
        self.code = payload['request']['symbol'].replace('.SS', '.XSHG').replace('.SZ', '.XSHE')
        self.interval = payload['request']['interval']
        unified = payload['request'].get('execution_model') == 'unified'
        self.input_bars = payload['bars']
        self.by_event = {}
        self.events = []
        daily_input = [*payload.get('previous_daily', []), *payload.get('daily_bars', self.input_bars)]
        frame = pd.DataFrame(daily_input)
        frame.index = pd.to_datetime(frame.time, unit='s', utc=True).dt.tz_convert('Asia/Shanghai')
        daily = frame.groupby(frame.index.date).agg(open=('open','first'),high=('high','max'),
            low=('low','min'),close=('close','last'),volume=('volume','sum'))
        self.daily = {}
        self.missing_limits = 0
        instrument = next(self.get_instruments([self.code]))
        for day, row in daily.iterrows():
            meta = None if unified else super().get_bar(instrument, day, '1d')
            limits = [float(meta[f]) if meta is not None and f in meta.dtype.names else np.nan
                      for f in ('limit_up', 'limit_down')]
            if not all(np.isfinite(limits)):
                self.missing_limits += 1
            self.daily[day] = self.record(datetime.combine(day, datetime.min.time()), row, limits)
        self.daily_array = np.array(list(self.daily.values()), dtype=DTYPE)
        if self.interval == '1wk' and not unified:
            for day, record in self.daily.items():
                if day >= pd.Timestamp(self.input_bars[0]['time'],unit='s',tz='UTC').tz_convert('Asia/Shanghai').date():
                    dt = datetime.combine(day,datetime.min.time()).replace(hour=15)
                    self.by_event[dt] = record
                    self.events.append((dt, None))
        for bar in self.input_bars:
            opened = pd.Timestamp(bar['time'], unit='s', tz='UTC').tz_convert('Asia/Shanghai').to_pydatetime().replace(tzinfo=None)
            if self.interval in ('4h', '1d'):
                end = opened.replace(hour=15, minute=0)
            elif self.interval == '1wk':
                dates = self.get_trading_calendars()[next(iter(self.get_trading_calendars()))]
                candidates = dates[(dates.date >= opened.date()) & (dates.date <= (opened + timedelta(days=6)).date())]
                end = candidates[-1].to_pydatetime().replace(hour=15, minute=0)
            else:
                end = opened + timedelta(minutes={'1m':1,'5m':5,'15m':15,'1h':60}[self.interval])
            meta = None if unified else super().get_bar(instrument, end.date(), '1d')
            limits = [float(meta[f]) if meta is not None and f in meta.dtype.names else np.nan for f in ('limit_up','limit_down')]
            self.by_event[end] = self.record(end, bar, limits)
            if self.interval == '1wk':
                self.events = [(dt,b) for dt,b in self.events if dt != end]
            self.events.append((end, bar))
        self.events.sort(key=lambda item:item[0])

    @staticmethod
    def record(dt, bar, limits):
        # Turnover is unavailable in the shared OHLCV format; don't invent it.
        return np.array([(int(dt.strftime('%Y%m%d%H%M%S')), *[float(bar[f]) for f in FIELDS],
                          *limits, np.nan)], dtype=DTYPE)[0]

    def get_bar(self, instrument, dt, frequency):
        if instrument.order_book_id != self.code:
            return super().get_bar(instrument, dt, frequency)
        return self.daily.get(dt.date() if isinstance(dt, datetime) else dt) if frequency == '1d' else self.by_event.get(dt)

    def history_bars(self, instrument, bar_count, frequency, fields, dt, skip_suspended=True,
                     include_now=False, adjust_type='pre', adjust_orig=None):
        if instrument.order_book_id != self.code:
            return super().history_bars(instrument,bar_count,frequency,fields,dt,skip_suspended,include_now,adjust_type,adjust_orig)
        # Used by RQAlpha for prior-close valuation only. Strategy SMAs consume
        # closed input bars directly, without loading future/bundle prices.
        if frequency != '1d':
            raise ValueError('HF策略仅使用已关闭的输入K线')
        cutoff = int(dt.strftime('%Y%m%d')) * 1000000
        rows = self.daily_array[self.daily_array['datetime'] <= cutoff][-bar_count:]
        return rows if fields is None else rows[fields]

    def available_data_range(self, frequency):
        return self.events[0][0].date(), self.events[-1][0].date()

    def get_open_auction_bar(self, instrument, dt):
        if instrument.order_book_id != self.code:
            return super().get_open_auction_bar(instrument, dt)
        daily = self.daily.get(dt.date())
        price = float(daily['open']) if daily is not None else np.nan
        return {'datetime':dt, 'open':price, 'last':price, 'volume':0.,
                'limit_up':np.nan,'limit_down':np.nan,'total_turnover':np.nan}


class PublishedEvents(AbstractEventSource):
    def __init__(self, source):
        self.source = source

    def events(self, start_date, end_date, frequency):
        day = None
        for dt, _ in self.source.events:
            if not start_date <= dt.date() <= end_date:
                continue
            if day != dt.date():
                if day is not None:
                    after = datetime.combine(day, datetime.min.time()).replace(hour=15,minute=30)
                    yield Event(EVENT.AFTER_TRADING, calendar_dt=after, trading_dt=after)
                day = dt.date()
                before = dt.replace(hour=8,minute=30)
                yield Event(EVENT.BEFORE_TRADING, calendar_dt=before,trading_dt=before)
                auction = dt.replace(hour=9,minute=27)
                yield Event(EVENT.OPEN_AUCTION,calendar_dt=auction,trading_dt=auction)
            yield Event(EVENT.BAR,calendar_dt=dt,trading_dt=dt)
        if day is not None:
            after = datetime.combine(day,datetime.min.time()).replace(hour=15,minute=30)
            yield Event(EVENT.AFTER_TRADING,calendar_dt=after,trading_dt=after)


class PublishedMod(AbstractMod):
    def start_up(self, env, mod_config):
        source = PublishedSource(env.config.base, PAYLOAD)
        env.set_data_source(source)
        # Run after sys_simulation so this event source is retained.
        env.set_event_source(PublishedEvents(source))

    def tear_down(self, code, exception=None):
        pass


def load_mod():
    return PublishedMod()
