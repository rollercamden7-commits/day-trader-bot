"""
KILL SWITCH: cancel every open order and close every position in bot #2's
account, right now. Bot #1's account is never touched.

    python -m day_trader.kill            do it
    python -m day_trader.kill --dry-run  only show what it would do
"""
from __future__ import annotations

import argparse
import sys

from . import config  # noqa: F401  (loads day_trader/.env)
from .broker import Broker
from .emailer import send_email


def main() -> int:
    parser = argparse.ArgumentParser(description="Bot #2 kill switch")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    broker = Broker(dry_run=args.dry_run)
    print("KILL SWITCH" + (" (dry run - nothing will be sent)" if args.dry_run else ""))
    result = broker.flatten_everything()
    print(result)
    if args.dry_run:
        return 0
    left = result["orders_left"] + result["positions_left"]
    status = "DONE - account is flat" if left == 0 else f"WARNING - {left} item(s) still open"
    print(status)
    send_email(f"KILL SWITCH used: {status}",
               f"Cancelled {result['orders_before']} order(s), closed "
               f"{result['positions_before']} position(s).\n"
               f"Still open afterwards: {result['orders_left']} order(s), "
               f"{result['positions_left']} position(s).")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
