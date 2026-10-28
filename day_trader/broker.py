"""
Everything that talks to bot #2's own Alpaca paper account.

It uses DT_ALPACA_API_KEY / DT_ALPACA_SECRET_KEY - never bot #1's keys - so the
two bots' trades and P&L can't mix.

dry_run=True: orders are only printed ("WOULD ..."), never sent.
"""
from __future__ import annotations

import os
import time

from alpaca.trading.client import TradingClient

from . import config  # noqa: F401  (loads day_trader/.env)
from . import safety


class Broker:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.mode = safety.check()             # refuses to start on a live setup
        key = os.environ.get("DT_ALPACA_API_KEY", "").strip()
        secret = os.environ.get("DT_ALPACA_SECRET_KEY", "").strip()
        if not key or not secret:
            raise RuntimeError("Missing DT_ALPACA_API_KEY / DT_ALPACA_SECRET_KEY "
                               "(put them in day_trader/.env or GitHub Secrets).")
        self.client = TradingClient(key, secret, paper=(self.mode == "paper"))
        safety.verify_connected_paper(self.client, self.mode)

    # ------------------------------------------------------------ read only
    def account(self):
        return self.client.get_account()

    def clock(self):
        return self.client.get_clock()

    def positions(self):
        return self.client.get_all_positions()

    def open_orders(self):
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        return self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))

    # ------------------------------------------------------- emergency stop
    def flatten_everything(self, wait_seconds: int = 60) -> dict:
        """
        Cancel every open order and sell every position at market.
        Used by the kill switch, the daily loss limit, and the 3:55pm close.
        Returns what was still left afterwards (should be nothing).
        """
        before_orders, before_pos = len(self.open_orders()), len(self.positions())
        if self.dry_run:
            print(f"  WOULD CANCEL {before_orders} open order(s) and CLOSE "
                  f"{before_pos} position(s)")
            return {"orders": before_orders, "positions": before_pos, "dry_run": True}
        self.client.cancel_orders()
        self.client.close_all_positions(cancel_orders=True)
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if not self.positions() and not self.open_orders():
                break
            time.sleep(2)
        return {"orders_before": before_orders, "positions_before": before_pos,
                "orders_left": len(self.open_orders()), "positions_left": len(self.positions())}

    # ------------------------------------------------------------- orders
    def bracket_buy(self, symbol: str, qty: int, stop: float, target: float, client_id: str):
        """
        Market buy with BOTH a stop-loss and a profit target attached
        ("bracket order"). Both exits sit on Alpaca's servers the moment the
        buy fills, so they work even if the bot stops running. Day orders only.
        """
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (MarketOrderRequest, StopLossRequest,
                                             TakeProfitRequest)
        if self.dry_run:
            print(f"  WOULD BUY {qty} {symbol} | stop {stop:.2f} | target {target:.2f}")
            return None
        return self.client.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET, client_order_id=client_id,
            take_profit=TakeProfitRequest(limit_price=round(target, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop, 2))))

    def get_order(self, order_id: str, nested: bool = True):
        from alpaca.trading.requests import GetOrderByIdRequest
        return self.client.get_order_by_id(order_id, GetOrderByIdRequest(nested=nested))

    def wait_for_fill(self, order_id: str, seconds: int = 15):
        order = self.get_order(order_id)
        deadline = time.time() + seconds
        while order.status.value not in ("filled", "canceled", "expired", "rejected") \
                and time.time() < deadline:
            time.sleep(1)
            order = self.get_order(order_id)
        return order

    def exit_fill(self, order_id: str):
        """
        For a bracket order: has it exited, and how?
        Returns (price, time, reason) or None if still open.
        """
        parent = self.get_order(order_id)
        for leg in parent.legs or []:
            if leg.status.value == "filled":
                why = "target" if leg.order_type.value == "limit" else "stop-loss"
                return float(leg.filled_avg_price), leg.filled_at, why
        return None

    def last_sell_fill(self, symbol: str, after):
        """Most recent filled sell of `symbol` after a time (e.g. a close-out)."""
        from alpaca.trading.enums import OrderSide, QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        orders = self.client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.CLOSED, symbols=[symbol], after=after, nested=True, limit=100))
        fills = [leg for o in orders for leg in [o] + list(o.legs or [])
                 if leg.side.value == "sell" and leg.filled_at is not None]
        return max(fills, key=lambda o: o.filled_at) if fills else None
