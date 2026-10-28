"""
Strategy: MOMENTUM

Plain English: buy a stock that is pushing to a new high for the day on a
burst of unusually heavy trading, while it's above its average price for the
day - i.e. it's moving fast and buyers are in control.

Rules (each 1-minute bar, between 9:45am and 2:00pm):
  1. The bar closes above the highest price of the day so far (new "high of day").
  2. The last 5 minutes traded at least 2x the stock's normal 5-minute volume
     so far today ("volume surge").
  3. Price is above VWAP (the volume-weighted average price for the day -
     the average price everyone has paid today).
  4. Stop-loss: the lowest price of the last 10 minutes. Skip if that's less
     than 0.5% away (too tight - noise would hit it) or more than 3% (too far).
  5. Target: 2x the risk. Anything left is closed at 3:55pm.
One trade per stock per day.
"""
from __future__ import annotations

from datetime import time
from typing import List

import numpy as np
import pandas as pd

from .base import Signal

NAME = "momentum"

PARAMS = {
    "first_entry": time(9, 45),
    "last_entry": time(14, 0),
    "vol_mult": 2.0,
    "reward_risk": 2.0,
    "stop_lookback": 10,
    "min_stop_pct": 0.005,
    "max_stop_pct": 0.03,
    "require_vwap": True,
    "stop_mode": "swing",     # "swing" = low of last 10 min, "vwap" = just under VWAP
}


def find_signals(symbol: str, day: pd.DataFrame, ctx: dict, p=PARAMS) -> List[Signal]:
    if len(day) < 20:
        return []
    h, l, c, v = day["high"], day["low"], day["close"], day["volume"]
    prior_high = h.cummax().shift(1)
    typical = (h + l + c) / 3
    vwap = (typical * v).cumsum() / v.cumsum().replace(0, np.nan)
    per_min_before = v.expanding().mean().shift(5)          # normal volume, before the last 5 min
    surge = v.rolling(5).sum() >= p["vol_mult"] * 5 * per_min_before
    t = np.array(day.index.time)
    ok = (t >= p["first_entry"]) & (t < p["last_entry"]) & (c > prior_high).to_numpy() & surge.to_numpy()
    if p["require_vwap"]:
        ok &= (c > vwap).to_numpy()
    lows = l.rolling(p["stop_lookback"]).min()
    for i in np.flatnonzero(ok):
        price = float(c.iloc[i])
        stop = float(lows.iloc[i]) if p["stop_mode"] == "swing" else float(vwap.iloc[i]) * 0.999
        dist = (price - stop) / price
        if p["min_stop_pct"] <= dist <= p["max_stop_pct"]:
            return [Signal(symbol, NAME, day.index[i].to_pydatetime(), "buy", stop,
                           p["reward_risk"],
                           reason=f"new high of day {price:.2f} on a volume surge, above "
                                  f"VWAP {float(vwap.iloc[i]):.2f}")]
    return []
