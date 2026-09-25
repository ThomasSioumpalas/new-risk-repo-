"""Analysis, compliance, monitoring and audit endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from sextant.api.deps import ActorDep, SessionDep, SettingsDep
from sextant.api.schemas import AuditEntryOut, WhatIfRequest
from sextant.compliance.catalog import all_catalogs
from sextant.compliance.readiness import ReadinessReport, SoAEntry
from sextant.engine.assessment import QuantitativeAssessment
from sextant.engine.portfolio import PortfolioResult
from sextant.services import analysis, audit, governance
from sextant.services.audit import ChainVerification
from sextant.services.register import require
from sextant.services.security import Permission

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.post("/analysis/what-if", response_model=QuantitativeAssessment)
def what_if(
    body: WhatIfRequest, actor: ActorDep, session: SessionDep, settings: SettingsDep
) -> QuantitativeAssessment:
    """Run an unsaved analysis of a modified scenario (e.g. different estimates or stress tests)."""
    return analysis.what_if(
        session,
        actor,
        body.scenario,
        body.stress_tests,
        trials=body.trials,
        seed=body.seed,
        max_trials=settings.api_max_trials,
        as_of=body.as_of,
    )


@router.get("/analysis/portfolio", response_model=PortfolioResult)
def portfolio(
    actor: ActorDep, session: SessionDep, settings: SettingsDep, trials: int = Query(default=20_000, ge=1_000)
) -> PortfolioResult:
    return analysis.portfolio(session, actor, trials=trials, max_trials=settings.api_max_trials)


@router.get("/compliance/catalogs")
def catalogs(actor: ActorDep) -> list[dict[str, str | int]]:
    require(actor, Permission.READ)
    return [
        {
            "id": c.id,
            "name": c.name,
            "requirements": len(c.requirements),
            "text_policy": c.text_policy.value,
            "license": c.license,
        }
        for c in all_catalogs().values()
    ]


@router.get("/compliance/readiness/{framework}", response_model=ReadinessReport)
def readiness(
    framework: str, actor: ActorDep, session: SessionDep, as_of: date | None = None
) -> ReadinessReport:
    return analysis.readiness(session, actor, framework, as_of)


@router.get("/compliance/soa", response_model=list[SoAEntry])
def statement_of_applicability(actor: ActorDep, session: SessionDep) -> list[SoAEntry]:
    return analysis.statement_of_applicability(session, actor)


@router.get("/monitoring", response_model=list[governance.MonitoringItem])
def monitoring(
    actor: ActorDep, session: SessionDep, horizon_days: int = Query(default=30, ge=0, le=365)
) -> list[governance.MonitoringItem]:
    require(actor, Permission.READ)
    return governance.monitoring(session, horizon_days)


@router.get("/audit", response_model=list[AuditEntryOut], tags=["audit"])
def audit_log(
    actor: ActorDep,
    session: SessionDep,
    entity_type: str | None = None,
    entity_id: str | None = None,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AuditEntryOut]:
    require(actor, Permission.READ_AUDIT)
    rows = audit.list_entries(session, entity_type, entity_id, limit, after_seq)
    return [AuditEntryOut.model_validate(r) for r in rows]


@router.get("/audit/verify", response_model=ChainVerification, tags=["audit"])
def verify(actor: ActorDep, session: SessionDep) -> ChainVerification:
    require(actor, Permission.READ_AUDIT)
    return audit.verify_chain(session)
