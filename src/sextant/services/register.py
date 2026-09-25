"""Register maintenance: assets, controls (and their tests), evidence, risks, methodology, users.

Every write validates against the domain schema, checks the actor's permission
and appends an audit entry in the same transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from sextant.clock import utc_today
from sextant.db.models import (
    AssetRecord,
    ControlRecord,
    EvidenceRecord,
    MethodologyRecord,
    RiskRecord,
    User,
)
from sextant.domain.controls import Control, ControlTest, Evidence
from sextant.domain.methodology import Methodology, Role, default_methodology
from sextant.domain.register import Asset, RiskRegister
from sextant.domain.scenario import Scenario
from sextant.services import audit
from sextant.services.errors import ConflictError, InvalidRequestError, NotFoundError, PermissionDeniedError
from sextant.services.security import Actor, Permission, generate_api_key, hash_api_key


def now() -> datetime:
    return datetime.now(UTC)


def require(actor: Actor, permission: Permission) -> None:
    if not actor.can(permission):
        raise PermissionDeniedError(f"role '{actor.role.value}' lacks permission '{permission.value}'")


# --- users ----------------------------------------------------------------------------


def create_user(session: Session, actor: Actor | None, username: str, display_name: str, role: Role) -> str:
    """Create a user and return the API key (shown once). ``actor`` None = bootstrap."""
    if actor is not None:
        require(actor, Permission.MANAGE_USERS)
    if session.scalar(select(User).where(User.username == username)) is not None:
        raise ConflictError(f"user '{username}' already exists")
    key = generate_api_key()
    session.add(
        User(
            username=username,
            display_name=display_name,
            role=role.value,
            api_key_hash=hash_api_key(key),
            active=True,
            created_at=now(),
        )
    )
    audit.record(session, actor or "system", "user.created", "user", username, {"role": role.value})
    return key


def authenticate(session: Session, api_key: str) -> Actor | None:
    user = session.scalar(
        select(User).where(User.api_key_hash == hash_api_key(api_key), User.active.is_(True))
    )
    return Actor(user.username, Role(user.role)) if user else None


# --- methodology ----------------------------------------------------------------------


def active_methodology(session: Session) -> Methodology:
    rec = session.scalar(select(MethodologyRecord).where(MethodologyRecord.active.is_(True)))
    if rec is None:
        raise NotFoundError("no active methodology; create one first")
    return Methodology.model_validate(rec.document)


def activate_methodology(session: Session, actor: Actor | str, methodology: Methodology) -> MethodologyRecord:
    """Register a new methodology version and make it active.

    Methodologies are never edited in place. Assessments reference them by
    fingerprint, so a changed methodology must be a new version.
    """
    if isinstance(actor, Actor):
        require(actor, Permission.MANAGE_METHODOLOGY)
    who = actor.username if isinstance(actor, Actor) else actor
    exists = session.scalar(
        select(MethodologyRecord).where(
            MethodologyRecord.key == methodology.id, MethodologyRecord.version == methodology.version
        )
    )
    if exists is not None:
        if exists.fingerprint != methodology.fingerprint:
            raise ConflictError(
                f"methodology {methodology.id} v{methodology.version} already exists with different content; "
                "bump the version"
            )
        rec = exists
    else:
        rec = MethodologyRecord(
            key=methodology.id,
            version=methodology.version,
            fingerprint=methodology.fingerprint,
            document=methodology.model_dump(mode="json"),
            active=False,
            created_by=who,
            created_at=now(),
        )
        session.add(rec)
    for other in session.scalars(select(MethodologyRecord).where(MethodologyRecord.active.is_(True))):
        other.active = False
    rec.active = True
    session.flush()
    audit.record(
        session,
        actor,
        "methodology.activated",
        "methodology",
        f"{methodology.id}@{methodology.version}",
        {"fingerprint": methodology.fingerprint},
    )
    return rec


# --- assets / evidence -----------------------------------------------------------------


def upsert_asset(session: Session, actor: Actor | str, asset: Asset) -> AssetRecord:
    if isinstance(actor, Actor):
        require(actor, Permission.EDIT_REGISTER)
    rec = session.get(AssetRecord, asset.id)
    before = rec.document if rec else None
    doc = asset.model_dump(mode="json")
    who = actor.username if isinstance(actor, Actor) else actor
    if rec is None:
        rec = AssetRecord(id=asset.id, document=doc, updated_by=who, updated_at=now())
        session.add(rec)
    else:
        rec.document, rec.updated_by, rec.updated_at = doc, who, now()
    audit.record(session, actor, "asset.saved", "asset", asset.id, {"before": before, "after": doc})
    return rec


def add_evidence(session: Session, actor: Actor | str, evidence: Evidence) -> EvidenceRecord:
    if isinstance(actor, Actor) and not (
        actor.can(Permission.EDIT_REGISTER) or actor.can(Permission.RECORD_TESTS)
    ):
        raise PermissionDeniedError("recording evidence requires edit_register or record_tests")
    if session.get(EvidenceRecord, evidence.id) is not None:
        raise ConflictError(f"evidence '{evidence.id}' already exists; evidence records are immutable")
    doc = evidence.model_dump(mode="json")
    rec = EvidenceRecord(
        id=evidence.id,
        sha256=evidence.sha256,
        valid_until=evidence.valid_until,
        document=doc,
        created_by=actor.username if isinstance(actor, Actor) else actor,
        created_at=now(),
    )
    session.add(rec)
    audit.record(session, actor, "evidence.recorded", "evidence", evidence.id, {"sha256": evidence.sha256})
    return rec


def list_evidence(session: Session) -> list[Evidence]:
    return [Evidence.model_validate(r.document) for r in session.scalars(select(EvidenceRecord))]


def _check_evidence_refs(session: Session, refs: list[str]) -> None:
    missing = [e for e in refs if session.get(EvidenceRecord, e) is None]
    if missing:
        raise InvalidRequestError(f"unknown evidence: {missing}")


# --- controls ---------------------------------------------------------------------------


def upsert_control(session: Session, actor: Actor | str, control: Control) -> ControlRecord:
    if isinstance(actor, Actor):
        require(actor, Permission.EDIT_REGISTER)
    _check_evidence_refs(session, control.evidence + [e for t in control.tests for e in t.evidence])
    rec = session.get(ControlRecord, control.id)
    before = rec.document if rec else None
    doc = control.model_dump(mode="json")
    who = actor.username if isinstance(actor, Actor) else actor
    if rec is None:
        rec = ControlRecord(
            id=control.id,
            status=control.status.value,
            owner=control.owner,
            document=doc,
            version=1,
            updated_by=who,
            updated_at=now(),
        )
        session.add(rec)
    else:
        if before is not None and before.get("tests") != doc.get("tests"):
            raise ConflictError("control tests are append-only; use the test endpoint to add results")
        rec.status, rec.owner, rec.document = control.status.value, control.owner, doc
        rec.version += 1
        rec.updated_by, rec.updated_at = who, now()
    audit.record(session, actor, "control.saved", "control", control.id, {"before": before, "after": doc})
    return rec


def add_control_test(session: Session, actor: Actor, control_id: str, test: ControlTest) -> Control:
    """Append a test result. Past results are never edited (they are evidence)."""
    require(actor, Permission.RECORD_TESTS)
    rec = session.get(ControlRecord, control_id)
    if rec is None:
        raise NotFoundError(f"control '{control_id}' not found")
    _check_evidence_refs(session, test.evidence)
    control = Control.model_validate(rec.document)
    updated = Control.model_validate(
        {
            **control.model_dump(mode="json"),
            "tests": [
                *[t.model_dump(mode="json") for t in control.tests],
                test.model_dump(mode="json"),
            ],
        }
    )
    rec.document = updated.model_dump(mode="json")
    rec.version += 1
    rec.updated_by, rec.updated_at = actor.username, now()
    audit.record(session, actor, "control.test_recorded", "control", control_id, test.model_dump(mode="json"))
    return updated


def get_control(session: Session, control_id: str) -> Control:
    rec = session.get(ControlRecord, control_id)
    if rec is None:
        raise NotFoundError(f"control '{control_id}' not found")
    return Control.model_validate(rec.document)


def control_library(session: Session) -> dict[str, Control]:
    return {r.id: Control.model_validate(r.document) for r in session.scalars(select(ControlRecord))}


# --- risks ------------------------------------------------------------------------------


def _check_scenario_refs(session: Session, scenario: Scenario) -> None:
    missing_assets = [a for a in scenario.assets if session.get(AssetRecord, a) is None]
    refs = [e.control_id for e in scenario.controls] + [
        e.control_id for t in scenario.treatments for e in t.add_controls
    ]
    missing_controls = sorted({c for c in refs if session.get(ControlRecord, c) is None})
    if missing_assets or missing_controls:
        raise InvalidRequestError(f"unknown assets {missing_assets} / controls {missing_controls}")


def create_risk(session: Session, actor: Actor | str, scenario: Scenario) -> RiskRecord:
    if isinstance(actor, Actor):
        require(actor, Permission.EDIT_REGISTER)
    if session.get(RiskRecord, scenario.id) is not None:
        raise ConflictError(f"risk '{scenario.id}' already exists")
    _check_scenario_refs(session, scenario)
    who = actor.username if isinstance(actor, Actor) else actor
    doc = scenario.model_dump(mode="json")
    rec = RiskRecord(
        id=scenario.id,
        title=scenario.title,
        owner=scenario.owner,
        category=scenario.category.value,
        status="identified",
        document=doc,
        version=1,
        created_by=who,
        created_at=now(),
        updated_by=who,
        updated_at=now(),
    )
    session.add(rec)
    audit.record(session, actor, "risk.created", "risk", scenario.id, {"after": doc})
    return rec


def update_risk(session: Session, actor: Actor, scenario: Scenario, expected_version: int) -> RiskRecord:
    """Replace the scenario definition, using optimistic concurrency (lost-update protection)."""
    require(actor, Permission.EDIT_REGISTER)
    rec = get_risk_record(session, scenario.id)
    if rec.version != expected_version:
        raise ConflictError(f"risk '{scenario.id}' was modified (version {rec.version}); reload and retry")
    _check_scenario_refs(session, scenario)
    before = rec.document
    doc = scenario.model_dump(mode="json")
    rec.document, rec.title, rec.owner, rec.category = (
        doc,
        scenario.title,
        scenario.owner,
        scenario.category.value,
    )
    rec.version += 1
    rec.updated_by, rec.updated_at = actor.username, now()
    audit.record(session, actor, "risk.updated", "risk", scenario.id, {"before": before, "after": doc})
    return rec


def get_risk_record(session: Session, risk_id: str) -> RiskRecord:
    rec = session.get(RiskRecord, risk_id)
    if rec is None:
        raise NotFoundError(f"risk '{risk_id}' not found")
    return rec


def get_scenario(session: Session, risk_id: str) -> Scenario:
    return Scenario.model_validate(get_risk_record(session, risk_id).document)


def list_risks(session: Session) -> list[RiskRecord]:
    return list(session.scalars(select(RiskRecord).order_by(RiskRecord.id)))


def list_assets(session: Session) -> list[Asset]:
    return [
        Asset.model_validate(r.document)
        for r in session.scalars(select(AssetRecord).order_by(AssetRecord.id))
    ]


# --- bulk import ------------------------------------------------------------------------


def import_register(
    session: Session, actor: str, register: RiskRegister, methodology: Methodology | None = None
) -> dict[str, Any]:
    """Load a risk-as-code register into an empty database (used for demos and migrations)."""
    activate_methodology(session, actor, methodology or default_methodology())
    for ev in register.evidence:
        add_evidence(session, actor, ev)
    for asset in register.assets:
        upsert_asset(session, actor, asset)
    for control in register.controls:
        upsert_control(session, actor, control)
    session.flush()
    for scenario in register.scenarios:
        create_risk(session, actor, scenario)
    return {
        "assets": len(register.assets),
        "controls": len(register.controls),
        "evidence": len(register.evidence),
        "risks": len(register.scenarios),
        "imported_on": utc_today().isoformat(),
    }
