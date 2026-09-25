"""Assessment, treatment and acceptance workflow endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from sextant.api.deps import ActorDep, SessionDep, SettingsDep
from sextant.api.schemas import (
    AcceptanceOut,
    AcceptanceRequest,
    AssessmentCreate,
    AssessmentDetail,
    AssessmentSummary,
    OverrideRequest,
    RevokeRequest,
    TreatmentApprovalOut,
    TreatmentApprovalRequest,
)
from sextant.db.models import AssessmentRecord, RiskAcceptance
from sextant.engine.explain import Explanation
from sextant.services import assessments as svc
from sextant.services import governance
from sextant.services.assessments import Reproduction
from sextant.services.errors import NotFoundError
from sextant.services.register import get_risk_record, require
from sextant.services.security import Permission

router = APIRouter(prefix="/api/v1", tags=["workflow"])


def _summary(rec: AssessmentRecord) -> AssessmentSummary:
    return AssessmentSummary.model_validate(rec)


def _acceptance(acc: RiskAcceptance) -> AcceptanceOut:
    data = {name: getattr(acc, name) for name in AcceptanceOut.model_fields if name != "effective_status"}
    return AcceptanceOut(**data, effective_status=governance.acceptance_status(acc))


@router.post(
    "/risks/{risk_id}/assessments", response_model=AssessmentSummary, status_code=status.HTTP_201_CREATED
)
def create_assessment(
    risk_id: str, body: AssessmentCreate, actor: ActorDep, session: SessionDep, settings: SettingsDep
) -> AssessmentSummary:
    rec = svc.create_assessment(
        session,
        actor,
        risk_id,
        as_of=body.as_of,
        trials=body.trials,
        seed=body.seed,
        max_trials=settings.api_max_trials,
        max_events=settings.api_max_events,
    )
    return _summary(rec)


@router.get("/risks/{risk_id}/assessments", response_model=list[AssessmentSummary])
def list_assessments(risk_id: str, actor: ActorDep, session: SessionDep) -> list[AssessmentSummary]:
    require(actor, Permission.READ)
    get_risk_record(session, risk_id)
    return [_summary(r) for r in svc.list_assessments(session, risk_id)]


@router.get("/assessments/{assessment_id}", response_model=AssessmentDetail)
def get_assessment(assessment_id: str, actor: ActorDep, session: SessionDep) -> AssessmentDetail:
    require(actor, Permission.READ)
    rec = svc.get_assessment(session, assessment_id)
    return AssessmentDetail(**_summary(rec).model_dump(), result=svc.result_of(rec))


@router.get("/assessments/{assessment_id}/explanation", response_model=Explanation)
def get_explanation(assessment_id: str, actor: ActorDep, session: SessionDep) -> Explanation:
    require(actor, Permission.READ)
    result = svc.result_of(svc.get_assessment(session, assessment_id))
    if result.explanation is None:  # pragma: no cover - run_assessment always sets it
        raise NotFoundError("assessment has no explanation")
    return result.explanation


@router.post("/assessments/{assessment_id}/override", response_model=AssessmentSummary)
def override(
    assessment_id: str, body: OverrideRequest, actor: ActorDep, session: SessionDep
) -> AssessmentSummary:
    return _summary(svc.override_level(session, actor, assessment_id, body.level, body.justification))


@router.post("/assessments/{assessment_id}/finalize", response_model=AssessmentSummary)
def finalize(assessment_id: str, actor: ActorDep, session: SessionDep) -> AssessmentSummary:
    return _summary(svc.finalize(session, actor, assessment_id))


@router.post("/assessments/{assessment_id}/reproduce", response_model=Reproduction)
def reproduce(assessment_id: str, actor: ActorDep, session: SessionDep) -> Reproduction:
    return svc.reproduce(session, actor, assessment_id)


@router.post(
    "/risks/{risk_id}/treatment-approvals",
    response_model=TreatmentApprovalOut,
    status_code=status.HTTP_201_CREATED,
)
def approve_treatment(
    risk_id: str, body: TreatmentApprovalRequest, actor: ActorDep, session: SessionDep
) -> TreatmentApprovalOut:
    approval = governance.approve_treatment(
        session, actor, risk_id, body.assessment_id, body.option_id, body.comment
    )
    return TreatmentApprovalOut.model_validate(approval)


@router.post(
    "/risks/{risk_id}/acceptances", response_model=AcceptanceOut, status_code=status.HTTP_201_CREATED
)
def accept(risk_id: str, body: AcceptanceRequest, actor: ActorDep, session: SessionDep) -> AcceptanceOut:
    acc = governance.accept_risk(
        session, actor, risk_id, body.assessment_id, body.justification, body.conditions, body.duration_days
    )
    return _acceptance(acc)


@router.get("/risks/{risk_id}/acceptances", response_model=list[AcceptanceOut])
def list_acceptances(risk_id: str, actor: ActorDep, session: SessionDep) -> list[AcceptanceOut]:
    require(actor, Permission.READ)
    return [_acceptance(a) for a in governance.list_acceptances(session, risk_id)]


@router.post("/acceptances/{acceptance_id}/revoke", response_model=AcceptanceOut)
def revoke(acceptance_id: str, body: RevokeRequest, actor: ActorDep, session: SessionDep) -> AcceptanceOut:
    return _acceptance(governance.revoke_acceptance(session, actor, acceptance_id, body.reason))
