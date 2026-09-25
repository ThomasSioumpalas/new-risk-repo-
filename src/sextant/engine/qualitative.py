"""Qualitative / semi-quantitative risk analysis and assessment-quality checks.

The qualitative method (ISO/IEC 27005, NIST SP 800-30) uses a matrix
**lookup**: ``risk level = matrix[likelihood][impact]``. The popular
alternative, multiplying two ordinal ranks (L × I), is also computed. It is
kept only as a reference, because ordinal numbers do not support arithmetic:

* ``2 × 3`` and ``3 × 2`` and ``1 × 6`` look identical, although the underlying
  expected losses can differ by orders of magnitude (range compression);
* the same score can be *lower* for a risk with a higher expected loss
  (ranking reversal; Cox 2008).

Quantitative results are *banded* into the same scales: likelihood from the
expected number of loss events per year, and impact from the expected loss per
event. Both methods can therefore be compared, and their disagreements are
reported.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from sextant.domain.methodology import Methodology, ScaleLevel
from sextant.domain.scenario import QualitativeRatings, Scenario, TreatmentType
from sextant.engine.controls import OperatingConclusion
from sextant.engine.model import CURRENT, ScenarioModel


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Finding(BaseModel):
    """An assessment-quality observation: the kind of thing a reviewer or auditor would raise."""

    model_config = ConfigDict(frozen=True)

    severity: Severity
    code: str
    message: str


class RatedState(BaseModel):
    model_config = ConfigDict(frozen=True)

    likelihood: int
    likelihood_name: str
    impact: int
    impact_name: str
    risk_level: str
    ordinal_score: int
    basis: str


class QualitativeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    inherent: RatedState
    current: RatedState
    target: RatedState | None
    impact_by_dimension: dict[str, dict[str, int]]


def band(value: float, scale: Sequence[ScaleLevel]) -> ScaleLevel:
    for lv in scale:
        if value >= lv.lower and (lv.upper is None or value < lv.upper):
            return lv
    raise ValueError(f"value {value} outside scale")  # pragma: no cover - scales start at 0, top unbounded


def risk_level(methodology: Methodology, likelihood: int, impact: int) -> str:
    return methodology.matrix[likelihood - 1][impact - 1]


def rate(methodology: Methodology, likelihood: int, impact: int, basis: str) -> RatedState:
    return RatedState(
        likelihood=likelihood,
        likelihood_name=methodology.likelihood_scale[likelihood - 1].name,
        impact=impact,
        impact_name=methodology.impact_scale[impact - 1].name,
        risk_level=risk_level(methodology, likelihood, impact),
        ordinal_score=likelihood * impact,
        basis=basis,
    )


def band_quantitative(
    methodology: Methodology, loss_events_per_year: float, loss_per_event: float | None
) -> RatedState:
    """Map quantitative results onto the qualitative scales."""
    lk = band(loss_events_per_year, methodology.likelihood_scale)
    im = band(loss_per_event or 0.0, methodology.impact_scale)
    basis = (
        f"{loss_events_per_year:.3g} expected loss events/yr → likelihood '{lk.name}'; "
        f"{methodology.currency} {loss_per_event or 0:,.0f} expected loss per event → impact '{im.name}'"
    )
    return rate(methodology, lk.level, im.level, basis)


def assess_qualitative(scenario: Scenario, methodology: Methodology) -> QualitativeResult | None:
    q = scenario.qualitative
    if q is None:
        return None

    def to_state(r: QualitativeRatings, label: str) -> RatedState:
        return rate(
            methodology,
            r.likelihood.level,
            r.impact.overall,
            f"{label}: analyst rating (impact = worst of {', '.join(r.impact.ratings())})",
        )

    dims = {"inherent": q.inherent, "current": q.current} | ({"target": q.target} if q.target else {})
    return QualitativeResult(
        inherent=to_state(q.inherent, "inherent"),
        current=to_state(q.current, "current"),
        target=to_state(q.target, "target") if q.target else None,
        impact_by_dimension={
            state: {dim: rating.level for dim, rating in r.impact.ratings().items()}
            for state, r in dims.items()
        },
    )


def quality_checks(
    scenario: Scenario, model: ScenarioModel, qualitative: QualitativeResult | None
) -> list[Finding]:
    """Checks a second-line reviewer or auditor would perform on an assessment."""
    findings: list[Finding] = []
    credited = model.credited_controls
    assessments = model.control_assessments

    for cid in credited:
        a = assessments[cid]
        if a.conclusion is OperatingConclusion.NOT_TESTED:
            findings.append(
                Finding(
                    severity=Severity.INFO,
                    code="CTL-UNTESTED",
                    message=f"{cid} is credited without operating-effectiveness evidence (prior only).",
                )
            )
        elif a.conclusion is OperatingConclusion.NOT_EFFECTIVE:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    code="CTL-NOT-EFFECTIVE",
                    message=f"{cid} tested NOT effective ({a.exceptions}/{a.samples} exceptions); "
                    "its reduced credit is reflected, but remediation should be tracked.",
                )
            )
    for note in model.notes:
        if "overrides test evidence" in note:
            findings.append(Finding(severity=Severity.WARNING, code="CTL-OVERRIDE", message=note))

    if scenario.selected_treatment is None and scenario.treatments:
        findings.append(
            Finding(
                severity=Severity.INFO,
                code="TRT-NONE-SELECTED",
                message="Treatment options exist but none is selected; target risk is undefined.",
            )
        )

    if qualitative is not None:
        inh, cur = qualitative.inherent, qualitative.current
        if (cur.likelihood < inh.likelihood or cur.impact < inh.impact) and not credited:
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    code="QUAL-UNSUPPORTED-REDUCTION",
                    message="Current risk is rated below inherent, but no implemented control is linked.",
                )
            )
        if cur.likelihood > inh.likelihood or cur.impact > inh.impact:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    code="QUAL-CURRENT-ABOVE-INHERENT",
                    message="Current risk is rated above inherent risk; check the ratings.",
                )
            )
        reduced = cur.likelihood < inh.likelihood or cur.impact < inh.impact
        tested_ok = [cid for cid in credited if assessments[cid].conclusion is OperatingConclusion.EFFECTIVE]
        if reduced and credited and not tested_ok:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    code="QUAL-REDUCTION-UNEVIDENCED",
                    message="Risk reduction is claimed, but none of the credited controls is tested effective.",
                )
            )
        if qualitative.target is not None:
            sel = scenario.selected_treatment
            if sel is None:
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        code="QUAL-TARGET-WITHOUT-TREATMENT",
                        message="A target rating is given but no treatment option is selected.",
                    )
                )
            elif (
                scenario.treatment(sel).type is TreatmentType.RETAIN
                and qualitative.target.risk_level != cur.risk_level
            ):
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        code="QUAL-RETAIN-CHANGES-RISK",
                        message="The selected treatment is 'retain', but the target level differs from current.",
                    )
                )
    if CURRENT not in model.states:  # pragma: no cover - defensive
        findings.append(Finding(severity=Severity.ERROR, code="MODEL", message="No current state"))
    return findings
