"""Coupled, FAIR-aligned Monte Carlo simulation.

Algorithm
---------
Each trial represents one possible year.

1. **Epistemic draws per trial**: threat event frequency, susceptibility,
   secondary-loss probability, and for each control effect its reduction and
   operating rate. These are what we are *uncertain about*.
2. **Inherent loss events**: ``N ~ Poisson(TEF × susceptibility)``, the loss
   events that would occur without any of the linked controls.
3. **Per-event draws**: loss-form magnitudes, correlated through a one-factor
   Gaussian copula; a survival uniform ``V``; a secondary-trigger uniform ``W``.
   These represent *variability* between events.
4. **Every control state is evaluated on the same events.** A frequency
   multiplier ``m`` keeps an event if ``V < m``. By Poisson thinning the
   surviving events are exactly ``Poisson(λ·m)``. Magnitude controls scale the
   loss-form amounts. Secondary loss occurs if ``W < p_sec · m_sec``.

Because all states share the same draws (common random numbers), the
differences between inherent, current, target and treatment options reflect
*only* the controls. In each trial, adding a control can never increase the
loss. This is a property the test-suite verifies. Differences between options
are therefore estimated far more precisely than with independent runs.

Random streams are derived from ``(seed, scenario id, input name)``. Adding a
treatment option does not change the draws of any other input, so results stay
reproducible and comparable across model revisions.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import stats

from sextant.domain.scenario import ControlTarget, LossForm
from sextant.engine.model import ControlState, ScenarioModel

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


class SimulationTooLargeError(ValueError):
    """The requested simulation would exceed the configured event budget."""


def stream(seed: int, scenario_id: str, name: str) -> np.random.Generator:
    """Independent, named random stream: reproducible and insensitive to model edits."""
    digest = hashlib.sha256(f"{scenario_id}/{name}".encode()).digest()
    key = int.from_bytes(digest[:8], "big")
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=(key,))))


@dataclass(frozen=True)
class StateOutcome:
    """Simulation output for one control state (arrays have one entry per trial)."""

    name: str
    label: str
    annual_loss: FloatArray
    expected_loss: FloatArray  # E[annual loss | epistemic parameters of the trial]
    loss_event_rate: FloatArray  # λ for the trial
    event_counts: IntArray
    loss_by_form: dict[LossForm, FloatArray]
    gross_loss: FloatArray  # before insurance recoveries


@dataclass(frozen=True)
class SimulationRun:
    scenario_id: str
    trials: int
    seed: int
    correlation: float
    inherent_events: int
    draws: dict[str, FloatArray]  # epistemic inputs by name (for sensitivity analysis)
    states: dict[str, StateOutcome]


def simulate(
    model: ScenarioModel,
    *,
    trials: int,
    seed: int,
    states: Iterable[str] | None = None,
    correlation: float | None = None,
    max_events: int | None = None,
) -> SimulationRun:
    settings = model.methodology.simulation
    if trials < 100 or trials > settings.max_trials:
        raise ValueError(f"trials must be between 100 and {settings.max_trials}")
    rho = settings.loss_component_correlation if correlation is None else correlation
    budget = settings.max_simulated_events if max_events is None else max_events
    sid = model.scenario.id
    selected = list(model.states) if states is None else list(states)

    def uniforms(name: str, size: int) -> FloatArray:
        return stream(seed, sid, name).random(size)

    # 1. Epistemic draws per trial.
    tef = model.tef.ppf(uniforms("tef", trials))
    susc = model.susceptibility.ppf(uniforms("susceptibility", trials))
    p_sec = (
        model.secondary_probability.ppf(uniforms("secondary_probability", trials))
        if model.secondary_probability is not None
        else np.zeros(trials)
    )
    draws: dict[str, FloatArray] = {
        "threat_event_frequency": tef,
        "susceptibility": susc,
    }
    if model.secondary_probability is not None:
        draws["secondary_loss_probability"] = p_sec
    u_red = {k: uniforms(f"reduction:{k}", trials) for k in model.effects}
    u_op = {k: uniforms(f"operating:{k}", trials) for k in model.effects}

    # 2. Inherent loss events.
    lam0 = tef * susc
    expected_events = float(lam0.sum())
    if expected_events > budget:
        raise SimulationTooLargeError(
            f"about {expected_events:,.0f} loss events would be simulated (budget {budget:,}). "
            "Reduce trials, or model the threat at a coarser event granularity "
            "(e.g. campaigns rather than individual emails)."
        )
    counts = stream(seed, sid, "event_counts").poisson(lam0).astype(np.int64)
    n_events = int(counts.sum())
    trial_of_event = np.repeat(np.arange(trials), counts)

    # 3. Per-event draws.
    survival = uniforms("survival", n_events)
    sec_trigger = uniforms("secondary_trigger", n_events)
    common = stream(seed, sid, "severity:common").standard_normal(n_events)
    magnitudes: dict[str, FloatArray] = {}
    for comp in model.components:
        idio = stream(seed, sid, f"severity:{comp.name}").standard_normal(n_events)
        z = math.sqrt(rho) * common + math.sqrt(1.0 - rho) * idio
        magnitudes[comp.name] = comp.dist.ppf(stats.norm.cdf(z))
    comp_means = {c.name: c.dist.mean() for c in model.components}

    # 4. Evaluate each control state on the same events.
    outcomes: dict[str, StateOutcome] = {}
    for name in selected:
        state = model.states[name]
        m_freq, m_psec, m_comp, reductions = _multipliers(model, state, trials, u_red, u_op)
        if name == "current":
            draws.update(reductions)
        if state.avoid:
            m_freq = np.zeros(trials)

        keep = survival < m_freq[trial_of_event]
        sec_on = sec_trigger < (p_sec * m_psec)[trial_of_event]
        t_idx = trial_of_event[keep]

        gross_event = np.zeros(int(keep.sum()))
        insurable_event = np.zeros_like(gross_event)
        by_form: dict[LossForm, FloatArray] = {}
        for comp in model.components:
            amount = magnitudes[comp.name] * m_comp[comp.name][trial_of_event]
            if comp.secondary:
                amount = np.where(sec_on, amount, 0.0)
            amount = amount[keep]
            gross_event += amount
            if state.insurance is not None and comp.form not in state.insurance.excluded_forms:
                insurable_event += amount
            annual_form = np.bincount(t_idx, weights=amount, minlength=trials)
            by_form[comp.form] = by_form.get(comp.form, np.zeros(trials)) + annual_form

        retained_event = gross_event
        if state.insurance is not None:
            ins = state.insurance
            recovery = np.clip(insurable_event - ins.deductible, 0.0, ins.limit)
            retained_event = gross_event - recovery

        annual_gross = np.bincount(t_idx, weights=gross_event, minlength=trials)
        annual = np.bincount(t_idx, weights=retained_event, minlength=trials)

        # Conditional expectation given the trial's epistemic parameters (closed form).
        lam = lam0 * m_freq
        primary = sum(
            (comp_means[c.name] * m_comp[c.name] for c in model.components if not c.secondary),
            start=np.zeros(trials),
        )
        secondary = sum(
            (comp_means[c.name] * m_comp[c.name] for c in model.components if c.secondary),
            start=np.zeros(trials),
        )
        expected = lam * (primary + p_sec * m_psec * secondary)
        if state.insurance is not None and annual_gross.sum() > 0:
            # No closed form for the insured layer; scale by the simulated retention ratio.
            expected = expected * (annual.sum() / annual_gross.sum())

        outcomes[name] = StateOutcome(
            name=name,
            label=state.label,
            annual_loss=annual,
            expected_loss=expected,
            loss_event_rate=lam,
            event_counts=np.bincount(t_idx, minlength=trials).astype(np.int64),
            loss_by_form=by_form,
            gross_loss=annual_gross,
        )

    return SimulationRun(
        scenario_id=sid,
        trials=trials,
        seed=seed,
        correlation=rho,
        inherent_events=n_events,
        draws=draws,
        states=outcomes,
    )


def _multipliers(
    model: ScenarioModel,
    state: ControlState,
    trials: int,
    u_red: dict[str, FloatArray],
    u_op: dict[str, FloatArray],
) -> tuple[FloatArray, FloatArray, dict[str, FloatArray], dict[str, FloatArray]]:
    """Per-trial multipliers (1 = no reduction) for frequency, secondary probability and each component.

    Controls acting on the same factor combine multiplicatively,
    ``Π (1 − eᵢ)``, which assumes independent layers of defence. This
    assumption is stated in the methodology and can be tested by
    sensitivity analysis.
    """
    m_freq = np.ones(trials)
    m_psec = np.ones(trials)
    m_comp = {c.name: np.ones(trials) for c in model.components}
    effective: dict[str, FloatArray] = {}
    for key, var in state.effects.items():
        eff = model.effects[key]
        r = var.reduction.ppf(u_red[key])
        o = var.operating.ppf(u_op[key])
        effective[f"reduction:{key}"] = r
        effective[f"operating:{key}"] = o
        e = r * o * var.coverage
        factor = 1.0 - e
        if eff.target.is_frequency:
            m_freq = m_freq * factor
        elif eff.target is ControlTarget.SECONDARY_LOSS_PROBABILITY:
            m_psec = m_psec * factor
        else:
            for comp in model.components:
                if eff.applies_to(comp):
                    m_comp[comp.name] = m_comp[comp.name] * factor
    return m_freq, m_psec, m_comp, effective
