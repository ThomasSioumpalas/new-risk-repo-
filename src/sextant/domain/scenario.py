"""Risk scenarios: the unit of the risk register.

The scenario follows the *event-based* approach of ISO/IEC 27005:2022. A threat
source initiates a threat event. The event exploits a vulnerability or
predisposing condition and affects assets, which leads to consequences. For
quantitative analysis the scenario is decomposed along the FAIR ontology:

    Risk (annual loss)
     ├── Loss Event Frequency = Threat Event Frequency × Susceptibility
     └── Loss Magnitude       = Σ primary loss forms
                               + P(secondary loss) × Σ secondary loss forms

Controls are linked to the specific factor they affect. That link is what makes
"which controls reduce this risk, and by how much?" answerable.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sextant.domain.estimates import (
    FrequencyEstimate,
    MagnitudeEstimate,
    ProbabilityEstimate,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ThreatSourceType(StrEnum):
    """Threat source taxonomy of NIST SP 800-30 Rev. 1 (Appendix D)."""

    ADVERSARIAL = "adversarial"
    ACCIDENTAL = "accidental"
    STRUCTURAL = "structural"
    ENVIRONMENTAL = "environmental"


class SecurityProperty(StrEnum):
    CONFIDENTIALITY = "confidentiality"
    INTEGRITY = "integrity"
    AVAILABILITY = "availability"


class RiskCategory(StrEnum):
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    MALWARE = "malware_ransomware"
    DATA_LEAKAGE = "data_leakage"
    THIRD_PARTY = "third_party"
    CLOUD_MISCONFIGURATION = "cloud_misconfiguration"
    SERVICE_AVAILABILITY = "service_availability"
    REGULATORY = "regulatory_compliance"
    AI_SYSTEM = "ai_system"


class LossForm(StrEnum):
    """The six FAIR forms of loss."""

    PRODUCTIVITY = "productivity"
    RESPONSE = "response"
    REPLACEMENT = "replacement"
    FINES_JUDGMENTS = "fines_judgments"
    COMPETITIVE_ADVANTAGE = "competitive_advantage"
    REPUTATION = "reputation"


class ControlTarget(StrEnum):
    """The model factor a control acts on.

    * ``threat_event_frequency``: avoidance and deterrence, e.g. email filtering
      reduces the phishing emails that reach users.
    * ``susceptibility``: resistance, e.g. MFA reduces the probability that a
      stolen password leads to a compromise.
    * ``primary_loss`` / ``secondary_loss``: containment and response, e.g.
      backups reduce outage duration and EDR reduces blast radius.
    * ``secondary_loss_probability``: e.g. a tested notification process reduces
      the chance of a regulatory penalty after a breach.
    """

    THREAT_EVENT_FREQUENCY = "threat_event_frequency"
    SUSCEPTIBILITY = "susceptibility"
    PRIMARY_LOSS = "primary_loss"
    SECONDARY_LOSS = "secondary_loss"
    SECONDARY_LOSS_PROBABILITY = "secondary_loss_probability"

    @property
    def is_frequency(self) -> bool:
        return self in (ControlTarget.THREAT_EVENT_FREQUENCY, ControlTarget.SUSCEPTIBILITY)

    @property
    def is_magnitude(self) -> bool:
        return self in (ControlTarget.PRIMARY_LOSS, ControlTarget.SECONDARY_LOSS)


class TreatmentType(StrEnum):
    """Risk treatment options (ISO/IEC 27005:2022 §8.2; ISO 31000 §6.5)."""

    MODIFY = "modify"  # mitigate: add or improve controls
    SHARE = "share"  # transfer the financial effect, e.g. insurance. Accountability stays.
    AVOID = "avoid"  # stop the activity that gives rise to the risk
    RETAIN = "retain"  # accept by informed decision


class Threat(_Frozen):
    source_type: ThreatSourceType
    source: str = Field(description="e.g. 'Financially motivated cybercriminal group'")
    event: str = Field(description="e.g. 'Deploys ransomware after phishing-based initial access'")


class LossComponent(_Frozen):
    """One form of loss per loss event. Its magnitude is in the methodology currency."""

    name: str = Field(pattern=r"^[a-z0-9_]+$")
    form: LossForm
    magnitude: MagnitudeEstimate
    description: str | None = None


class SecondaryLoss(_Frozen):
    """Losses from secondary stakeholders (regulators, customers, litigants).

    They occur only with probability ``probability`` per primary loss event.
    """

    probability: ProbabilityEstimate
    components: list[LossComponent] = Field(min_length=1, max_length=12)


class ControlEffect(_Frozen):
    """How one control from the library affects this scenario.

    The effective reduction of the targeted factor in a simulation trial is::

        reduction × operating_rate × coverage

    * ``reduction``: the proportional reduction *when the control operates as
      designed* (design strength). This is an expert estimate that should be
      justified in ``rationale``.
    * ``operating_rate``: the probability the control operates when needed.
      If omitted, it is **derived from the control's operating tests** (a
      Beta-Binomial posterior). If there are no tests, the methodology's
      uninformative prior applies, so an untested control gets only uncertain,
      partial credit.
    * ``coverage``: the fraction of the relevant population the control covers,
      e.g. MFA is enforced on 85 % of accounts. This is a measured fact, not an
      estimate.
    """

    control_id: str
    target: ControlTarget
    reduction: ProbabilityEstimate
    operating_rate: ProbabilityEstimate | None = None
    coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    loss_forms: list[LossForm] | None = Field(
        default=None, description="For magnitude targets: restrict the effect to these loss forms."
    )
    rationale: str = Field(min_length=10)

    @model_validator(mode="after")
    def _check_forms(self) -> ControlEffect:
        if self.loss_forms is not None and not self.target.is_magnitude:
            raise ValueError("loss_forms only apply to primary_loss / secondary_loss targets")
        return self


class ControlChange(_Frozen):
    """A treatment that improves an *existing* control rather than adding one."""

    control_id: str
    coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    operating_rate: ProbabilityEstimate | None = None
    rationale: str = Field(min_length=10)


class Insurance(_Frozen):
    """Per-occurrence cyber insurance terms (risk *sharing*).

    The recovery per loss event is ``min(max(insurable_loss − deductible, 0), limit)``.
    Fines and penalties are excluded by default, because they are often
    uninsurable.
    """

    deductible: float = Field(ge=0)
    limit: float = Field(gt=0)
    excluded_forms: list[LossForm] = Field(default_factory=lambda: [LossForm.FINES_JUDGMENTS])


class TreatmentOption(_Frozen):
    id: str
    title: str
    type: TreatmentType
    description: str
    add_controls: list[ControlEffect] = Field(default_factory=list, max_length=20)
    change_controls: list[ControlChange] = Field(default_factory=list, max_length=20)
    insurance: Insurance | None = None
    one_time_cost: float = Field(default=0.0, ge=0)
    annual_cost: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _check_consistency(self) -> TreatmentOption:
        has_change = bool(self.add_controls or self.change_controls)
        if self.type is TreatmentType.MODIFY and not has_change:
            raise ValueError("'modify' treatment must add or change at least one control")
        if self.type is TreatmentType.SHARE and self.insurance is None:
            raise ValueError("'share' treatment must specify the transfer mechanism (insurance)")
        if self.type is TreatmentType.RETAIN and (has_change or self.insurance):
            raise ValueError("'retain' treatment cannot change controls")
        return self


class Rating(_Frozen):
    """A qualitative rating with its mandatory justification."""

    level: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=10)


class ImpactRatings(_Frozen):
    """Impact rated per consequence dimension. The overall impact is the maximum.

    Taking the worst credible consequence avoids a severe regulatory impact being
    diluted by averaging it with minor operational ones.
    """

    financial: Rating | None = None
    operational: Rating | None = None
    legal_regulatory: Rating | None = None
    reputational: Rating | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> ImpactRatings:
        if not self.ratings():
            raise ValueError("at least one impact dimension must be rated")
        return self

    def ratings(self) -> dict[str, Rating]:
        return {
            name: r
            for name, r in (
                ("financial", self.financial),
                ("operational", self.operational),
                ("legal_regulatory", self.legal_regulatory),
                ("reputational", self.reputational),
            )
            if r is not None
        }

    @property
    def overall(self) -> int:
        return max(r.level for r in self.ratings().values())


class QualitativeRatings(_Frozen):
    likelihood: Rating
    impact: ImpactRatings


class QualitativeInput(_Frozen):
    """Analyst ratings for the qualitative (ISO 27005 / SP 800-30) method."""

    inherent: QualitativeRatings
    current: QualitativeRatings
    target: QualitativeRatings | None = None


class Scenario(_Frozen):
    id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]*$")
    title: str
    description: str
    category: RiskCategory
    owner: str = Field(description="Accountable risk owner (role or person).")
    assets: list[str] = Field(min_length=1, max_length=50)
    threat: Threat
    vulnerabilities: list[str] = Field(min_length=1, max_length=50)
    properties: list[SecurityProperty] = Field(min_length=1)

    threat_event_frequency: FrequencyEstimate
    susceptibility: ProbabilityEstimate
    # Upper bounds keep a single request's simulation cost bounded (states × components × events).
    primary_losses: list[LossComponent] = Field(min_length=1, max_length=12)
    secondary_loss: SecondaryLoss | None = None

    controls: list[ControlEffect] = Field(default_factory=list, max_length=40)
    treatments: list[TreatmentOption] = Field(default_factory=list, max_length=15)
    selected_treatment: str | None = Field(
        default=None, description="Treatment option proposed for approval; defines the target state."
    )
    qualitative: QualitativeInput | None = None

    assumptions: list[str] = Field(default_factory=list)
    references: list[str] = Field(
        default_factory=list, description="Framework references, e.g. 'nist_ai_rmf_1_0:MAP-5'."
    )

    @model_validator(mode="after")
    def _check_references(self) -> Scenario:
        names = [c.name for c in self.all_loss_components()]
        if len(names) != len(set(names)):
            raise ValueError("loss component names must be unique within a scenario")
        ids = [t.id for t in self.treatments]
        if len(ids) != len(set(ids)):
            raise ValueError("treatment ids must be unique within a scenario")
        if self.selected_treatment is not None and self.selected_treatment not in ids:
            raise ValueError(f"selected_treatment '{self.selected_treatment}' is not a defined option")
        linked = [c.control_id for c in self.controls]
        for opt in self.treatments:
            for change in opt.change_controls:
                if change.control_id not in linked:
                    raise ValueError(
                        f"treatment '{opt.id}' changes control '{change.control_id}' "
                        "which is not linked to the scenario"
                    )
        return self

    def all_loss_components(self) -> list[LossComponent]:
        secondary = self.secondary_loss.components if self.secondary_loss else []
        return [*self.primary_losses, *secondary]

    def treatment(self, option_id: str) -> TreatmentOption:
        for t in self.treatments:
            if t.id == option_id:
                return t
        raise KeyError(option_id)
