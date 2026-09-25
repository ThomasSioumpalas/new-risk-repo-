"""Conjugate Bayesian models for counts and proportions.

Two conjugate pairs cover almost every data source a risk function has:

* **Gamma-Poisson** for event *rates*, such as incidents per year. The prior is
  expert opinion, or Jeffreys when there is none. The data is ``k`` events in
  ``t`` years of exposure. The posterior is ``Gamma(a + k, b + t)``. The
  posterior mean is a *credibility-weighted* average of the prior mean and the
  observed rate, with weight ``Z = t / (b + t)`` on the data. This is the
  Bühlmann credibility result familiar from actuarial science, and it answers
  "how much did the data move us away from expert opinion?".
* **Beta-Binomial** for *proportions*, such as the operating rate of a control
  from test samples, or phishing click rates.

The formulas are closed-form, so every number can be recomputed with a
calculator. That is a deliberate choice over opaque numerical fitting.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import optimize, stats


@dataclass(frozen=True)
class GammaPosterior:
    """Gamma(shape, rate) belief about an event rate (events per unit exposure)."""

    shape: float
    rate: float
    prior_shape: float
    prior_rate: float
    events: int
    exposure: float

    @property
    def mean(self) -> float:
        return self.shape / self.rate

    def interval(self, level: float = 0.90) -> tuple[float, float]:
        tail = (1 - level) / 2
        dist = stats.gamma(a=self.shape, scale=1 / self.rate)
        return float(dist.ppf(tail)), float(dist.ppf(1 - tail))

    @property
    def credibility_weight(self) -> float:
        """Weight Z of the observed rate in the posterior mean (0 = prior only, 1 = data only)."""
        return self.exposure / (self.prior_rate + self.exposure)

    @property
    def observed_rate(self) -> float:
        return self.events / self.exposure

    @property
    def prior_mean(self) -> float | None:
        return self.prior_shape / self.prior_rate if self.prior_rate > 0 else None

    def predictive(self, horizon: float = 1.0) -> NegativeBinomialPredictive:
        """Posterior predictive count over ``horizon`` exposure units.

        Integrating Poisson(λ·h) over Gamma(a, b) gives a negative binomial with
        n = a and p = b / (b + h).
        """
        return NegativeBinomialPredictive(n=self.shape, p=self.rate / (self.rate + horizon))


@dataclass(frozen=True)
class NegativeBinomialPredictive:
    n: float
    p: float

    @property
    def _dist(self) -> stats.rv_discrete:
        return stats.nbinom(self.n, self.p)

    @property
    def mean(self) -> float:
        return float(self._dist.mean())

    def interval(self, level: float = 0.90) -> tuple[int, int]:
        tail = (1 - level) / 2
        return int(self._dist.ppf(tail)), int(self._dist.ppf(1 - tail))

    def prob_at_least(self, k: int) -> float:
        """P(count >= k)."""
        return float(self._dist.sf(k - 1))

    def pmf(self, k: int) -> float:
        return float(self._dist.pmf(k))

    def cdf(self, k: int) -> float:
        return float(self._dist.cdf(k))


def gamma_poisson_update(
    events: int, exposure: float, prior_shape: float = 0.5, prior_rate: float = 0.0
) -> GammaPosterior:
    """Update a Gamma prior with ``events`` observed over ``exposure`` units."""
    if events < 0 or exposure <= 0:
        raise ValueError("events must be >= 0 and exposure > 0")
    if prior_shape <= 0 or prior_rate < 0:
        raise ValueError("invalid Gamma prior")
    return GammaPosterior(
        shape=prior_shape + events,
        rate=prior_rate + exposure,
        prior_shape=prior_shape,
        prior_rate=prior_rate,
        events=events,
        exposure=exposure,
    )


def fit_gamma_to_interval(low: float, high: float, confidence: float = 0.90) -> tuple[float, float]:
    """Find Gamma(shape, rate) whose central ``confidence`` interval is [low, high].

    The ratio of two Gamma quantiles depends only on the shape, and it decreases
    monotonically as the shape grows. So the shape is found by a
    one-dimensional root search, and the rate then follows by scaling.
    """
    if not 0 < low < high:
        raise ValueError("require 0 < low < high")
    tail = (1 - confidence) / 2
    target = high / low

    def ratio_gap(log_shape: float) -> float:
        a = float(np.exp(log_shape))
        return float(stats.gamma.ppf(1 - tail, a) / stats.gamma.ppf(tail, a)) - target

    # Very wide intervals need small shapes; very narrow ones need large shapes.
    lo_bound, hi_bound = np.log(0.02), np.log(1e6)
    if ratio_gap(hi_bound) > 0:
        raise ValueError("interval too narrow to represent as a Gamma distribution")
    if ratio_gap(lo_bound) < 0:
        raise ValueError("interval too wide to represent as a Gamma distribution")
    log_shape = optimize.brentq(ratio_gap, lo_bound, hi_bound, xtol=1e-10)
    shape = float(np.exp(log_shape))
    rate = float(stats.gamma.ppf(tail, shape)) / low
    return shape, rate


@dataclass(frozen=True)
class BetaPosterior:
    """Beta(alpha, beta) belief about a proportion."""

    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    def interval(self, level: float = 0.90) -> tuple[float, float]:
        tail = (1 - level) / 2
        dist = stats.beta(self.alpha, self.beta)
        return float(dist.ppf(tail)), float(dist.ppf(1 - tail))

    def prob_below(self, x: float) -> float:
        return float(stats.beta.cdf(x, self.alpha, self.beta))

    def prob_above(self, x: float) -> float:
        return float(stats.beta.sf(x, self.alpha, self.beta))

    def upper_bound(self, confidence: float) -> float:
        """One-sided credible upper bound."""
        return float(stats.beta.ppf(confidence, self.alpha, self.beta))


def beta_binomial_update(
    successes: int, trials: int, prior_alpha: float = 1.0, prior_beta: float = 1.0
) -> BetaPosterior:
    if not 0 <= successes <= trials:
        raise ValueError("require 0 <= successes <= trials")
    if prior_alpha <= 0 or prior_beta <= 0:
        raise ValueError("invalid Beta prior")
    return BetaPosterior(alpha=prior_alpha + successes, beta=prior_beta + trials - successes)


def clopper_pearson_upper(k: int, n: int, confidence: float = 0.95) -> float:
    """Exact one-sided upper confidence bound for a binomial proportion.

    This is the classical audit-sampling bound. With 0 deviations in 25 samples
    and 95 % confidence it gives ≈ 0.113, so "the deviation rate is below about
    11 %". Beyond that, 0 exceptions proves nothing.
    """
    if not 0 <= k <= n or n <= 0:
        raise ValueError("require 0 <= k <= n, n > 0")
    if k == n:
        return 1.0
    return float(stats.beta.ppf(confidence, k + 1, n - k))


def clopper_pearson_interval(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """Exact two-sided Clopper-Pearson interval."""
    if not 0 <= k <= n or n <= 0:
        raise ValueError("require 0 <= k <= n, n > 0")
    tail = (1 - level) / 2
    lower = 0.0 if k == 0 else float(stats.beta.ppf(tail, k, n - k + 1))
    upper = 1.0 if k == n else float(stats.beta.ppf(1 - tail, k + 1, n - k))
    return lower, upper
