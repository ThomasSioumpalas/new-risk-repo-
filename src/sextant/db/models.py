"""Relational schema.

Design choice: the domain objects (scenario, control, evidence, methodology) are
stored as **validated JSON documents** next to a few relational columns used for
querying and integrity. The Pydantic domain schema therefore stays the single
source of truth for the structure. The database adds identity, history,
workflow state and constraints.

Governance-relevant tables (assessments, acceptances, approvals, audit log)
are fully relational. Finalised assessments and audit entries are never
updated in place. For the audit log, triggers in the migration enforce this.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MethodologyRecord(Base):
    __tablename__ = "methodologies"
    __table_args__ = (UniqueConstraint("key", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssetRecord(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ControlRecord(Base):
    __tablename__ = "controls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    owner: Mapped[str] = mapped_column(String(128))
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvidenceRecord(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskRecord(Base):
    """A register entry. ``document`` holds the validated scenario (risk-as-code)."""

    __tablename__ = "risks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    owner: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="identified")
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    next_review_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssessmentRecord(Base):
    """An assessment run. Immutable once ``status`` is 'final'."""

    __tablename__ = "assessments"
    __table_args__ = (Index("ix_assessments_risk_status", "risk_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    risk_id: Mapped[str] = mapped_column(ForeignKey("risks.id"))
    status: Mapped[str] = mapped_column(String(16))  # draft | final | superseded
    as_of: Mapped[date] = mapped_column(Date)
    trials: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    engine_version: Mapped[str] = mapped_column(String(16))
    methodology_fingerprint: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON)
    inputs_fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_fingerprint: Mapped[str] = mapped_column(String(64))
    computed_level: Mapped[str] = mapped_column(String(32))
    current_ale: Mapped[float]
    override_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    override_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assessed_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finalized_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    @property
    def effective_level(self) -> str:
        return self.override_level or self.computed_level


class TreatmentApproval(Base):
    """Risk-owner approval of a treatment plan (ISO/IEC 27001 6.1.3 f)."""

    __tablename__ = "treatment_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    risk_id: Mapped[str] = mapped_column(ForeignKey("risks.id"))
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"))
    option_id: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[str] = mapped_column(String(64))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str] = mapped_column(Text)


class RiskAcceptance(Base):
    __tablename__ = "risk_acceptances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    risk_id: Mapped[str] = mapped_column(ForeignKey("risks.id"))
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"))
    accepted_level: Mapped[str] = mapped_column(String(32))
    accepted_ale: Mapped[float]
    required_authority: Mapped[str] = mapped_column(String(32))
    accepted_by: Mapped[str] = mapped_column(String(64))
    accepted_role: Mapped[str] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_on: Mapped[date] = mapped_column(Date)
    justification: Mapped[str] = mapped_column(Text)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # active | revoked | invalidated
    closed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditHead(Base):
    """Single-row table holding the tip of the hash chain; locked to serialise appends."""

    __tablename__ = "audit_head"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer)
    last_hash: Mapped[str] = mapped_column(String(64))


class AuditEntry(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
