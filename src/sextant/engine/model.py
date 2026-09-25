"""Compile a scenario and control library into a simulation-ready model.

This is where the register vocabulary (scenario, control, test, treatment) is
translated into mathematical objects (distributions and multipliers).
Resolution is explicit and every step is recorded in ``notes``:

* which controls are credited in the *current* state and why (status, design
  test),
* where each operating rate comes from: test posterior, explicit override, or
  prior,
* which *control states* will be compared:

  - ``inherent``: none of the linked controls
  - ``current``: controls in operation, as tested
  - ``target``: current plus the selected treatment
  - ``option:<id>``: current plus each treatment option
  - ``without:<control>``: current minus one control (leave-one-out
    importance)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from sextant.domain.controls import Control
from sextant.domain.methodology import Methodology
from sextant.domain.scenario import (
    ControlEffect,
    ControlTarget,
    Insurance,
    LossForm,
    Scenario,
    TreatmentOption,
    TreatmentType,
)
from sextant.engine.controls import ControlAssessment, DesignStatus, assess_control
from sextant.engine.distributions import Distribution, build

INHERENT = "inherent"
CURRENT = "current"
TARGET = "target"


class ModelError(ValueError):
    """The scenario cannot be compiled (e.g. references an unknown control)."""


@dataclass(frozen=True)
class ComponentModel:
    name: str
    form: LossForm
    secondary: bool
    dist: Distribution


@dataclass(frozen=True)
class EffectModel:
    key: str
    control_id: str
    control_name: str
    target: ControlTarget
    loss_forms: frozenset[LossForm] | None

    def applies_to(self, comp: ComponentModel) -> bool:
        if self.target is ControlTarget.PRIMARY_LOSS and comp.secondary:
            return False
        if self.target is ControlTarget.SECONDARY_LOSS and not comp.secondary:
            return False
        return self.loss_forms is None or comp.form in self.loss_forms


@dataclass(frozen=True)
class EffectVariant:
    """How an effect is applied in a given control state.

    Variants of the same effect in different states share random numbers (the
    effect key), so a treatment that raises coverage or operating rate is
    compared with the current state draw by draw.
    """

    reduction: Distribution
    operating: Distribution
    coverage: float
    operating_source: str
    rationale: str


@dataclass(frozen=True)
class ControlState:
    name: str
    label: str
    effects: Mapping[str, EffectVariant]
    insurance: Insurance | None = None
    avoid: bool = False
    treatment: TreatmentOption | None = None


@dataclass(frozen=True)
class ScenarioModel:
    scenario: Scenario
    methodology: Methodology
    as_of: date
    tef: Distribution
    susceptibility: Distribution
    secondary_probability: Distribution | None
    components: tuple[ComponentModel, ...]
    effects: Mapping[str, EffectModel]
    states: Mapping[str, ControlState]
    control_assessments: Mapping[str, ControlAssessment]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def credited_controls(self) -> list[str]:
        """Controls (ids) credited in the current state, in link order."""
        seen: dict[str, None] = {}
        for key in self.states[CURRENT].effects:
            seen.setdefault(self.effects[key].control_id, None)
        return list(seen)


def _effect_key(effect: ControlEffect) -> str:
    key = f"{effect.control_id}:{effect.target.value}"
    if effect.loss_forms:
        key += ":" + "+".join(sorted(f.value for f in effect.loss_forms))
    return key


def build_model(
    scenario: Scenario,
    controls: Mapping[str, Control],
    methodology: Methodology,
    as_of: date,
) -> ScenarioModel:
    notes: list[str] = []
    policy = methodology.control_testing

    components = tuple(
        [ComponentModel(c.name, c.form, False, build(c.magnitude)) for c in scenario.primary_losses]
        + (
            [
                ComponentModel(c.name, c.form, True, build(c.magnitude))
                for c in scenario.secondary_loss.components
            ]
            if scenario.secondary_loss
            else []
        )
    )

    # Assess every control referenced by the scenario or its treatments.
    referenced = {e.control_id for e in scenario.controls} | {
        e.control_id for t in scenario.treatments for e in t.add_controls
    }
    missing = sorted(referenced - set(controls))
    if missing:
        raise ModelError(f"scenario {scenario.id} references unknown controls: {missing}")
    assessments = {cid: assess_control(controls[cid], policy, as_of) for cid in sorted(referenced)}

    effects: dict[str, EffectModel] = {}
    current: dict[str, EffectVariant] = {}

    def register(effect: ControlEffect, *, unique: bool) -> EffectModel:
        key = _effect_key(effect)
        if key in effects:
            if unique:
                raise ModelError(f"scenario {scenario.id}: duplicate control effect '{key}'")
            return effects[key]
        model = EffectModel(
            key=key,
            control_id=effect.control_id,
            control_name=controls[effect.control_id].name,
            target=effect.target,
            loss_forms=frozenset(effect.loss_forms) if effect.loss_forms else None,
        )
        effects[key] = model
        return model

    def variant(effect: ControlEffect) -> EffectVariant:
        reduction = build(effect.reduction)
        if effect.operating_rate is not None:
            return EffectVariant(
                reduction,
                build(effect.operating_rate),
                effect.coverage,
                "explicit estimate",
                effect.rationale,
            )
        assessment = assessments[effect.control_id]
        source = "control tests" if assessment.samples else "uninformative prior (untested)"
        return EffectVariant(
            reduction, assessment.operating_distribution(), effect.coverage, source, effect.rationale
        )

    for effect in scenario.controls:
        model = register(effect, unique=True)
        ctl = controls[effect.control_id]
        assessment = assessments[effect.control_id]
        if not ctl.status.is_in_operation:
            notes.append(f"{ctl.id} is {ctl.status.value}: not credited in current risk.")
            continue
        if assessment.design_status is DesignStatus.INEFFECTIVE:
            notes.append(f"{ctl.id} failed its latest design test: not credited in current risk.")
            continue
        v = variant(effect)
        current[model.key] = v
        if effect.operating_rate is not None and assessment.samples:
            notes.append(
                f"{ctl.id}: explicit operating-rate estimate overrides test evidence "
                f"({assessment.exceptions}/{assessment.samples} exceptions); justify in rationale."
            )

    states: dict[str, ControlState] = {
        INHERENT: ControlState(INHERENT, "Inherent (without linked controls)", {}),
        CURRENT: ControlState(CURRENT, "Current (controls as implemented and tested)", dict(current)),
    }

    def apply_option(option: TreatmentOption) -> ControlState:
        eff = dict(current)
        for add in option.add_controls:
            if _effect_key(add) in eff:
                raise ModelError(
                    f"treatment '{option.id}' adds effect '{_effect_key(add)}' which is already credited; "
                    "use change_controls to improve an existing control"
                )
            # A planned control linked to the scenario (or added by another option)
            # reuses its effect identity, and therefore its random numbers.
            model = register(add, unique=False)
            eff[model.key] = variant(add)
        for change in option.change_controls:
            keys = [k for k, m in effects.items() if m.control_id == change.control_id and k in eff]
            if not keys:
                raise ModelError(
                    f"treatment '{option.id}' changes {change.control_id}, which is not credited in current risk"
                )
            for k in keys:
                old = eff[k]
                eff[k] = EffectVariant(
                    reduction=old.reduction,
                    operating=build(change.operating_rate) if change.operating_rate else old.operating,
                    coverage=change.coverage if change.coverage is not None else old.coverage,
                    operating_source="treatment estimate" if change.operating_rate else old.operating_source,
                    rationale=change.rationale,
                )
        return ControlState(
            name=f"option:{option.id}",
            label=f"Option {option.id}: {option.title}",
            effects=eff,
            insurance=option.insurance,
            avoid=option.type is TreatmentType.AVOID,
            treatment=option,
        )

    for option in scenario.treatments:
        state = apply_option(option)
        states[state.name] = state
        if option.id == scenario.selected_treatment:
            states[TARGET] = ControlState(
                TARGET,
                f"Target (after '{option.title}')",
                state.effects,
                state.insurance,
                state.avoid,
                option,
            )

    credited = {effects[k].control_id for k in current}
    for cid in sorted(credited):
        remaining = {k: v for k, v in current.items() if effects[k].control_id != cid}
        states[f"without:{cid}"] = ControlState(f"without:{cid}", f"Current without {cid}", remaining)

    return ScenarioModel(
        scenario=scenario,
        methodology=methodology,
        as_of=as_of,
        tef=build(scenario.threat_event_frequency),
        susceptibility=build(scenario.susceptibility),
        secondary_probability=build(scenario.secondary_loss.probability) if scenario.secondary_loss else None,
        components=components,
        effects=effects,
        states=states,
        control_assessments=assessments,
        notes=tuple(notes),
    )
