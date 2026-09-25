"""Analysis pipeline: run every scenario, aggregate the portfolio, assess readiness.

``analyse_register`` is the single entry point the report and CLI commands use.
It is a thin orchestration layer over the engine and compliance modules: it
introduces no new statistics, only assembles their outputs into one object
that the Markdown and chart writers can consume without re-running anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from sextant.compliance.catalog import Catalog, all_catalogs
from sextant.compliance.readiness import (
    ReadinessReport,
    SoAEntry,
    assess_readiness,
    draft_statement_of_applicability,
)
from sextant.domain.methodology import Methodology
from sextant.domain.register import RiskRegister
from sextant.engine.assessment import AssessmentRun, run_assessment
from sextant.engine.metrics import default_thresholds
from sextant.engine.model import CURRENT
from sextant.engine.portfolio import PortfolioResult, aggregate

ISO_CATALOG_ID = "iso27001_2022"


@dataclass(frozen=True)
class RankingRow:
    """One scenario's place in the ALE ranking versus its ordinal matrix score.

    ``ale_rank`` is 1 for the scenario with the largest current ALE. Comparing
    it with ``ordinal_score`` (the legacy likelihood × impact product) shows
    where the ordinal score compresses or reverses the ranking that the
    quantitative model gives (Cox 2008).
    """

    scenario_id: str
    title: str
    ale_rank: int
    ale: float
    quantitative_level: str
    ordinal_score: int
    qualitative_level: str | None


@dataclass(frozen=True)
class RegisterAnalysis:
    """Everything the report writers need, computed once for a register."""

    register: RiskRegister
    methodology: Methodology
    as_of: date
    trials: int
    seed: int
    runs: dict[str, AssessmentRun]
    portfolio: PortfolioResult
    readiness: dict[str, ReadinessReport]
    soa: list[SoAEntry]
    ranking: list[RankingRow]

    @property
    def catalogs(self) -> dict[str, Catalog]:
        return all_catalogs()


def _ranking(runs: dict[str, AssessmentRun]) -> list[RankingRow]:
    by_ale = sorted(runs.values(), key=lambda run: run.result.states[CURRENT].stats.ale, reverse=True)
    rows = []
    for rank, run in enumerate(by_ale, start=1):
        result = run.result
        current = result.states[CURRENT]
        qualitative_level = result.qualitative.current.risk_level if result.qualitative else None
        rows.append(
            RankingRow(
                scenario_id=result.scenario_id,
                title=result.scenario_title,
                ale_rank=rank,
                ale=current.stats.ale,
                quantitative_level=current.banded.risk_level,
                ordinal_score=current.banded.ordinal_score,
                qualitative_level=qualitative_level,
            )
        )
    return rows


def analyse_register(
    register: RiskRegister,
    methodology: Methodology,
    as_of: date,
    trials: int | None = None,
    seed: int | None = None,
) -> RegisterAnalysis:
    """Run every scenario, aggregate the portfolio and assess compliance readiness.

    All scenarios use the same ``trials`` and ``seed`` (resolved once from the
    methodology's simulation settings when not given), so the portfolio
    aggregation in :func:`sextant.engine.portfolio.aggregate` sees equally
    sized loss arrays.
    """
    resolved_trials = trials if trials is not None else methodology.simulation.trials
    resolved_seed = methodology.simulation.seed if seed is None else seed

    controls = register.control_map()
    runs = {
        scenario.id: run_assessment(
            scenario, controls, methodology, as_of, trials=resolved_trials, seed=resolved_seed
        )
        for scenario in register.scenarios
    }

    losses = {sid: run.simulation.states[CURRENT].annual_loss for sid, run in runs.items()}
    titles = {sid: run.result.scenario_title for sid, run in runs.items()}
    total = np.sum(np.vstack(list(losses.values())), axis=0)
    thresholds = default_thresholds(float(total.max()))
    portfolio = aggregate(losses, titles, methodology, thresholds)

    readiness = {
        catalog_id: assess_readiness(
            catalog,
            register.controls,
            register.evidence_map(),
            methodology.control_testing,
            as_of,
            register.exclusions,
            register.scenarios,
        )
        for catalog_id, catalog in all_catalogs().items()
    }
    soa = draft_statement_of_applicability(readiness[ISO_CATALOG_ID])

    return RegisterAnalysis(
        register=register,
        methodology=methodology,
        as_of=as_of,
        trials=resolved_trials,
        seed=resolved_seed,
        runs=runs,
        portfolio=portfolio,
        readiness=readiness,
        soa=soa,
        ranking=_ranking(runs),
    )
