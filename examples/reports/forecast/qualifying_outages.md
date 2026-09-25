# KRI forecast: qualifying_outages

**Source:** `examples/halcyon/data/wms_outages.csv` (column `qualifying_outages`) &middot; **Discount factor:** 1.0
&middot; **Warm-up:** 24 periods &middot; **Horizon:** 1.0 period(s)
&middot; **Threshold:** > 1

## History

<details>
<summary>60 periods</summary>

| Period | Count |
|---|---|
| 2021-01 | 0 |
| 2021-02 | 0 |
| 2021-03 | 1 |
| 2021-04 | 0 |
| 2021-05 | 0 |
| 2021-06 | 0 |
| 2021-07 | 0 |
| 2021-08 | 0 |
| 2021-09 | 0 |
| 2021-10 | 0 |
| 2021-11 | 1 |
| 2021-12 | 0 |
| 2022-01 | 0 |
| 2022-02 | 0 |
| 2022-03 | 0 |
| 2022-04 | 0 |
| 2022-05 | 0 |
| 2022-06 | 1 |
| 2022-07 | 0 |
| 2022-08 | 0 |
| 2022-09 | 0 |
| 2022-10 | 0 |
| 2022-11 | 0 |
| 2022-12 | 0 |
| 2023-01 | 1 |
| 2023-02 | 0 |
| 2023-03 | 0 |
| 2023-04 | 0 |
| 2023-05 | 0 |
| 2023-06 | 0 |
| 2023-07 | 0 |
| 2023-08 | 0 |
| 2023-09 | 1 |
| 2023-10 | 0 |
| 2023-11 | 0 |
| 2023-12 | 0 |
| 2024-01 | 0 |
| 2024-02 | 0 |
| 2024-03 | 0 |
| 2024-04 | 0 |
| 2024-05 | 0 |
| 2024-06 | 0 |
| 2024-07 | 0 |
| 2024-08 | 0 |
| 2024-09 | 0 |
| 2024-10 | 0 |
| 2024-11 | 0 |
| 2024-12 | 1 |
| 2025-01 | 0 |
| 2025-02 | 0 |
| 2025-03 | 0 |
| 2025-04 | 0 |
| 2025-05 | 0 |
| 2025-06 | 0 |
| 2025-07 | 1 |
| 2025-08 | 0 |
| 2025-09 | 0 |
| 2025-10 | 0 |
| 2025-11 | 0 |
| 2025-12 | 0 |

</details>

## Forecast for the next 1.0 period(s)

| | |
|---|---|
| Effective (discounted) events | 7.00 |
| Effective (discounted) exposure | 60.00 periods |
| Posterior mean rate | 0.125 per period |
| Rate 90% credible interval | 0.061 – 0.208 |
| Predictive mean count | 0.13 |
| Predictive 50% interval | 0 – 0 |
| Predictive 90% interval | 0 – 1 |
| P(count > 1) | 0.8% |

## Trend test

No significant trend detected (rate ratio 0.990 per period, p = 0.654).

| | |
|---|---|
| Periods | 60 |
| Rate ratio per period | 0.990 |
| 95% CI | 0.948 – 1.034 |
| Likelihood-ratio statistic | 0.20 |
| p-value | 0.6541 |

## Backtest (rolling-origin, one-step-ahead)

36 periods evaluated after the 24-period warm-up.

| Interval | Nominal coverage | Observed coverage |
|---|---|---|
| 50% | 50% | 88.9% |
| 90% | 90% | 100.0% |

Mean log predictive score: -0.368 (a proper scoring rule; less
negative is better; useful only to compare models on the same data).

<details>
<summary>Per-period backtest detail</summary>

| Period | Observed | Predicted mean | 90% interval | Inside 50% | Inside 90% | Log score |
|---|---|---|---|---|---|---|
| 24 | 1 | 0.15 | 0 – 1 | ❌ | ✅ | -2.11 |
| 25 | 0 | 0.18 | 0 – 1 | ✅ | ✅ | -0.18 |
| 26 | 0 | 0.17 | 0 – 1 | ✅ | ✅ | -0.17 |
| 27 | 0 | 0.17 | 0 – 1 | ✅ | ✅ | -0.16 |
| 28 | 0 | 0.16 | 0 – 1 | ✅ | ✅ | -0.16 |
| 29 | 0 | 0.16 | 0 – 1 | ✅ | ✅ | -0.15 |
| 30 | 0 | 0.15 | 0 – 1 | ✅ | ✅ | -0.15 |
| 31 | 0 | 0.15 | 0 – 1 | ✅ | ✅ | -0.14 |
| 32 | 1 | 0.14 | 0 – 1 | ❌ | ✅ | -2.13 |
| 33 | 0 | 0.17 | 0 – 1 | ✅ | ✅ | -0.16 |
| 34 | 0 | 0.16 | 0 – 1 | ✅ | ✅ | -0.16 |
| 35 | 0 | 0.16 | 0 – 1 | ✅ | ✅ | -0.15 |
| 36 | 0 | 0.15 | 0 – 1 | ✅ | ✅ | -0.15 |
| 37 | 0 | 0.15 | 0 – 1 | ✅ | ✅ | -0.15 |
| 38 | 0 | 0.14 | 0 – 1 | ✅ | ✅ | -0.14 |
| 39 | 0 | 0.14 | 0 – 1 | ✅ | ✅ | -0.14 |
| 40 | 0 | 0.14 | 0 – 1 | ✅ | ✅ | -0.14 |
| 41 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.13 |
| 42 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.13 |
| 43 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.13 |
| 44 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.12 |
| 45 | 0 | 0.12 | 0 – 1 | ✅ | ✅ | -0.12 |
| 46 | 0 | 0.12 | 0 – 1 | ✅ | ✅ | -0.12 |
| 47 | 1 | 0.12 | 0 – 1 | ❌ | ✅ | -2.28 |
| 48 | 0 | 0.14 | 0 – 1 | ✅ | ✅ | -0.13 |
| 49 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.13 |
| 50 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.13 |
| 51 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.13 |
| 52 | 0 | 0.12 | 0 – 1 | ✅ | ✅ | -0.12 |
| 53 | 0 | 0.12 | 0 – 1 | ✅ | ✅ | -0.12 |
| 54 | 1 | 0.12 | 0 – 1 | ❌ | ✅ | -2.25 |
| 55 | 0 | 0.14 | 0 – 1 | ✅ | ✅ | -0.14 |
| 56 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.13 |
| 57 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.13 |
| 58 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.13 |
| 59 | 0 | 0.13 | 0 – 1 | ✅ | ✅ | -0.13 |

</details>

## How to read this

This is a **probabilistic** forecast, not a point prediction. The count per period is modelled as Poisson
with a Gamma belief about its rate; a discount factor of 1.0 down-weights older periods by
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