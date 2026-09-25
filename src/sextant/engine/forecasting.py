"""Forecasting incident counts and key risk indicators (KRIs).

Forecasting here means **probabilistic** forecasting: a predictive
distribution with intervals that can be checked against what actually
happened. Point predictions are not the goal.

* **Model**: counts per period are Poisson with an unknown rate, and the rate
  has a Gamma belief. With a discount factor δ ≤ 1, an observation that is
  ``a`` periods old is down-weighted by ``δᵃ`` (a power prior, or exponential
  forgetting). This makes the forecast adapt when the threat landscape shifts,
  and δ is an explicit, documented assumption. δ = 1 means a stationary rate.
* **Predictive distribution**: negative binomial (Gamma-Poisson mixture). It is
  wider than a Poisson because the rate itself is uncertain.
* **Validation**: rolling-origin backtest. Each period is forecast using only
  the data before it, and the report states how often the outcome fell inside
  the 50 % and 90 % intervals. A calibrated model covers about 50 % and 90 %.
  It also reports the mean log predictive score (a proper scoring rule).
* **Trend test**: a Poisson log-linear regression with a likelihood-ratio test.
  It answers "is the incident rate increasing?", with an estimated rate ratio
  per period and its confidence interval.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict
from scipy import stats


class Forecast(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon: float
    discount: float
    effective_events: float
    effective_exposure: float
    rate_mean: float
    rate_interval_90: tuple[float, float]
    predictive_mean: float
    predictive_interval_50: tuple[int, int]
    predictive_interval_90: tuple[int, int]
    threshold: int | None
    prob_exceed_threshold: float | None


class BacktestRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    period: int
    observed: int
    predicted_mean: float
    interval_90: tuple[int, int]
    inside_50: bool
    inside_90: bool
    log_score: float


class BacktestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    periods_evaluated: int
    coverage_50: float
    coverage_90: float
    mean_log_score: float
    records: list[BacktestRecord]


class TrendTest(BaseModel):
    model_config = ConfigDict(frozen=True)

    periods: int
    rate_ratio_per_period: float
    rate_ratio_ci_95: tuple[float, float]
    likelihood_ratio_statistic: float
    p_value: float
    interpretation: str


def _discounted(counts: Sequence[int], exposures: Sequence[float], discount: float) -> tuple[float, float]:
    n = len(counts)
    weights = np.array([discount ** (n - 1 - i) for i in range(n)])
    return float(weights @ np.asarray(counts, float)), float(weights @ np.asarray(exposures, float))


def forecast_counts(
    counts: Sequence[int],
    exposures: Sequence[float] | None = None,
    *,
    discount: float = 1.0,
    prior_shape: float = 0.5,
    prior_rate: float = 0.0,
    horizon: float = 1.0,
    threshold: int | None = None,
) -> Forecast:
    """Forecast the count in the next ``horizon`` periods (period = one exposure unit)."""
    if not counts:
        raise ValueError("at least one observed period is required")
    if not 0 < discount <= 1:
        raise ValueError("discount must be in (0, 1]")
    exp = list(exposures) if exposures is not None else [1.0] * len(counts)
    if len(exp) != len(counts):
        raise ValueError("counts and exposures must have equal length")
    k_eff, t_eff = _discounted(counts, exp, discount)
    # Conjugate update with fractional (discounted) counts and exposure.
    shape, rate = prior_shape + k_eff, prior_rate + t_eff
    if rate <= 0:
        raise ValueError("posterior rate must be positive (add exposure or an informative prior)")
    rate_dist = stats.gamma(shape, scale=1 / rate)
    pred = stats.nbinom(shape, rate / (rate + horizon))
    return Forecast(
        horizon=horizon,
        discount=discount,
        effective_events=k_eff,
        effective_exposure=t_eff,
        rate_mean=shape / rate,
        rate_interval_90=(float(rate_dist.ppf(0.05)), float(rate_dist.ppf(0.95))),
        predictive_mean=float(pred.mean()),
        predictive_interval_50=(int(pred.ppf(0.25)), int(pred.ppf(0.75))),
        predictive_interval_90=(int(pred.ppf(0.05)), int(pred.ppf(0.95))),
        threshold=threshold,
        prob_exceed_threshold=float(pred.sf(threshold)) if threshold is not None else None,
    )


def backtest(
    counts: Sequence[int],
    exposures: Sequence[float] | None = None,
    *,
    warmup: int = 12,
    discount: float = 1.0,
    prior_shape: float = 0.5,
    prior_rate: float = 0.0,
) -> BacktestResult:
    """Rolling-origin evaluation of one-step-ahead predictive intervals."""
    exp = list(exposures) if exposures is not None else [1.0] * len(counts)
    if len(counts) <= warmup:
        raise ValueError("need more periods than the warm-up length")
    records = []
    for t in range(warmup, len(counts)):
        k_eff, t_eff = _discounted(counts[:t], exp[:t], discount)
        shape, rate = prior_shape + k_eff, prior_rate + t_eff
        pred = stats.nbinom(shape, rate / (rate + exp[t]))
        y = int(counts[t])
        lo50, hi50 = int(pred.ppf(0.25)), int(pred.ppf(0.75))
        lo90, hi90 = int(pred.ppf(0.05)), int(pred.ppf(0.95))
        records.append(
            BacktestRecord(
                period=t,
                observed=y,
                predicted_mean=float(pred.mean()),
                interval_90=(lo90, hi90),
                inside_50=lo50 <= y <= hi50,
                inside_90=lo90 <= y <= hi90,
                log_score=float(pred.logpmf(y)),
            )
        )
    m = len(records)
    return BacktestResult(
        periods_evaluated=m,
        coverage_50=sum(r.inside_50 for r in records) / m,
        coverage_90=sum(r.inside_90 for r in records) / m,
        mean_log_score=sum(r.log_score for r in records) / m,
        records=records,
    )


def poisson_trend_test(counts: Sequence[int], exposures: Sequence[float] | None = None) -> TrendTest:
    """Fit log E[yₜ] = log eₜ + β₀ + β₁·t by Newton-Raphson and test β₁ = 0 (likelihood ratio)."""
    y = np.asarray(counts, dtype=float)
    e = np.asarray(exposures if exposures is not None else [1.0] * len(counts), dtype=float)
    n = y.size
    if n < 3:
        raise ValueError("need at least three periods")
    if y.sum() == 0:
        raise ValueError("no events observed; a trend cannot be estimated")
    t = np.arange(n) - (n - 1) / 2
    X = np.column_stack([np.ones(n), t])
    beta = np.array([math.log(y.sum() / e.sum()), 0.0])
    for _ in range(100):
        mu = e * np.exp(X @ beta)
        grad = X.T @ (y - mu)
        hess = X.T @ (X * mu[:, None])
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    mu1 = e * np.exp(X @ beta)
    mu0 = e * (y.sum() / e.sum())
    ll1 = float(stats.poisson.logpmf(y, mu1).sum())
    ll0 = float(stats.poisson.logpmf(y, mu0).sum())
    lr = max(0.0, 2 * (ll1 - ll0))
    p = float(stats.chi2.sf(lr, df=1))
    cov = np.linalg.inv(X.T @ (X * mu1[:, None]))
    se = math.sqrt(cov[1, 1])
    rr = math.exp(beta[1])
    ci = (math.exp(beta[1] - 1.96 * se), math.exp(beta[1] + 1.96 * se))
    if p < 0.05:
        direction = "increasing" if rr > 1 else "decreasing"
        text = f"Statistically significant {direction} trend: rate × {rr:.3f} per period (p = {p:.3g})."
    else:
        text = f"No significant trend detected (rate ratio {rr:.3f} per period, p = {p:.3g})."
    return TrendTest(
        periods=n,
        rate_ratio_per_period=rr,
        rate_ratio_ci_95=ci,
        likelihood_ratio_statistic=lr,
        p_value=p,
        interpretation=text,
    )
