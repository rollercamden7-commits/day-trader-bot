# Backtest: orb

Period: 2025-10-22 to 2026-10-21 | starting balance $500,000

```
Trades: 1071 over 251 trading days
Total return: -8.81%  (P&L $-44,048)
Win rate: 45%
Average win: $475 | average loss: $-468
Profit factor (total won / total lost): 0.84
Max drawdown (worst drop from a peak): -8.94%
Sharpe ratio (return per unit of bumpiness, yearly): -1.74
```

For comparison, simply holding SPY over the same period: +15.05%

## By exit reason

| Exit | Trades | P&L |
|---|---|---|
| end of day | 794 | $89,143 |
| stop-loss | 250 | $-170,144 |
| target | 27 | $36,953 |

## By month

| Month | Trades | Win rate | P&L |
|---|---|---|---|
| 2025-10 | 37 | 27% | $-5,451 |
| 2025-11 | 105 | 46% | $-11,670 |
| 2025-12 | 78 | 44% | $-1,080 |
| 2026-01 | 148 | 51% | $-192 |
| 2026-02 | 79 | 44% | $-77 |
| 2026-03 | 75 | 47% | $923 |
| 2026-04 | 92 | 49% | $901 |
| 2026-05 | 75 | 48% | $3,569 |
| 2026-06 | 101 | 35% | $-12,360 |
| 2026-07 | 71 | 41% | $-6,141 |
| 2026-08 | 58 | 50% | $-1,791 |
| 2026-09 | 80 | 49% | $-2,161 |
| 2026-10 | 72 | 47% | $-8,519 |

Trades per day: 4.3 on average

## Walk-forward test (2026-10-22): FAILED - strategy switched OFF

```
Practice: 2025-10-21 -> 2026-04-21 | Unseen: 2026-04-22 -> 2026-10-21
  baseline (current)               practice: -2.27% Sharpe -0.78 (585 trades) | unseen: -6.67% PF 0.75 (490 trades)
  stop at middle of range          practice: -3.12% Sharpe -1.36 (631 trades) | unseen: -4.28% PF 0.83 (527 trades)
  30-minute range                  practice: -1.80% Sharpe -0.72 (447 trades) | unseen: -8.01% PF 0.62 (400 trades)
  only when SPY also breaks out    practice: +0.45% Sharpe  0.22 (368 trades) | unseen: -4.55% PF 0.72 (296 trades)
  target 1x risk                   practice: -3.14% Sharpe -1.16 (596 trades) | unseen: -5.71% PF 0.79 (500 trades)
  middle stop + 1x target          practice: -3.42% Sharpe -1.94 (650 trades) | unseen: -5.15% PF 0.79 (551 trades)

Picked on practice months: only when SPY also breaks out
  [FAIL] made money on unseen months
  [FAIL] profit factor >= 1.1 on unseen months
  [PASS] beat the baseline on unseen months
RESULT: FAILED - strategy stays OFF
```
