"""
The safety lock.

Plain English: before the bot does anything, it checks that it is pointed at
Alpaca's PAPER (fake money) server. If anything looks like a real-money
setup, it refuses to start - unless you have deliberately set
ALLOW_LIVE_TRADING=true.

What counts as "looks live":
  - an Alpaca key starting with "AK" (live keys start with AK, paper keys with PK)
  - any Alpaca server address setting that isn't the paper server
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

PAPER_HOST = "paper-api.alpaca.markets"
# Settings people (or other tools) use to point Alpaca at a server.
URL_SETTINGS = ("APCA_API_BASE_URL", "ALPACA_BASE_URL", "DT_ALPACA_BASE_URL")


class LiveTradingBlocked(RuntimeError):
    """Raised when the bot detects a real-money setup and live trading isn't allowed."""


def _allowed(env: Mapping[str, str]) -> bool:
    return env.get("ALLOW_LIVE_TRADING", "false").strip().lower() in ("1", "true", "yes", "on")


def live_signs(env: Mapping[str, str]) -> list:
    """Every reason this setup looks like real money. Empty list = paper."""
    signs = []
    key = env.get("DT_ALPACA_API_KEY", "").strip()
    if key.upper().startswith("AK"):
        signs.append("the API key starts with 'AK', which means a LIVE (real-money) key")
    for name in URL_SETTINGS:
        url = env.get(name, "").strip()
        if url and PAPER_HOST not in url:
            signs.append(f"{name} points to {url}, which is not the paper server")
    return signs


def check(env: Optional[Mapping[str, str]] = None) -> str:
    """
    Returns "paper" or "live". Raises LiveTradingBlocked if the setup looks
    live and ALLOW_LIVE_TRADING isn't true.
    """
    env = os.environ if env is None else env
    signs = live_signs(env)
    if not signs:
        return "paper"
    if not _allowed(env):
        raise LiveTradingBlocked(
            "SAFETY LOCK: refusing to start because this looks like a REAL-MONEY setup:\n  - "
            + "\n  - ".join(signs)
            + "\nThis bot is paper-only. (To deliberately allow real money you would have to "
              "set ALLOW_LIVE_TRADING=true. Don't, unless you've decided to go live.)")
    return "live"


def verify_connected_paper(client, mode: str) -> None:
    """After connecting: double-check the client really talks to the paper server."""
    url = str(getattr(client, "_base_url", ""))
    on_paper = "paper" in url.lower()
    if mode == "paper" and not on_paper:
        raise LiveTradingBlocked(f"SAFETY LOCK: expected the paper server but connected to {url}.")
