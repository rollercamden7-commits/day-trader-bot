"""
The live trading engine. Runs during market hours, once a minute:

  1. Fetch the newest 1-minute prices (free IEX feed).
  2. Check the account; record any trades that hit their stop or target.
  3. Risk checks: daily loss limit, 3:55pm close-out, connection health.
  4. Ask each switched-on strategy for signals; every signal goes through
     the risk manager; approved ones are sent as bracket orders (entry +
     stop-loss + profit target together).
  5. After the close: record the day and send the recap email.

    python -m day_trader.engine                 trade (paper account)
    python -m day_trader.engine --dry-run       WATCH-ONLY: log what it would do, no orders
    python -m day_trader.engine --until 12:30   stop at 12:30 (morning job on GitHub)

Safe to restart any time: it rebuilds its picture from Alpaca + the trade log.
"""
from __future__ import annotations

import argparse
import importlib
import sys
import time as _time
import traceback
from datetime import datetime, time, timedelta

from . import config as C
from . import journal
from .broker import Broker
from .data import LiveBars
from .emailer import send_email
from .risk import ET, ConnectionHealth, DayState, Holding, RiskManager, Snapshot, TradeIdea
from .universe import UNIVERSE

STRATEGY_MODULES = {
    "opening_range_breakout": "day_trader.strategies.orb",
    "momentum": "day_trader.strategies.momentum",
    "mean_reversion": "day_trader.strategies.mean_reversion",
}
FRESH_SIGNAL = timedelta(minutes=3)   # only act on signals from the last few minutes


def log(msg):
    print(f"{datetime.now(ET):%H:%M:%S} {msg}", flush=True)


class Engine:
    def __init__(self, dry_run=False, until: time = None):
        self.dry = dry_run
        self.mode = "watch" if dry_run else "paper"
        self.until = until
        self.broker = Broker(dry_run=dry_run)
        self.now = datetime.now(ET)
        self.today = self.now.date()
        self.state = DayState.load(self.today)
        self.health = ConnectionHealth()
        self.rm = RiskManager(self.state, self.health)
        self.done = {(s["strategy"], s["symbol"]) for s in journal.signals_today(self.today)}
        self.would = []          # watch-only: trades it would have made

    # ------------------------------------------------------------ setup
    def session(self):
        from alpaca.trading.requests import GetCalendarRequest
        cal = self.broker.client.get_calendar(GetCalendarRequest(start=self.today, end=self.today))
        if not cal:
            return None
        c = cal[0]
        return (datetime.combine(self.today, c.open.time(), ET),
                datetime.combine(self.today, c.close.time(), ET))

    def wait_until(self, when: datetime):
        while datetime.now(ET) < when:
            _time.sleep(min(30, max(1, (when - datetime.now(ET)).total_seconds())))

    def setup(self) -> bool:
        sess = self.session()
        if sess is None:
            log("Market closed today (weekend/holiday). Nothing to do.")
            return False
        self.open_dt, self.close_dt = sess
        self.session_close = self.close_dt.time()
        acct = self.broker.account()
        self.start_equity = float(acct.last_equity)       # account value at yesterday's close
        log(f"=== Day trader {self.today} | mode {self.mode.upper()} | start equity "
            f"${self.start_equity:,.0f} | close {self.session_close:%H:%M} ===")

        from .watchlist import in_play, liquid_universe
        self.liquid = liquid_universe(self.today, verbose=False)
        self.wait_until(self.open_dt + timedelta(minutes=1, seconds=30))
        self.inplay = in_play(self.liquid)
        log(f"In play today ({len(self.inplay)}): {', '.join(self.inplay) or 'none'}")

        self.strats = {}
        for name, on in C.STRATEGIES_ENABLED.items():
            if on and name in STRATEGY_MODULES:
                mod = importlib.import_module(STRATEGY_MODULES[name])
                group = C.STRATEGY_UNIVERSE.get(name, "big")
                syms = self.inplay if group == "inplay" else [s for s in UNIVERSE if s in self.liquid]
                self.strats[name] = (mod, syms)
                tag = " [EXPERIMENT]" if C.STRATEGY_STATUS.get(name) == "experimental" else ""
                log(f"Strategy on: {name}{tag} scanning {len(syms)} symbols")
        watch = sorted({s for _, syms in self.strats.values() for s in syms} | {"SPY"})
        self.bars = LiveBars(watch)
        return True

    # ------------------------------------------------------------ each minute
    def snapshot(self, now) -> Snapshot:
        acct = self.broker.account()
        positions = self.broker.positions()
        orders = self.broker.open_orders()
        self.health.broker_ok()
        stops = {t["symbol"]: t for t in journal.open_trades() if t["mode"] == "paper"}
        holdings = []
        for p in positions:
            qty, entry = abs(float(p.qty)), float(p.avg_entry_price)
            t = stops.get(p.symbol)
            asset = "option" if p.asset_class.value == "us_option" else "stock"
            max_loss = qty * (entry - t["stop"]) if t and asset != "option" else None
            holdings.append(Holding(p.symbol, asset, abs(float(p.market_value)), max_loss))
        pending = sum(1 for o in orders if o.side.value == "buy" and o.filled_qty in (None, "0", 0)
                      and o.status.value in ("new", "accepted", "pending_new", "partially_filled"))
        self.positions = {p.symbol for p in positions}
        return Snapshot(now=now, equity=float(acct.equity), start_equity=self.start_equity,
                        holdings=holdings, pending_entries=pending,
                        session_close=self.session_close, market_open=self.broker.clock().is_open)

    def reconcile(self):
        """Record trades that have exited since last minute."""
        for t in journal.open_trades():
            if t["mode"] != "paper" or not t["order_id"]:
                continue
            parent = self.broker.get_order(t["order_id"])
            status = parent.status.value
            if status in ("canceled", "expired", "rejected") and not float(parent.filled_qty or 0):
                journal.cancel_trade(t["id"], status)
                continue
            if status != "filled":
                continue
            ex = self.broker.exit_fill(t["order_id"])
            if ex is None and t["symbol"] not in self.positions:
                fill = self.broker.last_sell_fill(t["symbol"], parent.filled_at)
                if fill is not None:
                    why = ("daily loss limit close-out" if self.state.halted
                           else "end-of-day close-out" if self.state.flattened_eod
                           else "closed outside the bot")
                    ex = (float(fill.filled_avg_price), fill.filled_at, why)
            if ex:
                pnl = journal.close_trade(t["id"], ex[1].astimezone(ET), ex[0], ex[2])
                log(f"EXIT {t['symbol']} ({t['strategy']}) {ex[2]} @ {ex[0]:.2f} -> P&L ${pnl:,.0f}")

    def ctx_for(self, sym):
        info = self.liquid.get(sym, {})
        return {"adv": info.get("adv"), "adv_dollar": info.get("adv_dollar"),
                "prev_close": info.get("prev_close"), "market_day": self.bars.bars.get("SPY")}

    def scan(self, snap: Snapshot, now):
        for name, (mod, syms) in self.strats.items():
            for sym in syms:
                if (name, sym) in self.done:
                    continue
                day = self.bars.bars.get(sym)
                if day is None or len(day) < 20:
                    continue
                ctx = self.ctx_for(sym)
                sigs = mod.find_signals(sym, day, ctx, mod.PARAMS)
                if not sigs:
                    continue
                sig = sigs[0]
                self.done.add((name, sym))          # first signal of the day only (as in backtests)
                if now - sig.time > FRESH_SIGNAL:
                    journal.log_signal(self.today, sig.time.strftime("%H:%M"), name, sym,
                                       "missed", "signal happened while the bot wasn't running")
                    continue
                self.act(sig, day, ctx, snap)

    def act(self, sig, day, ctx, snap):
        entry = float(day.close.iloc[-1])
        target = sig.target_for(entry)
        idea = TradeIdea(sig.symbol, "stock", "buy", sig.strategy, entry, sig.stop, target,
                         sig.reason, price=entry, avg_daily_volume=ctx["adv"],
                         avg_dollar_volume=ctx["adv_dollar"])
        dec = self.rm.check(idea, snap)
        hhmm = sig.time.strftime("%H:%M")
        if not dec.approved:
            journal.log_signal(self.today, hhmm, sig.strategy, sig.symbol, "rejected", str(dec))
            log(f"SKIP {sig.symbol} ({sig.strategy}): {'; '.join(dec.reasons)}")
            return
        detail = (f"{dec.qty} sh @ ~{entry:.2f}, stop {sig.stop:.2f}, target {target:.2f}. "
                  f"{sig.reason}")
        if self.dry:
            journal.log_signal(self.today, hhmm, sig.strategy, sig.symbol, "would trade", detail)
            self.would.append((sig, dec.qty))
            log(f"WOULD BUY {sig.symbol} ({sig.strategy}) {detail}")
            snap.pending_entries += 1
            return
        cid = f"dt-{sig.strategy[:4]}-{sig.symbol}-{self.today:%m%d}-{hhmm.replace(':', '')}"
        try:
            order = self.broker.bracket_buy(sig.symbol, dec.qty, sig.stop, target, cid)
        except Exception as e:
            journal.log_signal(self.today, hhmm, sig.strategy, sig.symbol, "order failed", str(e))
            log(f"ORDER FAILED {sig.symbol}: {e}")
            return
        tid = journal.open_trade(day=self.today, strategy=sig.strategy, symbol=sig.symbol,
                                 asset_class="stock", side="buy", qty=dec.qty,
                                 entry_time=datetime.now(ET), entry_price=entry, stop=sig.stop,
                                 target=target, reason=sig.reason, order_id=str(order.id),
                                 mode=self.mode)
        self.rm.record_trade_opened()
        journal.log_signal(self.today, hhmm, sig.strategy, sig.symbol, "traded", detail)
        snap.pending_entries += 1
        order = self.broker.wait_for_fill(str(order.id), seconds=10)
        if order.status.value == "filled":
            journal.update_entry(tid, float(order.filled_avg_price), float(order.filled_qty),
                                 order.filled_at.astimezone(ET))
            log(f"BOUGHT {order.filled_qty} {sig.symbol} @ {float(order.filled_avg_price):.2f} "
                f"({sig.strategy}) stop {sig.stop:.2f} target {target:.2f}")
        else:
            log(f"BUY SENT {sig.symbol} ({sig.strategy}), status {order.status.value}")

    def tick(self):
        now = datetime.now(ET)
        try:
            self.bars.refresh(now)
            if self.bars.last_bar_time and now - self.bars.last_bar_time < timedelta(minutes=3):
                self.health.data_tick()
        except Exception as e:
            log(f"Price feed error: {e}")
        try:
            snap = self.snapshot(now)
        except Exception as e:
            self.health.broker_failed(str(e))
            log(f"Broker error - no new trades until it's back: {e}")
            return
        if not self.dry:
            self.reconcile()
        if not self.dry:
            did = self.rm.enforce(snap, self.broker, send_email)
            if did:
                log(f"RISK ACTION: {did}")
        problems = self.health.problems()
        if problems:
            log("Not opening trades: " + "; ".join(problems))
            return
        if not self.state.halted and not self.rm.must_flatten(snap):
            self.scan(snap, now)

    # ------------------------------------------------------------ main loop
    def run(self):
        if not self.setup():
            return
        stop_at = self.close_dt + timedelta(minutes=2)
        if self.until:
            stop_at = min(stop_at, datetime.combine(self.today, self.until, ET))
        while datetime.now(ET) < stop_at:
            started = _time.time()
            try:
                self.tick()
            except Exception:
                log("Error during this minute (continuing):\n" + traceback.format_exc())
            nxt = (datetime.now(ET) + timedelta(minutes=1)).replace(second=5, microsecond=0)
            _time.sleep(max(1.0, (nxt - datetime.now(ET)).total_seconds()))
            if _time.time() - started > 120:
                log("Warning: a minute took over 2 minutes to process.")
        if datetime.now(ET) >= self.close_dt:
            self.end_of_day()
        else:
            log(f"Stopping at {self.until} (the afternoon job takes over).")

    def end_of_day(self):
        from . import recap
        if not self.dry:
            _time.sleep(20)
            self.positions = {p.symbol for p in self.broker.positions()}
            self.reconcile()
            acct = self.broker.account()
            journal.record_day(self.today, self.start_equity, float(acct.equity),
                               self.state.trades_opened, self.state.limits_hit)
        recap.send_daily(self.today, dry=self.dry, watch_bars=self.bars.bars if self.dry else None,
                         would=self.would)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="watch-only: no orders")
    ap.add_argument("--until", help="HH:MM - stop early (morning job)")
    args = ap.parse_args()
    until = time(*map(int, args.until.split(":"))) if args.until else None
    try:
        Engine(dry_run=args.dry_run, until=until).run()
    except Exception:
        err = traceback.format_exc()
        print(err, flush=True)
        if not args.dry_run:
            send_email("CRASH - the day trader stopped",
                       "The trading engine crashed. Open trades still have their stop-loss and "
                       "target orders on Alpaca, and the 3:50pm safety job will close everything "
                       "if needed.\n\n" + err)
            (C.PKG_DIR / ".crash_emailed").write_text("1")
        sys.exit(1)


if __name__ == "__main__":
    main()
