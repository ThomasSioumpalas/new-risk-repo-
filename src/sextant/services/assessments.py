"""Assessment lifecycle: run → (override) → finalise → reproduce.

* **Run** creates a *draft*. Its input snapshot contains the scenario, every
  referenced control with its test history, the methodology, the as-of date,
  the seed and the trial count. That snapshot is everything needed to recompute
  the result.
* **Override** lets a risk manager replace the computed level with a justified
  professional judgement. The computed level is kept, and the override is
  recorded with who, when and why. Overrides are only possible on drafts.
* **Finalise** freezes the assessment. It supersedes the previous final
  assessment, schedules the next review according to the risk criteria, and
  **invalidates any active acceptance** if the residual risk level has
  increased: an acceptance covers a specific assessed risk, not the risk
  forever.
* **Reproduce** recomputes the result from the stored snapshot and compares
  fingerprints. This is the auditor's re-performance test.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from sextant import ENGINE_VERSION
from sextant.clock import utc_today
from sextant.db.models import AssessmentRecord, RiskAcceptance
from sextant.domain.controls import Control
from sextant.domain.methodology import Methodology
from sextant.domain.scenario import Scenario
from sextant.engine.assessment import QuantitativeAssessment, run_assessment
from sextant.services import audit
from sextant.services.errors import ConflictError, InvalidRequestError, NotFoundError
from sextant.services.register import (
    active_methodology,
    control_library,
    get_risk_record,
    get_scenario,
    now,
    require,
)
from sextant.services.security import Actor, Permission

MIN_OVERRIDE_JUSTIFICATION = 30


def create_assessment(
    session: Session,
    actor: Actor,
    risk_id: str,
    *,
    as_of: date | None = None,
    trials: int | None = None,
    seed: int | None = None,
    max_trials: int = 50_000,
) -> AssessmentRecord:
    require(actor, Permission.ASSESS)
    scenario = get_scenario(session, risk_id)
    methodology = active_methodology(session)
    trials = trials or methodology.simulation.trials
    if trials > max_trials:
        raise InvalidRequestError(f"trials limited to {max_trials} through the API")
    library = control_library(session)
    run = run_assessment(scenario, library, methodology, as_of or utc_today(), trials=trials, seed=seed)
    result = run.result
    referenced = sorted(
        {e.control_id for e in scenario.controls}
        | {e.control_id for t in scenario.treatments for e in t.add_controls}
    )
    snapshot = {
        "scenario": scenario.model_dump(mode="json"),
        "controls": [library[c].model_dump(mode="json") for c in referenced],
        "methodology": methodology.model_dump(mode="json"),
        "as_of": result.as_of.isoformat(),
        "trials": result.trials,
        "seed": result.seed,
        "engine_version": ENGINE_VERSION,
    }
    rec = AssessmentRecord(
        id=str(uuid.uuid4()),
        risk_id=risk_id,
        status="draft",
        as_of=result.as_of,
        trials=result.trials,
        seed=result.seed,
        engine_version=ENGINE_VERSION,
        methodology_fingerprint=result.methodology_fingerprint,
        inputs=snapshot,
        inputs_fingerprint=result.inputs_fingerprint,
        result=result.model_dump(mode="json"),
        result_fingerprint=result.result_fingerprint,
        computed_level=result.evaluation.decision_level,
        current_ale=result.states["current"].stats.ale,
        assessed_by=actor.username,
        created_at=now(),
    )
    session.add(rec)
    session.flush()
    audit.record(
        session,
        actor,
        "assessment.created",
        "assessment",
        rec.id,
        {
            "risk_id": risk_id,
            "inputs_fingerprint": rec.inputs_fingerprint,
            "result_fingerprint": rec.result_fingerprint,
            "level": rec.computed_level,
            "ale": rec.current_ale,
        },
    )
    return rec


def get_assessment(session: Session, assessment_id: str) -> AssessmentRecord:
    rec = session.get(AssessmentRecord, assessment_id)
    if rec is None:
        raise NotFoundError(f"assessment '{assessment_id}' not found")
    return rec


def list_assessments(session: Session, risk_id: str) -> list[AssessmentRecord]:
    return list(
        session.scalars(
            select(AssessmentRecord)
            .where(AssessmentRecord.risk_id == risk_id)
            .order_by(AssessmentRecord.created_at)
        )
    )


def latest_final(session: Session, risk_id: str) -> AssessmentRecord | None:
    return session.scalar(
        select(AssessmentRecord).where(
            AssessmentRecord.risk_id == risk_id, AssessmentRecord.status == "final"
        )
    )


def override_level(
    session: Session, actor: Actor, assessment_id: str, level: str, justification: str
) -> AssessmentRecord:
    require(actor, Permission.OVERRIDE)
    rec = get_assessment(session, assessment_id)
    if rec.status != "draft":
        raise ConflictError("only draft assessments can be overridden; finalised assessments are immutable")
    methodology = Methodology.model_validate(rec.inputs["methodology"])
    if level not in methodology.risk_levels:
        raise InvalidRequestError(f"unknown risk level '{level}'; valid: {methodology.risk_levels}")
    if len(justification.strip()) < MIN_OVERRIDE_JUSTIFICATION:
        raise InvalidRequestError(
            f"an override needs a justification of at least {MIN_OVERRIDE_JUSTIFICATION} chars"
        )
    rec.override_level = level
    rec.override_justification = justification.strip()
    rec.override_by = actor.username
    rec.override_at = now()
    audit.record(
        session,
        actor,
        "assessment.overridden",
        "assessment",
        rec.id,
        {"computed_level": rec.computed_level, "override_level": level, "justification": justification},
    )
    return rec


def finalize(session: Session, actor: Actor, assessment_id: str) -> AssessmentRecord:
    require(actor, Permission.ASSESS)
    rec = get_assessment(session, assessment_id)
    if rec.status != "draft":
        raise ConflictError(f"assessment is already {rec.status}")
    methodology = Methodology.model_validate(rec.inputs["methodology"])
    previous = latest_final(session, rec.risk_id)
    if previous is not None:
        previous.status = "superseded"
        rec.supersedes_id = previous.id
    rec.status = "final"
    rec.finalized_by = actor.username
    rec.finalized_at = now()

    risk = get_risk_record(session, rec.risk_id)
    level = rec.effective_level
    review_days = methodology.acceptance_rule(level).review_every_days
    risk.next_review_due = rec.as_of + timedelta(days=review_days)
    risk.status = "assessed"

    invalidated = []
    for acc in session.scalars(
        select(RiskAcceptance).where(RiskAcceptance.risk_id == rec.risk_id, RiskAcceptance.status == "active")
    ):
        if methodology.level_rank(level) > methodology.level_rank(acc.accepted_level):
            acc.status = "invalidated"
            acc.closed_by = "system"
            acc.closed_at = now()
            acc.closed_reason = (
                f"superseded by assessment {rec.id}: level rose from {acc.accepted_level} to {level}"
            )
            invalidated.append(acc.id)
        else:
            risk.status = "accepted"
    session.flush()
    audit.record(
        session,
        actor,
        "assessment.finalized",
        "assessment",
        rec.id,
        {
            "risk_id": rec.risk_id,
            "effective_level": level,
            "supersedes": rec.supersedes_id,
            "next_review_due": risk.next_review_due.isoformat(),
            "invalidated_acceptances": invalidated,
        },
    )
    return rec


class Reproduction(BaseModel):
    assessment_id: str
    reproduced: bool
    stored_result_fingerprint: str
    recomputed_result_fingerprint: str
    stored_inputs_fingerprint: str
    recomputed_inputs_fingerprint: str
    engine_version_stored: str
    engine_version_now: str
    note: str


def reproduce(session: Session, actor: Actor, assessment_id: str) -> Reproduction:
    """Re-perform the calculation from the stored snapshot (the auditor's test)."""
    require(actor, Permission.READ)
    rec = get_assessment(session, assessment_id)
    snap: dict[str, Any] = rec.inputs
    scenario = Scenario.model_validate(snap["scenario"])
    controls = {c["id"]: Control.model_validate(c) for c in snap["controls"]}
    methodology = Methodology.model_validate(snap["methodology"])
    run = run_assessment(
        scenario,
        controls,
        methodology,
        date.fromisoformat(snap["as_of"]),
        trials=int(snap["trials"]),
        seed=int(snap["seed"]),
    )
    ok = run.result.result_fingerprint == rec.result_fingerprint
    if ok:
        note = "Result reproduced exactly from the stored inputs."
    elif rec.engine_version != ENGINE_VERSION:
        note = "Engine version differs from the one that produced the assessment; differences are expected."
    else:
        note = (
            "Result differs with the same engine version. Check the numerical library versions "
            f"(stored: {rec.result.get('library_versions')}); otherwise investigate."
        )
    audit.record(session, actor, "assessment.reproduced", "assessment", rec.id, {"reproduced": ok})
    return Reproduction(
        assessment_id=rec.id,
        reproduced=ok,
        stored_result_fingerprint=rec.result_fingerprint,
        recomputed_result_fingerprint=run.result.result_fingerprint,
        stored_inputs_fingerprint=rec.inputs_fingerprint,
        recomputed_inputs_fingerprint=run.result.inputs_fingerprint,
        engine_version_stored=rec.engine_version,
        engine_version_now=ENGINE_VERSION,
        note=note,
    )


def result_of(rec: AssessmentRecord) -> QuantitativeAssessment:
    return QuantitativeAssessment.model_validate(rec.result)
