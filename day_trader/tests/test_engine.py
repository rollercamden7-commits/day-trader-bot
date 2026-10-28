"""
End-to-end test of the engine with a FAKE broker (no internet, no real orders):
signal -> risk check -> bracket order -> fill -> exit -> trade log.
"""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import pandas as pd

from day_trader import config as C
from day_trader import journal
from day_trader.engine import Engine
from day_trader.risk import ET, ConnectionHealth, DayState, RiskManager
from day_trader.strategies import momentum

NOW = datetime(2026, 10, 23, 9, 57, 10, tzinfo=ET)   # just after the 9:56 signal bar


def enum(v):
    return NS(value=v)


class FakeBroker:
    def __init__(self):
        self.orders, self.pos = {}, {}

    def bracket_buy(self, symbol, qty, stop, target, cid):
        oid = f"o{len(self.orders) + 1}"
        legs = [NS(status=enum("new"), order_type=enum("limit"), filled_avg_price=None, filled_at=None),
                NS(status=enum("new"), order_type=enum("stop"), filled_avg_price=None, filled_at=None)]
        o = NS(id=oid, symbol=symbol, status=enum("filled"), filled_qty=str(qty),
               filled_avg_price="100.50", filled_at=NOW, legs=legs)
        self.orders[oid] = o
        self.pos[symbol] = NS(symbol=symbol, qty=str(qty), avg_entry_price="100.50",
                              market_value=str(qty * 100.5), asset_class=enum("us_equity"))
        return o

    def wait_for_fill(self, oid, seconds=10):
        return self.orders[oid]

    def get_order(self, oid, nested=True):
        return self.orders[oid]

    def exit_fill(self, oid):
        for leg in self.orders[oid].legs:
            if leg.status.value == "filled":
                return float(leg.filled_avg_price), leg.filled_at, \
                    "target" if leg.order_type.value == "limit" else "stop-loss"
        return None

    def hit_target(self, oid, price):
        leg = self.orders[oid].legs[0]
        leg.status, leg.filled_avg_price, leg.filled_at = enum("filled"), str(price), NOW + timedelta(minutes=30)
        self.pos.pop(self.orders[oid].symbol, None)

    def account(self):
        return NS(equity="500000", last_equity="500000")

    def positions(self):
        return list(self.pos.values())

    def open_orders(self):
        return []

    def clock(self):
        return NS(is_open=True)

    def flatten_everything(self):
        self.pos.clear()
        return {}


def momentum_day():
    rows = [(100.2, 99.8, 100.0, 1000)] * 20 + \
           [(100.3 + i * 0.1 + 0.05, 100.3 + i * 0.1 - 0.6, 100.3 + i * 0.1, 5000) for i in range(5)]
    idx = pd.date_range(NOW.replace(hour=9, minute=35, second=0), periods=len(rows), freq="1min")
    return pd.DataFrame([{"open": c, "high": h, "low": l, "close": c, "volume": v}
                         for h, l, c, v in rows], index=idx)


class EngineFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.patches = [mock.patch.object(C, "STATE_DIR", d),
                        mock.patch.object(C, "DB_FILE", d / "t.db")]
        for p in self.patches:
            p.start()
        e = Engine.__new__(Engine)
        e.dry, e.mode, e.until, e.would = False, "paper", None, []
        e.broker, e.today, e.done = FakeBroker(), NOW.date(), set()
        e.state = DayState(day=NOW.date().isoformat())
        e.health = ConnectionHealth(clock=lambda: NOW)
        e.health.data_tick()
        e.rm = RiskManager(e.state, e.health)
        e.start_equity, e.session_close = 500_000.0, datetime(2026, 1, 1, 16).time()
        e.liquid = {"XYZ": {"adv": 5e6, "adv_dollar": 5e8, "prev_close": 95.0}}
        e.strats = {"momentum": (momentum, ["XYZ"])}
        e.bars = NS(bars={"XYZ": momentum_day()})
        self.e = e

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_signal_to_order_to_exit(self):
        e = self.e
        snap = e.snapshot(NOW)
        e.scan(snap, NOW)
        opened = journal.open_trades()
        self.assertEqual(len(opened), 1, "one trade should be open")
        t = opened[0]
        self.assertEqual((t["symbol"], t["strategy"], t["status"]), ("XYZ", "momentum", "experimental"))
        self.assertEqual(t["entry_price"], 100.5)                 # updated to the real fill
        self.assertLess(t["stop"], t["entry_price"])
        self.assertGreater(t["target"], t["entry_price"])
        self.assertEqual(e.state.trades_opened, 1)

        e.scan(e.snapshot(NOW), NOW)                              # same signal never traded twice
        self.assertEqual(len(journal.open_trades()), 1)

        e.broker.hit_target("o1", 102.0)
        e.snapshot(NOW)
        e.reconcile()
        self.assertEqual(journal.open_trades(), [])
        done = journal.trades_df()
        self.assertEqual(done.iloc[0].exit_reason, "target")
        self.assertAlmostEqual(done.iloc[0].pnl, (102.0 - 100.5) * done.iloc[0].qty)

    def test_stale_signal_not_traded(self):
        e = self.e
        late = NOW + timedelta(minutes=30)
        e.health.clock = lambda: late
        e.health.data_tick()
        e.scan(e.snapshot(late), late)
        self.assertEqual(journal.open_trades(), [])
        self.assertEqual(journal.signals_today(NOW.date())[0]["action"], "missed")

    def test_watch_only_places_no_orders(self):
        e = self.e
        e.dry, e.mode = True, "watch"
        e.scan(e.snapshot(NOW), NOW)
        self.assertEqual(e.broker.orders, {})
        self.assertEqual(len(e.would), 1)
        self.assertEqual(journal.signals_today(NOW.date())[0]["action"], "would trade")


if __name__ == "__main__":
    unittest.main()
