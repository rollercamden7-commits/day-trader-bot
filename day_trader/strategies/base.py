"""
What every strategy hands back: a Signal = "buy this, here's my stop".

The profit target is set from the actual entry price:
    target = entry + reward_risk x (entry - stop)
so it's always fixed BEFORE the order is sent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Signal:
    symbol: str
    strategy: str
    time: datetime        # the bar that triggered it
    side: str             # "buy"
    stop: float
    reward_risk: float    # target distance as a multiple of the stop distance
    reason: str = ""
    target_price: Optional[float] = None   # fixed target (e.g. VWAP) instead of a multiple

    def target_for(self, entry: float) -> float:
        if self.target_price is not None:
            return self.target_price
        return entry + self.reward_risk * (entry - self.stop)
