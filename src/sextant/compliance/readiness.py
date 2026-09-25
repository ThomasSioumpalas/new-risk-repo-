"""Readiness (gap) assessment and a draft Statement of Applicability.

This module deliberately never outputs "compliant". It combines three
independent facts per requirement:

1. **Mapping**: is there a control, and how completely does it address the
   requirement (NIST IR 8477 relationship)?
2. **Control assessment**: is the control in operation, and do the tests
   support design and operating effectiveness?
3. **Evidence**: is there current, integrity-protected evidence?

The result is a *readiness status*. It is a planning heuristic for the
compliance function. It is not a conformity assessment and it is not an audit
opinion. Certification of an ISMS is performed by an accredited certification
body (ISO/IEC 17021-1, ISO/IEC 27006).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from sextant.compliance.catalog import Catalog
from sextant.domain.controls import Control, Evidence, RelationshipType
from sextant.domain.methodology import ControlTestingPolicy
from sextant.domain.register import Exclusion
from sextant.domain.scenario import Scenario
from sextant.engine.controls import DesignStatus, OperatingConclusion, assess_control

DISCLAIMER = (
    "Readiness indicators summarise mapped controls, test results and evidence currency. They are NOT an "
    "audit opinion, a conformity assessment or a certification. Mapping relationships reflect analyst "
    "judgement (NIST IR 8477 set-theory relationships) and should be reviewed by the compliance function."
)


class ControlReadiness(StrEnum):
    VERIFIED = "verified"  # in operation, tested effective, current evidence
    UNVERIFIED = "unverified"  # in operation but untested/inconclusive or evidence missing/stale
    INEFFECTIVE = "ineffective"  # design or operating test failed
    PLANNED = "planned"  # not yet in operation


class RequirementStatus(StrEnum):
    ADDRESSED = "addressed"
    IMPLEMENTED_NOT_EVIDENCED = "implemented_not_evidenced"
    PARTIALLY_ADDRESSED = "partially_addressed"
    CONTROL_INEFFECTIVE = "control_ineffective"
    PLANNED = "planned"
    GAP = "gap"
    NOT_APPLICABLE = "not_applicable"


STATUS_ORDER = list(RequirementStatus)


class MappedControl(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_id: str
    control_name: str
    relationship: RelationshipType
    readiness: ControlReadiness
    reason: str


class RequirementResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str
    title: str
    group: str
    status: RequirementStatus
    controls: list[MappedControl]
    related_risks: list[str]
    note: str


class ReadinessReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    framework_id: str
    framework_name: str
    text_policy: str
    as_of: date
    counts: dict[str, int]
    applicable: int
    readiness_indicator: float
    coverage_indicator: float
    requirements: list[RequirementResult]
    disclaimer: str = DISCLAIMER


def control_readiness(
    control: Control, evidence: Mapping[str, Evidence], policy: ControlTestingPolicy, as_of: date
) -> tuple[ControlReadiness, str]:
    if not control.status.is_in_operation:
        return ControlReadiness.PLANNED, f"status: {control.status.value}"
    a = assess_control(control, policy, as_of)
    if a.design_status is DesignStatus.INEFFECTIVE:
        return ControlReadiness.INEFFECTIVE, "latest design test ineffective"
    if a.conclusion is OperatingConclusion.NOT_EFFECTIVE:
        return ControlReadiness.INEFFECTIVE, f"operating test: {a.exceptions}/{a.samples} exceptions"
    cited = set(control.evidence) | {e for t in control.tests for e in t.evidence}
    current = [e for e in cited if e in evidence and evidence[e].is_current(as_of)]
    if a.conclusion is not OperatingConclusion.EFFECTIVE:
        return ControlReadiness.UNVERIFIED, f"operating effectiveness {a.conclusion.value.replace('_', ' ')}"
    if not current:
        return ControlReadiness.UNVERIFIED, "no current evidence"
    return (
        ControlReadiness.VERIFIED,
        f"tested effective ({a.samples} samples); {len(current)} current evidence item(s)",
    )


def _requirement_status(mapped: Sequence[MappedControl]) -> tuple[RequirementStatus, str]:
    if not mapped:
        return RequirementStatus.GAP, "No control is mapped to this requirement."
    full = [m for m in mapped if m.relationship.is_full_coverage]
    partial = [m for m in mapped if not m.relationship.is_full_coverage]
    in_op = {ControlReadiness.VERIFIED, ControlReadiness.UNVERIFIED}
    if any(m.readiness is ControlReadiness.VERIFIED for m in full):
        return RequirementStatus.ADDRESSED, "A fully-covering control is verified."
    if any(m.readiness is ControlReadiness.UNVERIFIED for m in full):
        return (
            RequirementStatus.IMPLEMENTED_NOT_EVIDENCED,
            "A fully-covering control operates but lacks effective test results or current evidence.",
        )
    if any(m.readiness in in_op for m in partial):
        return (
            RequirementStatus.PARTIALLY_ADDRESSED,
            "Only partially-covering controls (subset/intersects) are in operation; judgement required.",
        )
    if any(m.readiness is ControlReadiness.INEFFECTIVE for m in mapped):
        return RequirementStatus.CONTROL_INEFFECTIVE, "Mapped controls failed testing."
    return RequirementStatus.PLANNED, "Mapped controls are planned but not in operation."


def assess_readiness(
    catalog: Catalog,
    controls: Sequence[Control],
    evidence: Mapping[str, Evidence],
    policy: ControlTestingPolicy,
    as_of: date,
    exclusions: Sequence[Exclusion] = (),
    scenarios: Sequence[Scenario] = (),
) -> ReadinessReport:
    unknown = [
        f"{c.id} → {m.requirement}"
        for c in controls
        for m in c.mappings
        if m.framework == catalog.id and not catalog.has(m.requirement)
    ]
    if unknown:
        raise ValueError(f"mappings to requirements not in {catalog.id}: {unknown}")

    readiness_cache = {c.id: control_readiness(c, evidence, policy, as_of) for c in controls}
    risks_by_control: dict[str, set[str]] = {}
    for s in scenarios:
        for e in s.controls:
            risks_by_control.setdefault(e.control_id, set()).add(s.id)
    excluded = {x.requirement: x for x in exclusions if x.framework == catalog.id}

    results = []
    for req in catalog.requirements:
        mapped = [
            MappedControl(
                control_id=c.id,
                control_name=c.name,
                relationship=m.relationship,
                readiness=readiness_cache[c.id][0],
                reason=readiness_cache[c.id][1],
            )
            for c in controls
            for m in c.mappings
            if m.framework == catalog.id and m.requirement == req.id
        ]
        related = sorted({r for m in mapped for r in risks_by_control.get(m.control_id, set())})
        if req.id in excluded:
            status, note = RequirementStatus.NOT_APPLICABLE, excluded[req.id].justification
        else:
            status, note = _requirement_status(mapped)
        results.append(
            RequirementResult(
                requirement_id=req.id,
                title=req.title,
                group=req.group,
                status=status,
                controls=mapped,
                related_risks=related,
                note=note,
            )
        )

    counts = Counter(r.status.value for r in results)
    applicable = len(results) - counts.get(RequirementStatus.NOT_APPLICABLE.value, 0)
    addressed = counts.get(RequirementStatus.ADDRESSED.value, 0)
    covered = addressed + sum(
        counts.get(s.value, 0)
        for s in (RequirementStatus.IMPLEMENTED_NOT_EVIDENCED, RequirementStatus.PARTIALLY_ADDRESSED)
    )
    return ReadinessReport(
        framework_id=catalog.id,
        framework_name=catalog.name,
        text_policy=catalog.text_policy.value,
        as_of=as_of,
        counts={s.value: counts.get(s.value, 0) for s in STATUS_ORDER},
        applicable=applicable,
        readiness_indicator=addressed / applicable if applicable else 0.0,
        coverage_indicator=covered / applicable if applicable else 0.0,
        requirements=results,
    )


class SoAEntry(BaseModel):
    """One line of a draft Statement of Applicability (ISO/IEC 27001 6.1.3 d)."""

    model_config = ConfigDict(frozen=True)

    control_ref: str
    topic: str
    applicable: bool
    justification: str
    implementation_status: RequirementStatus
    implementing_controls: list[str]
    related_risks: list[str]


def draft_statement_of_applicability(report: ReadinessReport) -> list[SoAEntry]:
    """Derive a draft SoA for the Annex A controls from an ISO/IEC 27001 readiness report.

    Inclusion is justified by traceability to assessed risks, which is what 6.1.3
    asks for. Controls without a linked risk are flagged for the ISMS owner to
    justify (e.g. a legal or contractual requirement) or exclude.
    """
    if report.framework_id != "iso27001_2022":
        raise ValueError("a Statement of Applicability is specific to ISO/IEC 27001")
    entries = []
    for r in report.requirements:
        if not r.requirement_id.startswith("A."):
            continue
        applicable = r.status is not RequirementStatus.NOT_APPLICABLE
        if not applicable:
            why = f"Excluded: {r.note}"
        elif r.related_risks:
            why = "Selected to treat assessed risk(s): " + ", ".join(r.related_risks)
        elif r.controls:
            why = "Implemented; no linked risk scenario yet - document the legal, contractual or baseline driver."
        else:
            why = "TO DECIDE: no linked risk and no implementing control; justify inclusion or exclusion."
        entries.append(
            SoAEntry(
                control_ref=r.requirement_id,
                topic=r.title,
                applicable=applicable,
                justification=why,
                implementation_status=r.status,
                implementing_controls=[m.control_id for m in r.controls],
                related_risks=r.related_risks,
            )
        )
    return entries
