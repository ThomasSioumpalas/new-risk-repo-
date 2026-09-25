"""Statistical validation: the simulator against closed-form results.

These tests check that the *implementation* matches the *mathematics*. Each
tolerance is derived from the Monte Carlo standard error, not tuned to pass:
a check at 4-5 standard errors fails spuriously with probability < 1e-4, and
the seeds are fixed anyway.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from itertools import pairwise

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy import integrate, stats

from sextant.domain.controls import Control
from sextant.domain.methodology import Methodology
from sextant.domain.scenario import Scenario
from sextant.engine.distributions import Lognormal
from sextant.engine.model import CURRENT, INHERENT, TARGET, build_model
from sextant.engine.simulation import SimulationTooLargeError, simulate
from tests.conftest import make_control, scenario_data


def _simple(
    scenario_factory: Callable[..., Scenario], lam: float, low: float, high: float, **extra: object
) -> Scenario:
    """Constant-rate scenario with a single lognormal loss form (closed forms are known)."""
    fields: dict[str, object] = {
        "threat_event_frequency": {"dist": "constant", "value": lam},
        "susceptibility": {"dist": "constant", "value": 1.0},
        "primary_losses": [
            {"name": "loss", "form": "response", "magnitude": {"dist": "lognormal", "low": low, "high": high}}
        ],
        "secondary_loss": None,
        "controls": [],
        "treatments": [],
        "selected_treatment": None,
    }
    fields.update(extra)
    return scenario_factory(**fields)


def test_compound_poisson_mean_and_variance(
    scenario_factory: Callable[..., Scenario], methodology: Methodology, as_of: date
) -> None:
    """For L = Σ_{i≤N} Xᵢ with N ~ Poisson(λ): E[L] = λE[X], Var[L] = λE[X²]."""
    lam, low, high = 2.5, 1e4, 1e6
    sc = _simple(scenario_factory, lam, low, high)
    model = build_model(sc, {}, methodology, as_of)
    run = simulate(model, trials=100_000, seed=7)
    losses = run.states[INHERENT].annual_loss

    ln = Lognormal.from_interval(low, high)
    ex = math.exp(ln.mu + ln.sigma**2 / 2)
    ex2 = math.exp(2 * ln.mu + 2 * ln.sigma**2)
    mean_true, var_true = lam * ex, lam * ex2

    se_mean = math.sqrt(var_true / losses.size)
    assert abs(losses.mean() - mean_true) < 5 * se_mean
    # Variance of a heavy-tailed sample converges slowly; a relative tolerance is appropriate.
    assert losses.var() == pytest.approx(var_true, rel=0.15)
    # The closed-form conditional expectation equals λE[X] in every trial (no epistemic uncertainty here).
    assert np.allclose(run.states[INHERENT].expected_loss, mean_true)


def test_event_counts_are_poisson(
    scenario_factory: Callable[..., Scenario], methodology: Methodology, as_of: date
) -> None:
    sc = _simple(scenario_factory, 1.7, 1e3, 1e4)
    run = simulate(build_model(sc, {}, methodology, as_of), trials=50_000, seed=3)
    counts = run.states[INHERENT].event_counts
    assert counts.mean() == pytest.approx(1.7, abs=5 * math.sqrt(1.7 / counts.size))
    assert counts.var() == pytest.approx(1.7, rel=0.05)  # Poisson: variance equals mean


def test_thinning_gives_reduced_poisson_rate(
    scenario_factory: Callable[..., Scenario], methodology: Methodology, as_of: date
) -> None:
    """A control with reduction r, operating rate o and coverage c thins the rate to λ(1 − r·o·c)."""
    lam, r, o, c = 4.0, 0.6, 0.9, 0.8
    control = {
        "control_id": "CTL-MFA",
        "target": "susceptibility",
        "reduction": {"dist": "constant", "value": r},
        "operating_rate": {"dist": "constant", "value": o},
        "coverage": c,
        "rationale": "constant-strength control for the thinning check",
    }
    sc = _simple(scenario_factory, lam, 1e3, 1e4, controls=[control])
    lib = {"CTL-MFA": make_control("CTL-MFA")}
    run = simulate(build_model(sc, lib, methodology, as_of), trials=60_000, seed=11)
    counts = run.states[CURRENT].event_counts
    expected_rate = lam * (1 - r * o * c)
    assert counts.mean() == pytest.approx(expected_rate, abs=5 * math.sqrt(expected_rate / counts.size))
    assert counts.var() == pytest.approx(expected_rate, rel=0.05)


def test_insurance_recovery_matches_numerical_integral(
    scenario_factory: Callable[..., Scenario], methodology: Methodology, as_of: date
) -> None:
    """Retained loss per event = X − min(max(X − d, 0), L); check E[retained] by quadrature."""
    low, high, d, limit = 1e5, 5e6, 2.5e5, 1e6
    insurance = {
        "id": "INS",
        "title": "Insurance",
        "type": "share",
        "description": "Per-occurrence policy",
        "insurance": {"deductible": d, "limit": limit, "excluded_forms": []},
    }
    sc = _simple(scenario_factory, 1.0, low, high, treatments=[insurance])
    run = simulate(build_model(sc, {}, methodology, as_of), trials=100_000, seed=5)
    ln = Lognormal.from_interval(low, high)
    dist = stats.lognorm(s=ln.sigma, scale=math.exp(ln.mu))

    def retained(x: float) -> float:
        return x - min(max(x - d, 0.0), limit)

    # Integrate piecewise between the kinks of the retained-loss function.
    edges = [0.0, d, d + limit, float(dist.ppf(1 - 1e-12))]
    true_mean = sum(
        integrate.quad(lambda x: retained(x) * dist.pdf(x), a, b, limit=200)[0] for a, b in pairwise(edges)
    )
    losses = run.states["option:INS"].annual_loss
    se = losses.std() / math.sqrt(losses.size)
    assert abs(losses.mean() - true_mean) < 5 * se


def test_copula_changes_tail_not_mean(
    scenario_factory: Callable[..., Scenario], methodology: Methodology, as_of: date
) -> None:
    """Correlating loss forms leaves the mean unchanged but increases the spread of event losses.

    With two comparable forms X, Y: Var(X + Y) = Var X + Var Y + 2 Cov(X, Y), and Cov > 0 under ρ > 0.
    """
    comps = [
        {"name": "a", "form": "response", "magnitude": {"dist": "lognormal", "low": 1e4, "high": 1e5}},
        {"name": "b", "form": "productivity", "magnitude": {"dist": "lognormal", "low": 1e4, "high": 1e5}},
    ]
    sc = _simple(scenario_factory, 1.0, 1.0, 2.0, primary_losses=comps)
    model = build_model(sc, {}, methodology, as_of)
    independent = simulate(model, trials=80_000, seed=9, correlation=0.0).states[INHERENT].annual_loss
    correlated = simulate(model, trials=80_000, seed=9, correlation=0.9).states[INHERENT].annual_loss
    se = independent.std() / math.sqrt(independent.size)
    assert abs(independent.mean() - correlated.mean()) < 6 * se
    assert correlated.std() > 1.1 * independent.std()
    assert np.quantile(correlated, 0.99) > np.quantile(independent, 0.99)


def test_simulated_mean_matches_conditional_expectation(
    scenario: Scenario, library: dict[str, Control], methodology: Methodology, as_of: date
) -> None:
    """E[annual loss] = E[E[L | θ]] (law of total expectation) for every non-insured state."""
    run = simulate(build_model(scenario, library, methodology, as_of), trials=100_000, seed=1)
    for name, outcome in run.states.items():
        if name == "option:T2":  # insured: expectation is approximated by construction
            continue
        se = outcome.annual_loss.std() / math.sqrt(outcome.annual_loss.size)
        assert abs(outcome.annual_loss.mean() - outcome.expected_loss.mean()) < 5 * se, name


def test_states_are_monotone_trialwise(
    scenario: Scenario, library: dict[str, Control], methodology: Methodology, as_of: date
) -> None:
    run = simulate(build_model(scenario, library, methodology, as_of), trials=20_000, seed=2)
    inh = run.states[INHERENT].annual_loss
    cur = run.states[CURRENT].annual_loss
    assert np.all(cur <= inh + 1e-6)
    assert np.all(run.states[TARGET].annual_loss <= cur + 1e-6)
    assert np.all(run.states["option:T2"].annual_loss <= cur + 1e-6)
    for cid in ("CTL-MFA", "CTL-BKP"):
        assert np.all(run.states[f"without:{cid}"].annual_loss >= cur - 1e-6)


@settings(max_examples=25, deadline=None)
@given(
    r=st.floats(0.0, 1.0),
    o=st.floats(0.0, 1.0),
    c=st.floats(0.0, 1.0),
    seed=st.integers(0, 10_000),
)
def test_adding_any_control_never_increases_loss(r: float, o: float, c: float, seed: int) -> None:
    """Property: for any control strength, every simulated year is no worse than without it."""
    from sextant.domain.methodology import default_methodology

    sc = Scenario.model_validate(
        scenario_data(
            controls=[
                {
                    "control_id": "CTL-X",
                    "target": "susceptibility",
                    "reduction": {"dist": "constant", "value": r},
                    "operating_rate": {"dist": "constant", "value": o},
                    "coverage": c,
                    "rationale": "property-based test control",
                }
            ],
            treatments=[],
            selected_treatment=None,
        )
    )
    model = build_model(sc, {"CTL-X": make_control("CTL-X")}, default_methodology(), date(2026, 1, 1))
    run = simulate(model, trials=500, seed=seed)
    assert np.all(run.states[CURRENT].annual_loss <= run.states[INHERENT].annual_loss + 1e-6)


def test_reproducible_and_seed_sensitive(
    scenario: Scenario, library: dict[str, Control], methodology: Methodology, as_of: date
) -> None:
    model = build_model(scenario, library, methodology, as_of)
    a = simulate(model, trials=5_000, seed=123).states[CURRENT].annual_loss
    b = simulate(model, trials=5_000, seed=123).states[CURRENT].annual_loss
    c = simulate(model, trials=5_000, seed=124).states[CURRENT].annual_loss
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_adding_a_treatment_option_does_not_change_other_results(
    scenario_factory: Callable[..., Scenario],
    library: dict[str, Control],
    methodology: Methodology,
    as_of: date,
) -> None:
    """Named random streams: model edits elsewhere leave the current state's draws untouched."""
    base = scenario_factory(treatments=[], selected_treatment=None)
    extended = scenario_factory()
    a = simulate(build_model(base, library, methodology, as_of), trials=5_000, seed=8)
    b = simulate(build_model(extended, library, methodology, as_of), trials=5_000, seed=8)
    assert np.array_equal(a.states[CURRENT].annual_loss, b.states[CURRENT].annual_loss)


def test_event_budget_guard(
    scenario_factory: Callable[..., Scenario], methodology: Methodology, as_of: date
) -> None:
    sc = _simple(scenario_factory, 5_000.0, 1.0, 10.0)
    with pytest.raises(SimulationTooLargeError):
        simulate(build_model(sc, {}, methodology, as_of), trials=20_000, seed=1)


def test_avoid_treatment_eliminates_loss(
    scenario_factory: Callable[..., Scenario],
    library: dict[str, Control],
    methodology: Methodology,
    as_of: date,
) -> None:
    sc = scenario_factory(
        treatments=[{"id": "AV", "title": "Decommission", "type": "avoid", "description": "Retire system"}],
        selected_treatment="AV",
    )
    run = simulate(build_model(sc, library, methodology, as_of), trials=2_000, seed=1)
    assert run.states[TARGET].annual_loss.sum() == 0.0
