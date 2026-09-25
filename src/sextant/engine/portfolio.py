"""Portfolio aggregation: the risk committee's view.

Scenario losses are summed trial by trial. Each scenario uses its own random
streams, so v1 aggregates scenarios **as if independent**. Real cyber losses
can be correlated (a common threat actor, a shared supplier, the same
vulnerability). Independence then *understates* the portfolio tail. This is
documented as a limitation and is on the roadmap (a common-shock model).

Two decompositions are reported because they answer different questions:

* **ALE share**: which scenarios drive the *average* annual loss (budgeting).
* **Tail share**: the Euler allocation of expected shortfall,
  ``E[Lᵢ | L_total ≥ VaR₉₅]``. It shows which scenarios drive the *bad years*
  (capital, insurance, board appetite). Frequent small losses dominate the
  first; rare large losses dominate the second.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict
from scipy import stats

from sextant.domain.methodology import Methodology
from sextant.engine.metrics import exceedance_curve, expected_shortfall, tail_indices

FloatArray = NDArray[np.float64]


class ToleranceCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    loss: float
    max_probability: float
    simulated_probability: float
    mc_interval_95: tuple[float, float]
    status: str  # within | exceeds | borderline


class ScenarioShare(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    title: str
    ale: float
    ale_share: float
    standalone_var_95: float
    tail_contribution_95: float
    tail_share_95: float


class PortfolioResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    trials: int
    ale: float
    median: float
    var_95: float
    es_95: float
    var_99: float
    es_99: float
    lec: list[tuple[float, float]]
    tolerance: list[ToleranceCheck]
    within_tolerance: bool
    shares: list[ScenarioShare]
    sum_of_standalone_var_95: float
    assumptions: list[str]


def _jeffreys(x: int, n: int, level: float = 0.95) -> tuple[float, float]:
    tail = (1 - level) / 2
    lo = 0.0 if x == 0 else float(stats.beta.ppf(tail, x + 0.5, n - x + 0.5))
    hi = 1.0 if x == n else float(stats.beta.ppf(1 - tail, x + 0.5, n - x + 0.5))
    return lo, hi


def aggregate(
    losses: Mapping[str, FloatArray],
    titles: Mapping[str, str],
    methodology: Methodology,
    thresholds: Sequence[float],
) -> PortfolioResult:
    if not losses:
        raise ValueError("no scenarios to aggregate")
    sizes = {a.size for a in losses.values()}
    if len(sizes) != 1:
        raise ValueError("all scenarios must be simulated with the same number of trials")
    n = sizes.pop()
    total = np.sum(np.vstack(list(losses.values())), axis=0)

    checks = []
    for point in methodology.appetite.tolerance_curve:
        x = int((total >= point.loss).sum())
        p = x / n
        lo, hi = _jeffreys(x, n)
        status = (
            "exceeds"
            if lo > point.max_probability
            else "within"
            if hi <= point.max_probability
            else "borderline"
        )
        checks.append(
            ToleranceCheck(
                loss=point.loss,
                max_probability=point.max_probability,
                simulated_probability=p,
                mc_interval_95=(lo, hi),
                status=status,
            )
        )

    tail_idx = tail_indices(total, 0.95)
    es95 = float(total[tail_idx].mean())
    ale_total = float(total.mean())
    shares = []
    for sid, arr in losses.items():
        tail = float(arr[tail_idx].mean())
        shares.append(
            ScenarioShare(
                scenario_id=sid,
                title=titles.get(sid, sid),
                ale=float(arr.mean()),
                ale_share=float(arr.mean()) / ale_total if ale_total > 0 else 0.0,
                standalone_var_95=float(np.quantile(arr, 0.95)),
                tail_contribution_95=tail,
                tail_share_95=tail / es95 if es95 > 0 else 0.0,
            )
        )
    shares.sort(key=lambda s: s.tail_contribution_95, reverse=True)

    return PortfolioResult(
        trials=n,
        ale=ale_total,
        median=float(np.median(total)),
        var_95=float(np.quantile(total, 0.95)),
        es_95=expected_shortfall(total, 0.95),
        var_99=float(np.quantile(total, 0.99)),
        es_99=expected_shortfall(total, 0.99),
        lec=exceedance_curve(total, thresholds),
        tolerance=checks,
        within_tolerance=all(c.status != "exceeds" for c in checks),
        shares=shares,
        sum_of_standalone_var_95=sum(s.standalone_var_95 for s in shares),
        assumptions=[
            "Scenarios are aggregated as independent; correlated losses would widen the tail.",
            "Each scenario is evaluated in its current (as-implemented, as-tested) control state.",
        ],
    )
