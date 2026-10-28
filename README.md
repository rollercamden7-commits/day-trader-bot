# Day Trader (bot #2) — paper trading only

A rules-based (no AI) day-trading bot for a **paper** (fake money) Alpaca account.
It runs on GitHub Actions every market day. It refuses to start against a
real-money account unless `ALLOW_LIVE_TRADING=true` is set (it is not).

## Cheat sheet

| I want to... | Do this |
|---|---|
| **Stop everything right now** (kill switch) | Actions tab → **KILL SWITCH** → Run workflow → type `KILL`. Cancels all orders, closes all positions, emails you. |
| **Stop it trading from tomorrow** | Actions tab → **Trade (morning)** → `...` → Disable workflow. Same for **Trade (afternoon)**. |
| **Start it again** | Same place → Enable workflow (both Trade workflows). |
| **Health check** (account + test email) | Actions tab → **Health check** → Run workflow. |
| **See stats** | Actions tab → **Stats** → Run workflow → open the run → click the `stats` step. |
| **Run one day watch-only** (no orders) | Actions tab → Trade (morning) → Run workflow → mode `watch-only` (and the same for afternoon). |

## What happens each market day (Eastern time)

- ~8:50am (7:50am in winter): morning job starts and waits for the 9:30 open.
- 9:31am: picks today's top-20 "in play" stocks (big overnight gap, liquid).
- Every minute: looks for signals; every trade has a stop and target (bracket order).
- 12:30pm: morning job hands over to the afternoon job.
- 3:45pm: no new stock trades. 3:55pm: closes everything.
- 3:50pm: separate **backstop** job closes anything still open and emails you.
- After the close: recap email (P&L, win rate, best/worst trade, by strategy, limits hit, review).

## Safety limits

- Daily loss 5% → cancel all, close all, stop for the day, email immediately.
- Max 10% of the account per position, 20% in options, 10 open positions, 100 trades/day.
- No shorting. Stops opening trades if the price feed or broker connection drops.
- Email on any crash or failed job.

## Secrets (Settings → Secrets and variables → Actions)

`DT_ALPACA_API_KEY`, `DT_ALPACA_SECRET_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `EMAIL_TO`.
Never put keys in the code. Locally they live in `day_trader/.env`, which is git-ignored.

## Strategies

Settings are in `day_trader/config.py`. Only **momentum** (in-play stocks) is on, as an
**experiment**: it did not pass its walk-forward test (see `day_trader/reports/`).
The others are off because they failed their tests.

## On a computer

```
python -m day_trader.check            # health check (safe, read-only)
python -m day_trader.stats            # stats
python -m day_trader.kill             # kill switch
python -m unittest discover -s day_trader/tests -t .   # tests
```
