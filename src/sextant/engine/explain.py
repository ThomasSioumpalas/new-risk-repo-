"""Plain-language explanations of an assessment.

A risk number is only useful if the risk owner can answer, in their own words,
the questions a board member or auditor will ask. This module writes those
answers from the structured results. It never introduces a number that is not
already in the assessment, so the narrative is as reproducible as the maths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from sextant.engine.model import CURRENT, INHERENT, TARGET

if TYPE_CHECKING:
    from sextant.engine.assessment import QuantitativeAssessment


class Explanation(BaseModel):
    model_config = ConfigDict(frozen=True)

    headline: str
    what_is_the_risk: str
    why_this_level: str
    how_confident: str
    which_controls: str
    what_if: str
    best_mitigation: str


def money(value: float, currency: str) -> str:
    """Compact currency formatting: EUR 1.23M, EUR 450k."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e9:
        return f"{sign}{currency} {v / 1e9:.2f}B"
    if v >= 1e6:
        return f"{sign}{currency} {v / 1e6:.2f}M"
    if v >= 1e3:
        return f"{sign}{currency} {v / 1e3:.0f}k"
    return f"{sign}{currency} {v:.0f}"


def input_label(name: str) -> str:
    """Human label for a model input key."""
    fixed = {
        "threat_event_frequency": "Threat event frequency",
        "susceptibility": "Susceptibility",
        "secondary_loss_probability": "Probability of secondary loss",
    }
    if name in fixed:
        return fixed[name]
    kind, _, rest = name.partition(":")
    if kind == "magnitude":
        return f"Loss magnitude: {rest}"
    control, _, target = rest.partition(":")
    target = target.replace("_", " ")
    if kind == "reduction":
        return f"{control} design reduction ({target})"
    if kind == "operating":
        return f"{control} operating rate"
    return name


def explain(a: QuantitativeAssessment) -> Explanation:
    cur = a.currency
    inh = a.states[INHERENT]
    now = a.states[CURRENT]
    s = now.stats
    ev = a.evaluation

    lo, hi = s.ale_credible_interval_90
    what = (
        f"The current expected annual loss (ALE) is {money(s.ale, cur)}, with a 90% credible interval of "
        f"{money(lo, cur)} to {money(hi, cur)}. The probability of at least one loss event in a year is "
        f"{s.prob_at_least_one_event:.0%}. In a 1-in-20 bad year, losses reach {money(s.var_95, cur)} or more "
        f"(VaR 95%). The average of those worst 5% of years is {money(s.es_95, cur)} (expected shortfall)."
    )

    appetite = "within" if ev.within_appetite else "OUTSIDE"
    qual = ""
    if a.qualitative is not None:
        q = a.qualitative.current
        agree = "consistent with" if q.risk_level == now.banded.risk_level else "DIFFERENT from"
        qual = (
            f" The analyst's qualitative rating (likelihood {q.likelihood} × impact {q.impact} → "
            f"'{q.risk_level}') is {agree} the quantitative result."
        )
    why = (
        f"{now.banded.basis}. The risk matrix gives '{now.banded.risk_level}'. "
        f"The ALE of {money(s.ale, cur)} is compared with the scenario threshold of "
        f"{money(ev.ale_threshold, cur)}, and the level with the maximum acceptable level "
        f"'{ev.max_acceptable_level}'. The risk is **{appetite} appetite**. Given the parameter uncertainty, "
        f"the probability that the true ALE is within the threshold is {ev.prob_ale_within_threshold:.0%}.{qual}"
    )

    data_inputs = [i for i in a.inputs if i.provenance in ("data", "expert_and_data")]
    width = hi / lo if lo > 0 else float("inf")
    top = a.rank_sensitivity[0] if a.rank_sensitivity else None
    credited = {c.control_id for c in a.controls}
    tested = [c for c in a.control_assessments if c.control_id in credited and c.conclusion == "effective"]
    confident = (
        f"The ALE credible interval spans a factor of {width:.1f}. {len(data_inputs)} of {len(a.inputs)} inputs "
        f"are data-derived; the rest are expert judgement or assumptions. "
    )
    if top is not None:
        confident += (
            f"The largest single source of uncertainty in the ALE is {input_label(top.input)} "
            f"(rank correlation {top.spearman_rho:+.2f}), so better measurement of this input would narrow "
            "the estimate most. "
        )
    confident += (
        f"{len(tested)} of the {len(credited)} controls credited today are tested effective. "
        f"The Monte Carlo error on the ALE is ±{money(s.ale_mc_standard_error, cur)} ({a.trials:,} trials). "
        "This is simulation precision only and does not reflect input uncertainty."
    )

    reduction = inh.stats.ale - s.ale
    pct = reduction / inh.stats.ale if inh.stats.ale > 0 else 0.0
    controls = (
        f"The linked controls, as implemented and tested, reduce the ALE from {money(inh.stats.ale, cur)} "
        f"(inherent) to {money(s.ale, cur)}, a reduction of {pct:.0%}."
    )
    if a.controls:
        parts = [
            f"{c.control_id} (+{money(c.ale_increase_if_failed, cur)} if it failed)" for c in a.controls[:3]
        ]
        controls += f" The most critical controls are {', '.join(parts)}."
    not_credited = [n for n in a.model_notes if "not credited" in n]
    if not_credited:
        controls += " Not credited: " + " ".join(not_credited)

    drivers = ", ".join(
        f"{input_label(b.input)} ({money(b.ale_at_low, cur)}–{money(b.ale_at_high, cur)})"
        for b in a.tornado[:3]
    )
    stresses = "; ".join(
        f"{r.name}: ALE {money(r.ale, cur)} ({r.ale_change_pct:+.0%}), level '{r.risk_level}'"
        for r in a.stress_tests
    )
    what_if = (
        f"The main drivers, each moved from its P10 to its P90, are {drivers}. Stress tests: {stresses}."
    )

    if a.options:
        best = a.options[0]
        rosi = f"ROSI {best.rosi:+.0%}" if best.rosi is not None else "no cost recorded"
        mitigation = (
            f"The largest risk reduction comes from option {best.option_id} '{best.title}': ALE −"
            f"{money(best.ale_reduction, cur)} (±{money(best.ale_reduction_se_paired, cur)}, paired estimate), "
            f"VaR95 −{money(best.var_95_reduction, cur)}. Its annualised cost is "
            f"{money(best.annualised_cost, cur)} ({rosi}), and the residual level would be '{best.residual_level}'"
            f"{'' if best.within_appetite else ' (still outside appetite)'}."
        )
        if len(a.options) > 1:
            mitigation += " Other options: " + "; ".join(
                f"{o.option_id} ALE −{money(o.ale_reduction, cur)}, cost {money(o.annualised_cost, cur)}/yr"
                for o in a.options[1:]
            )
            mitigation += "."
        if TARGET in a.states:
            mitigation += (
                f" The selected treatment gives a target ALE of {money(a.states[TARGET].stats.ale, cur)} "
                f"('{a.states[TARGET].banded.risk_level}')."
            )
    else:
        mitigation = "No treatment options are defined for this scenario."

    headline = (
        f"{a.scenario_id} {a.scenario_title}: current risk '{now.banded.risk_level}', ALE "
        f"{money(s.ale, cur)} (90% CI {money(lo, cur)}–{money(hi, cur)}), {appetite} appetite."
    )
    return Explanation(
        headline=headline,
        what_is_the_risk=what,
        why_this_level=why,
        how_confident=confident,
        which_controls=controls,
        what_if=what_if,
        best_mitigation=mitigation,
    )
