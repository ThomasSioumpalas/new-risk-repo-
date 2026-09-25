"""Treatment approval, risk acceptance and monitoring.

Rules enforced in code, because a policy that only lives in a document is not
enforced:

* **Authority**: the acceptor's role must carry at least the authority that the
  methodology requires for the assessed level. Retaining a risk outside
  appetite escalates the requirement (see ``Evaluation.acceptance_authority``).
* **Segregation of duties**: the person who performed or finalised the
  assessment cannot accept its residual risk or approve its treatment.
* **Time limit**: an acceptance expires after at most the period set by the
  methodology for that level.
* **Specificity**: an acceptance refers to one *final* assessment. A later
  assessment with a higher level invalidates it automatically (see
  ``assessments.finalize``).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from sextant.clock import utc_today
from sextant.db.models import AssessmentRecord, RiskAcceptance, RiskRecord, TreatmentApproval
from sextant.domain.methodology import Methodology, Role
from sextant.services import audit
from sextant.services.assessments import get_assessment, latest_final, result_of
from sextant.services.errors import ConflictError, InvalidRequestError, NotFoundError, PermissionDeniedError
from sextant.services.register import get_risk_record, list_evidence, now, require
from sextant.services.security import Actor, Permission

MIN_JUSTIFICATION = 30


def _assert_segregation(actor: Actor, assessment: AssessmentRecord, what: str) -> None:
    involved = {assessment.assessed_by, assessment.finalized_by, assessment.override_by} - {None}
    if actor.username in involved:
        raise PermissionDeniedError(
            f"segregation of duties: {actor.username} prepared or finalised this assessment and cannot {what}"
        )


def _final_current(session: Session, risk_id: str, assessment_id: str) -> AssessmentRecord:
    rec = get_assessment(session, assessment_id)
    if rec.risk_id != risk_id:
        raise InvalidRequestError("assessment does not belong to this risk")
    if rec.status != "final":
        raise ConflictError("decisions must reference a finalised assessment")
    latest = latest_final(session, risk_id)
    if latest is None or latest.id != rec.id:
        raise ConflictError("a newer assessment exists; decide on the latest one")
    return rec


def approve_treatment(
    session: Session, actor: Actor, risk_id: str, assessment_id: str, option_id: str, comment: str
) -> TreatmentApproval:
    """Risk-owner approval of the treatment plan (ISO/IEC 27001 6.1.3 f)."""
    require(actor, Permission.APPROVE_TREATMENT)
    rec = _final_current(session, risk_id, assessment_id)
    _assert_segregation(actor, rec, "approve its treatment plan")
    result = result_of(rec)
    if option_id not in {o.option_id for o in result.options}:
        raise InvalidRequestError(f"option '{option_id}' was not evaluated in this assessment")
    approval = TreatmentApproval(
        id=str(uuid.uuid4()),
        risk_id=risk_id,
        assessment_id=assessment_id,
        option_id=option_id,
        approved_by=actor.username,
        approved_at=now(),
        comment=comment,
    )
    session.add(approval)
    get_risk_record(session, risk_id).status = "treatment_planned"
    audit.record(
        session,
        actor,
        "treatment.approved",
        "risk",
        risk_id,
        {"assessment_id": assessment_id, "option": option_id},
    )
    return approval


def accept_risk(
    session: Session,
    actor: Actor,
    risk_id: str,
    assessment_id: str,
    justification: str,
    conditions: str | None = None,
    duration_days: int | None = None,
) -> RiskAcceptance:
    require(actor, Permission.ACCEPT_RISK)
    rec = _final_current(session, risk_id, assessment_id)
    _assert_segregation(actor, rec, "accept its residual risk")
    if len(justification.strip()) < MIN_JUSTIFICATION:
        raise InvalidRequestError(
            f"acceptance needs a justification of at least {MIN_JUSTIFICATION} characters"
        )

    methodology = Methodology.model_validate(rec.inputs["methodology"])
    result = result_of(rec)
    level = rec.effective_level
    rule = methodology.acceptance_rule(level)
    required = max(rule.min_authority, result.evaluation.acceptance_authority, key=lambda r: r.authority_rank)
    if actor.role.authority_rank < required.authority_rank:
        raise PermissionDeniedError(
            f"accepting a '{level}' risk{'' if result.evaluation.within_appetite else ' outside appetite'} "
            f"requires '{required.value}' authority; '{actor.role.value}' is insufficient"
        )
    max_days = rule.max_acceptance_days
    days = min(duration_days or max_days, max_days)
    acc = RiskAcceptance(
        id=str(uuid.uuid4()),
        risk_id=risk_id,
        assessment_id=assessment_id,
        accepted_level=level,
        accepted_ale=rec.current_ale,
        required_authority=required.value,
        accepted_by=actor.username,
        accepted_role=actor.role.value,
        accepted_at=now(),
        expires_on=utc_today() + timedelta(days=days),
        justification=justification.strip(),
        conditions=conditions,
        status="active",
    )
    session.add(acc)
    risk = get_risk_record(session, risk_id)
    risk.status = "accepted"
    audit.record(
        session,
        actor,
        "risk.accepted",
        "risk",
        risk_id,
        {
            "acceptance_id": acc.id,
            "assessment_id": assessment_id,
            "level": level,
            "ale": rec.current_ale,
            "required_authority": required.value,
            "expires_on": acc.expires_on.isoformat(),
            "within_appetite": result.evaluation.within_appetite,
        },
    )
    return acc


def revoke_acceptance(session: Session, actor: Actor, acceptance_id: str, reason: str) -> RiskAcceptance:
    require(actor, Permission.ACCEPT_RISK)
    acc = session.get(RiskAcceptance, acceptance_id)
    if acc is None:
        raise NotFoundError(f"acceptance '{acceptance_id}' not found")
    if acc.status != "active":
        raise ConflictError(f"acceptance is {acc.status}")
    if actor.role.authority_rank < Role(acc.required_authority).authority_rank:
        raise PermissionDeniedError("revocation requires the same authority as acceptance")
    acc.status, acc.closed_by, acc.closed_at, acc.closed_reason = "revoked", actor.username, now(), reason
    get_risk_record(session, acc.risk_id).status = "assessed"
    audit.record(
        session,
        actor,
        "risk.acceptance_revoked",
        "risk",
        acc.risk_id,
        {"acceptance_id": acc.id, "reason": reason},
    )
    return acc


def acceptance_status(acc: RiskAcceptance, today: date | None = None) -> str:
    """Effective status: an active acceptance past its expiry date is reported as expired."""
    if acc.status == "active" and acc.expires_on < (today or utc_today()):
        return "expired"
    return acc.status


def list_acceptances(session: Session, risk_id: str) -> list[RiskAcceptance]:
    return list(
        session.scalars(
            select(RiskAcceptance)
            .where(RiskAcceptance.risk_id == risk_id)
            .order_by(RiskAcceptance.accepted_at)
        )
    )


class MonitoringItem(BaseModel):
    kind: str
    entity_id: str
    due: date | None
    message: str


def monitoring(session: Session, horizon_days: int = 30, today: date | None = None) -> list[MonitoringItem]:
    """What needs attention: reviews due, acceptances expiring, evidence going stale, unassessed risks."""
    today = today or utc_today()
    horizon = today + timedelta(days=horizon_days)
    items: list[MonitoringItem] = []
    for risk in session.scalars(select(RiskRecord).order_by(RiskRecord.id)):
        if risk.next_review_due is None:
            items.append(
                MonitoringItem(
                    kind="not_assessed",
                    entity_id=risk.id,
                    due=None,
                    message="Risk has no finalised assessment.",
                )
            )
        elif risk.next_review_due <= horizon:
            state = "overdue" if risk.next_review_due < today else "due"
            items.append(
                MonitoringItem(
                    kind=f"review_{state}",
                    entity_id=risk.id,
                    due=risk.next_review_due,
                    message=f"Periodic review {state} (ISO/IEC 27001 8.2).",
                )
            )
    for acc in session.scalars(select(RiskAcceptance).where(RiskAcceptance.status == "active")):
        if acc.expires_on <= horizon:
            items.append(
                MonitoringItem(
                    kind="acceptance_expiring",
                    entity_id=acc.risk_id,
                    due=acc.expires_on,
                    message=f"Acceptance {acc.id[:8]} expires; re-assess and re-decide.",
                )
            )
    for ev in list_evidence(session):
        if ev.valid_until is not None and ev.valid_until <= horizon:
            state = "expired" if ev.valid_until < today else "expiring"
            items.append(
                MonitoringItem(
                    kind=f"evidence_{state}",
                    entity_id=ev.id,
                    due=ev.valid_until,
                    message=f"Evidence '{ev.title}' {state}; controls relying on it lose credit.",
                )
            )
    return sorted(items, key=lambda i: (i.due or date.min, i.kind))
