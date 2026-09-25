from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest

from sextant.domain.controls import Control
from sextant.domain.methodology import ControlTestingPolicy, Methodology
from sextant.domain.scenario import Scenario
from sextant.engine.controls import OperatingConclusion, assess_control
from sextant.engine.model import CURRENT, ModelError, build_model
from sextant.engine.qualitative import assess_qualitative, band, band_quantitative, quality_checks, risk_level
from tests.conftest import make_control, operating_test

POLICY = ControlTestingPolicy(tolerable_deviation_rate=0.10, required_confidence=0.90)
AS_OF = date(2026, 9, 1)


@pytest.mark.parametrize(
    ("samples", "exceptions", "expected"),
    [
        (21, 0, OperatingConclusion.EFFECTIVE),  # Bayesian (uniform prior) threshold for TDR 10 % / 90 %
        (20, 0, OperatingConclusion.INCONCLUSIVE),
        (25, 1, OperatingConclusion.INCONCLUSIVE),
        (25, 8, OperatingConclusion.NOT_EFFECTIVE),
    ],
)
def test_operating_conclusions(samples: int, exceptions: int, expected: OperatingConclusion) -> None:
    ctl = make_control("C", tests=[operating_test(samples, exceptions)])
    assert assess_control(ctl, POLICY, AS_OF).conclusion is expected


def test_bayesian_threshold_close_to_classical_plan() -> None:
    """Uniform-prior Bayes needs n = 21 clean samples; classical attribute sampling needs n = 22."""
    ctl = make_control("C", tests=[operating_test(20, 0)])
    a = assess_control(ctl, POLICY, AS_OF)
    assert a.additional_samples_needed == 1
    assert 0.9**22 < 0.10 < 0.9**21  # classical: (1 − TDR)^n ≤ 1 − confidence


def test_tests_outside_lookback_are_ignored() -> None:
    ctl = make_control("C", tests=[operating_test(40, 0, on="2024-01-01")])
    a = assess_control(ctl, POLICY, AS_OF)
    assert a.conclusion is OperatingConclusion.NOT_TESTED
    assert a.operating_rate_mean == pytest.approx(0.5)  # uninformative prior


def test_untested_control_gets_prior_credit(
    scenario: Scenario, library: dict[str, Control], methodology: Methodology
) -> None:
    model = build_model(scenario, library, methodology, AS_OF)
    bkp = next(k for k in model.states[CURRENT].effects if k.startswith("CTL-BKP"))
    assert model.states[CURRENT].effects[bkp].operating_source.startswith("uninformative prior")


def test_design_failure_removes_credit(scenario: Scenario, methodology: Methodology) -> None:
    design_fail = {
        "kind": "design",
        "performed_on": "2026-05-01",
        "performed_by": "IA",
        "procedure": "walkthrough",
        "design_conclusion": "ineffective",
    }
    lib = {
        "CTL-MFA": make_control("CTL-MFA", tests=[design_fail]),
        "CTL-BKP": make_control("CTL-BKP"),
        "CTL-EDR": make_control("CTL-EDR", status="planned"),
    }
    model = build_model(scenario, lib, methodology, AS_OF)
    assert "CTL-MFA" not in model.credited_controls
    assert any("failed its latest design test" in n for n in model.notes)


def test_unknown_control_is_a_model_error(scenario: Scenario, methodology: Methodology) -> None:
    with pytest.raises(ModelError, match="unknown controls"):
        build_model(scenario, {}, methodology, AS_OF)


def test_matrix_lookup_is_not_multiplication(methodology: Methodology) -> None:
    # Same ordinal product (4), different levels: the lookup encodes judgement, the product cannot.
    assert risk_level(methodology, 1, 4) == "Low"
    assert risk_level(methodology, 4, 1) == "Very Low"
    assert risk_level(methodology, 2, 2) == "Low"


def test_banding_boundaries(methodology: Methodology) -> None:
    assert band(0.2, methodology.likelihood_scale).name == "Moderate"  # lower bound inclusive
    assert band(0.1999, methodology.likelihood_scale).name == "Low"
    assert band(1e9, methodology.impact_scale).level == 5
    banded = band_quantitative(methodology, 0.3, 2_000_000)
    assert (banded.likelihood, banded.impact, banded.risk_level) == (3, 4, "Moderate")


def _qual(inh: tuple[int, int], cur: tuple[int, int]) -> dict[str, object]:
    def ratings(lv: tuple[int, int]) -> dict[str, object]:
        return {
            "likelihood": {"level": lv[0], "rationale": "workshop consensus rating"},
            "impact": {"financial": {"level": lv[1], "rationale": "based on outage cost model"}},
        }

    return {"inherent": ratings(inh), "current": ratings(cur)}


def test_unsupported_reduction_is_flagged(
    scenario_factory: Callable[..., Scenario], methodology: Methodology
) -> None:
    sc = scenario_factory(
        controls=[], treatments=[], selected_treatment=None, qualitative=_qual((4, 4), (2, 4))
    )
    model = build_model(sc, {}, methodology, AS_OF)
    codes = {f.code for f in quality_checks(sc, model, assess_qualitative(sc, methodology))}
    assert "QUAL-UNSUPPORTED-REDUCTION" in codes


def test_reduction_without_effective_tests_is_warned(
    scenario_factory: Callable[..., Scenario], methodology: Methodology
) -> None:
    lib = {
        "CTL-MFA": make_control("CTL-MFA"),
        "CTL-BKP": make_control("CTL-BKP"),
        "CTL-EDR": make_control("CTL-EDR"),
    }
    sc = scenario_factory(qualitative=_qual((4, 4), (3, 4)))
    model = build_model(sc, lib, methodology, AS_OF)
    codes = {f.code for f in quality_checks(sc, model, assess_qualitative(sc, methodology))}
    assert "QUAL-REDUCTION-UNEVIDENCED" in codes
    assert "CTL-UNTESTED" in codes


def test_impact_is_worst_dimension(
    scenario_factory: Callable[..., Scenario], methodology: Methodology
) -> None:
    q = _qual((3, 2), (3, 2))
    q["current"]["impact"]["legal_regulatory"] = {"level": 5, "rationale": "regulator could revoke licence"}  # type: ignore[index]
    sc = scenario_factory(qualitative=q)
    result = assess_qualitative(sc, methodology)
    assert result is not None
    assert result.current.impact == 5
