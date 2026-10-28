"""
Backtester: replays past days minute by minute and pretends to trade.

    python -m day_trader.backtest orb              last ~6 months
    python -m day_trader.backtest orb --months 12

How it pretends (kept deliberately pessimistic):
  - Signals use only bars that had finished at that moment (no peeking ahead).
  - Buy at the NEXT minute's opening price, plus 0.05% slippage
    (the small extra you pay versus the quoted price).
  - If the stop and target are both touched in the same minute, assume the
    stop hit first. If the price gaps through the stop, fill at the worse price.
  - Every trade goes through the SAME risk manager as the live bot (size caps,
    10 positions, 100 trades/day, daily loss limit, 3:45/3:55 cutoffs).
  - Commission: $0 (Alpaca charges none for stocks).
"""
from __future__ import annotations

import argparse
import importlib
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

from . import config as C
from . import stats
from .data import minute_bars
from .risk import ET, DayState, Holding, RiskManager, Snapshot, TradeIdea
from .universe import UNIVERSE

SLIPPAGE = 0.0005
STRATEGIES = {"orb": "day_trader.strategies.orb",
              "momentum": "day_trader.strategies.momentum",
              "mean_reversion": "day_trader.strategies.mean_reversion",
              "news": "day_trader.strategies.news"}
REPORTS = C.PKG_DIR / "reports"


def simulate_exit(day: pd.DataFrame, sig, flatten_at: time):
    """From the bar after the signal: entry, then stop / target / end-of-day exit."""
    later = day[day.index > sig.time]
    if later.empty:
        return None
    o, h, l, c = (later[k].to_numpy() for k in ("open", "high", "low", "close"))
    entry = float(o[0]) * (1 + SLIPPAGE)
    if entry <= sig.stop:
        return None
    target = sig.target_for(entry)
    if target <= entry:            # target already passed by the time we'd get in
        return None
    times = later.index
    flat = np.array([t >= flatten_at for t in times.time])
    hits = {"end of day": flat, "stop-loss": l <= sig.stop, "target": h >= target}
    first = {k: (int(np.argmax(m)) if m.any() else len(o)) for k, m in hits.items()}
    i = min(first.values())
    if i == len(o):
        return entry, target, times[0], times[-1], float(c[-1]) * (1 - SLIPPAGE), "end of day"
    # same minute: end-of-day first, then the stop (pessimistic), then the target
    why = next(k for k in ("end of day", "stop-loss", "target") if first[k] == i)
    if why == "end of day":
        px = float(o[i]) * (1 - SLIPPAGE)
    elif why == "stop-loss":
        px = min(float(o[i]), sig.stop) * (1 - SLIPPAGE)
    else:
        px = target if i == 0 else max(float(o[i]), target)
    return entry, target, times[0], times[i], px, why


def run(name: str, start: date, end: date, symbols=UNIVERSE, params=None, verbose=True,
        bars=None, days=None, daily=None, day_symbols=None, day_ctx=None):
    """
    daily: {symbol: daily bars} - if given, average volume / previous close come
           from these (needed when minute data only exists for "in play" days).
    day_symbols: {date: [symbols]} - only these symbols are traded that day.
    """
    strat = importlib.import_module(STRATEGIES[name])
    p = dict(strat.PARAMS, **(params or {}))
    warmup = start - timedelta(days=45)
    if verbose:
        print(f"Loading minute data {warmup} -> {end} for {len(symbols)} symbols (cached after first time)")
    if bars is None:
        bars = minute_bars(list(symbols), warmup, end, verbose=verbose)
    if days is None:
        days = split_days(bars)

    # Pre-compute daily facts from minute bars (unless daily bars were given).
    facts = {}
    if daily is None:
        for sym, g in days.items():
            facts[sym] = pd.DataFrame({
                "volume": {d: x.volume.sum() for d, x in g.items()},
                "dollar_volume": {d: (x.volume * x.close).sum() for d, x in g.items()},
                "open_volume": {d: strat.opening_volume(x, p) if hasattr(strat, "opening_volume")
                                else None for d, x in g.items()},
                "close": {d: float(x.close.iloc[-1]) for d, x in g.items()},
            }).sort_index()
    all_days = sorted({d for g in days.values() for d in g if start <= d <= end})

    equity, trades, curve = C.STARTING_BALANCE, [], {}
    for d in all_days:
        cands = []
        todays = day_symbols.get(d, []) if day_symbols is not None else list(days)
        for sym in todays:
            day = days.get(sym, {}).get(d)
            if day is None or len(day) < 30:
                continue
            if daily is not None:
                dd = daily.get(sym)
                prior = dd[dd.index < pd.Timestamp(d)].tail(20) if dd is not None else []
                if len(prior) < 10:
                    continue
                ctx = {"adv": prior.volume.mean(),
                       "adv_dollar": (prior.volume * prior.close).mean(),
                       "prev_close": float(prior.close.iloc[-1])}
            else:
                prior = facts[sym][facts[sym].index < d].tail(20)
                if len(prior) < 10:
                    continue
                ctx = {"avg_open_volume": prior.open_volume.mean(),
                       "adv": prior.volume.mean(), "adv_dollar": prior.dollar_volume.mean(),
                       "prev_close": float(prior.close.iloc[-1])}
            ctx["market_day"] = days.get("SPY", {}).get(d)
            if day_ctx:
                ctx.update(day_ctx.get((d, sym), {}))
            last = day.index[-1].time()
            close = time(16, 0) if last >= time(15, 59) else \
                (datetime.combine(d, last) + timedelta(minutes=1)).time()
            flatten = RiskManager.cutoffs(close)["flatten"]
            for sig in strat.find_signals(sym, day, ctx, p):
                sim = simulate_exit(day, sig, flatten)
                if sim:
                    cands.append((sig, ctx, close, sim))
        cands.sort(key=lambda c: c[3][2])   # by entry time

        state = DayState(day=d.isoformat())
        rm = RiskManager(state)
        start_eq, realized, open_pos = equity, 0.0, []
        for sig, ctx, close, (entry, target, t_in, t_out, px_out, why) in cands:
            # close anything that exited before this entry
            for pos in [x for x in open_pos if x["exit_time"] <= t_in]:
                realized += pos["pnl"]
                open_pos.remove(pos)
            if realized <= -C.DAILY_LOSS_LIMIT_PCT * start_eq:
                state.halted, state.halt_reason = True, "daily loss limit"
            snap = Snapshot(now=t_in, equity=start_eq + realized, start_equity=start_eq,
                            holdings=[Holding(x["symbol"], "stock", x["qty"] * x["entry"],
                                              x["qty"] * (x["entry"] - x["stop"])) for x in open_pos],
                            session_close=close)
            idea = TradeIdea(sig.symbol, "stock", "buy", sig.strategy, entry, sig.stop, target,
                             sig.reason, price=entry, avg_daily_volume=ctx["adv"],
                             avg_dollar_volume=ctx["adv_dollar"])
            dec = rm.check(idea, snap)
            if not dec.approved:
                continue
            state.trades_opened += 1
            pnl = (px_out - entry) * dec.qty
            row = {"date": d, "symbol": sig.symbol, "strategy": sig.strategy,
                   "entry_time": t_in.strftime("%H:%M"), "exit_time": t_out.strftime("%H:%M"),
                   "qty": dec.qty, "entry": round(entry, 2), "stop": round(sig.stop, 2),
                   "target": round(target, 2), "exit": round(px_out, 2),
                   "pnl": round(pnl, 2), "exit_reason": why, "reason": sig.reason}
            trades.append(row)
            open_pos.append({**row, "exit_time": t_out, "entry": entry, "stop": sig.stop})
        realized += sum(x["pnl"] for x in open_pos)
        equity = start_eq + realized
        curve[d] = equity

    tdf = pd.DataFrame(trades)
    eq = pd.Series(curve)
    summary = stats.summarize(tdf, eq, C.STARTING_BALANCE)
    return tdf, eq, summary, bars


def split_days(bars):
    return {sym: {d: x for d, x in df.groupby(df.index.date)} for sym, df in bars.items()}


def benchmark(bars, start, end):
    spy = bars.get("SPY")
    if spy is None:
        return None
    spy = spy[(spy.index.date >= start) & (spy.index.date <= end)]
    return float(spy.close.iloc[-1] / spy.open.iloc[0] - 1)


def report(name, start, end, tdf, eq, s, spy_ret) -> str:
    lines = [f"# Backtest: {name}", "",
             f"Period: {start} to {end} | starting balance ${C.STARTING_BALANCE:,.0f}", "",
             "```", stats.describe(s), "```", ""]
    if spy_ret is not None:
        lines += [f"For comparison, simply holding SPY over the same period: {spy_ret:+.2%}", ""]
    if len(tdf):
        lines += ["## By exit reason", "", "| Exit | Trades | P&L |", "|---|---|---|"]
        for why, g in tdf.groupby("exit_reason"):
            lines.append(f"| {why} | {len(g)} | ${g.pnl.sum():,.0f} |")
        tdf = tdf.copy()
        tdf["month"] = pd.to_datetime(tdf["date"]).dt.strftime("%Y-%m")
        lines += ["", "## By month", "", "| Month | Trades | Win rate | P&L |", "|---|---|---|---|"]
        for m, g in tdf.groupby("month"):
            lines.append(f"| {m} | {len(g)} | {(g.pnl > 0).mean():.0%} | ${g.pnl.sum():,.0f} |")
        lines += ["", f"Trades per day: {len(tdf) / max(len(eq), 1):.1f} on average"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy", choices=list(STRATEGIES))
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=int(args.months * 30.4))
    tdf, eq, s, bars = run(args.strategy, start, end)
    text = report(args.strategy, start, end, tdf, eq, s, benchmark(bars, start, end))
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"backtest_{args.strategy}.md").write_text(text)
    tdf.to_csv(REPORTS / f"backtest_{args.strategy}_trades.csv", index=False)
    print(text)


if __name__ == "__main__":
    main()
