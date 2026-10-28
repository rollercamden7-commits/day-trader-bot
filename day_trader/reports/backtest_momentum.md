# Momentum walk-forward tests (2026-10-22)

## Big stocks: FAILED
```
  baseline (current)               practice: -1.88% Sharpe -1.07 (486 trades) | unseen: -6.02% PF 0.75 (544 trades)
  target 1x risk                   practice: -2.53% Sharpe -1.87 (492 trades) | unseen: -6.14% PF 0.73 (549 trades)
  stop just under VWAP             practice: -7.42% Sharpe -2.72 (842 trades) | unseen: -11.84% PF 0.66 (850 trades)
  bigger volume surge (3x)         practice: +0.00% Sharpe  0.01 (178 trades) | unseen: -1.44% PF 0.82 (176 trades)
  mornings only (until 11:00)      practice: -1.21% Sharpe -1.09 (243 trades) | unseen: -3.58% PF 0.76 (317 trades)
  no VWAP rule                     practice: -1.88% Sharpe -1.07 (486 trades) | unseen: -6.02% PF 0.75 (544 trades)

Picked on practice months: bigger volume surge (3x)
  [FAIL] made money on unseen months
  [FAIL] profit factor >= 1.1 on unseen months
  [PASS] beat the baseline on unseen months
RESULT: FAILED - strategy stays OFF

[exited with code 0]
```

## In-play stocks: FAILED -> running as an EXPERIMENT with paper money (user's choice), baseline settings
```
  baseline (current)               practice: -0.92% Sharpe -0.45 (166 trades) | unseen: +3.06% PF 1.25 (133 trades)
  target 1x risk                   practice: -0.13% Sharpe -0.06 (166 trades) | unseen: +2.03% PF 1.20 (133 trades)
  stop just under VWAP             practice: -0.18% Sharpe -0.09 (122 trades) | unseen: +3.40% PF 1.42 (95 trades)
  bigger volume surge (3x)         practice: +0.57% Sharpe  0.56 (53 trades) | unseen: -0.26% PF 0.93 (43 trades)
  mornings only (until 11:00)      practice: -0.92% Sharpe -0.59 (65 trades) | unseen: +0.37% PF 1.08 (43 trades)
  no VWAP rule                     practice: -0.92% Sharpe -0.45 (166 trades) | unseen: +3.06% PF 1.25 (133 trades)

Picked on practice months: bigger volume surge (3x)
  [FAIL] made money on unseen months
  [FAIL] profit factor >= 1.1 on unseen months
  [FAIL] beat the baseline on unseen months
RESULT: FAILED - strategy stays OFF

[exited with code 0]
```

## Cost check (12 months, big stocks)
ORB: +1.9% at 0% cost, -3.0% at 0.02%, -8.8% at 0.05%. Momentum: +1.4% / -2.9% / -7.8%. No edge before costs.
