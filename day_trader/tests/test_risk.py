"""
Tests for the risk manager.   Run:  python -m unittest discover -s day_trader/tests -t .
Each test is one rule from your spec, checked with made-up numbers.
"""
import tempfile
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest import mock

from day_trader import config as C
from day_trader.risk import (ET, ConnectionHealth, DayState, Holding, RiskManager, Snapshot,
                             TradeIdea)

DAY = datetime(2026, 10, 23, tzinfo=ET)


def at(h, m):
    return DAY.replace(hour=h, minute=m)


def stock(**kw):
    base = dict(symbol="AAPL", asset_class="stock", side="buy", strategy="momentum",
                entry=100.0, stop=98.0, target=104.0, price=100.0,
                avg_daily_volume=50_000_000, avg_dollar_volume=5e9)
    base.update(kw)
    return TradeIdea(**base)


def option(**kw):
    base = dict(symbol="SPY261023C00580000", asset_class="option", side="buy",
                strategy="momentum", entry=2.00, stop=1.40, target=3.00,
                open_interest=5000, bid=1.98, ask=2.02, expires_today=True)
    base.update(kw)
    return TradeIdea(**base)


def snap(now=None, equity=500_000, start=500_000, holdings=(), **kw):
    return Snapshot(now=now or at(10, 30), equity=equity, start_equity=start,
                    holdings=list(holdings), **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(C, "STATE_DIR", Path(self.tmp.name))
        self.patch.start()
        self.state = DayState(day="2026-10-23")
        self.rm = RiskManager(self.state)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def assertRejected(self, decision, words):
        self.assertFalse(decision.approved, str(decision))
        self.assertIn(words, " ".join(decision.reasons))


class SizingTests(Base):
    def test_risk_per_trade_is_half_percent(self):
        d = self.rm.check(stock(entry=100, stop=98), snap())
        # $2,500 risk / $2 per share = 1,250 shares ($125k) -> capped at 10% = $50k = 500 shares
        self.assertTrue(d.approved)
        self.assertEqual(d.qty, 500)
        self.assertIn("max position size", " ".join(d.reasons))

    def test_wide_stop_means_fewer_shares(self):
        d = self.rm.check(stock(entry=100, stop=90, target=120), snap())
        self.assertEqual(d.qty, 250)            # $2,500 / $10
        self.assertEqual(d.max_loss, 2500)

    def test_position_never_over_10_percent(self):
        d = self.rm.check(stock(entry=100, stop=99.9, target=101), snap())
        self.assertLessEqual(d.cost, 50_000)

    def test_option_full_cost_is_max_loss_capped_at_1_percent(self):
        d = self.rm.check(option(), snap())
        # $5,000 / ($2.02 x 100) = 24 contracts
        self.assertTrue(d.approved, str(d))
        self.assertEqual(d.qty, 24)
        self.assertEqual(d.max_loss, d.cost)

    def test_options_cap_20_percent(self):
        held = [Holding("SPY_C1", "option", 99_000, 99_000)]
        with mock.patch.object(C, "OPEN_RISK_MUST_FIT_DAILY_LIMIT", False):
            d = self.rm.check(option(), snap(holdings=held))
        # only $1,000 of the $100k options allowance left -> 4 contracts
        self.assertEqual(d.qty, 4)

    def test_open_risk_rule_limits_options_total(self):
        held = [Holding("SPY_C1", "option", 24_000, 24_000)]
        d = self.rm.check(option(), snap(holdings=held))
        # $25,000 limit - $24,000 already at risk = $1,000 room -> 4 contracts
        self.assertEqual(d.qty, 4)

    def test_no_margin(self):
        held = [Holding(f"S{i}", "stock", 49_900, 1_000) for i in range(9)]
        held.append(Holding("BIG", "etf", 50_000, 1_000))   # $499,100 invested
        rm = RiskManager(self.state)
        with mock.patch.object(C, "MAX_OPEN_POSITIONS", 20):
            d = rm.check(stock(), snap(holdings=held))
        self.assertLessEqual(d.cost, 900)

    def test_open_stops_cant_add_up_past_daily_limit(self):
        held = [Holding(f"S{i}", "stock", 40_000, 2_400) for i in range(9)]  # $21,600 at risk
        d = self.rm.check(stock(entry=100, stop=90, target=120), snap(holdings=held))
        # $25,000 limit - $21,600 open risk = $3,400 room, but $2,500 budget wins -> 250
        self.assertEqual(d.qty, 250)
        d = self.rm.check(stock(entry=100, stop=90, target=120),
                          snap(holdings=held, equity=498_000))   # already down $2,000
        self.assertEqual(d.qty, 140)            # $1,400 room / $10


class RuleTests(Base):
    def test_needs_entry_stop_target(self):
        self.assertRejected(self.rm.check(stock(stop=None), snap()), "must all be set")
        self.assertRejected(self.rm.check(stock(target=None), snap()), "must all be set")

    def test_stop_must_be_below_entry_for_buy(self):
        self.assertRejected(self.rm.check(stock(stop=101), snap()), "stop < entry < target")

    def test_shorting_off(self):
        self.assertRejected(self.rm.check(stock(side="sell", stop=102, target=96), snap()),
                            "short selling is turned off")

    def test_options_buy_only(self):
        self.assertRejected(self.rm.check(option(side="sell"), snap()), "buying only")

    def test_options_must_be_0dte(self):
        self.assertRejected(self.rm.check(option(expires_today=False), snap()), "0DTE")

    def test_max_open_positions(self):
        held = [Holding(f"S{i}", "stock", 1_000, 100) for i in range(10)]
        self.assertRejected(self.rm.check(stock(), snap(holdings=held)), "max open positions")

    def test_pending_orders_count_toward_max(self):
        held = [Holding(f"S{i}", "stock", 1_000, 100) for i in range(8)]
        self.assertRejected(self.rm.check(stock(), snap(holdings=held, pending_entries=2)),
                            "max open positions")

    def test_no_doubling_up(self):
        held = [Holding("AAPL", "stock", 10_000, 200)]
        self.assertRejected(self.rm.check(stock(), snap(holdings=held)), "already holding")

    def test_trade_cap_100(self):
        self.state.trades_opened = 100
        self.assertRejected(self.rm.check(stock(), snap()), "trade cap")
        self.state.trades_opened = 99
        self.assertTrue(self.rm.check(stock(), snap()).approved)


class LiquidityTests(Base):
    def test_cheap_stock(self):
        self.assertRejected(self.rm.check(stock(entry=4, stop=3.9, target=4.3, price=4), snap()),
                            "below $5.00")

    def test_thin_volume(self):
        self.assertRejected(self.rm.check(stock(avg_daily_volume=200_000), snap()),
                            "average volume")

    def test_missing_volume_data_rejected(self):
        self.assertRejected(self.rm.check(stock(avg_daily_volume=None), snap()),
                            "missing liquidity")

    def test_low_open_interest(self):
        self.assertRejected(self.rm.check(option(open_interest=100), snap()), "open interest")

    def test_wide_spread(self):
        self.assertRejected(self.rm.check(option(bid=1.80, ask=2.20), snap()), "spread")


class TimeTests(Base):
    def test_no_options_after_3pm(self):
        self.assertTrue(self.rm.check(option(), snap(now=at(14, 59))).approved)
        self.assertRejected(self.rm.check(option(), snap(now=at(15, 0))), "0DTE options after")

    def test_no_stocks_after_345(self):
        self.assertTrue(self.rm.check(stock(), snap(now=at(15, 44))).approved)
        self.assertRejected(self.rm.check(stock(), snap(now=at(15, 45))), "stock/ETF")

    def test_flatten_at_355(self):
        self.assertFalse(self.rm.must_flatten(snap(now=at(15, 54))))
        self.assertTrue(self.rm.must_flatten(snap(now=at(15, 55))))

    def test_early_close_day_shifts_everything(self):
        early = time(13, 0)
        self.assertEqual(RiskManager.cutoffs(early),
                         {"options": time(12, 0), "stocks": time(12, 45), "flatten": time(12, 55)})
        self.assertTrue(self.rm.must_flatten(snap(now=at(12, 55), session_close=early)))

    def test_market_closed(self):
        self.assertRejected(self.rm.check(stock(), snap(market_open=False)), "market is closed")


class ConnectionTests(Base):
    def test_stale_data_blocks_new_trades(self):
        now = [at(10, 0)]
        health = ConnectionHealth(clock=lambda: now[0])
        rm = RiskManager(self.state, health)
        health.data_tick(); health.broker_ok()
        self.assertTrue(rm.check(stock(), snap(now=now[0])).approved)
        now[0] += timedelta(seconds=C.DATA_STALE_SECONDS + 1)
        health.broker_ok()
        self.assertRejected(rm.check(stock(), snap(now=now[0])), "data feed")
        health.data_tick()                       # feed comes back
        self.assertTrue(rm.check(stock(), snap(now=now[0])).approved)

    def test_broker_error_blocks_new_trades(self):
        health = ConnectionHealth(clock=lambda: at(10, 0))
        health.data_tick(); health.broker_failed("timeout")
        self.assertRejected(RiskManager(self.state, health).check(stock(), snap()), "broker")


class FakeBroker:
    def __init__(self):
        self.flattens = 0

    def flatten_everything(self):
        self.flattens += 1
        return {"orders_left": 0, "positions_left": 0}


class EnforcementTests(Base):
    def setUp(self):
        super().setUp()
        self.broker, self.emails = FakeBroker(), []
        self.send = lambda subj, body: self.emails.append(subj)

    def test_daily_loss_limit_flattens_halts_and_emails(self):
        s = snap(equity=474_999)                 # down $25,001 = past 5%
        self.assertEqual(self.rm.enforce(s, self.broker, self.send), "halted")
        self.assertEqual(self.broker.flattens, 1)
        self.assertEqual(len(self.emails), 1)
        self.assertIn("DAILY LOSS LIMIT", self.emails[0])
        self.assertTrue(self.state.halted)
        # stays halted even if the account recovers
        self.assertRejected(self.rm.check(stock(), snap(equity=490_000)), "halted")
        # only one email, no repeat flatten when already flat
        self.rm.enforce(snap(equity=474_000), self.broker, self.send)
        self.assertEqual(len(self.emails), 1)
        self.assertEqual(self.broker.flattens, 1)

    def test_halt_survives_restart(self):
        self.rm.enforce(snap(equity=470_000), self.broker, self.send)
        reloaded = DayState.load(DAY.date())
        self.assertTrue(reloaded.halted)
        self.assertTrue(DayState.load(DAY.date() + timedelta(days=1)).halted is False)

    def test_just_under_limit_does_nothing(self):
        self.assertIsNone(self.rm.enforce(snap(equity=475_001), self.broker, self.send))

    def test_end_of_day_flatten_and_retry(self):
        self.assertIsNone(self.rm.enforce(snap(now=at(15, 54)), self.broker, self.send))
        self.assertEqual(self.rm.enforce(snap(now=at(15, 55)), self.broker, self.send),
                         "flattened end of day")
        held = [Holding("AAPL", "stock", 10_000, 200)]   # something didn't close
        self.rm.enforce(snap(now=at(15, 56), holdings=held), self.broker, self.send)
        self.assertEqual(self.broker.flattens, 2)


if __name__ == "__main__":
    unittest.main()
