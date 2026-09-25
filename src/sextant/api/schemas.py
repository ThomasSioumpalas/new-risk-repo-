"""API request and response models.

Domain models (Scenario, Control, Evidence, Asset, Methodology, results) are
reused directly. The API adds only workflow envelopes and summaries.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sextant.domain.scenario import Scenario
from sextant.engine.assessment import QuantitativeAssessment
from sextant.engine.sensitivity import StressTest


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    error: str
    message: str


class RiskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(description="Version you edited (optimistic concurrency).")
    scenario: Scenario


class LatestAssessment(BaseModel):
    assessment_id: str
    effective_level: str
    current_ale: float
    as_of: date


class RiskSummary(_Out):
    id: str
    title: str
    owner: str
    category: str
    status: str
    version: int
    next_review_due: date | None
    latest: LatestAssessment | None = None


class RiskDetail(RiskSummary):
    scenario: Scenario


class AssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date | None = None
    trials: int | None = Field(default=None, ge=1_000)
    seed: int | None = Field(default=None, ge=0)


class AssessmentSummary(_Out):
    id: str
    risk_id: str
    status: str
    as_of: date
    trials: int
    seed: int
    engine_version: str
    methodology_fingerprint: str
    inputs_fingerprint: str
    result_fingerprint: str
    computed_level: str
    override_level: str | None
    override_justification: str | None
    override_by: str | None
    effective_level: str
    current_ale: float
    assessed_by: str
    created_at: datetime
    finalized_by: str | None
    finalized_at: datetime | None
    supersedes_id: str | None


class AssessmentDetail(AssessmentSummary):
    result: QuantitativeAssessment


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str
    justification: str = Field(min_length=30)


class TreatmentApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str
    option_id: str
    comment: str = Field(min_length=5)


class TreatmentApprovalOut(_Out):
    id: str
    risk_id: str
    assessment_id: str
    option_id: str
    approved_by: str
    approved_at: datetime
    comment: str


class AcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str
    justification: str = Field(min_length=30)
    conditions: str | None = None
    duration_days: int | None = Field(default=None, gt=0)


class AcceptanceOut(_Out):
    id: str
    risk_id: str
    assessment_id: str
    accepted_level: str
    accepted_ale: float
    required_authority: str
    accepted_by: str
    accepted_role: str
    accepted_at: datetime
    expires_on: date
    justification: str
    conditions: str | None
    status: str
    effective_status: str
    closed_by: str | None
    closed_reason: str | None


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10)


class WhatIfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Scenario
    stress_tests: list[StressTest] = Field(default_factory=list)
    trials: int = Field(default=10_000, ge=1_000)
    seed: int | None = Field(default=None, ge=0)
    as_of: date | None = None


class AuditEntryOut(_Out):
    seq: int
    ts: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str


class Me(BaseModel):
    username: str
    role: str
    permissions: list[str]
