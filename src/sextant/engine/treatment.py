"""Treatment option analysis and control contribution.

"Which mitigation would have the greatest effect?" is answered by comparing
every option against the *current* state **on the same simulated years**. The
paired difference ``L_current − L_option`` has a much smaller Monte Carlo error
than two independent runs, and both standard errors are reported to make the
variance reduction visible.

Cost-effectiveness uses the Return on Security Investment::

    annualised cost = annual cost + one-time cost / amortisation years
    ROSI            = (ΔALE − annualised cost) / annualised cost

ROSI rests on the *expected* loss. An option can have a negative ROSI and
still be justified by its effect on the tail (ΔVaR, ΔES) or by a regulatory
requirement. Both are shown so that the decision is made by people, not by one
number.

Control contribution uses leave-one-out: "how much would the expected loss rise
if this control stopped working?" Contributions do not sum exactly to the total
reduction, because layered controls interact multiplicatively. The report
states this.
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel, ConfigDict

from sextant.domain.methodology import Methodology
from sextant.domain.scenario import TreatmentType
from sextant.engine.metrics import expected_shortfall
from sextant.engine.model import CURRENT, INHERENT, ScenarioModel
from sextant.engine.qualitative import band_quantitative
from sextant.engine.simulation import SimulationRun


class OptionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    option_id: str
    title: str
    type: TreatmentType
    ale: float
    var_95: float
    es_95: float
    ale_reduction: float
    ale_reduction_se_paired: float
    ale_reduction_se_independent: float
    var_95_reduction: float
    es_95_reduction: float
    annualised_cost: float
    net_benefit: float
    rosi: float | None
    residual_level: str
    within_appetite: bool


class ControlContribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_id: str
    control_name: str
    targets: list[str]
    operating_source: str
    ale_increase_if_failed: float
    ale_increase_se: float
    share_of_total_reduction: float | None


def _se(x: np.ndarray) -> float:
    return float(x.std(ddof=1) / math.sqrt(x.size))


def compare_options(model: ScenarioModel, run: SimulationRun, methodology: Methodology) -> list[OptionResult]:
    cur = run.states[CURRENT].annual_loss
    results = []
    for opt in model.scenario.treatments:
        state_name = f"option:{opt.id}"
        outcome = run.states[state_name]
        loss = outcome.annual_loss
        diff = cur - loss
        cost = opt.annual_cost + opt.one_time_cost / methodology.simulation.cost_amortisation_years
        reduction = float(diff.mean())
        level = band_quantitative(
            methodology,
            float(outcome.loss_event_rate.mean()),
            (float(outcome.expected_loss.mean()) / float(outcome.loss_event_rate.mean()))
            if outcome.loss_event_rate.mean() > 0
            else None,
        ).risk_level
        ale = float(loss.mean())
        results.append(
            OptionResult(
                option_id=opt.id,
                title=opt.title,
                type=opt.type,
                ale=ale,
                var_95=float(np.quantile(loss, 0.95)),
                es_95=expected_shortfall(loss, 0.95),
                ale_reduction=reduction,
                ale_reduction_se_paired=_se(diff),
                ale_reduction_se_independent=math.sqrt(_se(cur) ** 2 + _se(loss) ** 2),
                var_95_reduction=float(np.quantile(cur, 0.95) - np.quantile(loss, 0.95)),
                es_95_reduction=expected_shortfall(cur, 0.95) - expected_shortfall(loss, 0.95),
                annualised_cost=cost,
                net_benefit=reduction - cost,
                rosi=(reduction - cost) / cost if cost > 0 else None,
                residual_level=level,
                within_appetite=methodology.within_appetite(level)
                and ale <= methodology.appetite.scenario_ale_threshold,
            )
        )
    return sorted(results, key=lambda r: r.ale_reduction, reverse=True)


def control_contributions(model: ScenarioModel, run: SimulationRun) -> list[ControlContribution]:
    cur = run.states[CURRENT].annual_loss
    total_reduction = float(run.states[INHERENT].annual_loss.mean() - cur.mean())
    out = []
    current_effects = model.states[CURRENT].effects
    for cid in model.credited_controls:
        without = run.states[f"without:{cid}"].annual_loss
        diff = without - cur
        keys = [k for k in current_effects if model.effects[k].control_id == cid]
        increase = float(diff.mean())
        out.append(
            ControlContribution(
                control_id=cid,
                control_name=model.effects[keys[0]].control_name,
                targets=sorted({model.effects[k].target.value for k in keys}),
                operating_source=current_effects[keys[0]].operating_source,
                ale_increase_if_failed=increase,
                ale_increase_se=_se(diff),
                share_of_total_reduction=increase / total_reduction if total_reduction > 0 else None,
            )
        )
    return sorted(out, key=lambda c: c.ale_increase_if_failed, reverse=True)
