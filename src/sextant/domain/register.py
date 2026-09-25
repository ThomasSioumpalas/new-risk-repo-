"""The risk register as a whole: organisation, assets, controls, evidence, scenarios.

A register can be written as YAML ("risk-as-code") and version-controlled,
or held in the database behind the API. The same validation applies to both.
Cross-references (a scenario naming an asset, a test citing evidence) are
checked here, so a broken reference is caught when the register is loaded, not
during an audit.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sextant.domain.controls import Control, Evidence
from sextant.domain.methodology import Methodology, default_methodology, load_methodology
from sextant.domain.scenario import Scenario


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssetType(StrEnum):
    BUSINESS_PROCESS = "business_process"
    INFORMATION = "information"
    APPLICATION = "application"
    INFRASTRUCTURE = "infrastructure"
    CLOUD_SERVICE = "cloud_service"
    SUPPLIER = "supplier"
    AI_SYSTEM = "ai_system"
    PEOPLE = "people"


class Rating3(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Asset(_Frozen):
    """A primary (business process, information) or supporting asset (ISO/IEC 27005)."""

    id: str
    name: str
    type: AssetType
    owner: str
    description: str
    classification: str | None = None
    confidentiality: Rating3
    integrity: Rating3
    availability: Rating3
    contains_personal_data: bool = False


class Organization(_Frozen):
    name: str
    description: str
    sector: str
    jurisdiction: str
    annual_revenue: float | None = None
    fictional: bool = True


class Exclusion(_Frozen):
    """A requirement declared not applicable, with justification (as in an SoA)."""

    framework: str
    requirement: str
    justification: str = Field(min_length=20)
    approved_by: str


class RiskRegister(_Frozen):
    organization: Organization
    assets: list[Asset]
    controls: list[Control]
    evidence: list[Evidence] = Field(default_factory=list)
    scenarios: list[Scenario]
    exclusions: list[Exclusion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> RiskRegister:
        def unique(ids: list[str], what: str) -> set[str]:
            if len(ids) != len(set(ids)):
                dupes = sorted({i for i in ids if ids.count(i) > 1})
                raise ValueError(f"duplicate {what} ids: {dupes}")
            return set(ids)

        assets = unique([a.id for a in self.assets], "asset")
        controls = unique([c.id for c in self.controls], "control")
        evidence = unique([e.id for e in self.evidence], "evidence")
        unique([s.id for s in self.scenarios], "scenario")
        problems: list[str] = []
        for s in self.scenarios:
            problems += [f"{s.id}: unknown asset '{a}'" for a in s.assets if a not in assets]
            refs = [e.control_id for e in s.controls] + [
                e.control_id for t in s.treatments for e in t.add_controls
            ]
            problems += [f"{s.id}: unknown control '{c}'" for c in refs if c not in controls]
        for c in self.controls:
            problems += [f"{c.id}: unknown evidence '{e}'" for e in c.evidence if e not in evidence]
            for t in c.tests:
                problems += [f"{c.id} test: unknown evidence '{e}'" for e in t.evidence if e not in evidence]
        if problems:
            raise ValueError("broken references:\n  " + "\n  ".join(problems))
        return self

    def control_map(self) -> dict[str, Control]:
        return {c.id: c for c in self.controls}

    def evidence_map(self) -> dict[str, Evidence]:
        return {e.id: e for e in self.evidence}

    def scenario(self, sid: str) -> Scenario:
        for s in self.scenarios:
            if s.id == sid:
                return s
        raise KeyError(sid)


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text("utf-8"))


def load_register(directory: str | Path) -> tuple[RiskRegister, Methodology]:
    """Load a register directory.

    Layout::

        methodology.yaml        (optional; the reference methodology is used otherwise)
        organization.yaml
        assets.yaml             (list)
        controls.yaml           (list)
        evidence.yaml           (list, optional)
        exclusions.yaml         (list, optional)
        scenarios/*.yaml        (one scenario per file)
    """
    root = Path(directory)
    methodology_file = root / "methodology.yaml"
    methodology = (
        load_methodology(_read_yaml(methodology_file)) if methodology_file.exists() else default_methodology()
    )

    def optional_list(name: str) -> list[Any]:
        path = root / name
        return list(_read_yaml(path) or []) if path.exists() else []

    register = RiskRegister.model_validate(
        {
            "organization": _read_yaml(root / "organization.yaml"),
            "assets": _read_yaml(root / "assets.yaml"),
            "controls": _read_yaml(root / "controls.yaml"),
            "evidence": optional_list("evidence.yaml"),
            "exclusions": optional_list("exclusions.yaml"),
            "scenarios": [_read_yaml(p) for p in sorted((root / "scenarios").glob("*.yaml"))],
        }
    )
    return register, methodology
