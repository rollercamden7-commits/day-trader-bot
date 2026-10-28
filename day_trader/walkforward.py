"""
Walk-forward test: pick the best version of a strategy on PRACTICE months,
then check it on UNSEEN months. Rules are fixed before the run.

    python -m day_trader.walkforward orb
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from . import backtest as B
from .data import minute_bars
from .universe import UNIVERSE

VARIANTS = {
    "orb": {
        "baseline (current)": {},
        "stop at middle of range": {"stop": "mid"},
        "30-minute range": {"range_minutes": 30},
        "only when SPY also breaks out": {"spy_confirm": True},
        "target 1x risk": {"reward_risk": 1.0},
        "middle stop + 1x target": {"stop": "mid", "reward_risk": 1.0},
    },
    "momentum": {
        "baseline (current)": {},
        "target 1x risk": {"reward_risk": 1.0},
        "stop just under VWAP": {"stop_mode": "vwap"},
        "bigger volume surge (3x)": {"vol_mult": 3.0},
        "mornings only (until 11:00)": {"last_entry": __import__("datetime").time(11, 0)},
        "no VWAP rule": {"require_vwap": False},
    },
    "mean_reversion": {
        "baseline (current)": {},
        "fixed target 1x risk": {"target": "r", "reward_risk": 1.0},
        "deeper drop (3%)": {"min_drop": 0.03, "min_below_vwap": 0.02},
        "skip when SPY down >1%": {"spy_filter": -0.01},
        "buy without waiting for the turn": {"confirm_turn": False},
        "60-minute lookback": {"lookback": 60},
    },
    "news": {
        "baseline (current)": {},
        "no news needed (pure gap-and-go)": {"require_news": False},
        "bigger gap (5%)": {"min_gap": 0.05},
        "15-minute opening range": {"range_minutes": 15},
        "target 1x risk": {"reward_risk": 1.0},
        "entries until 11:30": {"last_entry": __import__("datetime").time(11, 30)},
    },
}
MIN_TRAIN_TRADES = 30
MIN_TEST_PROFIT_FACTOR = 1.1


def load_inplay(start, end, big_days):
    """Each day's top-20 gap-up stocks from the whole market, with minute bars."""
    from .data import all_tradable_symbols, daily_bars_cached, minute_bars_for_days
    from .universe import in_play
    syms = all_tradable_symbols()
    print(f"Whole market: {len(syms)} symbols. Loading daily bars (cached after first time)...")
    daily = daily_bars_cached(syms, start - timedelta(days=60), end, "all")
    trading_days = sorted(d for d in big_days.get("SPY", {}) if start <= d <= end)
    picks = {d: in_play(daily, d) for d in trading_days}
    print(f"In-play picks: {sum(map(len, picks.values()))} stock-days. Loading their minute bars...")
    days = minute_bars_for_days(picks)
    days["SPY"] = big_days["SPY"]
    return days, {"daily": daily, "day_symbols": picks}


def load_news(start, end, big_days):
    """Top-30 gap-ups (3%+) each day, tagged with any overnight news headline."""
    from bisect import bisect_right
    from collections import defaultdict
    from datetime import datetime, time as dtime
    from .data import (all_tradable_symbols, daily_bars_cached, minute_bars_for_days,
                       news_history)
    from .risk import ET
    from .universe import in_play
    syms = all_tradable_symbols()
    daily = daily_bars_cached(syms, start - timedelta(days=60), end, "all")
    trading_days = sorted(d for d in big_days.get("SPY", {}) if start <= d <= end)
    print("Loading news history (cached after first time)...")
    news = news_history(start - timedelta(days=5), end)
    by_sym_day = defaultdict(list)
    tdays = set(trading_days)
    for when, symbols, headline in news:
        w, t = when.date(), when.time()
        if w in tdays and t <= dtime(9, 25):
            d = w                                   # this morning's pre-market news
        elif w in tdays and t < dtime(16, 0):
            continue                                # during market hours: not overnight
        else:                                       # after the close / weekend -> next trading day
            i = bisect_right(trading_days, w)
            if i >= len(trading_days):
                continue
            d = trading_days[i]
        for s_ in symbols:
            by_sym_day[(d, s_)].append(headline)
    picks = {d: in_play(daily, d, top_n=30, min_gap=0.03) for d in trading_days}
    tagged = sum(1 for d, ss in picks.items() for s in ss if (d, s) in by_sym_day)
    print(f"Gap-ups: {sum(map(len, picks.values()))} stock-days, {tagged} with overnight news.")
    days = minute_bars_for_days(picks)
    days["SPY"] = big_days["SPY"]
    day_ctx = {k: {"news": v} for k, v in by_sym_day.items()}
    return days, {"daily": daily, "day_symbols": picks, "day_ctx": day_ctx}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy", choices=list(VARIANTS))
    ap.add_argument("--universe", choices=["big", "inplay", "news"], default="big",
                    help="big = 113 large stocks/ETFs; inplay = each day's top-20 gap-ups")
    args = ap.parse_args()
    end = date.today() - timedelta(days=1)
    split = end - timedelta(days=183)
    start = split - timedelta(days=182)
    print(f"{args.strategy} on '{args.universe}' stocks | Practice: {start} -> {split} | "
          f"Unseen: {split + timedelta(days=1)} -> {end}")
    bars = minute_bars(list(UNIVERSE), start - timedelta(days=45), end, verbose=False)
    days = B.split_days(bars)
    extra = {}
    if args.universe == "inplay":
        days, extra = load_inplay(start, end, days)
    elif args.universe == "news":
        days, extra = load_news(start, end, days)

    rows = []
    for label, params in VARIANTS[args.strategy].items():
        r = {"variant": label}
        for part, (a, b) in {"train": (start, split), "test": (split + timedelta(days=1), end)}.items():
            _, _, s, _ = B.run(args.strategy, a, b, params=params, verbose=False, bars=bars, days=days,
                               **extra)
            r[part] = s
        rows.append(r)
        t, u = r["train"], r["test"]
        print(f"  {label:32s} practice: {t.get('total_return', 0):+6.2%} Sharpe {t.get('sharpe', 0):5.2f} "
              f"({t['trades']} trades) | unseen: {u.get('total_return', 0):+6.2%} "
              f"PF {u.get('profit_factor', 0):.2f} ({u['trades']} trades)")

    eligible = [r for r in rows if r["train"]["trades"] >= MIN_TRAIN_TRADES]
    best = max(eligible, key=lambda r: r["train"].get("sharpe", -99))
    base = rows[0]
    u = best["test"]
    checks = {
        "made money on unseen months": u.get("total_return", 0) > 0,
        f"profit factor >= {MIN_TEST_PROFIT_FACTOR} on unseen months": u.get("profit_factor", 0) >= MIN_TEST_PROFIT_FACTOR,
        "beat the baseline on unseen months":
            best is base or u.get("total_return", 0) > base["test"].get("total_return", 0),
    }
    print(f"\nPicked on practice months: {best['variant']}")
    for k, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {k}")
    print("RESULT:", "PASSED - can be switched on" if all(checks.values())
          else "FAILED - strategy stays OFF")


if __name__ == "__main__":
    main()
