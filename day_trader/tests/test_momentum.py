"""Tests for the momentum strategy and the in-play picker."""
import unittest
from datetime import date, datetime, time

import pandas as pd

from day_trader.risk import ET
from day_trader.strategies import momentum
from day_trader.universe import in_play


def make_day(rows):
    """rows: list of (high, low, close, volume) per minute from 9:30."""
    idx = pd.date_range(datetime(2026, 10, 23, 9, 30, tzinfo=ET), periods=len(rows), freq="1min")
    return pd.DataFrame([{"open": c, "high": h, "low": l, "close": c, "volume": v}
                         for h, l, c, v in rows], index=idx)


QUIET = [(100.2, 99.8, 100.0, 1000)] * 20          # 9:30-9:49, high of day 100.2


def surge(n=5, start=100.3, step=0.1):
    # rising prices on 5x volume; lows tight so the 10-min low is ~0.5-1% away
    return [(start + i * step + 0.05, start + i * step - 0.6, start + i * step, 5000) for i in range(n)]


class MomentumTests(unittest.TestCase):
    def test_new_high_on_volume_surge_signals(self):
        sigs = momentum.find_signals("X", make_day(QUIET + surge()), {})
        self.assertEqual(len(sigs), 1)
        self.assertGreaterEqual(sigs[0].time.time(), time(9, 50))
        self.assertLess(sigs[0].stop, 100.3)

    def test_new_high_without_volume_does_not_signal(self):
        quiet_rise = [(h, l, c, 1000) for h, l, c, _ in surge()]
        self.assertEqual(momentum.find_signals("X", make_day(QUIET + quiet_rise), {}), [])

    def test_too_early_ignored(self):
        early = surge(5) + [(100.0, 99.5, 99.8, 1000)] * 20
        self.assertEqual(momentum.find_signals("X", make_day(early), {}), [])

    def test_stop_too_far_skipped(self):
        wide = [(101, 95, 100.5, 5000)] * 5        # 10-minute low ~5% away
        self.assertEqual(momentum.find_signals("X", make_day(QUIET + wide), {}), [])


class InPlayTests(unittest.TestCase):
    def daily(self, opens, closes, vol=5_000_000):
        idx = pd.to_datetime([date(2026, 10, d) for d in range(1, len(opens) + 1)])
        return pd.DataFrame({"open": opens, "close": closes, "high": closes, "low": closes,
                             "volume": vol}, index=idx)

    def test_picks_gap_ups_biggest_first(self):
        base = [50.0] * 14
        data = {
            "UP5": self.daily(base + [52.5], base + [53]),     # +5% gap
            "UP3": self.daily(base + [51.5], base + [51]),     # +3% gap
            "FLAT": self.daily(base + [50.2], base + [50]),
            "THIN": self.daily(base + [55], base + [55], vol=10_000),
            "CHEAP": self.daily([4.0] * 14 + [4.4], [4.0] * 14 + [4.4]),
        }
        self.assertEqual(in_play(data, date(2026, 10, 15)), ["UP5", "UP3"])


if __name__ == "__main__":
    unittest.main()
