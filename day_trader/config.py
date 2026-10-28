"""
All of bot #2's settings in one place.

Plain-English rule: anything that limits risk lives here, and only YOU change
this file. The bot's daily review may SUGGEST changes, but it never edits it.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------- file paths
PKG_DIR = Path(__file__).resolve().parent          # .../day-trader-bot/day_trader
ENV_FILE = PKG_DIR / ".env"                        # your secret keys (never uploaded)
STATE_DIR = PKG_DIR / "state"                      # trade log, daily stats
DB_FILE = STATE_DIR / "trades.db"                  # every trade (SQLite database)

# Read day_trader/.env. Values already set (for example by GitHub Secrets) win.
load_dotenv(ENV_FILE, override=False)


def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# ------------------------------------------------------------- safety switches
ALLOW_LIVE_TRADING = _flag("ALLOW_LIVE_TRADING", False)   # real money: OFF
SHORTING_ENABLED = _flag("SHORTING_ENABLED", False)       # short selling: OFF

# ------------------------------------------------------------------ account
STARTING_BALANCE = 500_000.0

# ------------------------------------------------- hard risk limits (step 3)
DAILY_LOSS_LIMIT_PCT = 0.05      # stop for the day after losing 5% ($25,000)
MAX_POSITION_PCT = 0.10          # one position: at most 10% ($50,000)
MAX_OPTIONS_PCT = 0.20           # all options together: at most 20% ($100,000)
MAX_OPEN_POSITIONS = 10          # most positions held at once
RISK_PER_TRADE_PCT = 0.005       # entry-to-stop loss on one trade: 0.5% ($2,500)
OPTION_MAX_LOSS_PER_TRADE_PCT = 0.01  # one option trade: full cost at most 1% ($5,000)
MAX_TOTAL_EXPOSURE_PCT = 1.00    # never hold more than the cash we have (no margin)
MAX_TRADES_PER_DAY = 100         # round trips (a buy and its matching sell = 1)
# If every open stop hit at once (options: lose their full cost), the day's loss
# must still stay under the daily limit. Safer, but limits options to ~$25k total.
OPEN_RISK_MUST_FIT_DAILY_LIMIT = True

# If no fresh price data / broker reply for this long, stop opening new trades.
DATA_STALE_SECONDS = 30
BROKER_STALE_SECONDS = 60

# --------------------------------------------------- times (US Eastern time)
WATCHLIST_TIME = (8, 30)         # build today's watchlist
NO_NEW_OPTIONS_AFTER = (15, 0)   # no new 0DTE options after 3:00pm
NO_NEW_STOCKS_AFTER = (15, 45)   # no new stock/ETF trades after 3:45pm
FLATTEN_AT = (15, 55)            # close everything by 3:55pm

# ------------------------------------------------- only trade liquid names
MIN_PRICE = 5.00                 # share price at least $5
MIN_AVG_DAILY_VOLUME = 1_000_000 # shares traded per day (20-day average)
MIN_AVG_DOLLAR_VOLUME = 20_000_000
MIN_OPTION_OPEN_INTEREST = 500
MAX_OPTION_SPREAD_PCT = 0.05     # bid-ask gap at most 5% of the option's price...
MAX_OPTION_SPREAD_ABS = 0.15     # ...and at most $0.15

# ------------------------------------------------------ strategies on / off
STRATEGIES_ENABLED = {
    "opening_range_breakout": False,  # OFF: failed walk-forward test 2026-10-22
    "momentum": True,                 # EXPERIMENT (see STRATEGY_STATUS)
    "mean_reversion": False,          # OFF: failed walk-forward test (both stock groups) 2026-10-22
    "news": False,                    # OFF: failed walk-forward test 2026-10-22 (+7% practice, -4% unseen)
}
# "proven" = passed the walk-forward test. "experimental" = failed it but you chose
# to paper-trade it anyway; reported separately so it can't blur the proven stats.
STRATEGY_STATUS = {
    "momentum": "experimental",       # your choice 2026-10-22: failed test, unseen months +3.1%
}
# Which stocks each strategy scans: "inplay" = the morning's top-20 gap-ups,
# "big" = the 113 large stocks/ETFs.
STRATEGY_UNIVERSE = {
    "opening_range_breakout": "big",
    "momentum": "inplay",
}

OPTIONS_ENABLED = True

# --------------------------------------------------------------- data feed
DATA_FEED = os.environ.get("DT_DATA_FEED", "iex")  # free feed; "sip" needs the $99/mo plan
