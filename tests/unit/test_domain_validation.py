"""Schema-level validation: modelling errors are rejected at the boundary."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from sextant.domain.controls import ControlTest, Evidence, FrameworkMapping, RelationshipType
from sextant.domain.methodology import Methodology, Role, default_methodology
from sextant.domain.scenario import Scenario
from tests.conftest import scenario_data


def test_probability_cannot_be_lognormal() -> None:
    with pytest.raises(ValidationError, match="not valid for a probability"):
        Scenario.model_validate(scenario_data(susceptibility={"dist": "lognormal", "low": 0.1, "high": 0.5}))


def test_probability_constant_out_of_range() -> None:
    with pytest.raises(ValidationError, match=r"within \[0, 1\]"):
        Scenario.model_validate(scenario_data(susceptibility={"dist": "constant", "value": 1.5}))


def test_magnitude_cannot_be_beta() -> None:
    bad = scenario_data()
    bad["primary_losses"][0]["magnitude"] = {"dist": "beta", "alpha": 2, "beta": 3}
    with pytest.raises(ValidationError, match="not valid for a loss magnitude"):
        Scenario.model_validate(bad)


def test_frequency_cannot_be_beta_from_trials() -> None:
    with pytest.raises(ValidationError, match="annual frequency"):
        Scenario.model_validate(
            scenario_data(threat_event_frequency={"dist": "beta_from_trials", "successes": 1, "trials": 3})
        )


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate(scenario_data(risk_score=25))


def test_selected_treatment_must_exist() -> None:
    with pytest.raises(ValidationError, match="not a defined option"):
        Scenario.model_validate(scenario_data(selected_treatment="NOPE"))


def test_share_treatment_requires_mechanism() -> None:
    data = scenario_data()
    data["treatments"] = [{"id": "S", "title": "t", "type": "share", "description": "d"}]
    data["selected_treatment"] = None
    with pytest.raises(ValidationError, match="transfer mechanism"):
        Scenario.model_validate(data)


def test_rationale_is_mandatory_for_control_effects(scenario_factory: Callable[..., Scenario]) -> None:
    data = scenario_data()
    data["controls"][0]["rationale"] = "short"
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_operating_test_requires_counts() -> None:
    with pytest.raises(ValidationError):
        ControlTest(kind="operating", performed_on="2026-01-01", performed_by="x", procedure="y")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ControlTest(
            kind="operating",
            performed_on="2026-01-01",
            performed_by="x",
            procedure="y",
            samples=5,
            exceptions=6,  # type: ignore[arg-type]
        )


def test_evidence_digest_format() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            id="E", title="t", type="document", collected_on="2026-01-01", collected_by="x", sha256="abc"
        )  # type: ignore[arg-type]


def test_relationship_coverage_semantics() -> None:
    assert RelationshipType.EQUAL.is_full_coverage
    assert RelationshipType.SUPERSET_OF.is_full_coverage
    assert not RelationshipType.SUBSET_OF.is_full_coverage
    assert not RelationshipType.INTERSECTS_WITH.is_full_coverage
    FrameworkMapping(framework="nist_csf_2_0", requirement="PR.AA-03", relationship="subset_of")  # type: ignore[arg-type]


def test_default_methodology_is_valid_and_fingerprinted() -> None:
    m = default_methodology()
    assert m.matrix[4][4] == "Very High"
    assert m.matrix[0][0] == "Very Low"
    assert len(m.fingerprint) == 64
    assert default_methodology().fingerprint == m.fingerprint  # deterministic


def _methodology_dict(**changes: Any) -> dict[str, Any]:
    data = default_methodology().model_dump(mode="json")
    data.update(changes)
    return data


def test_non_monotone_matrix_rejected() -> None:
    data = _methodology_dict()
    data["matrix"][4][4] = "Very Low"
    with pytest.raises(ValidationError, match="non-decreasing"):
        Methodology.model_validate(data)


def test_gap_in_scale_rejected() -> None:
    data = _methodology_dict()
    data["likelihood_scale"][1]["lower"] = 0.06
    with pytest.raises(ValidationError, match="contiguous"):
        Methodology.model_validate(data)


def test_admin_has_no_acceptance_authority() -> None:
    assert Role.ADMIN.authority_rank == 0
    assert Role.EXECUTIVE.authority_rank > Role.RISK_MANAGER.authority_rank > Role.RISK_OWNER.authority_rank
