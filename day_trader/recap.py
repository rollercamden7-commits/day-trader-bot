"""
After-close recap email + rules-based review (no AI).

The review looks at the numbers and writes plain-English notes. It may
SUGGEST a settings change; suggestions are saved for you to approve and are
never applied automatically.

    python -m day_trader.recap            rebuild and print today's recap (no email)
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta

import pandas as pd

from . import config as C
from . import journal, stats
from .emailer import send_email
from .risk import ET, DayState, RiskManager


def money(x):
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def review(today: date) -> list:
    """Plain-English notes + suggestions (saved for approval)."""
    notes, trades = [], journal.trades_df()
    trades = trades[~trades.exit_reason.str.startswith("not filled", na=False)]
    if trades.empty:
        return ["No completed trades yet - nothing to review."]
    recent_days = sorted(trades.day.unique())[-20:]
    recent = trades[trades.day.isin(recent_days)]
    for strat, g in recent.groupby("strategy"):
        if len(g) < 10:
            notes.append(f"{strat}: only {len(g)} trades in the last 20 days - too few to judge.")
            continue
        lost = -g[g.pnl <= 0].pnl.sum()
        pf = g[g.pnl > 0].pnl.sum() / lost if lost > 0 else float("inf")
        wr = (g.pnl > 0).mean()
        stops = (g.exit_reason == "stop-loss").mean()
        notes.append(f"{strat}: {len(g)} trades in the last {len(recent_days)} days, win rate "
                     f"{wr:.0%}, profit factor {pf:.2f}, P&L {money(g.pnl.sum())}. "
                     f"{stops:.0%} ended at the stop-loss.")
        status = C.STRATEGY_STATUS.get(strat, "proven")
        if len(g) >= 30 and pf < 0.8:
            journal.add_suggestion(today, f"STRATEGIES_ENABLED['{strat}']", True, False,
                                   f"profit factor {pf:.2f} over its last {len(g)} trades")
            notes.append(f"  -> SUGGESTION: switch {strat} off. It is losing about "
                         f"${1 - pf:.2f} for every $1 it wins.")
        elif status == "experimental" and len(g) >= 50 and pf >= 1.2:
            notes.append(f"  -> {strat} (experiment) is doing well live. Worth re-running its "
                         f"walk-forward test to see if it now passes.")
        if len(g) >= 20 and stops > 0.6:
            notes.append(f"  -> Most {strat} trades hit their stop. A backtest of a wider stop "
                         f"could be worth trying (not changed automatically).")
    sigs = journal.signals_today(today)
    rejected = Counter(s["detail"].split("| ")[-1].split(";")[0] for s in sigs if s["action"] == "rejected")
    for why, n in rejected.most_common(3):
        if n >= 5:
            notes.append(f"Today {n} signals were blocked because: {why}. That limit is doing a lot "
                         f"of work - worth knowing, not necessarily a problem.")
    return notes


def build(today: date, dry=False, watch_bars=None, would=None) -> tuple:
    state = DayState.load(today)
    lines = []
    if dry:
        subject, body = watch_only(today, watch_bars or {}, would or [])
        return subject, body
    days = journal.days_df()
    trades = journal.trades_df(day=today.isoformat())
    trades = trades[~trades.exit_reason.str.startswith("not filled", na=False)]
    row = days[days.day == today.isoformat()]
    if row.empty:
        return f"Recap {today}: no record", "No record for today."
    r = row.iloc[0]
    since = days.end_equity.iloc[-1] / days.start_equity.iloc[0] - 1
    subject = f"Recap {today}: {money(r.pnl)} ({r.pnl_pct:+.2%}) | {len(trades)} trades"
    lines += ["TODAY",
              f"  P&L: {money(r.pnl)} ({r.pnl_pct:+.2%})   account ${r.end_equity:,.0f}",
              f"  Since launch ({days.day.iloc[0]}): {since:+.2%} "
              f"(${days.start_equity.iloc[0]:,.0f} -> ${days.end_equity.iloc[-1]:,.0f})",
              f"  Trades: {len(trades)}"]
    if len(trades):
        best, worst = trades.loc[trades.pnl.idxmax()], trades.loc[trades.pnl.idxmin()]
        lines += [f"  Win rate: {(trades.pnl > 0).mean():.0%}",
                  f"  Biggest winner: {best.symbol} {money(best.pnl)} ({best.strategy})",
                  f"  Biggest loser:  {worst.symbol} {money(worst.pnl)} ({worst.strategy})",
                  "", "BY STRATEGY"]
        for k, g in trades.groupby("strategy"):
            tag = " [EXPERIMENT]" if C.STRATEGY_STATUS.get(k) == "experimental" else ""
            lines.append(f"  {k}{tag}: {len(g)} trades, {money(g.pnl.sum())}")
        lines += ["", "BY TYPE"]
        for k in ("stock", "etf", "option"):
            g = trades[trades.asset_class == k]
            lines.append(f"  {k}: {len(g)} trades, {money(g.pnl.sum())}")
        lines += ["", "EVERY TRADE"]
        for _, t in trades.iterrows():
            lines.append(f"  {str(t.entry_time)[11:16]}-{str(t.exit_time)[11:16]} {t.symbol} "
                         f"{t.qty:g} @ {t.entry_price:.2f} -> {t.exit_price:.2f} "
                         f"{money(t.pnl)} ({t.exit_reason}) [{t.strategy}]")
    lines += ["", "RISK LIMITS HIT"] + ([f"  {x}" for x in state.limits_hit] or ["  none"])
    lines += ["", "REVIEW (rules-based)"] + [f"  {n}" for n in review(today)]
    pend = journal.suggestions()
    if pend:
        lines += ["", "SUGGESTIONS WAITING FOR YOUR OK (nothing changes unless you approve)"]
        lines += [f"  #{p['id']}: {p['setting']} {p['current']} -> {p['suggested']} ({p['why']})"
                  for p in pend]
    lines += ["", "Full stats any time: python -m day_trader.stats"]
    return subject, "\n".join(lines)


def watch_only(today, bars, would) -> tuple:
    """What the would-be trades would have made, replayed on today's prices."""
    from .backtest import simulate_exit
    flatten = RiskManager.cutoffs(datetime.now(ET).replace(hour=16, minute=0).time())["flatten"]
    lines, total = ["WATCH-ONLY DAY (no orders were placed)", ""], 0.0
    for sig, qty in would:
        day = bars.get(sig.symbol)
        sim = simulate_exit(day, sig, flatten) if day is not None else None
        if not sim:
            lines.append(f"  {sig.symbol}: couldn't replay")
            continue
        entry, target, t_in, t_out, px, why = sim
        pnl = (px - entry) * qty
        total += pnl
        lines.append(f"  {t_in:%H:%M}-{t_out:%H:%M} {sig.symbol} {qty} @ {entry:.2f} -> {px:.2f} "
                     f"{money(pnl)} ({why}) [{sig.strategy}]")
    if not would:
        lines.append("  No trades would have been made today.")
    lines += ["", f"Would-be P&L: {money(total)} on {len(would)} trades",
              "(Replayed with the same pessimistic rules as the backtests.)"]
    return f"Watch-only recap {today}: would-be P&L {money(total)}", "\n".join(lines)


def send_daily(today: date, dry=False, watch_bars=None, would=None):
    subject, body = build(today, dry, watch_bars, would)
    print("\n" + subject + "\n" + body, flush=True)
    send_email(subject, body)          # watch-only days email their recap too


if __name__ == "__main__":
    print("\n".join(build(datetime.now(ET).date())))
