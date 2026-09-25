from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from sextant.domain.estimates import GammaFromEventsEstimate, LognormalEstimate
from sextant.engine.bayes import (
    beta_binomial_update,
    clopper_pearson_interval,
    clopper_pearson_upper,
    fit_gamma_to_interval,
    gamma_poisson_update,
)
from sextant.engine.distributions import BetaDist, Lognormal, Pert, Scaled, build


def test_lognormal_from_interval_recovers_bounds() -> None:
    d = Lognormal.from_interval(1e5, 4e6, 0.90)
    assert d.quantile(0.05) == pytest.approx(1e5, rel=1e-9)
    assert d.quantile(0.95) == pytest.approx(4e6, rel=1e-9)
    assert d.quantile(0.5) == pytest.approx(math.sqrt(1e5 * 4e6), rel=1e-9)  # median = geometric mean


def test_capped_lognormal_mean_matches_numerical_integration() -> None:
    d = Lognormal.from_interval(1e4, 1e7, cap=2e6)
    grid = (np.arange(200_000) + 0.5) / 200_000
    assert d.mean() == pytest.approx(float(d.ppf(grid).mean()), rel=1e-3)
    assert d.mean() < Lognormal.from_interval(1e4, 1e7).mean()


def test_pert_mean_and_bounds() -> None:
    p = Pert(10, 20, 60)
    assert p.mean() == pytest.approx((10 + 4 * 20 + 60) / 6)
    samples = p.ppf(np.linspace(0.001, 0.999, 999))
    assert samples.min() >= 10
    assert samples.max() <= 60


def test_scaled_distribution() -> None:
    base = Pert(0.1, 0.2, 0.5)
    s = Scaled(base, 3.0, upper=1.0)
    assert s.ppf(np.array([0.999]))[0] <= 1.0
    assert Scaled(base, 2.0).mean() == pytest.approx(2 * base.mean())


def test_gamma_poisson_update_and_credibility() -> None:
    # Prior Gamma(2, 4): mean 0.5/yr. Observe 6 events in 3 years (observed rate 2/yr).
    post = gamma_poisson_update(6, 3.0, prior_shape=2.0, prior_rate=4.0)
    assert (post.shape, post.rate) == (8.0, 7.0)
    z = post.credibility_weight
    assert z == pytest.approx(3 / 7)
    # Posterior mean is the credibility-weighted average of observed and prior means.
    assert post.mean == pytest.approx(z * 2.0 + (1 - z) * 0.5)


def test_negative_binomial_predictive_matches_simulation() -> None:
    post = gamma_poisson_update(5, 4.0, 1.0, 1.0)
    pred = post.predictive(horizon=1.0)
    rng = np.random.default_rng(0)
    lam = rng.gamma(post.shape, 1 / post.rate, 400_000)
    counts = rng.poisson(lam)
    assert pred.mean == pytest.approx(counts.mean(), rel=0.01)
    assert pred.prob_at_least(1) == pytest.approx((counts >= 1).mean(), abs=0.005)


def test_fit_gamma_to_interval() -> None:
    shape, rate = fit_gamma_to_interval(0.2, 3.0, 0.90)
    d = stats.gamma(shape, scale=1 / rate)
    assert d.ppf(0.05) == pytest.approx(0.2, rel=1e-6)
    assert d.ppf(0.95) == pytest.approx(3.0, rel=1e-6)


def test_gamma_from_events_estimate_blends_prior_and_data() -> None:
    est = GammaFromEventsEstimate(events=12, exposure_years=4, prior_low=0.5, prior_high=4)
    d = build(est)
    assert d.provenance.value == "expert_and_data"
    assert 0.5 < d.mean() < 3.0


def test_beta_binomial() -> None:
    post = beta_binomial_update(23, 25, 1, 1)
    assert (post.alpha, post.beta) == (24, 3)
    assert post.mean == pytest.approx(24 / 27)
    assert isinstance(build_beta := BetaDist(post.alpha, post.beta), BetaDist)
    assert build_beta.mean() == pytest.approx(post.mean)


@pytest.mark.parametrize(
    ("k", "n", "conf", "expected"),
    [
        (0, 25, 0.95, 1 - 0.05 ** (1 / 25)),  # zero-deviation closed form ≈ 11.3 %
        (0, 59, 0.95, 1 - 0.05 ** (1 / 59)),  # classic 59-sample plan ≈ 4.95 %
    ],
)
def test_clopper_pearson_zero_deviation_closed_form(k: int, n: int, conf: float, expected: float) -> None:
    assert clopper_pearson_upper(k, n, conf) == pytest.approx(expected, rel=1e-9)


def test_clopper_pearson_interval_contains_estimate() -> None:
    lo, hi = clopper_pearson_interval(3, 50)
    assert lo < 3 / 50 < hi


def test_estimate_validation_rejects_bad_ranges() -> None:
    with pytest.raises(ValueError):
        LognormalEstimate(low=10, high=5)
    with pytest.raises(ValueError):
        LognormalEstimate(low=1, high=5, cap=3)
