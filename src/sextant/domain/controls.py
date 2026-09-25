"""Control library, control testing and evidence.

This module separates three things that are often mixed up:

* **Control definition**: what the control is, who owns it and whether it is
  implemented.
* **Control testing**: whether it is *designed* adequately (test of design) and
  whether it *operates* as designed over a period (test of operating
  effectiveness, a sample-based test). This is the audit view: ISAE 3402 /
  SOC 2 style design versus operating effectiveness.
* **Evidence**: artefacts with provenance, integrity hash and validity period
  that support a test or an implementation claim.

Framework mappings use the set-theory relationship types of NIST IR 8477, so
that a mapping never implies more coverage than it provides.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ControlType(StrEnum):
    PREVENTIVE = "preventive"
    DETECTIVE = "detective"
    CORRECTIVE = "corrective"


class ImplementationStatus(StrEnum):
    IMPLEMENTED = "implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    PLANNED = "planned"
    NOT_IMPLEMENTED = "not_implemented"

    @property
    def is_in_operation(self) -> bool:
        """Controls that exist today and can therefore reduce *current* risk."""
        return self in (ImplementationStatus.IMPLEMENTED, ImplementationStatus.PARTIALLY_IMPLEMENTED)


class TestKind(StrEnum):
    DESIGN = "design"
    OPERATING = "operating"


class DesignConclusion(StrEnum):
    EFFECTIVE = "effective"
    INEFFECTIVE = "ineffective"


class RelationshipType(StrEnum):
    """How a control relates to a framework requirement (NIST IR 8477 STRM).

    Read it as "the *control* is <relationship> the *requirement*".
    """

    EQUAL = "equal"
    SUPERSET_OF = "superset_of"
    SUBSET_OF = "subset_of"
    INTERSECTS_WITH = "intersects_with"

    @property
    def is_full_coverage(self) -> bool:
        """Only equal and superset relationships can, alone, address a requirement."""
        return self in (RelationshipType.EQUAL, RelationshipType.SUPERSET_OF)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FrameworkMapping(_Frozen):
    framework: str = Field(description="Catalog id, e.g. 'iso27001_2022', 'nist_csf_2_0'.")
    requirement: str = Field(description="Requirement id within the catalog, e.g. 'A.5.15', 'PR.AA-03'.")
    relationship: RelationshipType
    rationale: str | None = None


class ControlTest(_Frozen):
    """A single test performed on a control.

    Operating tests are attribute samples: ``samples`` items were inspected and
    ``exceptions`` of them showed the control not operating as designed.
    """

    id: str | None = None
    kind: TestKind
    performed_on: date
    performed_by: str
    procedure: str = Field(description="Inspection, re-performance, observation, inquiry...")
    samples: int | None = Field(default=None, gt=0)
    exceptions: int | None = Field(default=None, ge=0)
    design_conclusion: DesignConclusion | None = None
    evidence: list[str] = Field(default_factory=list, description="Evidence ids supporting the test.")
    notes: str | None = None

    @model_validator(mode="after")
    def _check_kind(self) -> ControlTest:
        if self.kind is TestKind.OPERATING:
            if self.samples is None or self.exceptions is None:
                raise ValueError("operating test requires 'samples' and 'exceptions'")
            if self.exceptions > self.samples:
                raise ValueError("exceptions cannot exceed samples")
        elif self.design_conclusion is None:
            raise ValueError("design test requires 'design_conclusion'")
        return self


class Control(_Frozen):
    id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]*$")
    name: str
    description: str
    type: ControlType
    owner: str
    status: ImplementationStatus
    mappings: list[FrameworkMapping] = Field(default_factory=list)
    tests: list[ControlTest] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list, description="Evidence ids for implementation.")

    def latest_design_test(self) -> ControlTest | None:
        design = [t for t in self.tests if t.kind is TestKind.DESIGN]
        return max(design, key=lambda t: t.performed_on) if design else None


class EvidenceType(StrEnum):
    DOCUMENT = "document"
    CONFIGURATION = "configuration_export"
    LOG_EXTRACT = "log_extract"
    SCREENSHOT = "screenshot"
    REPORT = "report"
    INTERVIEW = "interview_record"
    TEST_RESULT = "test_result"
    ATTESTATION = "third_party_attestation"


class Evidence(_Frozen):
    """Metadata of an evidence artefact.

    Sextant stores the *metadata and integrity digest*, not the file. The
    artefact stays in the document-management system of record. The SHA-256
    digest lets an auditor verify that the artefact reviewed is the one
    referenced.
    """

    id: str
    title: str
    type: EvidenceType
    collected_on: date
    collected_by: str
    uri: str | None = None
    sha256: str | None = None
    valid_until: date | None = None
    description: str | None = None

    @field_validator("sha256")
    @classmethod
    def _check_digest(cls, v: str | None) -> str | None:
        if v is not None and not _SHA256.match(v):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return v

    def is_current(self, as_of: date) -> bool:
        return self.valid_until is None or self.valid_until >= as_of
