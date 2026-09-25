"""Risk methodology: versioned risk criteria (ISO/IEC 27001 6.1.2 a, ISO 31000 6.3.4).

Scales, matrix, appetite, acceptance authority, review cycles and simulation
settings are **data, not code**. A methodology is identified by a version and a
SHA-256 fingerprint of its canonical JSON form. Every assessment records the
fingerprint, so an auditor can see exactly which criteria were applied.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from functools import cached_property
from importlib import resources
from itertools import pairwise
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Role(StrEnum):
    """Roles known to the governance layer.

    ``authority_rank`` is the risk-acceptance authority. The administrator has
    **no** acceptance authority: technical privilege is not business
    accountability. That is a segregation-of-duties decision.
    """

    VIEWER = "viewer"
    AUDITOR = "auditor"
    ANALYST = "analyst"
    CONTROL_OWNER = "control_owner"
    RISK_OWNER = "risk_owner"
    RISK_MANAGER = "risk_manager"
    EXECUTIVE = "executive"
    ADMIN = "admin"

    @property
    def authority_rank(self) -> int:
        return {Role.RISK_OWNER: 1, Role.RISK_MANAGER: 2, Role.EXECUTIVE: 3}.get(self, 0)


class ScaleLevel(_Frozen):
    level: int = Field(ge=1, le=5)
    name: str
    lower: float = Field(ge=0, description="Inclusive lower bound of the band.")
    upper: float | None = Field(default=None, description="Exclusive upper bound; None = unbounded.")
    description: str


class ImpactLevel(ScaleLevel):
    descriptors: dict[str, str] = Field(
        default_factory=dict,
        description="Non-financial descriptors per dimension (operational, legal_regulatory, ...).",
    )


def _check_contiguous(levels: list[ScaleLevel] | list[ImpactLevel], what: str) -> None:
    if [lv.level for lv in levels] != [1, 2, 3, 4, 5]:
        raise ValueError(f"{what}: exactly five levels 1..5 in order are required")
    for lo, hi in pairwise(levels):
        if lo.upper is None or lo.upper != hi.lower:
            raise ValueError(
                f"{what}: bands must be contiguous (level {lo.level} upper == level {hi.level} lower)"
            )
    if levels[0].lower != 0 or levels[-1].upper is not None:
        raise ValueError(f"{what}: bands must start at 0 and the top band must be unbounded")


class AcceptanceRule(_Frozen):
    risk_level: str
    min_authority: Role
    max_acceptance_days: int = Field(gt=0)
    review_every_days: int = Field(gt=0)


class TolerancePoint(_Frozen):
    """A point on the portfolio loss-exceedance tolerance curve.

    For example: "at most a 5 % chance per year of losing ≥ €5M"."""

    loss: float = Field(gt=0)
    max_probability: float = Field(gt=0, lt=1)


class Appetite(_Frozen):
    scenario_ale_threshold: float = Field(
        gt=0, description="Expected annual loss above which a single scenario is outside appetite."
    )
    max_acceptable_level: str = Field(description="Highest risk level acceptable without treatment.")
    tolerance_curve: list[TolerancePoint] = Field(min_length=1)


class SimulationSettings(_Frozen):
    trials: int = Field(default=20_000, ge=1_000)
    max_trials: int = Field(default=200_000, ge=1_000)
    seed: int = Field(default=20_260_101, ge=0)
    loss_component_correlation: float = Field(
        default=0.5,
        ge=0.0,
        lt=1.0,
        description="One-factor Gaussian-copula correlation between loss forms of the same event.",
    )
    max_simulated_events: int = Field(default=8_000_000, gt=0)
    cost_amortisation_years: float = Field(default=3.0, gt=0)


class ControlTestingPolicy(_Frozen):
    tolerable_deviation_rate: float = Field(default=0.10, gt=0, lt=1)
    required_confidence: float = Field(default=0.90, gt=0.5, lt=1)
    lookback_days: int = Field(default=365, gt=0)
    prior_alpha: float = Field(default=1.0, gt=0, description="Prior on the operating rate.")
    prior_beta: float = Field(default=1.0, gt=0)


class Methodology(_Frozen):
    id: str
    version: str
    name: str
    owner: str
    currency: str = Field(min_length=3, max_length=3)
    likelihood_scale: list[ScaleLevel] = Field(
        description="Bands on expected loss events per year (loss event frequency)."
    )
    impact_scale: list[ImpactLevel] = Field(description="Bands on expected loss per event.")
    risk_levels: list[str] = Field(min_length=2, description="Ordered lowest → highest.")
    matrix: list[list[str]] = Field(
        description="matrix[likelihood-1][impact-1] → risk level name. Row 0 = likelihood 1."
    )
    acceptance: list[AcceptanceRule]
    appetite: Appetite
    simulation: SimulationSettings = SimulationSettings()
    control_testing: ControlTestingPolicy = ControlTestingPolicy()
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Methodology:
        _check_contiguous(self.likelihood_scale, "likelihood_scale")
        _check_contiguous(self.impact_scale, "impact_scale")
        if len(self.matrix) != 5 or any(len(row) != 5 for row in self.matrix):
            raise ValueError("matrix must be 5x5")
        levels = set(self.risk_levels)
        if unknown := {cell for row in self.matrix for cell in row} - levels:
            raise ValueError(f"matrix uses undefined risk levels: {sorted(unknown)}")
        # Monotonicity: more likely or more severe must never yield a *lower* risk.
        rank = {name: i for i, name in enumerate(self.risk_levels)}
        for li in range(5):
            for ii in range(5):
                here = rank[self.matrix[li][ii]]
                if li < 4 and rank[self.matrix[li + 1][ii]] < here:
                    raise ValueError("matrix must be non-decreasing in likelihood")
                if ii < 4 and rank[self.matrix[li][ii + 1]] < here:
                    raise ValueError("matrix must be non-decreasing in impact")
        if {r.risk_level for r in self.acceptance} != levels:
            raise ValueError("acceptance rules must cover every risk level exactly once")
        if len(self.acceptance) != len(levels):
            raise ValueError("duplicate acceptance rule")
        if self.appetite.max_acceptable_level not in levels:
            raise ValueError("appetite.max_acceptable_level must be a defined risk level")
        losses = [p.loss for p in self.appetite.tolerance_curve]
        probs = [p.max_probability for p in self.appetite.tolerance_curve]
        if losses != sorted(losses) or probs != sorted(probs, reverse=True):
            raise ValueError("tolerance curve: losses increasing and probabilities decreasing")
        return self

    # --- helpers --------------------------------------------------------------------

    def level_rank(self, level: str) -> int:
        return self.risk_levels.index(level)

    def acceptance_rule(self, level: str) -> AcceptanceRule:
        return next(r for r in self.acceptance if r.risk_level == level)

    def within_appetite(self, level: str) -> bool:
        return self.level_rank(level) <= self.level_rank(self.appetite.max_acceptable_level)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    @cached_property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


def load_methodology(data: dict[str, Any]) -> Methodology:
    return Methodology.model_validate(data)


def default_methodology() -> Methodology:
    """The reference methodology shipped with the package."""
    text = resources.files("sextant.domain").joinpath("default_methodology.yaml").read_text("utf-8")
    return load_methodology(yaml.safe_load(text))
