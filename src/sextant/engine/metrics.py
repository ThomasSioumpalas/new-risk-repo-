"""Risk measures computed from simulated annual losses.

Several kinds of uncertainty are reported separately, because mixing them up is
a common error in quantitative risk reports:

* **Predictive spread** of annual loss (P10–P99). A year can be good or bad
  even if every parameter were known exactly.
* **Epistemic uncertainty about the ALE**: the 90 % credible interval of
  ``E[L | θ]`` across the parameter draws. This answers "how confident are we in
  the expected loss?".
* **Monte Carlo error**: the standard error of the simulated mean, and a
  distribution-free interval for a quantile from order statistics. This only
  measures simulation precision, and more trials make it shrink. It says
  *nothing* about whether the inputs are right.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict
from scipy import stats

from sextant.engine.simulation import StateOutcome

FloatArray = NDArray[np.float64]


class LossStatistics(BaseModel):
    model_config = ConfigDict(frozen=True)

    ale: float
    ale_mc_standard_error: float
    ale_credible_interval_90: tuple[float, float]
    median: float
    p90: float
    p95: float
    p99: float
    var_95: float
    es_95: float
    var_99: float
    es_99: float
    var_95_mc_interval: tuple[float, float]
    prob_any_loss: float
    expected_loss_events: float
    prob_at_least_one_event: float
    expected_loss_per_event: float | None
    loss_by_form: dict[str, float]
    lec: list[tuple[float, float]]


def tail_indices(losses: FloatArray, q: float) -> NDArray[np.intp]:
    """Indices of the worst ``ceil(N·(1 − q))`` trials."""
    n = losses.size
    # Round before ceil: 1 − 0.95 is 0.05000000000000004 in floating point.
    k = max(1, math.ceil(round(n * (1 - q), 9)))
    return np.argpartition(losses, n - k)[n - k :]


def expected_shortfall(losses: FloatArray, q: float) -> float:
    """Mean of the worst ``(1 − q)`` share of years (tail conditional expectation).

    Unlike VaR it is coherent (sub-additive), and it describes *how bad* the
    tail is, not just where it starts.
    """
    return float(losses[tail_indices(losses, q)].mean())


def quantile_mc_interval(losses: FloatArray, q: float, level: float = 0.95) -> tuple[float, float]:
    """Distribution-free confidence interval for a quantile, from order statistics.

    The number of samples below the true q-quantile is Binomial(N, q). The
    normal approximation gives the ranks of the bounding order statistics.
    """
    n = losses.size
    z = float(stats.norm.ppf((1 + level) / 2))
    half = z * math.sqrt(n * q * (1 - q))
    lo = max(0, math.floor(n * q - half))
    hi = min(n - 1, math.ceil(n * q + half))
    ordered = np.sort(losses)
    return float(ordered[lo]), float(ordered[hi])


def exceedance_curve(losses: FloatArray, thresholds: Sequence[float]) -> list[tuple[float, float]]:
    """Loss-exceedance curve: P(annual loss ≥ x) for each threshold x."""
    ordered = np.sort(losses)
    n = ordered.size
    return [(float(x), float((n - np.searchsorted(ordered, x, side="left")) / n)) for x in thresholds]


def default_thresholds(max_loss: float, points: int = 40) -> list[float]:
    """Log-spaced thresholds from €1k up to the largest simulated loss."""
    top = max(max_loss, 10_000.0)
    return [float(x) for x in np.geomspace(1_000.0, top, points)]


def summarize(outcome: StateOutcome, thresholds: Sequence[float]) -> LossStatistics:
    losses = outcome.annual_loss
    n = losses.size
    exp_rate = float(outcome.loss_event_rate.mean())
    mean_expected = float(outcome.expected_loss.mean())
    return LossStatistics(
        ale=float(losses.mean()),
        ale_mc_standard_error=float(losses.std(ddof=1) / math.sqrt(n)),
        ale_credible_interval_90=(
            float(np.quantile(outcome.expected_loss, 0.05)),
            float(np.quantile(outcome.expected_loss, 0.95)),
        ),
        median=float(np.quantile(losses, 0.50)),
        p90=float(np.quantile(losses, 0.90)),
        p95=float(np.quantile(losses, 0.95)),
        p99=float(np.quantile(losses, 0.99)),
        var_95=float(np.quantile(losses, 0.95)),
        es_95=expected_shortfall(losses, 0.95),
        var_99=float(np.quantile(losses, 0.99)),
        es_99=expected_shortfall(losses, 0.99),
        var_95_mc_interval=quantile_mc_interval(losses, 0.95),
        prob_any_loss=float((losses > 0).mean()),
        expected_loss_events=exp_rate,
        prob_at_least_one_event=float((1.0 - np.exp(-outcome.loss_event_rate)).mean()),
        expected_loss_per_event=mean_expected / exp_rate if exp_rate > 0 else None,
        loss_by_form={form.value: float(arr.mean()) for form, arr in outcome.loss_by_form.items()},
        lec=exceedance_curve(losses, thresholds),
    )
