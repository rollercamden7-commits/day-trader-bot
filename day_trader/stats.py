"""
Performance stats, used by backtests and (later) the live stats command.
"""
from __future__ import annotations

import math

import pandas as pd


def summarize(trades: pd.DataFrame, equity: pd.Series, start_balance: float) -> dict:
    """trades needs a 'pnl' column; equity is account value at each day's close."""
    out = {"trades": int(len(trades))}
    if len(equity):
        out["end_balance"] = float(equity.iloc[-1])
        out["total_return"] = float(equity.iloc[-1] / start_balance - 1)
        curve = pd.concat([pd.Series([start_balance]), equity.reset_index(drop=True)])
        out["max_drawdown"] = float((curve / curve.cummax() - 1).min())
        rets = curve.pct_change().dropna()
        sd = rets.std()
        out["sharpe"] = float(rets.mean() / sd * math.sqrt(252)) if sd and sd > 0 else 0.0
        out["days"] = int(len(equity))
    if len(trades):
        wins, losses = trades[trades.pnl > 0], trades[trades.pnl <= 0]
        out["win_rate"] = len(wins) / len(trades)
        out["avg_win"] = float(wins.pnl.mean()) if len(wins) else 0.0
        out["avg_loss"] = float(losses.pnl.mean()) if len(losses) else 0.0
        lost = -losses.pnl.sum()
        out["profit_factor"] = float(wins.pnl.sum() / lost) if lost > 0 else float("inf")
        out["total_pnl"] = float(trades.pnl.sum())
        out["best"] = trades.loc[trades.pnl.idxmax()].to_dict()
        out["worst"] = trades.loc[trades.pnl.idxmin()].to_dict()
    return out


def describe(s: dict) -> str:
    if not s.get("trades"):
        return "No trades."
    pf = s["profit_factor"]
    return "\n".join([
        f"Trades: {s['trades']} over {s.get('days', '?')} trading days",
        f"Total return: {s.get('total_return', 0):+.2%}  (P&L ${s['total_pnl']:,.0f})",
        f"Win rate: {s['win_rate']:.0%}",
        f"Average win: ${s['avg_win']:,.0f} | average loss: ${s['avg_loss']:,.0f}",
        f"Profit factor (total won / total lost): {'n/a' if pf == float('inf') else f'{pf:.2f}'}",
        f"Max drawdown (worst drop from a peak): {s.get('max_drawdown', 0):.2%}",
        f"Sharpe ratio (return per unit of bumpiness, yearly): {s.get('sharpe', 0):.2f}",
    ])


# ------------------------------------------------------------ stats command
def report_live() -> str:
    """Everything since launch, from the trade log. `python -m day_trader.stats`"""
    from . import config as C
    from . import journal
    trades, days = journal.trades_df(), journal.days_df()
    if days.empty and trades.empty:
        return "No trading days recorded yet."
    lines = ["BOT #2 (DAY TRADER) - STATS SINCE LAUNCH", "=" * 44]
    if not days.empty:
        start = float(days.start_equity.iloc[0])
        eq = pd.Series(days.end_equity.values, index=days.day)
        s = summarize(trades, eq, start)
        lines += [f"Launched: {days.day.iloc[0]} | days traded: {len(days)}",
                  f"Account: ${start:,.0f} -> ${eq.iloc[-1]:,.0f}"]
    else:
        s = summarize(trades, pd.Series(dtype=float), C.STARTING_BALANCE)
    lines += [describe(s)]
    if not trades.empty:
        def table(col, title):
            out = ["", title]
            for k, g in trades.groupby(col):
                out.append(f"  {k:24s} {len(g):4d} trades | win {(g.pnl > 0).mean():4.0%} | "
                           f"P&L ${g.pnl.sum():>10,.0f}")
            return out
        lines += table("strategy", "P&L BY STRATEGY")
        lines += table("status", "PROVEN vs EXPERIMENTAL")
        lines += table("asset_class", "P&L BY TYPE (stock / etf / option)")
        lines += ["", "LAST 10 TRADES"]
        for _, t in trades.tail(10).iterrows():
            lines.append(f"  {t.day} {t.symbol:6s} {t.strategy:16s} {t.qty:>6g} @ {t.entry_price:.2f}"
                         f" -> {t.exit_price:.2f} ({t.exit_reason}) ${t.pnl:,.0f}")
    pend = journal.suggestions()
    if pend:
        lines += ["", f"SETTINGS SUGGESTIONS WAITING FOR YOU: {len(pend)}"]
        lines += [f"  #{p['id']} {p['setting']}: {p['current']} -> {p['suggested']} ({p['why']})"
                  for p in pend]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report_live())
