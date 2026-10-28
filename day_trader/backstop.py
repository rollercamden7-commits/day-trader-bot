"""
3:50pm SAFETY BACKSTOP. Runs separately from the engine. If anything is
still open between 3:50 and 4:10pm Eastern, it closes everything and emails
you. Outside that window it does nothing (GitHub runs it twice a day because
its clock ignores daylight saving - the wrong-season run just exits).

    python -m day_trader.backstop
"""
from __future__ import annotations

import sys
from datetime import datetime, time

from .broker import Broker
from .emailer import send_email
from .risk import ET


def main() -> int:
    now = datetime.now(ET)
    if not (time(15, 50) <= now.time() <= time(16, 10)):
        print(f"{now:%H:%M} ET is outside the 3:50-4:10pm window. Nothing to do.")
        return 0
    b = Broker()
    pos, orders = b.positions(), b.open_orders()
    if not pos and not orders:
        print("Account is flat. Nothing to do.")
        return 0
    names = ", ".join(p.symbol for p in pos)
    print(f"Still open at {now:%H:%M}: {len(pos)} position(s) [{names}], {len(orders)} order(s). Closing.")
    result = b.flatten_everything()
    send_email("BACKSTOP closed positions at 3:50pm",
               f"At {now:%H:%M} ET the account still had {len(pos)} position(s) ({names}) and "
               f"{len(orders)} open order(s). The engine should have closed these at 3:55pm "
               f"(or may not be running). The backstop closed everything.\n\nResult: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
