"""
The trade log: every trade, every day's result, and every settings
suggestion, kept in one small database file (state/trades.db, SQLite).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import pandas as pd

from . import config as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT, strategy TEXT, status TEXT, symbol TEXT, asset_class TEXT, side TEXT,
    qty REAL, entry_time TEXT, entry_price REAL, stop REAL, target REAL,
    exit_time TEXT, exit_price REAL, pnl REAL, pnl_pct REAL, exit_reason TEXT,
    reason TEXT, order_id TEXT, mode TEXT
);
CREATE TABLE IF NOT EXISTS days (
    day TEXT PRIMARY KEY, start_equity REAL, end_equity REAL, pnl REAL, pnl_pct REAL,
    trades INTEGER, limits_hit TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, setting TEXT, current TEXT,
    suggested TEXT, why TEXT, status TEXT DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, time TEXT, strategy TEXT, symbol TEXT,
    action TEXT, detail TEXT
);
"""


@contextmanager
def db(path=None):
    path = path or C.DB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def status_of(strategy: str) -> str:
    return C.STRATEGY_STATUS.get(strategy, "proven")


def open_trade(*, day, strategy, symbol, asset_class, side, qty, entry_time, entry_price,
               stop, target, reason, order_id, mode, path=None) -> int:
    with db(path) as con:
        cur = con.execute(
            "INSERT INTO trades (day, strategy, status, symbol, asset_class, side, qty, entry_time,"
            " entry_price, stop, target, reason, order_id, mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(day), strategy, status_of(strategy), symbol, asset_class, side, qty,
             str(entry_time), entry_price, stop, target, reason, order_id, mode))
        return cur.lastrowid


def close_trade(trade_id: int, exit_time, exit_price: float, exit_reason: str, path=None):
    with db(path) as con:
        t = con.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        mult = 100 if t["asset_class"] == "option" else 1
        sign = 1 if t["side"] == "buy" else -1
        pnl = sign * (exit_price - t["entry_price"]) * t["qty"] * mult
        con.execute("UPDATE trades SET exit_time=?, exit_price=?, pnl=?, pnl_pct=?, exit_reason=? "
                    "WHERE id=?", (str(exit_time), exit_price, round(pnl, 2),
                                   round(sign * (exit_price / t["entry_price"] - 1), 5),
                                   exit_reason, trade_id))
        return pnl


def open_trades(path=None) -> list:
    with db(path) as con:
        return [dict(r) for r in con.execute("SELECT * FROM trades WHERE exit_time IS NULL")]


def trades_df(path=None, day: Optional[str] = None) -> pd.DataFrame:
    with db(path) as con:
        q, args = "SELECT * FROM trades WHERE exit_time IS NOT NULL", ()
        if day:
            q, args = q + " AND day=?", (day,)
        return pd.read_sql_query(q, con, params=args)


def record_day(day, start_equity, end_equity, trades, limits_hit, notes="", path=None):
    with db(path) as con:
        pnl = end_equity - start_equity
        con.execute("INSERT OR REPLACE INTO days VALUES (?,?,?,?,?,?,?,?)",
                    (str(day), start_equity, end_equity, round(pnl, 2),
                     round(pnl / start_equity, 5) if start_equity else 0, trades,
                     json.dumps(limits_hit), notes))


def days_df(path=None) -> pd.DataFrame:
    with db(path) as con:
        return pd.read_sql_query("SELECT * FROM days ORDER BY day", con)


def log_signal(day, time, strategy, symbol, action, detail, path=None):
    """Every signal and what happened to it (traded, rejected, would-trade)."""
    with db(path) as con:
        con.execute("INSERT INTO signals (day, time, strategy, symbol, action, detail) "
                    "VALUES (?,?,?,?,?,?)", (str(day), str(time), strategy, symbol, action, detail))


def add_suggestion(day, setting, current, suggested, why, path=None):
    with db(path) as con:
        con.execute("INSERT INTO suggestions (day, setting, current, suggested, why) "
                    "VALUES (?,?,?,?,?)", (str(day), setting, str(current), str(suggested), why))


def suggestions(status="pending", path=None) -> list:
    with db(path) as con:
        return [dict(r) for r in con.execute("SELECT * FROM suggestions WHERE status=?", (status,))]


def update_entry(trade_id: int, entry_price: float, qty: float, entry_time, path=None):
    with db(path) as con:
        con.execute("UPDATE trades SET entry_price=?, qty=?, entry_time=? WHERE id=?",
                    (entry_price, qty, str(entry_time), trade_id))


def cancel_trade(trade_id: int, why: str, path=None):
    """Entry never filled: remove it from open trades."""
    with db(path) as con:
        con.execute("UPDATE trades SET exit_time=entry_time, exit_price=entry_price, pnl=0, "
                    "pnl_pct=0, exit_reason=? WHERE id=?", (f"not filled: {why}", trade_id))


def signals_today(day, path=None) -> list:
    with db(path) as con:
        return [dict(r) for r in con.execute("SELECT * FROM signals WHERE day=?", (str(day),))]
