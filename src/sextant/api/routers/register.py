"""Register endpoints: methodology, assets, evidence, controls, risks."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, status

from sextant.api.deps import ActorDep, SessionDep
from sextant.api.schemas import LatestAssessment, Me, RiskDetail, RiskSummary, RiskUpdate
from sextant.clock import utc_today
from sextant.db.models import RiskRecord
from sextant.domain.controls import Control, ControlTest, Evidence
from sextant.domain.methodology import Methodology
from sextant.domain.register import Asset
from sextant.domain.scenario import Scenario
from sextant.engine.controls import ControlAssessment, assess_control
from sextant.services import register as svc
from sextant.services.assessments import latest_final
from sextant.services.errors import InvalidRequestError
from sextant.services.security import ROLE_PERMISSIONS, Permission

router = APIRouter(prefix="/api/v1", tags=["register"])


@router.get("/me", response_model=Me)
def me(actor: ActorDep) -> Me:
    return Me(
        username=actor.username,
        role=actor.role.value,
        permissions=sorted(p.value for p in ROLE_PERMISSIONS[actor.role]),
    )


@router.get("/methodology", response_model=Methodology)
def get_methodology(actor: ActorDep, session: SessionDep) -> Methodology:
    svc.require(actor, Permission.READ)
    return svc.active_methodology(session)


@router.post("/methodology", response_model=Methodology, status_code=status.HTTP_201_CREATED)
def activate_methodology(body: Methodology, actor: ActorDep, session: SessionDep) -> Methodology:
    svc.activate_methodology(session, actor, body)
    return body


@router.get("/assets", response_model=list[Asset])
def list_assets(actor: ActorDep, session: SessionDep) -> list[Asset]:
    svc.require(actor, Permission.READ)
    return svc.list_assets(session)


@router.put("/assets/{asset_id}", response_model=Asset)
def put_asset(asset_id: str, body: Asset, actor: ActorDep, session: SessionDep) -> Asset:
    if body.id != asset_id:
        raise InvalidRequestError("asset id in path and body differ")
    svc.upsert_asset(session, actor, body)
    return body


@router.get("/evidence", response_model=list[Evidence])
def list_evidence(actor: ActorDep, session: SessionDep) -> list[Evidence]:
    svc.require(actor, Permission.READ)
    return svc.list_evidence(session)


@router.post("/evidence", response_model=Evidence, status_code=status.HTTP_201_CREATED)
def add_evidence(body: Evidence, actor: ActorDep, session: SessionDep) -> Evidence:
    svc.add_evidence(session, actor, body)
    return body


@router.get("/controls", response_model=list[Control])
def list_controls(actor: ActorDep, session: SessionDep) -> list[Control]:
    svc.require(actor, Permission.READ)
    return sorted(svc.control_library(session).values(), key=lambda c: c.id)


@router.get("/controls/{control_id}", response_model=Control)
def get_control(control_id: str, actor: ActorDep, session: SessionDep) -> Control:
    svc.require(actor, Permission.READ)
    return svc.get_control(session, control_id)


@router.put("/controls/{control_id}", response_model=Control)
def put_control(control_id: str, body: Control, actor: ActorDep, session: SessionDep) -> Control:
    if body.id != control_id:
        raise InvalidRequestError("control id in path and body differ")
    svc.upsert_control(session, actor, body)
    return body


@router.post(
    "/controls/{control_id}/tests", response_model=ControlAssessment, status_code=status.HTTP_201_CREATED
)
def add_control_test(
    control_id: str, body: ControlTest, actor: ActorDep, session: SessionDep
) -> ControlAssessment:
    control = svc.add_control_test(session, actor, control_id, body)
    return assess_control(control, svc.active_methodology(session).control_testing, utc_today())


@router.get("/controls/{control_id}/effectiveness", response_model=ControlAssessment)
def control_effectiveness(
    control_id: str, actor: ActorDep, session: SessionDep, as_of: date | None = None
) -> ControlAssessment:
    svc.require(actor, Permission.READ)
    control = svc.get_control(session, control_id)
    return assess_control(control, svc.active_methodology(session).control_testing, as_of or utc_today())


def _summary(session: SessionDep, rec: RiskRecord) -> RiskSummary:
    latest = latest_final(session, rec.id)
    return RiskSummary(
        id=rec.id,
        title=rec.title,
        owner=rec.owner,
        category=rec.category,
        status=rec.status,
        version=rec.version,
        next_review_due=rec.next_review_due,
        latest=LatestAssessment(
            assessment_id=latest.id,
            effective_level=latest.effective_level,
            current_ale=latest.current_ale,
            as_of=latest.as_of,
        )
        if latest
        else None,
    )


@router.get("/risks", response_model=list[RiskSummary])
def list_risks(actor: ActorDep, session: SessionDep) -> list[RiskSummary]:
    svc.require(actor, Permission.READ)
    return [_summary(session, r) for r in svc.list_risks(session)]


@router.post("/risks", response_model=RiskDetail, status_code=status.HTTP_201_CREATED)
def create_risk(body: Scenario, actor: ActorDep, session: SessionDep) -> RiskDetail:
    rec = svc.create_risk(session, actor, body)
    return RiskDetail(**_summary(session, rec).model_dump(), scenario=body)


@router.get("/risks/{risk_id}", response_model=RiskDetail)
def get_risk(risk_id: str, actor: ActorDep, session: SessionDep) -> RiskDetail:
    svc.require(actor, Permission.READ)
    rec = svc.get_risk_record(session, risk_id)
    return RiskDetail(**_summary(session, rec).model_dump(), scenario=Scenario.model_validate(rec.document))


@router.put("/risks/{risk_id}", response_model=RiskDetail)
def update_risk(risk_id: str, body: RiskUpdate, actor: ActorDep, session: SessionDep) -> RiskDetail:
    if body.scenario.id != risk_id:
        raise InvalidRequestError("risk id in path and body differ")
    rec = svc.update_risk(session, actor, body.scenario, body.version)
    return RiskDetail(**_summary(session, rec).model_dump(), scenario=body.scenario)
