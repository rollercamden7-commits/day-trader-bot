"""
Morning watchlist (rules-based - no AI).

    python -m day_trader.watchlist      print today's pre-market report

8:30am  prepare():  every liquid stock (price >= $5, avg volume >= 1M shares,
                    >= $20M traded/day), the market mood before the open, top
                    movers, and overnight news headlines.
9:31am  in_play():  the day's top-20 gap-ups among the liquid stocks - the
                    exact rule the backtests used.
"""
from __future__ import annotations

import json
import pickle
from datetime import date, datetime, timedelta

import pandas as pd

from . import config as C
from .data import CACHE_DIR, all_tradable_symbols, daily_bars, snapshots
from .risk import ET
from .universe import UNIVERSE

WATCH_FILE = C.STATE_DIR / "watchlist.json"


def liquid_universe(today: date, verbose=True) -> dict:
    """{symbol: {adv, adv_dollar, prev_close}} for every liquid stock. Cached per day."""
    CACHE_DIR.mkdir(exist_ok=True)
    f = CACHE_DIR / f"liquid_{today}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    syms = all_tradable_symbols()
    if verbose:
        print(f"Checking liquidity of {len(syms)} symbols (a few minutes)...")
    start = today - timedelta(days=45)
    out = {}
    for i in range(0, len(syms), 200):
        try:
            bars = daily_bars(syms[i:i + 200], start, today - timedelta(days=1))
        except Exception as e:
            print(f"  skipped a batch: {e}")
            continue
        for s, df in bars.items():
            df = df.tail(20)
            if len(df) < 10:
                continue
            adv, close = float(df.volume.mean()), float(df.close.iloc[-1])
            adv_d = float((df.volume * df.close).mean())
            if close >= C.MIN_PRICE and adv >= C.MIN_AVG_DAILY_VOLUME and adv_d >= C.MIN_AVG_DOLLAR_VOLUME:
                out[s] = {"adv": adv, "adv_dollar": adv_d, "prev_close": close}
    f.write_bytes(pickle.dumps(out))
    return out


def market_mood(snaps: dict) -> dict:
    """How SPY/QQQ/IWM are trading before the open vs yesterday's close."""
    mood = {}
    for s in ("SPY", "QQQ", "IWM"):
        snap = snaps.get(s)
        if not (snap and snap.latest_trade and snap.daily_bar):
            continue
        # Before today's open, the newest daily bar is YESTERDAY's - compare to its close.
        today = datetime.now(ET).date()
        ref = snap.daily_bar if snap.daily_bar.timestamp.astimezone(ET).date() < today \
            else snap.previous_daily_bar
        if ref is not None:
            mood[s] = snap.latest_trade.price / ref.close - 1
    spy = mood.get("SPY", 0)
    if spy <= -0.01:
        label = "market set to open sharply DOWN"
    elif spy >= 0.01:
        label = "market set to open sharply UP"
    else:
        label = "market set to open roughly flat"
    return {"moves": mood, "label": label}


def headlines(symbols, hours=16, limit=50) -> list:
    """Recent news headlines (Benzinga via Alpaca's free news feed)."""
    try:
        import os
        from alpaca.data.historical.news import NewsClient
        from alpaca.data.requests import NewsRequest
        nc = NewsClient(os.environ["DT_ALPACA_API_KEY"], os.environ["DT_ALPACA_SECRET_KEY"])
        start = datetime.now(ET) - timedelta(hours=hours)
        res = nc.get_news(NewsRequest(start=start, limit=limit, sort="desc", include_content=False))
        items = res.data.get("news", []) if hasattr(res, "data") else res.news
        wanted = set(symbols)
        out = []
        for n in items:
            syms = [s for s in (n.symbols or []) if s in wanted]
            if syms:
                out.append({"time": n.created_at.astimezone(ET).strftime("%H:%M"),
                            "symbols": syms, "headline": n.headline})
        return out
    except Exception as e:
        return [{"time": "", "symbols": [], "headline": f"(news feed unavailable: {e})"}]


def prepare(today: date = None, verbose=True) -> dict:
    today = today or datetime.now(ET).date()
    liquid = liquid_universe(today, verbose)
    snaps = snapshots(["SPY", "QQQ", "IWM"])
    mood = market_mood(snaps)
    news = headlines(liquid)
    enabled = [k for k, on in C.STRATEGIES_ENABLED.items() if on]
    report = {"day": today.isoformat(), "liquid_count": len(liquid), "mood": mood,
              "news": news, "strategies_today": enabled, "in_play": []}
    C.STATE_DIR.mkdir(parents=True, exist_ok=True)
    WATCH_FILE.write_text(json.dumps(report, indent=2, default=str))
    return report


def in_play(liquid: dict, top_n=20, min_gap=0.02) -> list:
    """Top gap-ups at the open. Call just after 9:30."""
    snaps = snapshots(sorted(liquid))
    rows = []
    for s, snap in snaps.items():
        bar = getattr(snap, "daily_bar", None)
        if bar is None or bar.timestamp.astimezone(ET).date() != datetime.now(ET).date():
            continue
        if bar.open < C.MIN_PRICE:
            continue
        gap = bar.open / liquid[s]["prev_close"] - 1
        if gap >= min_gap:
            rows.append((gap, s))
    picks = [s for _, s in sorted(rows, reverse=True)[:top_n]]
    if WATCH_FILE.exists():
        rep = json.loads(WATCH_FILE.read_text())
        rep["in_play"] = [{"symbol": s, "gap": round(g, 4)} for g, s in sorted(rows, reverse=True)[:top_n]]
        WATCH_FILE.write_text(json.dumps(rep, indent=2, default=str))
    return picks


def describe(rep: dict) -> str:
    lines = [f"PRE-MARKET REPORT {rep['day']}",
             f"Market mood: {rep['mood']['label']} "
             + " ".join(f"{k} {v:+.2%}" for k, v in rep["mood"]["moves"].items()),
             f"Liquid stocks to scan: {rep['liquid_count']}",
             f"Strategies on today: {', '.join(rep['strategies_today'])}"]
    if rep.get("in_play"):
        lines.append("In play at the open: " + ", ".join(f"{x['symbol']} {x['gap']:+.1%}"
                                                         for x in rep["in_play"]))
    if rep["news"]:
        lines.append("Overnight headlines:")
        lines += [f"  {n['time']} {','.join(n['symbols'])}: {n['headline']}" for n in rep["news"][:15]]
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe(prepare()))
