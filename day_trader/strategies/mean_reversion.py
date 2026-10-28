"""
Strategy: MEAN REVERSION (intraday)

Plain English: when a stock drops sharply and quickly, it often bounces part
of the way back toward its average price for the day. Buy once the drop
stops, aim for the average.

Rules (each 1-minute bar, between 10:00am and 3:00pm):
  1. "Sharp drop": the price fell at least 2% from its high of the last
     30 minutes, AND it's at least 1.5% below VWAP (the day's average price
     everyone paid).
  2. "Drop has stopped": this bar closes above the previous bar's high.
     (Don't catch a falling knife.)
  3. Stop-loss: 0.1% under the lowest price of the last 30 minutes.
     Skip if that's under 0.3% away (noise) or over 3% away.
  4. Target: VWAP - the "mean" it reverts to. Skip if VWAP is less than
     1x the risk away (not worth it).
  5. Anything left is closed at 3:55pm. One trade per stock per day.
"""
from __future__ import annotations

from datetime import time
from typing import List

import numpy as np
import pandas as pd

from .base import Signal

NAME = "mean_reversion"

PARAMS = {
    "first_entry": time(10, 0),
    "last_entry": time(15, 0),
    "lookback": 30,
    "min_drop": 0.02,          # fall from the 30-minute high
    "min_below_vwap": 0.015,
    "confirm_turn": True,      # wait for a bar to close above the prior bar's high
    "target": "vwap",          # "vwap", or "r" = reward_risk x the risk
    "reward_risk": 1.0,
    "min_reward_risk": 1.0,    # VWAP target must be at least this many R away
    "min_stop_pct": 0.003,
    "max_stop_pct": 0.03,
    "spy_filter": None,        # e.g. -0.01: skip if SPY is down more than 1% today
}


def find_signals(symbol: str, day: pd.DataFrame, ctx: dict, p=PARAMS) -> List[Signal]:
    n = p["lookback"]
    if len(day) < n + 2:
        return []
    h, l, c, v = day["high"], day["low"], day["close"], day["volume"]
    typical = (h + l + c) / 3
    vwap = (typical * v).cumsum() / v.cumsum().replace(0, np.nan)
    recent_high = h.rolling(n).max()
    recent_low = l.rolling(n).min()
    drop = 1 - c / recent_high
    below = 1 - c / vwap
    t = np.array(day.index.time)
    ok = (t >= p["first_entry"]) & (t < p["last_entry"])
    ok &= (drop.shift(1) >= p["min_drop"]).to_numpy() & (below.shift(1) >= p["min_below_vwap"]).to_numpy()
    if p["confirm_turn"]:
        ok &= (c > h.shift(1)).to_numpy()
    else:
        ok &= (drop >= p["min_drop"]).to_numpy() & (below >= p["min_below_vwap"]).to_numpy()

    spy_day = ctx.get("market_day")
    for i in np.flatnonzero(ok):
        if p["spy_filter"] is not None and spy_day is not None and len(spy_day):
            spy_now = spy_day[spy_day.index <= day.index[i]]
            if len(spy_now) and spy_now.close.iloc[-1] / spy_day.open.iloc[0] - 1 < p["spy_filter"]:
                continue
        price = float(c.iloc[i])
        stop = float(recent_low.iloc[i]) * 0.999
        risk = price - stop
        if not (p["min_stop_pct"] <= risk / price <= p["max_stop_pct"]):
            continue
        tgt = float(vwap.iloc[i]) if p["target"] == "vwap" else price + p["reward_risk"] * risk
        if (tgt - price) < p["min_reward_risk"] * risk:
            continue
        return [Signal(symbol, NAME, day.index[i].to_pydatetime(), "buy", stop, p["reward_risk"],
                       reason=f"fell {float(drop.iloc[i - 1]):.1%} in {n} min to "
                              f"{float(below.iloc[i - 1]):.1%} below VWAP, then turned up; "
                              f"target VWAP {float(vwap.iloc[i]):.2f}",
                       target_price=tgt if p["target"] == "vwap" else None)]
    return []
