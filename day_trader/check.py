"""
Connection check (read only - never places orders).

    python -m day_trader.check
"""
from __future__ import annotations

from . import config
from .broker import Broker


def main() -> None:
    b = Broker(dry_run=True)
    a, clock = b.account(), b.clock()
    print(f"Safety lock: OK - mode = {b.mode.upper()}")
    print(f"Account ...{str(a.account_number)[-4:]} | status {a.status.value} | "
          f"equity ${float(a.equity):,.2f} | cash ${float(a.cash):,.2f}")
    print(f"Options level: {a.options_trading_level} | open positions: {len(b.positions())} | "
          f"open orders: {len(b.open_orders())}")
    print(f"Market is {'OPEN' if clock.is_open else 'closed'} "
          f"(next open {clock.next_open:%a %b %d %I:%M %p} ET)")
    print(f"Live trading allowed: {config.ALLOW_LIVE_TRADING} | shorting: {config.SHORTING_ENABLED}")


if __name__ == "__main__":
    main()
