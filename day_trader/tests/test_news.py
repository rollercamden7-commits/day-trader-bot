"""Tests for the news / catalyst strategy."""
import unittest
from datetime import datetime, time

import pandas as pd

from day_trader.risk import ET
from day_trader.strategies import news


def make_day(rows):
    idx = pd.date_range(datetime(2026, 10, 23, 9, 30, tzinfo=ET), periods=len(rows), freq="1min")
    return pd.DataFrame([{"open": o, "high": h, "low": l, "close": c, "volume": 1000}
                         for o, h, l, c in rows], index=idx)


# opens at 104 (prev close 100 -> +4% gap); first 5 min range 103-105; breaks out at 9:37
DAY = make_day([(104, 105, 103, 104.5)] * 5 + [(104.5, 104.9, 104.2, 104.6),
                                                (104.6, 105.6, 104.5, 105.4)] + [(105.4, 106, 105, 105.8)] * 5)
CTX = {"prev_close": 100.0, "news": ["Company beats earnings estimates"]}


class NewsTests(unittest.TestCase):
    def test_news_gap_breakout_signals(self):
        sigs = news.find_signals("X", DAY, CTX)
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].time.time(), time(9, 36))
        self.assertEqual(sigs[0].stop, 103)
        self.assertIn("earnings", sigs[0].reason)

    def test_no_news_no_signal(self):
        self.assertEqual(news.find_signals("X", DAY, {"prev_close": 100.0}), [])

    def test_no_news_variant_trades_anyway(self):
        p = dict(news.PARAMS, require_news=False)
        self.assertEqual(len(news.find_signals("X", DAY, {"prev_close": 100.0}, p)), 1)

    def test_small_gap_ignored(self):
        self.assertEqual(news.find_signals("X", DAY, dict(CTX, prev_close=102.0)), [])

    def test_late_breakout_ignored(self):
        late = make_day([(104, 105, 103, 104.5)] * 70 + [(105, 106, 105, 105.8)])
        self.assertEqual(news.find_signals("X", late, CTX), [])


if __name__ == "__main__":
    unittest.main()
