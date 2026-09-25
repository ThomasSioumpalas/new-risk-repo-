"""End-to-end quantitative assessment of one scenario: the unit that is persisted.

``run_assessment`` is a *pure function* of its inputs::

    (scenario, controls, methodology, as_of, trials, seed, engine version)
        → QuantitativeAssessment

Two SHA-256 fingerprints are recorded:

* ``inputs_fingerprint`` covers everything that determines the result;
* ``result_fingerprint`` covers the result itself.

Re-running a stored assessment from its input snapshot must reproduce the same
result fingerprint with the same dependency versions (``uv.lock``). This is the
reproducibility guarantee an auditor can test. Library versions are recorded
because floating-point output can differ in the last bits between versions of
NumPy or SciPy.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import scipy
from pydantic import BaseModel, ConfigDict

from sextant import ENGINE_VERSION
from sextant.domain.controls import Control
from sextant.domain.methodology import Methodology, Role
from sextant.domain.scenario import Scenario
from sextant.engine.controls import ControlAssessment
from sextant.engine.explain import Explanation, explain
from sextant.engine.metrics import LossStatistics, default_thresholds, summarize
from sextant.engine.model import CURRENT, INHERENT, TARGET, ScenarioModel, build_model
from sextant.engine.qualitative import (
    Finding,
    QualitativeResult,
    RatedState,
    Severity,
    assess_qualitative,
    band_quantitative,
    quality_checks,
)
from sextant.engine.sensitivity import (
    RankSensitivity,
    StressTest,
    TornadoBar,
    apply_stress,
    default_stress_tests,
    rank_sensitivity,
    tornado,
)
from sextant.engine.simulation import SimulationRun, simulate
from sextant.engine.treatment import ControlContribution, OptionResult, compare_options, control_contributions

MODEL_ASSUMPTIONS = [
    "Loss events follow a Poisson process given the annual rate (events are independent in time).",
    "Controls acting on the same factor combine multiplicatively (independent layers of defence).",
    "A control's operating rate is the probability it works for a given event; failures are independent "
    "between events.",
    "Loss forms of the same event are positively correlated through a one-factor Gaussian copula.",
    "Loss-magnitude ranges describe event-to-event variability; uncertainty about severity parameters is "
    "not modelled separately (v1).",
    "Inherent risk is the risk without the controls linked to the scenario; the wider environment is unchanged.",
    "Quantitative banding: likelihood from expected loss events per year, impact from expected loss per event.",
]


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class InputRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    input: str
    distribution: str
    provenance: str
    source: str | None
    rationale: str | None


class StateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    label: str
    stats: LossStatistics
    banded: RatedState
    within_appetite: bool


class StressResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    ale: float
    ale_change_pct: float
    var_95: float
    risk_level: str


class Evaluation(BaseModel):
    """Risk evaluation against the criteria (ISO 31000 §6.4.4)."""

    model_config = ConfigDict(frozen=True)

    quantitative_level: str
    qualitative_level: str | None
    decision_level: str
    ale_threshold: float
    ale_within_threshold: bool
    max_acceptable_level: str
    level_within_appetite: bool
    within_appetite: bool
    treatment_required: bool
    acceptance_authority: Role
    max_acceptance_days: int
    review_every_days: int
    rationale: str


class QuantitativeAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    scenario_title: str
    as_of: date
    currency: str
    methodology_id: str
    methodology_version: str
    methodology_fingerprint: str
    engine_version: str
    library_versions: dict[str, str]
    trials: int
    seed: int
    loss_component_correlation: float
    inputs_fingerprint: str
    states: dict[str, StateResult]
    options: list[OptionResult]
    controls: list[ControlContribution]
    control_assessments: list[ControlAssessment]
    tornado: list[TornadoBar]
    rank_sensitivity: list[RankSensitivity]
    stress_tests: list[StressResult]
    qualitative: QualitativeResult | None
    evaluation: Evaluation
    inputs: list[InputRecord]
    assumptions: list[str]
    model_notes: list[str]
    findings: list[Finding]
    explanation: Explanation | None = None
    result_fingerprint: str = ""


@dataclass(frozen=True)
class AssessmentRun:
    """The persisted result plus the raw simulation (for charts and portfolio aggregation)."""

    result: QuantitativeAssessment
    simulation: SimulationRun
    model: ScenarioModel


def inputs_snapshot(
    scenario: Scenario,
    controls: Mapping[str, Control],
    methodology: Methodology,
    as_of: date,
    trials: int,
    seed: int,
) -> dict[str, Any]:
    """Everything that determines the result, in serialisable form."""
    referenced = sorted(
        {e.control_id for e in scenario.controls}
        | {e.control_id for t in scenario.treatments for e in t.add_controls}
    )
    return {
        "scenario": scenario.model_dump(mode="json"),
        "controls": [controls[c].model_dump(mode="json") for c in referenced if c in controls],
        "methodology": methodology.model_dump(mode="json"),
        "as_of": as_of.isoformat(),
        "trials": trials,
        "seed": seed,
        "engine_version": ENGINE_VERSION,
    }


def _input_records(scenario: Scenario, model: ScenarioModel) -> list[InputRecord]:
    records = [
        InputRecord(
            input="threat_event_frequency",
            distribution=model.tef.describe(),
            provenance=model.tef.provenance.value,
            source=scenario.threat_event_frequency.source,
            rationale=scenario.threat_event_frequency.rationale,
        ),
        InputRecord(
            input="susceptibility",
            distribution=model.susceptibility.describe(),
            provenance=model.susceptibility.provenance.value,
            source=scenario.susceptibility.source,
            rationale=scenario.susceptibility.rationale,
        ),
    ]
    if scenario.secondary_loss is not None and model.secondary_probability is not None:
        est = scenario.secondary_loss.probability
        records.append(
            InputRecord(
                input="secondary_loss_probability",
                distribution=model.secondary_probability.describe(),
                provenance=model.secondary_probability.provenance.value,
                source=est.source,
                rationale=est.rationale,
            )
        )
    for comp, spec in zip(model.components, scenario.all_loss_components(), strict=True):
        records.append(
            InputRecord(
                input=f"magnitude:{comp.name}",
                distribution=comp.dist.describe(),
                provenance=comp.dist.provenance.value,
                source=spec.magnitude.source,
                rationale=spec.magnitude.rationale or spec.description,
            )
        )
    for key, var in model.states[CURRENT].effects.items():
        records.append(
            InputRecord(
                input=f"reduction:{key}",
                distribution=var.reduction.describe(),
                provenance=var.reduction.provenance.value,
                source=None,
                rationale=var.rationale,
            )
        )
        records.append(
            InputRecord(
                input=f"operating:{key}",
                distribution=var.operating.describe(),
                provenance=var.operating.provenance.value,
                source=var.operating_source,
                rationale=f"coverage {var.coverage:.0%}",
            )
        )
    return records


def _state_result(
    name: str, run: SimulationRun, model: ScenarioModel, thresholds: Sequence[float]
) -> StateResult:
    methodology = model.methodology
    outcome = run.states[name]
    stats = summarize(outcome, thresholds)
    banded = band_quantitative(methodology, stats.expected_loss_events, stats.expected_loss_per_event)
    return StateResult(
        name=name,
        label=model.states[name].label,
        stats=stats,
        banded=banded,
        within_appetite=methodology.within_appetite(banded.risk_level)
        and stats.ale <= methodology.appetite.scenario_ale_threshold,
    )


def run_assessment(
    scenario: Scenario,
    controls: Mapping[str, Control],
    methodology: Methodology,
    as_of: date,
    *,
    trials: int | None = None,
    seed: int | None = None,
    stress_tests: Sequence[StressTest] | None = None,
) -> AssessmentRun:
    trials = trials or methodology.simulation.trials
    seed = methodology.simulation.seed if seed is None else seed
    model = build_model(scenario, controls, methodology, as_of)
    run = simulate(model, trials=trials, seed=seed)

    thresholds = default_thresholds(float(run.states[INHERENT].annual_loss.max()))
    named = [INHERENT, CURRENT] + ([TARGET] if TARGET in model.states else [])
    states = {n: _state_result(n, run, model, thresholds) for n in named}

    # Stress tests: re-simulate only the current state with identical random streams.
    stress_results = []
    base_ale = states[CURRENT].stats.ale
    for test in stress_tests if stress_tests is not None else default_stress_tests(model):
        stressed = apply_stress(model, test)
        srun = simulate(stressed, trials=trials, seed=seed, states=[CURRENT])
        st = summarize(srun.states[CURRENT], thresholds)
        lvl = band_quantitative(methodology, st.expected_loss_events, st.expected_loss_per_event).risk_level
        stress_results.append(
            StressResult(
                name=test.name,
                description=test.description,
                ale=st.ale,
                ale_change_pct=(st.ale - base_ale) / base_ale if base_ale > 0 else 0.0,
                var_95=st.var_95,
                risk_level=lvl,
            )
        )

    qualitative = assess_qualitative(scenario, methodology)
    findings = quality_checks(scenario, model, qualitative)

    quant_level = states[CURRENT].banded.risk_level
    qual_level = qualitative.current.risk_level if qualitative else None
    if (
        qual_level is not None
        and abs(methodology.level_rank(qual_level) - methodology.level_rank(quant_level)) >= 2
    ):
        findings.append(
            Finding(
                severity=Severity.WARNING,
                code="METHODS-DISAGREE",
                message=(
                    f"Qualitative rating '{qual_level}' and quantitative result '{quant_level}' differ by two or "
                    "more levels; review the ratings and the estimates."
                ),
            )
        )
    for rec in _input_records(scenario, model):
        if rec.input.startswith("magnitude:") or rec.input == "threat_event_frequency":
            spec_ratio = _range_ratio(model, rec.input)
            if spec_ratio is not None and spec_ratio > 1000:
                findings.append(
                    Finding(
                        severity=Severity.INFO,
                        code="INPUT-VERY-WIDE",
                        message=f"{rec.input}: 90% range spans a factor of {spec_ratio:,.0f}; consider decomposing it.",
                    )
                )

    s = states[CURRENT].stats
    ale_ok = s.ale <= methodology.appetite.scenario_ale_threshold
    level_ok = methodology.within_appetite(quant_level)
    rule = methodology.acceptance_rule(quant_level)
    evaluation = Evaluation(
        quantitative_level=quant_level,
        qualitative_level=qual_level,
        decision_level=quant_level,
        ale_threshold=methodology.appetite.scenario_ale_threshold,
        ale_within_threshold=ale_ok,
        max_acceptable_level=methodology.appetite.max_acceptable_level,
        level_within_appetite=level_ok,
        within_appetite=ale_ok and level_ok,
        treatment_required=not (ale_ok and level_ok),
        acceptance_authority=rule.min_authority,
        max_acceptance_days=rule.max_acceptance_days,
        review_every_days=rule.review_every_days,
        rationale=(
            "The quantitative result is the decision basis (see methodology notes). The qualitative rating is "
            "retained for communication and consistency checking."
        ),
    )

    snapshot = inputs_snapshot(scenario, controls, methodology, as_of, trials, seed)
    result = QuantitativeAssessment(
        scenario_id=scenario.id,
        scenario_title=scenario.title,
        as_of=as_of,
        currency=methodology.currency,
        methodology_id=methodology.id,
        methodology_version=methodology.version,
        methodology_fingerprint=methodology.fingerprint,
        engine_version=ENGINE_VERSION,
        library_versions={"numpy": np.__version__, "scipy": scipy.__version__},
        trials=trials,
        seed=seed,
        loss_component_correlation=run.correlation,
        inputs_fingerprint=sha256(canonical_json(snapshot)),
        states=states,
        options=compare_options(model, run, methodology),
        controls=control_contributions(model, run),
        control_assessments=list(model.control_assessments.values()),
        tornado=tornado(model),
        rank_sensitivity=rank_sensitivity(run),
        stress_tests=stress_results,
        qualitative=qualitative,
        evaluation=evaluation,
        inputs=_input_records(scenario, model),
        assumptions=[*MODEL_ASSUMPTIONS, *scenario.assumptions],
        model_notes=list(model.notes),
        findings=findings,
    )
    result = result.model_copy(update={"explanation": explain(result)})
    result = result.model_copy(update={"result_fingerprint": result_fingerprint(result)})
    return AssessmentRun(result=result, simulation=run, model=model)


def result_fingerprint(result: QuantitativeAssessment) -> str:
    data = result.model_dump(mode="json", exclude={"result_fingerprint"})
    return sha256(canonical_json(data))


def _range_ratio(model: ScenarioModel, name: str) -> float | None:
    if name == "threat_event_frequency":
        dist = model.tef
    else:
        comp = next((c for c in model.components if f"magnitude:{c.name}" == name), None)
        if comp is None:
            return None
        dist = comp.dist
    lo, hi = dist.quantile(0.05), dist.quantile(0.95)
    return hi / lo if lo > 0 else None
