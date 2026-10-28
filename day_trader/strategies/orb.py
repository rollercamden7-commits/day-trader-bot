"""
Strategy: OPENING RANGE BREAKOUT (ORB)

Plain English:
  1. Watch the first 15 minutes (9:30-9:45). Note the highest and lowest price.
     That's the "opening range".
  2. Only bother if the stock is "in play": its first-15-minute volume is at
     least 1.5x its normal first-15-minute volume.
  3. After 9:45 (and before 11:30), if a 1-minute bar CLOSES above the range
     high, buy.
  4. Stop-loss: the bottom of the range. Target: 2x the risk above the entry.
  5. Anything still open is closed by the end-of-day rule (3:55pm).

Long only, because shorting is off. (Downside breakouts could later be traded
by buying puts.)
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import List, Optional

import pandas as pd

from .base import Signal

NAME = "opening_range_breakout"

PARAMS = {
    "range_minutes": 15,
    "last_entry": time(11, 30),
    "min_rel_volume": 1.5,     # opening volume vs its 20-day normal
    "reward_risk": 2.0,
    "min_range_pct": 0.003,    # skip ranges narrower than 0.3% (noise)
    "max_range_pct": 0.03,     # ...or wider than 3% (stop too far)
    "stop": "low",             # "low" = range low, "mid" = range middle
    "spy_confirm": False,      # also require SPY to be above ITS opening range high
}


def range_end(p=PARAMS) -> time:
    return (datetime.combine(datetime.today(), time(9, 30))
            + timedelta(minutes=p["range_minutes"])).time()


def opening_volume(day: pd.DataFrame, p=PARAMS) -> Optional[float]:
    """Volume traded in the opening range (used to judge 'in play')."""
    rng = day[day.index.time < range_end(p)]
    return float(rng["volume"].sum()) if len(rng) >= p["range_minutes"] * 0.8 else None


def find_signals(symbol: str, day: pd.DataFrame, ctx: dict, p=PARAMS) -> List[Signal]:
    """
    day: today's 1-minute bars so far. ctx: {"avg_open_volume": ...}.
    Returns at most one signal (the first breakout).
    """
    end = range_end(p)
    t = day.index.time
    rng = day[t < end]
    if len(rng) < p["range_minutes"] * 0.8 or not ctx.get("avg_open_volume"):
        return []
    hi, lo = float(rng["high"].max()), float(rng["low"].min())
    rel_vol = float(rng["volume"].sum()) / ctx["avg_open_volume"]
    width = (hi - lo) / hi
    if rel_vol < p["min_rel_volume"] or not (p["min_range_pct"] <= width <= p["max_range_pct"]):
        return []
    after = day[(t >= end) & (t < p["last_entry"])]
    brk = after[after["close"] > hi]
    if p.get("spy_confirm"):
        spy = ctx.get("market_day")
        if spy is None or spy.empty:
            return []
        s_rng = spy[spy.index.time < end]
        if s_rng.empty:
            return []
        spy_up = spy["close"] > float(s_rng["high"].max())
        brk = brk[spy_up.reindex(brk.index, fill_value=False).to_numpy()]
    if brk.empty:
        return []
    stop = lo if p["stop"] == "low" else (hi + lo) / 2
    return [Signal(symbol, NAME, brk.index[0].to_pydatetime(), "buy", stop, p["reward_risk"],
                   reason=f"broke above opening range high {hi:.2f} on {rel_vol:.1f}x "
                          f"normal opening volume; range {lo:.2f}-{hi:.2f}")]
