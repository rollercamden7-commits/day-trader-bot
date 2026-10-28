#!/bin/zsh
# Watch-only day on this Mac: live prices, logs what it WOULD trade, places NO orders.
# Keeps the Mac awake while it runs. Log: day_trader/logs/watch_<date>.log
cd "$(dirname "$0")/.."
LOG="day_trader/logs/watch_$(date +%F).log"
export PYTHONWARNINGS=ignore
nohup caffeinate -dims .venv/bin/python -u -m day_trader.engine --dry-run >> "$LOG" 2>&1 &
echo "Watch-only run started (process $!). Follow along with:  tail -f $LOG"
