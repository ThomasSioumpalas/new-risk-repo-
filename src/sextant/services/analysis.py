"""Read-side analysis over the stored register: what-if, portfolio and readiness."""

from __future__ import annotations

from datetime import date

import numpy as np
from sqlalchemy.orm import Session

from sextant.clock import utc_today
from sextant.compliance.catalog import load_catalog
from sextant.compliance.readiness import (
    ReadinessReport,
    SoAEntry,
    assess_readiness,
    draft_statement_of_applicability,
)
from sextant.domain.controls import Control
from sextant.domain.scenario import Scenario
from sextant.engine.assessment import QuantitativeAssessment, run_assessment
from sextant.engine.metrics import default_thresholds
from sextant.engine.model import CURRENT, build_model
from sextant.engine.portfolio import PortfolioResult, aggregate
from sextant.engine.sensitivity import StressTest
from sextant.engine.simulation import simulate
from sextant.services.assessments import latest_final
from sextant.services.errors import InvalidRequestError
from sextant.services.register import active_methodology, control_library, list_evidence, list_risks, require
from sextant.services.security import Actor, Permission


def what_if(
    session: Session,
    actor: Actor,
    scenario: Scenario,
    stress_tests: list[StressTest],
    *,
    trials: int,
    seed: int | None,
    max_trials: int,
    max_events: int | None = None,
    as_of: date | None = None,
) -> QuantitativeAssessment:
    """Stateless analysis of a (possibly modified) scenario. Nothing is stored."""
    require(actor, Permission.READ)
    if trials > max_trials:
        raise InvalidRequestError(f"trials limited to {max_trials} through the API")
    library = control_library(session)
    methodology = active_methodology(session)
    return run_assessment(
        scenario,
        library,
        methodology,
        as_of or utc_today(),
        trials=trials,
        seed=seed,
        stress_tests=stress_tests or None,
        max_events=max_events,
    ).result


def portfolio(session: Session, actor: Actor, *, trials: int, max_trials: int) -> PortfolioResult:
    """Aggregate the current state of every risk with a final assessment.

    Each risk is re-simulated from its *finalised input snapshot* with a common trial
    count, so the portfolio is consistent with what was approved rather than
    with unreviewed edits.
    """
    require(actor, Permission.READ)
    if trials > max_trials:
        raise InvalidRequestError(f"trials limited to {max_trials} through the API")
    losses = {}
    titles = {}
    methodology = active_methodology(session)
    for risk in list_risks(session):
        rec = latest_final(session, risk.id)
        if rec is None:
            continue
        snap = rec.inputs
        scenario = Scenario.model_validate(snap["scenario"])
        controls = {c["id"]: Control.model_validate(c) for c in snap["controls"]}
        model = build_model(scenario, controls, methodology, date.fromisoformat(snap["as_of"]))
        run = simulate(model, trials=trials, seed=int(snap["seed"]), states=[CURRENT])
        losses[risk.id] = run.states[CURRENT].annual_loss
        titles[risk.id] = risk.title
    if not losses:
        raise InvalidRequestError("no finalised assessments to aggregate")
    total_max = float(np.sum(np.vstack(list(losses.values())), axis=0).max())
    return aggregate(losses, titles, methodology, default_thresholds(total_max))


def readiness(session: Session, actor: Actor, framework: str, as_of: date | None = None) -> ReadinessReport:
    require(actor, Permission.READ)
    try:
        catalog = load_catalog(framework)
    except KeyError as exc:
        raise InvalidRequestError(str(exc)) from exc
    methodology = active_methodology(session)
    scenarios = [Scenario.model_validate(r.document) for r in list_risks(session)]
    evidence = {e.id: e for e in list_evidence(session)}
    return assess_readiness(
        catalog,
        list(control_library(session).values()),
        evidence,
        methodology.control_testing,
        as_of or utc_today(),
        scenarios=scenarios,
    )


def statement_of_applicability(session: Session, actor: Actor) -> list[SoAEntry]:
    return draft_statement_of_applicability(readiness(session, actor, "iso27001_2022"))
