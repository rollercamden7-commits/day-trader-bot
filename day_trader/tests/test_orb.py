"""Tests for the opening range breakout strategy and the backtest's exit rules."""
import unittest
from datetime import datetime, time

import pandas as pd

from day_trader.backtest import SLIPPAGE, simulate_exit
from day_trader.risk import ET
from day_trader.strategies import orb


def make_day(prices, volume=1000):
    """prices: list of (high, low, close) per minute starting 9:30."""
    idx = pd.date_range(datetime(2026, 10, 23, 9, 30, tzinfo=ET), periods=len(prices), freq="1min")
    rows = [{"open": c, "high": h, "low": l, "close": c, "volume": volume} for h, l, c in prices]
    return pd.DataFrame(rows, index=idx)


RANGE = [(101, 99, 100)] * 15          # 9:30-9:44: range 99-101


class OrbTests(unittest.TestCase):
    ctx = {"avg_open_volume": 5000}     # today 15 x 1000 = 15000 -> 3x normal

    def test_breakout_signals_once(self):
        day = make_day(RANGE + [(101, 100, 100.5)] * 5 + [(102, 101, 101.5)] + [(103, 102, 102.5)] * 5)
        sigs = orb.find_signals("X", day, self.ctx)
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].time.time(), time(9, 50))
        self.assertEqual(sigs[0].stop, 99)

    def test_no_breakout_no_signal(self):
        day = make_day(RANGE + [(101, 100, 100.5)] * 30)
        self.assertEqual(orb.find_signals("X", day, self.ctx), [])

    def test_breakout_during_range_ignored(self):
        day = make_day([(101, 99, 100)] * 10 + [(103, 100, 102.9)] * 5 + [(102, 101, 101.5)] * 10)
        sigs = orb.find_signals("X", day, self.ctx)
        # range now 99-103; closes at 101.5 never break it
        self.assertEqual(sigs, [])

    def test_not_in_play_no_signal(self):
        day = make_day(RANGE + [(103, 102, 102.5)] * 5)
        self.assertEqual(orb.find_signals("X", day, {"avg_open_volume": 50_000}), [])

    def test_no_entries_after_1130(self):
        day = make_day(RANGE + [(101, 100, 100.5)] * 125 + [(103, 102, 102.5)] * 5)
        self.assertEqual(orb.find_signals("X", day, self.ctx), [])

    def test_target_is_2x_risk(self):
        day = make_day(RANGE + [(102, 101, 101.5)])
        sig = orb.find_signals("X", day, self.ctx)[0]
        self.assertAlmostEqual(sig.target_for(101), 101 + 2 * 2)


class ExitSimTests(unittest.TestCase):
    def sig(self, day):
        return orb.find_signals("X", day, {"avg_open_volume": 5000})[0]

    def test_stop_hit_first_when_both_touched(self):
        day = make_day(RANGE + [(102, 101, 101.5), (101.5, 101, 101.2), (110, 90, 100)])
        e = simulate_exit(day, self.sig(day), time(15, 55))
        self.assertEqual(e[5], "stop-loss")

    def test_target(self):
        day = make_day(RANGE + [(102, 101, 101.5), (101.5, 101, 101.2), (106, 101, 105)])
        e = simulate_exit(day, self.sig(day), time(15, 55))
        self.assertEqual(e[5], "target")
        self.assertGreater(e[4], e[0])

    def test_entry_pays_slippage(self):
        day = make_day(RANGE + [(102, 101, 101.5), (101.5, 101, 101.2), (101.5, 101, 101.2)])
        e = simulate_exit(day, self.sig(day), time(15, 55))
        self.assertAlmostEqual(e[0], 101.2 * (1 + SLIPPAGE))

    def test_end_of_day_exit(self):
        day = make_day(RANGE + [(102, 101, 101.5)] + [(101.5, 101, 101.2)] * 400)
        e = simulate_exit(day, self.sig(day), time(15, 55))
        self.assertEqual(e[5], "end of day")
        self.assertEqual(e[3].time(), time(15, 55))


if __name__ == "__main__":
    unittest.main()
