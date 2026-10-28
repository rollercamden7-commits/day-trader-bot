"""
Downloads price history from Alpaca.

Live trading uses the free IEX feed. Backtests use "SIP" history (all US
exchanges), which Alpaca gives free for anything older than 15 minutes - so
backtest volumes are realistic.

Downloads are cached in day_trader/data_cache/ (never uploaded).
"""
from __future__ import annotations

import os
import pickle
from datetime import date, datetime, time, timedelta
from typing import Dict, List

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from . import config as C
from .risk import ET

CACHE_DIR = C.PKG_DIR / "data_cache"
OPEN, CLOSE = time(9, 30), time(16, 0)


def client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(os.environ["DT_ALPACA_API_KEY"],
                                     os.environ["DT_ALPACA_SECRET_KEY"])


def _fetch(symbols, timeframe, start, end, feed) -> Dict[str, pd.DataFrame]:
    out = {}
    req = StockBarsRequest(symbol_or_symbols=list(symbols), timeframe=timeframe,
                           start=start, end=end, adjustment=Adjustment.SPLIT,
                           feed=DataFeed(feed))
    df = client().get_stock_bars(req).df
    if df.empty:
        return out
    for sym, part in df.groupby(level="symbol"):
        part = part.droplevel("symbol")
        part.index = part.index.tz_convert(ET)
        out[sym] = part[["open", "high", "low", "close", "volume"]].astype(float)
    return out


def minute_bars(symbols: List[str], start: date, end: date, feed: str = "sip",
                verbose: bool = True) -> Dict[str, pd.DataFrame]:
    """1-minute bars, regular hours only (9:30-4:00 ET), cached month by month."""
    CACHE_DIR.mkdir(exist_ok=True)
    result = {s: [] for s in symbols}
    month = date(start.year, start.month, 1)
    while month <= end:
        nxt = (month + timedelta(days=32)).replace(day=1)
        m_start, m_end = max(month, start), min(nxt - timedelta(days=1), end)
        # a month is only cached once it's complete
        cacheable = nxt <= date.today() - timedelta(days=1)
        todo = []
        for s in symbols:
            f = CACHE_DIR / f"{s}_{month:%Y-%m}_{feed}.pkl"
            if cacheable and f.exists():
                result[s].append(pickle.loads(f.read_bytes()))
            else:
                todo.append(s)
        for i in range(0, len(todo), 20):
            chunk = todo[i:i + 20]
            if verbose:
                print(f"  downloading {month:%Y-%m} minute bars for {len(chunk)} symbols...")
            got = _fetch(chunk, TimeFrame.Minute,
                         datetime.combine(m_start, time(0), ET),
                         datetime.combine(m_end, time(23, 59), ET), feed)
            for s in chunk:
                df = got.get(s, pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))
                t = df.index.time if len(df) else []
                df = df[(t >= OPEN) & (t < CLOSE)] if len(df) else df
                if cacheable:
                    (CACHE_DIR / f"{s}_{month:%Y-%m}_{feed}.pkl").write_bytes(pickle.dumps(df))
                result[s].append(df)
        month = nxt
    out = {}
    for s, parts in result.items():
        parts = [p for p in parts if len(p)]
        if parts:
            df = pd.concat(parts).sort_index()
            out[s] = df[(df.index.date >= start) & (df.index.date <= end)]
    return out


def daily_bars(symbols: List[str], start: date, end: date, feed: str = "sip"):
    out = {}
    for i in range(0, len(symbols), 50):
        got = _fetch(symbols[i:i + 50], TimeFrame.Day, datetime.combine(start, time(0), ET),
                     datetime.combine(end, time(23, 59), ET), feed)
        for s, df in got.items():
            df.index = pd.to_datetime(df.index.date)
            out[s] = df
    return out


# ------------------------------------------------ whole-market helpers
def all_tradable_symbols() -> List[str]:
    """Every active, tradable stock/ETF on the main US exchanges (no OTC)."""
    from alpaca.trading.client import TradingClient
    tc = TradingClient(os.environ["DT_ALPACA_API_KEY"], os.environ["DT_ALPACA_SECRET_KEY"], paper=True)
    # Raw request: the library's asset model rejects newer exchanges (e.g. TXSE).
    assets = tc.get("/assets", {"status": "active", "asset_class": "us_equity"})
    ok = {"NYSE", "NASDAQ", "ARCA", "AMEX", "BATS"}
    return sorted(a["symbol"] for a in assets
                  if a.get("tradable") and a.get("exchange") in ok and "/" not in a["symbol"])


def daily_bars_cached(symbols: List[str], start: date, end: date, name: str,
                      verbose: bool = True) -> Dict[str, pd.DataFrame]:
    """Daily bars for many symbols, cached as one file per (name, end date)."""
    CACHE_DIR.mkdir(exist_ok=True)
    f = CACHE_DIR / f"daily_{name}_{start}_{end}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    out = {}
    for i in range(0, len(symbols), 200):
        if verbose and i % 2000 == 0:
            print(f"  daily bars {i}/{len(symbols)}...")
        try:
            out.update(daily_bars(symbols[i:i + 200], start, end))
        except Exception as e:  # one bad symbol shouldn't kill the download
            print(f"  skipped a batch: {e}")
    f.write_bytes(pickle.dumps(out))
    return out


def minute_bars_for_days(day_symbols: Dict[date, List[str]], feed: str = "sip",
                         verbose: bool = True) -> Dict[str, Dict[date, pd.DataFrame]]:
    """1-minute bars only for the given symbols on the given days (cached per day)."""
    CACHE_DIR.mkdir(exist_ok=True)
    out: Dict[str, Dict[date, pd.DataFrame]] = {}
    for n, (d, syms) in enumerate(sorted(day_symbols.items())):
        f = CACHE_DIR / f"inplay_{d}_{feed}.pkl"
        have = pickle.loads(f.read_bytes()) if f.exists() else {}
        todo = [s for s in syms if s not in have]
        if todo:
            if verbose and n % 25 == 0:
                print(f"  minute bars for in-play stocks: day {n + 1}/{len(day_symbols)}")
            got = _fetch(todo, TimeFrame.Minute, datetime.combine(d, time(9, 30), ET),
                         datetime.combine(d, time(16, 0), ET), feed)
            for s in todo:
                df = got.get(s)
                if df is not None and len(df):
                    t = df.index.time
                    have[s] = df[(t >= OPEN) & (t < CLOSE)]
                else:
                    have[s] = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            if d < date.today():
                f.write_bytes(pickle.dumps(have))
        for s in syms:
            if s in have and len(have[s]):
                out.setdefault(s, {})[d] = have[s]
    return out


# ------------------------------------------------------------ live helpers
class LiveBars:
    """
    Keeps today's 1-minute bars for a list of symbols, fetching only new bars
    each minute (free IEX feed). Only COMPLETED minutes are kept.
    """

    def __init__(self, symbols: List[str], feed: str = None):
        self.symbols = sorted(set(symbols))
        self.feed = feed or C.DATA_FEED
        self.bars: Dict[str, pd.DataFrame] = {}
        self.last_bar_time = None

    def refresh(self, now: datetime) -> int:
        today_open = datetime.combine(now.date(), OPEN, ET)
        start = self.last_bar_time or today_open
        got = _fetch(self.symbols, TimeFrame.Minute, start, now, self.feed)
        cutoff = pd.Timestamp(now).floor("min")          # drop the minute still forming
        new = 0
        for s, df in got.items():
            df = df[(df.index >= today_open) & (df.index < cutoff)]
            if df.empty:
                continue
            old = self.bars.get(s)
            merged = df if old is None else pd.concat([old, df])
            self.bars[s] = merged[~merged.index.duplicated(keep="last")].sort_index()
            new += len(df)
        times = [df.index[-1] for df in self.bars.values() if len(df)]
        if times:
            self.last_bar_time = max(times).to_pydatetime()
        return new


def snapshots(symbols: List[str], feed: str = None) -> dict:
    from alpaca.data.requests import StockSnapshotRequest
    out = {}
    for i in range(0, len(symbols), 500):
        out.update(client().get_stock_snapshot(StockSnapshotRequest(
            symbol_or_symbols=symbols[i:i + 500], feed=DataFeed(feed or C.DATA_FEED))))
    return out


def news_history(start: date, end: date, verbose: bool = True) -> list:
    """All headlines between two dates as (time ET, [symbols], headline). Cached per month."""
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    nc = NewsClient(os.environ["DT_ALPACA_API_KEY"], os.environ["DT_ALPACA_SECRET_KEY"])
    CACHE_DIR.mkdir(exist_ok=True)
    out, month = [], date(start.year, start.month, 1)
    while month <= end:
        nxt = (month + timedelta(days=32)).replace(day=1)
        f = CACHE_DIR / f"news_{month:%Y-%m}.pkl"
        if f.exists():
            items = pickle.loads(f.read_bytes())
        else:
            if verbose:
                print(f"  downloading news {month:%Y-%m}...")
            res = nc.get_news(NewsRequest(start=datetime.combine(month, time(0), ET),
                                          end=datetime.combine(nxt, time(0), ET), limit=None,
                                          include_content=False, exclude_contentless=False))
            items = [(n.created_at.astimezone(ET), list(n.symbols or []), n.headline)
                     for n in res.data["news"]]
            if nxt <= date.today():
                f.write_bytes(pickle.dumps(items))
        out += [x for x in items if start <= x[0].date() <= end]
        month = nxt
    return out
