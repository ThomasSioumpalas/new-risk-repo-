from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from sextant.compliance.catalog import all_catalogs, load_catalog
from sextant.compliance.readiness import (
    RequirementStatus,
    assess_readiness,
    draft_statement_of_applicability,
)
from sextant.domain.controls import Control, Evidence
from sextant.domain.methodology import ControlTestingPolicy
from sextant.domain.register import Exclusion, RiskRegister, load_register

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "halcyon"
AS_OF = date(2026, 9, 1)
POLICY = ControlTestingPolicy()


def test_catalog_sizes_match_published_frameworks() -> None:
    csf = load_catalog("nist_csf_2_0")
    assert len(csf.requirements) == 106  # CSF 2.0 subcategories (withdrawn 1.1 items excluded)
    assert len([g for g in csf.groups if g.parent]) == 22  # categories
    iso = load_catalog("iso27001_2022")
    annex = [r for r in iso.requirements if r.id.startswith("A.")]
    assert len(annex) == 93
    assert {r.group for r in annex} == {"A.5", "A.6", "A.7", "A.8"}
    nis2 = load_catalog("nis2_2022_2555")
    assert {f"21.2.{c}" for c in "abcdefghij"} <= {r.id for r in nis2.requirements}
    assert len(load_catalog("nist_ai_rmf_1_0").requirements) == 19


def test_every_catalog_declares_copyright_handling() -> None:
    for cat in all_catalogs().values():
        assert cat.license
        assert cat.source
    assert load_catalog("iso27001_2022").text_policy.value == "identifiers_with_paraphrased_labels"


def _control(
    cid: str,
    relationship: str,
    *,
    status: str = "implemented",
    tests: list[dict[str, Any]] | None = None,
    evidence: list[str] | None = None,
) -> Control:
    return Control.model_validate(
        {
            "id": cid,
            "name": cid,
            "description": "d",
            "type": "preventive",
            "owner": "o",
            "status": status,
            "evidence": evidence or [],
            "tests": tests or [],
            "mappings": [
                {"framework": "nis2_2022_2555", "requirement": "21.2.j", "relationship": relationship}
            ],
        }
    )


GOOD_TEST = {
    "kind": "operating",
    "performed_on": "2026-06-01",
    "performed_by": "IA",
    "procedure": "p",
    "samples": 30,
    "exceptions": 0,
}
EVIDENCE = {
    "E1": Evidence(id="E1", title="t", type="document", collected_on=date(2026, 6, 1), collected_by="x")
}  # type: ignore[arg-type]


def _status(*controls: Control, exclusions: tuple[Exclusion, ...] = ()) -> RequirementStatus:
    report = assess_readiness(
        load_catalog("nis2_2022_2555"), list(controls), EVIDENCE, POLICY, AS_OF, exclusions
    )
    return next(r for r in report.requirements if r.requirement_id == "21.2.j").status


def test_readiness_status_rules() -> None:
    assert _status() is RequirementStatus.GAP
    assert _status(_control("C1", "equal", tests=[GOOD_TEST], evidence=["E1"])) is RequirementStatus.ADDRESSED
    # Fully covering but no evidence → not evidenced, never "addressed".
    assert _status(_control("C1", "equal", tests=[GOOD_TEST])) is RequirementStatus.IMPLEMENTED_NOT_EVIDENCED
    # Verified, but only partial coverage → partially addressed.
    assert (
        _status(_control("C1", "subset_of", tests=[GOOD_TEST], evidence=["E1"]))
        is RequirementStatus.PARTIALLY_ADDRESSED
    )
    assert _status(_control("C1", "equal", status="planned")) is RequirementStatus.PLANNED
    failing = {**GOOD_TEST, "exceptions": 10}
    assert (
        _status(_control("C1", "equal", tests=[failing], evidence=["E1"]))
        is RequirementStatus.CONTROL_INEFFECTIVE
    )
    excl = Exclusion(
        framework="nis2_2022_2555",
        requirement="21.2.j",
        justification="Not applicable because x y z.",
        approved_by="CISO",
    )
    assert _status(exclusions=(excl,)) is RequirementStatus.NOT_APPLICABLE


def test_expired_evidence_does_not_count() -> None:
    old = {
        "E1": Evidence(
            id="E1",
            title="t",
            type="document",
            collected_on=date(2025, 1, 1),
            collected_by="x",  # type: ignore[arg-type]
            valid_until=date(2025, 12, 31),
        )
    }
    ctl = _control("C1", "equal", tests=[GOOD_TEST], evidence=["E1"])
    report = assess_readiness(load_catalog("nis2_2022_2555"), [ctl], old, POLICY, AS_OF)
    status = next(r for r in report.requirements if r.requirement_id == "21.2.j").status
    assert status is RequirementStatus.IMPLEMENTED_NOT_EVIDENCED


def test_mapping_to_unknown_requirement_is_rejected() -> None:
    data = _control("C1", "equal").model_dump(mode="json")
    data["mappings"] = [{"framework": "nis2_2022_2555", "requirement": "99.9", "relationship": "equal"}]
    with pytest.raises(ValueError, match="not in nis2"):
        assess_readiness(load_catalog("nis2_2022_2555"), [Control.model_validate(data)], {}, POLICY, AS_OF)


def test_example_register_loads_and_produces_soa() -> None:
    register, methodology = load_register(EXAMPLE)
    assert len(register.scenarios) == 8
    report = assess_readiness(
        load_catalog("iso27001_2022"),
        register.controls,
        register.evidence_map(),
        methodology.control_testing,
        AS_OF,
        register.exclusions,
        register.scenarios,
    )
    soa = draft_statement_of_applicability(report)
    assert len(soa) == 93
    a830 = next(e for e in soa if e.control_ref == "A.8.30")
    assert not a830.applicable
    a85 = next(e for e in soa if e.control_ref == "A.8.5")
    assert "RSK-001" in a85.related_risks
    assert "NOT an audit opinion" in report.disclaimer


def test_register_detects_broken_references() -> None:
    register, _ = load_register(EXAMPLE)
    data = register.model_dump(mode="json")
    data["scenarios"][0]["assets"] = ["AST-DOES-NOT-EXIST"]
    with pytest.raises(ValidationError, match="unknown asset"):
        RiskRegister.model_validate(data)


def test_expired_acceptance_is_reported_as_expired() -> None:
    from sextant.db.models import RiskAcceptance
    from sextant.services.governance import acceptance_status

    acc = RiskAcceptance(status="active", expires_on=date(2026, 1, 31))
    assert acceptance_status(acc, today=date(2026, 1, 31)) == "active"
    assert acceptance_status(acc, today=date(2026, 2, 1)) == "expired"
