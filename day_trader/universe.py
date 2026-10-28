"""
Fixed list of liquid stocks/ETFs used for backtests (and as a fallback
watchlist). The live bot's daily watchlist is built fresh each morning.
Copied from bot #1's list (S&P 100 + 13 big ETFs) so bot #1 is never imported.
"""
LARGE_CAPS = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMT", "AMZN",
    "AVGO", "AXP", "BA", "BAC", "BK", "BKNG", "BLK", "BMY", "BRK.B", "C",
    "CAT", "CL", "CMCSA", "COF", "COP", "COST", "CRM", "CSCO", "CVS", "CVX",
    "DE", "DHR", "DIS", "DUK", "EMR", "FDX", "GD", "GE", "GILD", "GM",
    "GOOGL", "GS", "HD", "HON", "IBM", "INTC", "INTU", "ISRG", "JNJ", "JPM",
    "KO", "LIN", "LLY", "LMT", "LOW", "MA", "MCD", "MDLZ", "MDT", "MET",
    "META", "MMM", "MO", "MRK", "MS", "MSFT", "NEE", "NFLX", "NKE", "NOW",
    "NVDA", "ORCL", "PEP", "PFE", "PG", "PLTR", "PM", "PYPL", "QCOM", "RTX",
    "SBUX", "SCHW", "SO", "SPG", "T", "TGT", "TMO", "TMUS", "TSLA", "TXN",
    "UBER", "UNH", "UNP", "UPS", "USB", "V", "VZ", "WFC", "WMT", "XOM",
]
ETFS = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI",
        "XLY", "XLP", "XLU", "SMH"]
UNIVERSE = LARGE_CAPS + ETFS


def in_play(daily, d, top_n=20, min_gap=0.02, min_price=5.0, min_adv=1_000_000,
            min_adv_dollar=20_000_000):
    """
    The day's "in play" stocks, knowable at 9:30am: liquid names that opened
    at least 2% above yesterday's close, biggest gaps first. Uses only the
    open price of day d plus earlier days - no peeking at the rest of the day.
    """
    import pandas as pd
    ts = pd.Timestamp(d)
    rows = []
    for sym, df in daily.items():
        if ts not in df.index:
            continue
        prior = df[df.index < ts].tail(20)
        if len(prior) < 10:
            continue
        prev_close = float(prior.close.iloc[-1])
        today_open = float(df.loc[ts, "open"])
        adv = float(prior.volume.mean())
        if (today_open < min_price or adv < min_adv
                or (prior.volume * prior.close).mean() < min_adv_dollar):
            continue
        gap = today_open / prev_close - 1
        if gap >= min_gap:
            rows.append((gap, sym))
    return [s for _, s in sorted(rows, reverse=True)[:top_n]]
