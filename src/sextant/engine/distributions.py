"""Probability distributions built from estimate specifications.

Every distribution is sampled by **inverse transform**: ``x = F⁻¹(u)`` with
``u ~ Uniform(0, 1)``. Using one sampling mechanism everywhere has three
advantages:

1. **Coupling.** The same ``u`` passed to two versions of an input (e.g. an
   operating rate before and after a treatment) gives comonotone draws.
   Comparisons between control states then differ only by the change being
   analysed, not by sampling noise (common random numbers).
2. **Correlation.** Correlated uniforms from a Gaussian copula become correlated
   draws of *any* marginal distribution.
3. **Auditability.** ``F⁻¹`` is a documented closed form or a SciPy special
   function. No custom samplers are involved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from scipy import stats

from sextant.domain.estimates import (
    BetaEstimate,
    BetaFromTrialsEstimate,
    ConstantEstimate,
    Estimate,
    GammaEstimate,
    GammaFromEventsEstimate,
    LognormalEstimate,
    PertEstimate,
    Provenance,
    UniformEstimate,
)
from sextant.engine.bayes import fit_gamma_to_interval, gamma_poisson_update

FloatArray = NDArray[np.float64]

_EPS = 1e-12


def _clip(u: FloatArray) -> FloatArray:
    return np.clip(u, _EPS, 1.0 - _EPS)


class Distribution(Protocol):
    @property
    def provenance(self) -> Provenance: ...

    def ppf(self, u: FloatArray) -> FloatArray: ...

    def mean(self) -> float: ...

    def quantile(self, q: float) -> float: ...

    def describe(self) -> str: ...


@dataclass(frozen=True)
class Constant:
    value: float
    provenance: Provenance = Provenance.ASSUMPTION

    def ppf(self, u: FloatArray) -> FloatArray:
        return np.full_like(u, self.value, dtype=np.float64)

    def mean(self) -> float:
        return self.value

    def quantile(self, q: float) -> float:
        return self.value

    def describe(self) -> str:
        return f"constant {self.value:,.4g}"


@dataclass(frozen=True)
class Lognormal:
    """Lognormal parameterised by (mu, sigma) of log X, optionally censored at ``cap``."""

    mu: float
    sigma: float
    cap: float | None = None
    provenance: Provenance = Provenance.EXPERT

    @classmethod
    def from_interval(
        cls, low: float, high: float, confidence: float = 0.90, cap: float | None = None
    ) -> Lognormal:
        """Fit so that [low, high] is the central ``confidence`` interval.

        With z = Φ⁻¹((1 + c) / 2):  μ = (ln low + ln high) / 2,  σ = (ln high − ln low) / 2z.
        """
        z = float(stats.norm.ppf((1 + confidence) / 2))
        mu = (math.log(low) + math.log(high)) / 2
        sigma = (math.log(high) - math.log(low)) / (2 * z)
        return cls(mu=mu, sigma=sigma, cap=cap)

    def ppf(self, u: FloatArray) -> FloatArray:
        x: FloatArray = np.exp(self.mu + self.sigma * stats.norm.ppf(_clip(u)))
        return np.minimum(x, self.cap) if self.cap is not None else x

    def mean(self) -> float:
        m = math.exp(self.mu + self.sigma**2 / 2)
        if self.cap is None:
            return m
        # E[min(X, c)] for lognormal X (limited expected value).
        c, mu, s = self.cap, self.mu, self.sigma
        lc = math.log(c)
        return float(m * stats.norm.cdf((lc - mu - s**2) / s) + c * stats.norm.sf((lc - mu) / s))

    def quantile(self, q: float) -> float:
        return float(self.ppf(np.array([q]))[0])

    def describe(self) -> str:
        cap = f", capped at {self.cap:,.0f}" if self.cap else ""
        return (
            f"lognormal (median {math.exp(self.mu):,.4g}, 90% range "
            f"{self.quantile(0.05):,.4g}–{self.quantile(0.95):,.4g}{cap})"
        )


@dataclass(frozen=True)
class Pert:
    """Modified PERT: a Beta distribution rescaled to [low, high] with mode ``mode``."""

    low: float
    mode: float
    high: float
    shape: float = 4.0
    provenance: Provenance = Provenance.EXPERT

    @property
    def _ab(self) -> tuple[float, float]:
        span = self.high - self.low
        a = 1 + self.shape * (self.mode - self.low) / span
        b = 1 + self.shape * (self.high - self.mode) / span
        return a, b

    def ppf(self, u: FloatArray) -> FloatArray:
        a, b = self._ab
        x: FloatArray = self.low + (self.high - self.low) * stats.beta.ppf(_clip(u), a, b)
        return x

    def mean(self) -> float:
        return (self.low + self.shape * self.mode + self.high) / (self.shape + 2)

    def quantile(self, q: float) -> float:
        return float(self.ppf(np.array([q]))[0])

    def describe(self) -> str:
        return f"PERT (min {self.low:,.4g}, most likely {self.mode:,.4g}, max {self.high:,.4g})"


@dataclass(frozen=True)
class Uniform:
    low: float
    high: float
    provenance: Provenance = Provenance.EXPERT

    def ppf(self, u: FloatArray) -> FloatArray:
        return self.low + (self.high - self.low) * u

    def mean(self) -> float:
        return (self.low + self.high) / 2

    def quantile(self, q: float) -> float:
        return self.low + (self.high - self.low) * q

    def describe(self) -> str:
        return f"uniform [{self.low:,.4g}, {self.high:,.4g}]"


@dataclass(frozen=True)
class BetaDist:
    alpha: float
    beta: float
    provenance: Provenance = Provenance.EXPERT
    note: str = ""

    def ppf(self, u: FloatArray) -> FloatArray:
        out: FloatArray = stats.beta.ppf(_clip(u), self.alpha, self.beta)
        return out

    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    def quantile(self, q: float) -> float:
        return float(stats.beta.ppf(q, self.alpha, self.beta))

    def describe(self) -> str:
        lo, hi = self.quantile(0.05), self.quantile(0.95)
        base = f"Beta({self.alpha:g}, {self.beta:g}), mean {self.mean():.3f}, 90% CI {lo:.3f}–{hi:.3f}"
        return f"{base} [{self.note}]" if self.note else base


@dataclass(frozen=True)
class GammaDist:
    shape: float
    rate: float
    provenance: Provenance = Provenance.EXPERT
    note: str = ""

    def ppf(self, u: FloatArray) -> FloatArray:
        out: FloatArray = stats.gamma.ppf(_clip(u), self.shape, scale=1 / self.rate)
        return out

    def mean(self) -> float:
        return self.shape / self.rate

    def quantile(self, q: float) -> float:
        return float(stats.gamma.ppf(q, self.shape, scale=1 / self.rate))

    def describe(self) -> str:
        lo, hi = self.quantile(0.05), self.quantile(0.95)
        base = (
            f"Gamma(shape {self.shape:.3g}, rate {self.rate:.3g}), mean {self.mean():.3g}, "
            f"90% CI {lo:.3g}–{hi:.3g}"
        )
        return f"{base} [{self.note}]" if self.note else base


def build(spec: Estimate) -> Distribution:
    """Translate an estimate specification into a distribution."""
    match spec:
        case ConstantEstimate(value=v):
            return Constant(v)
        case LognormalEstimate(low=lo, high=hi, confidence=c, cap=cap):
            return Lognormal.from_interval(lo, hi, c, cap)
        case PertEstimate(min=lo, mode=m, max=hi, shape=s):
            if hi == lo:
                return Constant(lo, provenance=Provenance.EXPERT)
            return Pert(lo, m, hi, s)
        case UniformEstimate(low=lo, high=hi):
            return Constant(lo, provenance=Provenance.EXPERT) if hi == lo else Uniform(lo, hi)
        case BetaEstimate(alpha=a, beta=b):
            return BetaDist(a, b)
        case BetaFromTrialsEstimate(successes=k, trials=n, prior_alpha=a, prior_beta=b):
            return BetaDist(
                a + k,
                b + n - k,
                provenance=Provenance.DATA,
                note=f"posterior from {k}/{n} observed",
            )
        case GammaEstimate(shape=a, rate=b):
            return GammaDist(a, b)
        case GammaFromEventsEstimate() as g:
            if g.prior_low is not None and g.prior_high is not None:
                a0, b0 = fit_gamma_to_interval(g.prior_low, g.prior_high, 0.90)
                prov = Provenance.EXPERT_AND_DATA
            else:
                a0, b0 = g.prior_shape, g.prior_rate
                prov = Provenance.DATA
            post = gamma_poisson_update(g.events, g.exposure_years, a0, b0)
            return GammaDist(
                post.shape,
                post.rate,
                provenance=prov,
                note=(
                    f"posterior from {g.events} events in {g.exposure_years:g} years; "
                    f"data credibility weight {post.credibility_weight:.0%}"
                ),
            )
    raise TypeError(f"unsupported estimate: {spec!r}")  # pragma: no cover


@dataclass(frozen=True)
class Scaled:
    """A distribution multiplied by ``factor`` and optionally capped. Used for stress tests."""

    base: Distribution
    factor: float
    upper: float | None = None

    @property
    def provenance(self) -> Provenance:
        return self.base.provenance

    def ppf(self, u: FloatArray) -> FloatArray:
        x = self.base.ppf(u) * self.factor
        return np.minimum(x, self.upper) if self.upper is not None else x

    def mean(self) -> float:
        if self.upper is None:
            return self.base.mean() * self.factor
        # Capped: no closed form in general; integrate the quantile function numerically.
        grid = (np.arange(4096) + 0.5) / 4096
        return float(self.ppf(grid).mean())

    def quantile(self, q: float) -> float:
        return float(self.ppf(np.array([q]))[0])

    def describe(self) -> str:
        cap = f", capped at {self.upper:g}" if self.upper is not None else ""
        return f"{self.base.describe()} × {self.factor:g}{cap}"
