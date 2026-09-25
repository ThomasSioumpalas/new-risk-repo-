# KRI forecast: reported_phishing_bypassing_filter

**Source:** `examples/halcyon/data/kri_phishing_bypass.csv` (column `reported_phishing_bypassing_filter`) &middot; **Discount factor:** 0.9
&middot; **Warm-up:** 12 periods &middot; **Horizon:** 1.0 period(s)
&middot; **Threshold:** > 20

## History

<details>
<summary>44 periods</summary>

| Period | Count |
|---|---|
| 2023-01 | 9 |
| 2023-02 | 9 |
| 2023-03 | 6 |
| 2023-04 | 9 |
| 2023-05 | 4 |
| 2023-06 | 6 |
| 2023-07 | 8 |
| 2023-08 | 9 |
| 2023-09 | 8 |
| 2023-10 | 13 |
| 2023-11 | 4 |
| 2023-12 | 6 |
| 2024-01 | 8 |
| 2024-02 | 14 |
| 2024-03 | 7 |
| 2024-04 | 5 |
| 2024-05 | 9 |
| 2024-06 | 6 |
| 2024-07 | 15 |
| 2024-08 | 11 |
| 2024-09 | 11 |
| 2024-10 | 14 |
| 2024-11 | 6 |
| 2024-12 | 8 |
| 2025-01 | 12 |
| 2025-02 | 7 |
| 2025-03 | 11 |
| 2025-04 | 16 |
| 2025-05 | 10 |
| 2025-06 | 8 |
| 2025-07 | 17 |
| 2025-08 | 13 |
| 2025-09 | 11 |
| 2025-10 | 12 |
| 2025-11 | 16 |
| 2025-12 | 10 |
| 2026-01 | 19 |
| 2026-02 | 18 |
| 2026-03 | 14 |
| 2026-04 | 12 |
| 2026-05 | 12 |
| 2026-06 | 16 |
| 2026-07 | 18 |
| 2026-08 | 24 |

</details>

## Forecast for the next 1.0 period(s)

| | |
|---|---|
| Effective (discounted) events | 144.38 |
| Effective (discounted) exposure | 9.90 periods |
| Posterior mean rate | 14.630 per period |
| Rate 90% credible interval | 12.690 – 16.685 |
| Predictive mean count | 14.63 |
| Predictive 50% interval | 12 – 17 |
| Predictive 90% interval | 8 – 22 |
| P(count > 20) | 7.8% |

## Trend test

Statistically significant increasing trend: rate × 1.022 per period (p = 1.45e-09).

| | |
|---|---|
| Periods | 44 |
| Rate ratio per period | 1.022 |
| 95% CI | 1.015 – 1.030 |
| Likelihood-ratio statistic | 36.60 |
| p-value | 0.0000 |

## Backtest (rolling-origin, one-step-ahead)

32 periods evaluated after the 12-period warm-up.

| Interval | Nominal coverage | Observed coverage |
|---|---|---|
| 50% | 50% | 56.2% |
| 90% | 90% | 81.2% |

Mean log predictive score: -2.843 (a proper scoring rule; less
negative is better; useful only to compare models on the same data).

<details>
<summary>Per-period backtest detail</summary>

| Period | Observed | Predicted mean | 90% interval | Inside 50% | Inside 90% | Log score |
|---|---|---|---|---|---|---|
| 12 | 8 | 7.57 | 3 – 13 | ✅ | ✅ | -2.05 |
| 13 | 14 | 7.64 | 3 – 13 | ❌ | ❌ | -4.17 |
| 14 | 7 | 8.47 | 4 – 14 | ✅ | ✅ | -2.08 |
| 15 | 5 | 8.29 | 4 – 14 | ❌ | ✅ | -2.47 |
| 16 | 9 | 7.89 | 3 – 13 | ✅ | ✅ | -2.16 |
| 17 | 6 | 8.03 | 3 – 13 | ✅ | ✅ | -2.13 |
| 18 | 15 | 7.80 | 3 – 13 | ❌ | ❌ | -4.65 |
| 19 | 11 | 8.64 | 4 – 14 | ✅ | ✅ | -2.46 |
| 20 | 11 | 8.91 | 4 – 14 | ✅ | ✅ | -2.39 |
| 21 | 14 | 9.15 | 4 – 15 | ❌ | ✅ | -3.30 |
| 22 | 6 | 9.70 | 5 – 15 | ❌ | ✅ | -2.61 |
| 23 | 8 | 9.30 | 4 – 15 | ✅ | ✅ | -2.10 |
| 24 | 12 | 9.16 | 4 – 15 | ❌ | ✅ | -2.59 |
| 25 | 7 | 9.47 | 5 – 15 | ✅ | ✅ | -2.27 |
| 26 | 11 | 9.21 | 4 – 15 | ✅ | ✅ | -2.33 |
| 27 | 16 | 9.41 | 4 – 15 | ❌ | ❌ | -4.08 |
| 28 | 10 | 10.11 | 5 – 16 | ✅ | ✅ | -2.13 |
| 29 | 8 | 10.10 | 5 – 16 | ✅ | ✅ | -2.22 |
| 30 | 17 | 9.89 | 5 – 16 | ❌ | ❌ | -4.29 |
| 31 | 13 | 10.63 | 5 – 17 | ✅ | ✅ | -2.49 |
| 32 | 11 | 10.88 | 6 – 17 | ✅ | ✅ | -2.18 |
| 33 | 12 | 10.90 | 6 – 17 | ✅ | ✅ | -2.27 |
| 34 | 16 | 11.02 | 6 – 17 | ❌ | ✅ | -3.26 |
| 35 | 10 | 11.53 | 6 – 18 | ✅ | ✅ | -2.22 |
| 36 | 19 | 11.38 | 6 – 18 | ❌ | ❌ | -4.36 |
| 37 | 18 | 12.17 | 7 – 18 | ❌ | ✅ | -3.53 |
| 38 | 14 | 12.76 | 7 – 19 | ✅ | ✅ | -2.35 |
| 39 | 12 | 12.90 | 7 – 19 | ✅ | ✅ | -2.24 |
| 40 | 12 | 12.81 | 7 – 19 | ✅ | ✅ | -2.24 |
| 41 | 16 | 12.73 | 7 – 19 | ❌ | ✅ | -2.72 |
| 42 | 18 | 13.07 | 7 – 20 | ❌ | ✅ | -3.18 |
| 43 | 24 | 13.57 | 8 – 20 | ❌ | ❌ | -5.49 |

</details>

## How to read this

This is a **probabilistic** forecast, not a point prediction. The count per period is modelled as Poisson
with a Gamma belief about its rate; a discount factor of 0.9 down-weights older periods by
`discount^age`, so the model adapts to a shifting rate (`1.0` means the rate is assumed stationary). The
predictive interval is wider than a plain Poisson interval because it also carries the *uncertainty about
the rate itself* (a negative-binomial predictive distribution). The 50% and 90% intervals are not
confidence intervals on a fixed number: they are ranges that should contain the actual outcome about 50% and
90% of the time, respectively, if the model is well calibrated. The backtest checks exactly that, by
re-forecasting every period from only the data before it and recording how often the outcome fell inside
each interval ("rolling-origin" evaluation, so no future data leaks into a forecast). Observed coverage
close to the nominal 50%/90% means the model's uncertainty is realistic; observed coverage well below
nominal means the intervals are too narrow (overconfident), and well above means they are too wide
(underconfident). The trend test is a separate question — whether the *rate itself* is moving over time —
and does not by itself change the forecast above unless the discount factor is also adjusted to track it.