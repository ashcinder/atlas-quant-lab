"""Persistent OHLCV snapshots, isolated by provider, symbol, interval and query.

The cache key includes adjustment and requested boundaries. Never splice two
providers or assume a differently requested range has complete coverage.
"""
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pandas as pd


class CandleStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS snapshots (key TEXT PRIMARY KEY, fetched_at REAL NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS candles (
                key TEXT NOT NULL, time TEXT NOT NULL,
                open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
                close REAL NOT NULL, volume REAL NOT NULL,
                PRIMARY KEY(key,time))""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def timestamp(self, key: str) -> datetime | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT fetched_at FROM snapshots WHERE key=?", (key,)).fetchone()
        return datetime.fromtimestamp(row[0], UTC) if row else None

    def read(self, key: str) -> pd.DataFrame | None:
        with closing(self.connect()) as db:
            rows = db.execute("SELECT time,open,high,low,close,volume FROM candles WHERE key=? ORDER BY time", (key,)).fetchall()
        if not rows:
            return None
        frame = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        frame["time"] = pd.to_datetime(frame["time"], utc=True)
        return frame.set_index("time")

    def write(self, key: str, frame: pd.DataFrame, fetched_at: datetime | None = None):
        columns = ["open", "high", "low", "close", "volume"]
        rows = [(key, pd.Timestamp(t).isoformat(), *(float(v) for v in values))
                for t, values in zip(frame.index, frame[columns].itertuples(index=False, name=None))]
        # Replacement is atomic: an interrupted refresh retains the old snapshot.
        with closing(self.connect()) as db, db:
            db.execute("DELETE FROM candles WHERE key=?", (key,))
            db.executemany("INSERT INTO candles VALUES(?,?,?,?,?,?,?)", rows)
            db.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?)", (key, (fetched_at or datetime.now(UTC)).timestamp()))

    def full_history(self, provider: str, symbol: str, interval: str) -> pd.DataFrame:
        """Union cached queries for one instrument/feed/interval; newest wins.

        Used only for raw crypto proof snapshots. Never mixes feeds or periods.
        """
        prefix = f"{provider}_{symbol.replace('/', '_').replace('=', '-')}_{interval}_"
        with closing(self.connect()) as db:
            rows = db.execute("""SELECT c.time,c.open,c.high,c.low,c.close,c.volume
                FROM candles c JOIN snapshots s ON s.key=c.key
                WHERE substr(c.key,1,?)=? ORDER BY s.fetched_at,c.key,c.time""",
                (len(prefix),prefix)).fetchall()
        frame=pd.DataFrame(rows,columns=['time','open','high','low','close','volume'])
        frame['time']=pd.to_datetime(frame['time'],utc=True)
        return frame.drop_duplicates('time',keep='last').set_index('time').sort_index()
