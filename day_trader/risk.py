"""
The risk manager: every trade idea must pass through here before an order
is sent. It can say NO, or shrink the size. It can never make a trade bigger.

It also watches the whole account:
  - daily loss limit hit -> cancel everything, close everything, stop for the
    day, email you immediately
  - 3:55pm (or 5 minutes before an early close) -> close everything
  - data feed or broker connection stale -> no new trades until it's back

The checking logic here is pure math (no internet), so it can be tested
thoroughly. `enforce()` is the only part that acts, through the broker and
emailer it's given.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable, List, Optional
from zoneinfo import ZoneInfo

from . import config as C

ET = ZoneInfo("America/New_York")
REGULAR_CLOSE = time(16, 0)


# ====================================================================== inputs
@dataclass
class TradeIdea:
    """What a strategy wants to do. Entry, stop and target are REQUIRED."""
    symbol: str
    asset_class: str          # "stock", "etf" or "option"
    side: str                 # "buy" (long). "sell" = short selling a stock.
    strategy: str
    entry: Optional[float]    # expected entry price (per share / per option)
    stop: Optional[float]     # stop-loss price
    target: Optional[float]   # profit-target price
    reason: str = ""
    # Liquidity facts (filled in by the scanner)
    price: Optional[float] = None
    avg_daily_volume: Optional[float] = None
    avg_dollar_volume: Optional[float] = None
    open_interest: Optional[int] = None       # options only
    bid: Optional[float] = None               # options only
    ask: Optional[float] = None               # options only
    expires_today: bool = False               # options only (0DTE)


@dataclass
class Holding:
    symbol: str
    asset_class: str
    market_value: float       # current dollar value (positive)
    max_loss: Optional[float] = None  # $ lost if the stop hits (option: full value)


@dataclass
class Snapshot:
    """The account right now."""
    now: datetime                   # timezone-aware
    equity: float                   # account value now
    start_equity: float             # account value at the start of today
    holdings: List[Holding] = field(default_factory=list)
    pending_entries: int = 0        # entry orders sent but not filled yet
    session_close: time = REGULAR_CLOSE   # 13:00 on early-close days
    market_open: bool = True


@dataclass
class Decision:
    approved: bool
    qty: int = 0
    reasons: List[str] = field(default_factory=list)   # why rejected / shrunk
    max_loss: float = 0.0                              # $ at risk if the stop hits
    cost: float = 0.0

    def __str__(self):
        head = f"APPROVED qty={self.qty} cost=${self.cost:,.0f} max_loss=${self.max_loss:,.0f}" \
            if self.approved else "REJECTED"
        return head + ("" if not self.reasons else " | " + "; ".join(self.reasons))


# ================================================================= day state
@dataclass
class DayState:
    """What must survive a restart during the day. Resets every new day."""
    day: str
    trades_opened: int = 0
    halted: bool = False            # daily loss limit hit -> done for today
    halt_reason: str = ""
    flattened_eod: bool = False
    limits_hit: List[str] = field(default_factory=list)

    @classmethod
    def load(cls, today: date, path=None) -> "DayState":
        path = path or C.STATE_DIR / "day_state.json"
        if path.exists():
            data = json.loads(path.read_text())
            if data.get("day") == today.isoformat():
                return cls(**data)
        return cls(day=today.isoformat())

    def save(self, path=None):
        path = path or C.STATE_DIR / "day_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2) + "\n")


# ========================================================== connection health
class ConnectionHealth:
    """Tracks when we last heard from the price feed and from the broker."""

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(ET)):
        self.clock = clock
        self.last_data: Optional[datetime] = None
        self.last_broker_ok: Optional[datetime] = None
        self.broker_error: Optional[str] = None

    def data_tick(self):
        self.last_data = self.clock()

    def broker_ok(self):
        self.last_broker_ok = self.clock()
        self.broker_error = None

    def broker_failed(self, err: str):
        self.broker_error = err

    def problems(self) -> List[str]:
        now, out = self.clock(), []
        if self.last_data is None or (now - self.last_data).total_seconds() > C.DATA_STALE_SECONDS:
            out.append("price data feed is stale or disconnected")
        if self.broker_error:
            out.append(f"broker connection error: {self.broker_error}")
        elif self.last_broker_ok is None or \
                (now - self.last_broker_ok).total_seconds() > C.BROKER_STALE_SECONDS:
            out.append("no recent reply from the broker")
        return out


# ============================================================= the risk manager
def _shift(t: tuple, close: time) -> time:
    """Move a 4pm-based cutoff earlier on early-close days (e.g. 3:55pm -> 12:55pm)."""
    base = datetime.combine(date.today(), REGULAR_CLOSE)
    offset = base - datetime.combine(date.today(), time(*t))
    return (datetime.combine(date.today(), close) - offset).time()


class RiskManager:
    def __init__(self, state: DayState, health: Optional[ConnectionHealth] = None):
        self.state = state
        self.health = health

    # ------------------------------------------------------------- cutoffs
    @staticmethod
    def cutoffs(session_close: time) -> dict:
        return {"options": _shift(C.NO_NEW_OPTIONS_AFTER, session_close),
                "stocks": _shift(C.NO_NEW_STOCKS_AFTER, session_close),
                "flatten": _shift(C.FLATTEN_AT, session_close)}

    def must_flatten(self, snap: Snapshot) -> bool:
        return snap.now.astimezone(ET).time() >= self.cutoffs(snap.session_close)["flatten"]

    # ---------------------------------------------------------- daily loss
    @staticmethod
    def daily_limit(snap: Snapshot) -> float:
        return C.DAILY_LOSS_LIMIT_PCT * snap.start_equity

    @staticmethod
    def loss_today(snap: Snapshot) -> float:
        return max(0.0, snap.start_equity - snap.equity)

    def daily_loss_hit(self, snap: Snapshot) -> bool:
        return self.loss_today(snap) >= self.daily_limit(snap)

    # ----------------------------------------------------- check a trade
    def check(self, idea: TradeIdea, snap: Snapshot) -> Decision:
        no = lambda why: Decision(False, reasons=[why])
        now_t = snap.now.astimezone(ET).time()
        cut = self.cutoffs(snap.session_close)
        is_option = idea.asset_class == "option"

        # 1. Account-level stops
        if self.state.halted:
            return no(f"trading halted for today ({self.state.halt_reason})")
        if self.daily_loss_hit(snap):
            return no("daily loss limit reached")
        if not snap.market_open:
            return no("market is closed")
        if self.health is not None and self.health.problems():
            return no("connection problem: " + "; ".join(self.health.problems()))
        if self.state.trades_opened >= C.MAX_TRADES_PER_DAY:
            return no(f"daily trade cap reached ({C.MAX_TRADES_PER_DAY})")

        # 2. Time of day
        if now_t >= cut["flatten"]:
            return no("past the end-of-day close-out time")
        if is_option and now_t >= cut["options"]:
            return no(f"no new 0DTE options after {cut['options']:%H:%M} ET")
        if not is_option and now_t >= cut["stocks"]:
            return no(f"no new stock/ETF trades after {cut['stocks']:%H:%M} ET")

        # 3. Direction rules
        if idea.side not in ("buy", "sell"):
            return no(f"unknown side '{idea.side}'")
        if is_option and idea.side != "buy":
            return no("options: buying only (no selling/writing)")
        if idea.side == "sell" and not C.SHORTING_ENABLED:
            return no("short selling is turned off")
        if is_option and not C.OPTIONS_ENABLED:
            return no("options trading is turned off")
        if is_option and not idea.expires_today:
            return no("options must be same-day expiry (0DTE)")

        # 4. Entry, stop and target must all be set and make sense
        e, s, t = idea.entry, idea.stop, idea.target
        if not all(isinstance(x, (int, float)) and x > 0 for x in (e, s, t)):
            return no("entry, stop-loss and profit target must all be set before ordering")
        long = idea.side == "buy"
        if long and not (s < e < t):
            return no(f"for a buy, need stop < entry < target (got {s} / {e} / {t})")
        if not long and not (t < e < s):
            return no(f"for a short, need target < entry < stop (got {t} / {e} / {s})")

        # 5. Liquidity
        why = self._liquidity_problem(idea)
        if why:
            return no(why)

        # 6. Position count / duplicates
        held = {h.symbol for h in snap.holdings}
        if idea.symbol in held:
            return no(f"already holding {idea.symbol}")
        if len(snap.holdings) + snap.pending_entries >= C.MAX_OPEN_POSITIONS:
            return no(f"max open positions reached ({C.MAX_OPEN_POSITIONS})")

        # 7. Size it
        return self._size(idea, snap)

    def _liquidity_problem(self, idea: TradeIdea) -> Optional[str]:
        if idea.asset_class == "option":
            if idea.open_interest is None or idea.bid is None or idea.ask is None:
                return "missing option liquidity data (open interest / bid / ask)"
            if idea.open_interest < C.MIN_OPTION_OPEN_INTEREST:
                return f"open interest {idea.open_interest} < {C.MIN_OPTION_OPEN_INTEREST}"
            if idea.bid <= 0 or idea.ask < idea.bid:
                return "no valid bid/ask quote"
            mid, spread = (idea.bid + idea.ask) / 2, idea.ask - idea.bid
            if spread > C.MAX_OPTION_SPREAD_ABS or spread > C.MAX_OPTION_SPREAD_PCT * mid:
                return f"bid-ask spread too wide (${spread:.2f} on ${mid:.2f})"
            return None
        price = idea.price if idea.price is not None else idea.entry
        if idea.avg_daily_volume is None or idea.avg_dollar_volume is None:
            return "missing liquidity data (average volume)"
        if price < C.MIN_PRICE:
            return f"price ${price:.2f} below ${C.MIN_PRICE:.2f} minimum"
        if idea.avg_daily_volume < C.MIN_AVG_DAILY_VOLUME:
            return f"average volume {idea.avg_daily_volume:,.0f} below {C.MIN_AVG_DAILY_VOLUME:,}"
        if idea.avg_dollar_volume < C.MIN_AVG_DOLLAR_VOLUME:
            return f"average dollar volume ${idea.avg_dollar_volume:,.0f} too low"
        return None

    def _size(self, idea: TradeIdea, snap: Snapshot) -> Decision:
        eq, notes = snap.equity, []
        is_option = idea.asset_class == "option"
        gross = sum(h.market_value for h in snap.holdings)
        options_value = sum(h.market_value for h in snap.holdings if h.asset_class == "option")
        open_risk = sum(h.max_loss if h.max_loss is not None else h.market_value
                        for h in snap.holdings)
        # Worst case if EVERY open stop hit at once must still stay inside the daily limit.
        room = self.daily_limit(snap) - self.loss_today(snap) - open_risk

        if is_option:
            unit_cost = idea.ask * 100            # one contract = 100 options
            unit_risk = unit_cost                 # full cost treated as max loss
            risk_budget = C.OPTION_MAX_LOSS_PER_TRADE_PCT * eq
        else:
            unit_cost = idea.entry
            unit_risk = abs(idea.entry - idea.stop)
            risk_budget = C.RISK_PER_TRADE_PCT * eq

        dollar_caps = {
            "max position size (10%)": C.MAX_POSITION_PCT * eq,
            "no-margin cash limit": C.MAX_TOTAL_EXPOSURE_PCT * eq - gross,
        }
        if is_option:
            dollar_caps["options cap (20%)"] = C.MAX_OPTIONS_PCT * eq - options_value

        qty = math.floor(risk_budget / unit_risk)
        for name, cap in dollar_caps.items():
            allowed = math.floor(max(cap, 0) / unit_cost)
            if allowed < qty:
                qty = allowed
                notes.append(f"shrunk by {name}")
        allowed = math.floor(max(room, 0) / unit_risk) if C.OPEN_RISK_MUST_FIT_DAILY_LIMIT else qty
        if allowed < qty:
            qty = allowed
            notes.append("shrunk so all open stops together can't break the daily loss limit")

        if qty < 1:
            return Decision(False, reasons=notes + ["size works out to zero"])
        return Decision(True, qty=qty, reasons=notes,
                        max_loss=round(qty * unit_risk, 2), cost=round(qty * unit_cost, 2))

    def record_trade_opened(self):
        self.state.trades_opened += 1
        self.state.save()

    # --------------------------------------------------------- take action
    def enforce(self, snap: Snapshot, broker, send_email) -> Optional[str]:
        """
        Called every loop. Returns what it did (or None).
        broker must have flatten_everything(); send_email(subject, body).
        """
        if not self.state.halted and self.daily_loss_hit(snap):
            loss = self.loss_today(snap)
            self.state.halted = True
            self.state.halt_reason = (f"daily loss limit: down ${loss:,.0f} "
                                      f"({loss / snap.start_equity:.1%}) today")
            self.state.limits_hit.append(f"{snap.now:%H:%M} {self.state.halt_reason}")
            self.state.save()
            result = broker.flatten_everything()
            send_email("DAILY LOSS LIMIT HIT - all positions closed, trading stopped for today",
                       f"{self.state.halt_reason}.\n\nThe bot cancelled every order, closed every "
                       f"position, and will not trade again until tomorrow.\n\nResult: {result}")
            return "halted"
        if self.state.halted and snap.holdings:
            broker.flatten_everything()          # something survived: try again
            return "re-flattened after halt"
        if self.must_flatten(snap) and (not self.state.flattened_eod or snap.holdings):
            self.state.flattened_eod = True
            self.state.save()
            broker.flatten_everything()
            return "flattened end of day"
        return None
