"""Assessment orchestration, sensitivity, treatment, portfolio and forecasting."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from sextant.domain.controls import Control
from sextant.domain.methodology import Methodology
from sextant.domain.scenario import Scenario
from sextant.engine.assessment import run_assessment
from sextant.engine.forecasting import backtest, forecast_counts, poisson_trend_test
from sextant.engine.model import CURRENT, build_model
from sextant.engine.portfolio import aggregate
from sextant.engine.sensitivity import StressTest, apply_stress, baseline_expected_loss, tornado
from sextant.engine.simulation import simulate
from tests.conftest import AS_OF


@pytest.fixture(scope="module")
def assessed() -> object:
    from sextant.domain.methodology import default_methodology
    from tests.conftest import make_control, operating_test, scenario_data

    lib = {
        "CTL-MFA": make_control("CTL-MFA", tests=[operating_test(40, 0)]),
        "CTL-BKP": make_control("CTL-BKP"),
        "CTL-EDR": make_control("CTL-EDR", status="planned"),
    }
    return run_assessment(
        Scenario.model_validate(scenario_data()), lib, default_methodology(), AS_OF, trials=10_000
    )


def test_assessment_is_reproducible(
    scenario: Scenario, library: dict[str, Control], methodology: Methodology
) -> None:
    a = run_assessment(scenario, library, methodology, AS_OF, trials=5_000, seed=1).result
    b = run_assessment(scenario, library, methodology, AS_OF, trials=5_000, seed=1).result
    c = run_assessment(scenario, library, methodology, AS_OF, trials=5_000, seed=2).result
    assert a.result_fingerprint == b.result_fingerprint
    assert a.inputs_fingerprint == b.inputs_fingerprint
    assert a.result_fingerprint != c.result_fingerprint
    assert a.inputs_fingerprint != c.inputs_fingerprint


def test_inputs_fingerprint_tracks_scenario_changes(
    scenario_factory: Callable[..., Scenario], library: dict[str, Control], methodology: Methodology
) -> None:
    a = run_assessment(scenario_factory(), library, methodology, AS_OF, trials=2_000).result
    b = run_assessment(scenario_factory(owner="CFO"), library, methodology, AS_OF, trials=2_000).result
    assert a.inputs_fingerprint != b.inputs_fingerprint


def test_assessment_contents(assessed: object) -> None:
    r = assessed.result  # type: ignore[attr-defined]
    assert set(r.states) == {"inherent", "current", "target"}
    assert r.states["current"].stats.ale < r.states["inherent"].stats.ale
    assert r.explanation is not None
    assert r.explanation.headline.startswith("RSK-T01")
    assert {o.option_id for o in r.options} == {"T1", "T2"}
    # Coupling makes paired estimates of option effects more precise than independent runs.
    for o in r.options:
        assert o.ale_reduction_se_paired < o.ale_reduction_se_independent
    assert r.controls[0].control_id == "CTL-MFA"  # most critical control ranked first
    assert r.evaluation.acceptance_authority in {"risk_owner", "risk_manager", "executive"}
    assert any(i.provenance == "data" for i in r.inputs)  # MFA operating rate from tests


def test_tornado_baseline_equals_simulated_ale(
    scenario: Scenario, library: dict[str, Control], methodology: Methodology
) -> None:
    model = build_model(scenario, library, methodology, AS_OF)
    run = simulate(model, trials=100_000, seed=4, states=[CURRENT])
    sim = run.states[CURRENT].annual_loss
    se = sim.std() / np.sqrt(sim.size)
    assert abs(baseline_expected_loss(model) - sim.mean()) < 5 * se
    bars = tornado(model)
    assert bars == sorted(bars, key=lambda b: b.swing, reverse=True)
    tef = next(b for b in bars if b.input == "threat_event_frequency")
    assert tef.ale_at_high > tef.ale_at_low


def test_stress_control_failure_equals_leave_one_out(
    scenario: Scenario, library: dict[str, Control], methodology: Methodology
) -> None:
    model = build_model(scenario, library, methodology, AS_OF)
    base = simulate(model, trials=5_000, seed=3)
    stressed = simulate(
        apply_stress(model, StressTest(name="x", description="x", failed_controls=["CTL-MFA"])),
        trials=5_000,
        seed=3,
        states=[CURRENT],
    )
    assert np.allclose(stressed.states[CURRENT].annual_loss, base.states["without:CTL-MFA"].annual_loss)


def test_portfolio_tail_contributions_sum_to_expected_shortfall(methodology: Methodology) -> None:
    rng = np.random.default_rng(0)
    losses = {
        "A": rng.lognormal(10, 1, 20_000) * (rng.random(20_000) < 0.5),
        "B": rng.lognormal(13, 1.5, 20_000) * (rng.random(20_000) < 0.05),
    }
    res = aggregate(losses, {"A": "frequent small", "B": "rare large"}, methodology, [1e5, 1e6])
    assert sum(s.tail_contribution_95 for s in res.shares) == pytest.approx(res.es_95, rel=1e-9)
    assert sum(s.ale_share for s in res.shares) == pytest.approx(1.0)
    by_id = {s.scenario_id: s for s in res.shares}
    # The rare/large scenario dominates the tail even though it is not the most frequent.
    assert by_id["B"].tail_share_95 > by_id["A"].tail_share_95


def test_forecast_and_trend() -> None:
    f = forecast_counts([2, 3, 1, 4, 2, 3], threshold=6)
    assert f.predictive_interval_90[0] <= f.predictive_mean <= f.predictive_interval_90[1]
    assert 0 < (f.prob_exceed_threshold or 0) < 0.2
    rng = np.random.default_rng(1)
    rising = rng.poisson(np.exp(0.5 + 0.08 * np.arange(36)))
    assert poisson_trend_test(list(rising)).p_value < 0.01


@pytest.mark.slow
def test_trend_test_false_positive_rate_is_nominal() -> None:
    """Under a constant rate the likelihood-ratio test should reject about 5 % of the time."""
    rng = np.random.default_rng(7)
    rejections = [poisson_trend_test(list(rng.poisson(3.0, 36))).p_value < 0.05 for _ in range(300)]
    assert 0.02 <= np.mean(rejections) <= 0.09


def test_discounting_adapts_to_level_shift() -> None:
    history = [2] * 24 + [8] * 6
    stationary = forecast_counts(history, discount=1.0)
    adaptive = forecast_counts(history, discount=0.8)
    assert adaptive.predictive_mean > stationary.predictive_mean


@pytest.mark.slow
def test_backtest_coverage_is_calibrated_on_stationary_data() -> None:
    """On data that satisfies the model, 90 % intervals should cover about 90 % of outcomes.

    Discrete predictive intervals are conservative (they include both end points),
    so coverage is checked from below with a small tolerance.
    """
    rng = np.random.default_rng(2024)
    coverages = []
    for _ in range(40):
        counts = list(rng.poisson(4.0, 60))
        coverages.append(backtest(counts, warmup=12).coverage_90)
    assert np.mean(coverages) >= 0.86
