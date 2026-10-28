"""
Strategy: NEWS / CATALYST ("gap and go" on news)

Plain English: a stock that had news overnight (earnings, an announcement,
an upgrade...) and opens well above yesterday's close often keeps running in
the first hour. Buy when it breaks above its first-5-minute high.

Rules:
  1. Candidate: news headline between yesterday 4pm and 9:25am today, AND it
     opened at least 3% above yesterday's close.
  2. After 9:35 (and before 10:30): a 1-minute bar closes above the high of
     the first 5 minutes -> buy.
  3. Stop-loss: the low of the first 5 minutes (skip if under 0.5% or over 5% away).
  4. Target: 2x the risk. Anything left is closed at 3:55pm.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import List

import numpy as np
import pandas as pd

from .base import Signal

NAME = "news"

PARAMS = {
    "require_news": True,
    "min_gap": 0.03,
    "range_minutes": 5,
    "last_entry": time(10, 30),
    "reward_risk": 2.0,
    "min_stop_pct": 0.005,
    "max_stop_pct": 0.05,
}


def find_signals(symbol: str, day: pd.DataFrame, ctx: dict, p=PARAMS) -> List[Signal]:
    if p["require_news"] and not ctx.get("news"):
        return []
    prev = ctx.get("prev_close")
    if not prev or day.empty:
        return []
    gap = float(day.open.iloc[0]) / prev - 1
    if gap < p["min_gap"]:
        return []
    end = (datetime(2000, 1, 1, 9, 30) + timedelta(minutes=p["range_minutes"])).time()
    t = np.array(day.index.time)
    rng = day[t < end]
    if len(rng) < max(2, p["range_minutes"] - 1):
        return []
    hi, lo = float(rng.high.max()), float(rng.low.min())
    after = day[(t >= end) & (t < p["last_entry"])]
    brk = after[after.close > hi]
    if brk.empty:
        return []
    price = float(brk.close.iloc[0])
    if not (p["min_stop_pct"] <= (price - lo) / price <= p["max_stop_pct"]):
        return []
    head = (ctx.get("news") or ["(no news)"])[0]
    return [Signal(symbol, NAME, brk.index[0].to_pydatetime(), "buy", lo, p["reward_risk"],
                   reason=f"gapped {gap:+.1%} on news ('{head[:70]}'), broke first-"
                          f"{p['range_minutes']}-min high {hi:.2f}")]
