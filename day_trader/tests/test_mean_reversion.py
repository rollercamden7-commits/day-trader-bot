"""Tests for the mean reversion strategy."""
import unittest
from datetime import datetime, time

import pandas as pd

from day_trader.risk import ET
from day_trader.strategies import mean_reversion as mr


def make_day(rows):
    """rows: list of (high, low, close, volume) per minute from 9:30."""
    idx = pd.date_range(datetime(2026, 10, 23, 9, 30, tzinfo=ET), periods=len(rows), freq="1min")
    return pd.DataFrame([{"open": c, "high": h, "low": l, "close": c, "volume": v}
                         for h, l, c, v in rows], index=idx)


FLAT = [(100.1, 99.9, 100.0, 10_000)] * 40                       # 9:30-10:09 around $100
# slide from 100 to ~97 over 15 minutes on light volume (VWAP stays near 100)
SLIDE = [(100 - i * 0.2 + 0.05, 100 - i * 0.2 - 0.1, 100 - i * 0.2, 1000) for i in range(16)]
TURN = [(97.6, 97.1, 97.5, 1000)]                                 # closes above prior bar's high


class MeanReversionTests(unittest.TestCase):
    def test_sharp_drop_then_turn_signals(self):
        sigs = mr.find_signals("X", make_day(FLAT + SLIDE + TURN), {})
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s.time.time(), time(10, 26))
        self.assertLess(s.stop, 97.0)
        self.assertGreater(s.target_for(97.5), 99)     # target ~ VWAP near $100

    def test_no_turn_no_signal(self):
        self.assertEqual(mr.find_signals("X", make_day(FLAT + SLIDE), {}), [])

    def test_small_drop_ignored(self):
        small = [(100 - i * 0.05 + 0.05, 100 - i * 0.05 - 0.1, 100 - i * 0.05, 1000) for i in range(16)]
        self.assertEqual(mr.find_signals("X", make_day(FLAT + small + [(99.5, 99.2, 99.4, 1000)]), {}), [])

    def test_before_10am_ignored(self):
        early = [(100.1, 99.9, 100.0, 10_000)] * 10 + SLIDE + TURN   # turn at 9:56
        self.assertEqual(mr.find_signals("X", make_day(early), {}), [])

    def test_spy_filter_blocks_on_market_selloff(self):
        day = make_day(FLAT + SLIDE + TURN)
        spy = make_day([(500, 490, 492, 1)] * len(day))
        spy.iloc[0, spy.columns.get_loc("open")] = 500             # SPY -1.6% on the day
        p = dict(mr.PARAMS, spy_filter=-0.01)
        self.assertEqual(mr.find_signals("X", day, {"market_day": spy}, p), [])


if __name__ == "__main__":
    unittest.main()
