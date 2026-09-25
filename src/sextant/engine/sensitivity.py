"""Sensitivity and stress analysis: "what would happen if the assumptions changed?"

Three complementary views are provided:

1. **Tornado (one-at-a-time, analytic).** Each input is moved to its 10th and
   90th percentile while the others stay at their means, and the resulting
   expected annual loss is computed in closed form. Because the ALE is
   multilinear in independent inputs, the baseline equals the simulated ALE,
   which makes the chart exact rather than simulated. For loss-magnitude
   components the swing means "every event at the component's P10 / P90".
   That is a stress of event severity, labelled as such.
2. **Global rank sensitivity.** The Spearman correlation between each
   *epistemic* input draw and the trial's conditional expected loss. It ranks
   which *uncertainty* drives the uncertainty of the ALE, which indicates where
   better measurement (more data, control testing) has the most value of
   information.
3. **Stress tests.** Named what-if scenarios (e.g. "threat frequency doubles",
   "backup control fails") re-simulated with the same random numbers.
"""

from __future__ import annotations

import dataclasses

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy import stats

from sextant.domain.scenario import ControlTarget
from sextant.engine.distributions import Constant, Distribution, Scaled
from sextant.engine.model import CURRENT, ControlState, EffectVariant, ScenarioModel
from sextant.engine.simulation import SimulationRun


class TornadoBar(BaseModel):
    model_config = ConfigDict(frozen=True)

    input: str
    kind: str  # "epistemic" or "severity stress"
    low_value: float
    high_value: float
    ale_at_low: float
    ale_at_high: float
    swing: float


class RankSensitivity(BaseModel):
    model_config = ConfigDict(frozen=True)

    input: str
    spearman_rho: float
    share_of_explained: float


class StressTest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    tef_multiplier: float = Field(default=1.0, gt=0)
    susceptibility_multiplier: float = Field(default=1.0, gt=0)
    magnitude_multiplier: float = Field(default=1.0, gt=0)
    failed_controls: list[str] = Field(default_factory=list)


def default_stress_tests(model: ScenarioModel) -> list[StressTest]:
    tests = [
        StressTest(name="TEF ×2", description="Threat event frequency doubles.", tef_multiplier=2.0),
        StressTest(
            name="Magnitude ×2", description="Every loss form costs twice as much.", magnitude_multiplier=2.0
        ),
    ]
    tests += [
        StressTest(
            name=f"{cid} fails",
            description=f"{cid} stops operating (operating rate = 0).",
            failed_controls=[cid],
        )
        for cid in model.credited_controls
    ]
    return tests


# --- analytic expected annual loss ----------------------------------------------------


def _expected_loss(
    model: ScenarioModel,
    state: ControlState,
    point: dict[str, float],
) -> float:
    """Closed-form E[annual loss] for a state with every input at a point value."""
    m_freq, m_psec = 1.0, 1.0
    m_comp = {c.name: 1.0 for c in model.components}
    for key in state.effects:
        eff = model.effects[key]
        factor = 1.0 - point[f"reduction:{key}"] * point[f"operating:{key}"] * point[f"coverage:{key}"]
        if eff.target.is_frequency:
            m_freq *= factor
        elif eff.target is ControlTarget.SECONDARY_LOSS_PROBABILITY:
            m_psec *= factor
        else:
            for c in model.components:
                if eff.applies_to(c):
                    m_comp[c.name] *= factor
    if state.avoid:
        return 0.0
    lam = point["threat_event_frequency"] * point["susceptibility"] * m_freq
    primary = sum(point[f"magnitude:{c.name}"] * m_comp[c.name] for c in model.components if not c.secondary)
    secondary = sum(point[f"magnitude:{c.name}"] * m_comp[c.name] for c in model.components if c.secondary)
    p_sec = point.get("secondary_loss_probability", 0.0)
    return lam * (primary + p_sec * m_psec * secondary)


def _inputs(model: ScenarioModel, state: ControlState) -> dict[str, tuple[Distribution, str]]:
    inputs: dict[str, tuple[Distribution, str]] = {
        "threat_event_frequency": (model.tef, "epistemic"),
        "susceptibility": (model.susceptibility, "epistemic"),
    }
    if model.secondary_probability is not None:
        inputs["secondary_loss_probability"] = (model.secondary_probability, "epistemic")
    for key, var in state.effects.items():
        inputs[f"reduction:{key}"] = (var.reduction, "epistemic")
        inputs[f"operating:{key}"] = (var.operating, "epistemic")
    for c in model.components:
        inputs[f"magnitude:{c.name}"] = (c.dist, "severity stress")
    return inputs


def tornado(
    model: ScenarioModel, state_name: str = CURRENT, low_q: float = 0.10, high_q: float = 0.90
) -> list[TornadoBar]:
    state = model.states[state_name]
    inputs = _inputs(model, state)
    base = {name: dist.mean() for name, (dist, _) in inputs.items()}
    base |= {f"coverage:{k}": v.coverage for k, v in state.effects.items()}
    bars = []
    for name, (dist, kind) in inputs.items():
        lo, hi = dist.quantile(low_q), dist.quantile(high_q)
        at_lo = _expected_loss(model, state, base | {name: lo})
        at_hi = _expected_loss(model, state, base | {name: hi})
        bars.append(
            TornadoBar(
                input=name,
                kind=kind,
                low_value=lo,
                high_value=hi,
                ale_at_low=at_lo,
                ale_at_high=at_hi,
                swing=abs(at_hi - at_lo),
            )
        )
    return sorted(bars, key=lambda b: b.swing, reverse=True)


def baseline_expected_loss(model: ScenarioModel, state_name: str = CURRENT) -> float:
    state = model.states[state_name]
    point = {name: dist.mean() for name, (dist, _) in _inputs(model, state).items()}
    point |= {f"coverage:{k}": v.coverage for k, v in state.effects.items()}
    return _expected_loss(model, state, point)


def rank_sensitivity(run: SimulationRun, state_name: str = CURRENT) -> list[RankSensitivity]:
    target = run.states[state_name].expected_loss
    rows: list[tuple[str, float]] = []
    for name, draws in run.draws.items():
        if np.ptp(draws) == 0 or np.ptp(target) == 0:
            continue
        rho = float(stats.spearmanr(draws, target).statistic)
        rows.append((name, rho))
    total = sum(r * r for _, r in rows) or 1.0
    out = [RankSensitivity(input=n, spearman_rho=r, share_of_explained=r * r / total) for n, r in rows]
    return sorted(out, key=lambda r: abs(r.spearman_rho), reverse=True)


# --- stress tests ---------------------------------------------------------------------


def apply_stress(model: ScenarioModel, test: StressTest) -> ScenarioModel:
    """Return a model with the stress applied. Random streams are unaffected (same names)."""
    comps = tuple(
        dataclasses.replace(c, dist=Scaled(c.dist, test.magnitude_multiplier))
        if test.magnitude_multiplier != 1.0
        else c
        for c in model.components
    )
    unknown = set(test.failed_controls) - {e.control_id for e in model.effects.values()}
    if unknown:
        raise ValueError(f"stress test references controls not linked to the scenario: {sorted(unknown)}")

    def fail(variant: EffectVariant) -> EffectVariant:
        return dataclasses.replace(
            variant, operating=Constant(0.0), operating_source="stress: control failed"
        )

    def restate(state: ControlState) -> ControlState:
        effects = {
            k: fail(v) if model.effects[k].control_id in test.failed_controls else v
            for k, v in state.effects.items()
        }
        return dataclasses.replace(state, effects=effects)

    def scale(dist: Distribution, factor: float, cap: float | None) -> Distribution:
        return dist if factor == 1.0 else Scaled(dist, factor, cap)

    return dataclasses.replace(
        model,
        tef=scale(model.tef, test.tef_multiplier, None),
        susceptibility=scale(model.susceptibility, test.susceptibility_multiplier, 1.0),
        components=comps,
        states={name: restate(s) for name, s in model.states.items()},
    )
