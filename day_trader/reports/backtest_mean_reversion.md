# Mean reversion walk-forward tests (2026-10-22): FAILED on both stock groups - OFF

## mr_big
```
mean_reversion on 'big' stocks | Practice: 2025-10-21 -> 2026-04-21 | Unseen: 2026-04-22 -> 2026-10-21
  baseline (current)               practice: -4.40% Sharpe -2.52 (355 trades) | unseen: -1.83% PF 0.90 (397 trades)
  fixed target 1x risk             practice: -4.85% Sharpe -3.63 (359 trades) | unseen: -2.32% PF 0.84 (399 trades)
  deeper drop (3%)                 practice: -1.80% Sharpe -2.26 (80 trades) | unseen: +2.02% PF 1.32 (119 trades)
  skip when SPY down >1%           practice: -3.19% Sharpe -2.05 (327 trades) | unseen: -2.58% PF 0.86 (383 trades)
  buy without waiting for the turn practice: -4.31% Sharpe -3.29 (269 trades) | unseen: -0.63% PF 0.95 (305 trades)
  60-minute lookback               practice: -2.56% Sharpe -1.24 (465 trades) | unseen: -2.96% PF 0.86 (496 trades)

Picked on practice months: 60-minute lookback
  [FAIL] made money on unseen months
  [FAIL] profit factor >= 1.1 on unseen months
  [FAIL] beat the baseline on unseen months
RESULT: FAILED - strategy stays OFF
```

## mr_inplay
```
mean_reversion on 'inplay' stocks | Practice: 2025-10-21 -> 2026-04-21 | Unseen: 2026-04-22 -> 2026-10-21
  baseline (current)               practice: -11.27% Sharpe -1.81 (1536 trades) | unseen: -12.49% PF 0.91 (1600 trades)
  fixed target 1x risk             practice: -8.71% Sharpe -1.93 (1581 trades) | unseen: -12.99% PF 0.89 (1672 trades)
  deeper drop (3%)                 practice: -8.36% Sharpe -1.34 (1157 trades) | unseen: -10.91% PF 0.91 (1257 trades)
  skip when SPY down >1%           practice: -11.76% Sharpe -1.91 (1517 trades) | unseen: -14.75% PF 0.89 (1596 trades)
  buy without waiting for the turn practice: -12.50% Sharpe -2.54 (1515 trades) | unseen: -24.32% PF 0.78 (1594 trades)
  60-minute lookback               practice: -3.99% Sharpe -0.72 (1512 trades) | unseen: -7.62% PF 0.94 (1491 trades)

Picked on practice months: 60-minute lookback
  [FAIL] made money on unseen months
  [FAIL] profit factor >= 1.1 on unseen months
  [PASS] beat the baseline on unseen months
RESULT: FAILED - strategy stays OFF
```
