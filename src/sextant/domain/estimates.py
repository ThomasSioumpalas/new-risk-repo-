"""Estimate specifications: how uncertain quantities are expressed.

Every uncertain input in Sextant is an *estimate*: a probability distribution
together with where it came from (``source``) and why (``rationale``). The
specification here is pure data. The mathematics lives in
:mod:`sextant.engine.distributions`.

Two families of estimate exist:

* **Expert-judgement** estimates (``lognormal`` from a calibrated interval,
  ``pert``, ``uniform``, ``beta``, ``gamma``, ``constant``).
* **Data-derived** estimates (``beta_from_trials``, ``gamma_from_events``).
  They are Bayesian posteriors computed from observed counts, for example
  control-test samples, phishing-simulation clicks, red-team attempts or
  incident history.

Keeping the two families apart lets the reports say how much of a risk estimate
rests on data and how much on judgement.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


class Provenance(StrEnum):
    """Where an estimate comes from. Reported alongside every result."""

    EXPERT = "expert_judgement"
    DATA = "data"
    EXPERT_AND_DATA = "expert_and_data"
    ASSUMPTION = "assumption"


class _EstimateBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str | None = Field(
        default=None, description="Who or what produced the estimate (workshop, dataset, test)."
    )
    rationale: str | None = Field(default=None, description="Why these values are reasonable.")


class ConstantEstimate(_EstimateBase):
    """A known value. Use sparingly: a constant claims zero uncertainty."""

    dist: Literal["constant"] = "constant"
    value: float = Field(ge=0)

    @property
    def provenance(self) -> Provenance:
        return Provenance.ASSUMPTION


class LognormalEstimate(_EstimateBase):
    """Right-skewed positive quantity from a calibrated confidence interval.

    ``low`` and ``high`` are the lower and upper bounds of a central
    ``confidence`` interval (default 90 %: the 5th and 95th percentiles). This
    is the standard way to elicit loss magnitudes and frequencies from calibrated
    experts (Hubbard & Seiersen). ``cap`` optionally censors the distribution at
    a maximum plausible value, such as the total value of the asset.
    """

    dist: Literal["lognormal"] = "lognormal"
    low: float = Field(gt=0)
    high: float = Field(gt=0)
    confidence: float = Field(default=0.90, gt=0.5, lt=1.0)
    cap: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check_order(self) -> LognormalEstimate:
        if self.high <= self.low:
            raise ValueError("lognormal: 'high' must be greater than 'low'")
        if self.cap is not None and self.cap < self.high:
            raise ValueError("lognormal: 'cap' must be >= 'high' (otherwise the interval is not credible)")
        return self

    @property
    def provenance(self) -> Provenance:
        return Provenance.EXPERT


class PertEstimate(_EstimateBase):
    """Bounded estimate from minimum / most likely / maximum (modified PERT).

    This is the conventional FAIR input form. ``shape`` (λ, default 4) controls
    how strongly the mode is weighted.
    """

    dist: Literal["pert"] = "pert"
    min: float
    mode: float
    max: float
    shape: float = Field(default=4.0, gt=0)

    @model_validator(mode="after")
    def _check_order(self) -> PertEstimate:
        if not (self.min <= self.mode <= self.max):
            raise ValueError("pert: require min <= mode <= max")
        if self.min < 0:
            raise ValueError("pert: values must be non-negative")
        return self

    @property
    def provenance(self) -> Provenance:
        return Provenance.EXPERT


class UniformEstimate(_EstimateBase):
    """All values in [low, high] are equally plausible: maximum ignorance within bounds."""

    dist: Literal["uniform"] = "uniform"
    low: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def _check_order(self) -> UniformEstimate:
        if self.high < self.low:
            raise ValueError("uniform: 'high' must be >= 'low'")
        return self

    @property
    def provenance(self) -> Provenance:
        return Provenance.EXPERT


class BetaEstimate(_EstimateBase):
    """Probability with explicit Beta(alpha, beta) parameters."""

    dist: Literal["beta"] = "beta"
    alpha: float = Field(gt=0)
    beta: float = Field(gt=0)

    @property
    def provenance(self) -> Provenance:
        return Provenance.EXPERT


class BetaFromTrialsEstimate(_EstimateBase):
    """Probability estimated from observed trials: a Beta-Binomial posterior.

    ``successes`` counts the outcome whose probability is being estimated. For
    example, 7 successful prompt injections in 200 attempts, or 38 users who
    clicked in a 500-email phishing simulation. The prior defaults to
    Beta(1, 1), which is uniform and deliberately uninformative.
    """

    dist: Literal["beta_from_trials"] = "beta_from_trials"
    successes: int = Field(ge=0)
    trials: int = Field(gt=0)
    prior_alpha: float = Field(default=1.0, gt=0)
    prior_beta: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def _check_counts(self) -> BetaFromTrialsEstimate:
        if self.successes > self.trials:
            raise ValueError("beta_from_trials: successes cannot exceed trials")
        return self

    @property
    def provenance(self) -> Provenance:
        return Provenance.DATA


class GammaEstimate(_EstimateBase):
    """Rate (events per year) with explicit Gamma(shape, rate) parameters."""

    dist: Literal["gamma"] = "gamma"
    shape: float = Field(gt=0)
    rate: float = Field(gt=0)

    @property
    def provenance(self) -> Provenance:
        return Provenance.EXPERT


class GammaFromEventsEstimate(_EstimateBase):
    """Event rate from history: a Gamma-Poisson posterior.

    ``events`` were observed over ``exposure_years``. The prior is one of:

    * an expert 90 % interval (``prior_low``, ``prior_high``). A Gamma prior is
      fitted to it, and the posterior blends expert opinion with data (a
      credibility weighting).
    * explicit ``prior_shape`` / ``prior_rate``. The default, shape 0.5 and
      rate 0, is the Jeffreys prior, so the data speaks almost entirely for
      itself.
    """

    dist: Literal["gamma_from_events"] = "gamma_from_events"
    events: int = Field(ge=0)
    exposure_years: float = Field(gt=0)
    prior_low: float | None = Field(default=None, gt=0)
    prior_high: float | None = Field(default=None, gt=0)
    prior_shape: float = Field(default=0.5, gt=0)
    prior_rate: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _check_prior(self) -> GammaFromEventsEstimate:
        if (self.prior_low is None) != (self.prior_high is None):
            raise ValueError("gamma_from_events: give both prior_low and prior_high, or neither")
        if self.prior_low is not None and self.prior_high is not None and self.prior_high <= self.prior_low:
            raise ValueError("gamma_from_events: prior_high must exceed prior_low")
        return self

    @property
    def provenance(self) -> Provenance:
        if self.prior_low is not None:
            return Provenance.EXPERT_AND_DATA
        return Provenance.DATA


Estimate = Annotated[
    ConstantEstimate
    | LognormalEstimate
    | PertEstimate
    | UniformEstimate
    | BetaEstimate
    | BetaFromTrialsEstimate
    | GammaEstimate
    | GammaFromEventsEstimate,
    Field(discriminator="dist"),
]


# --- Semantic constraints -----------------------------------------------------------
# Distribution *families* are generic. What a quantity means restricts which
# families make sense: a probability cannot be lognormal, and a loss cannot be a
# Gamma rate posterior. These validators turn such modelling errors into
# validation errors at the boundary instead of silent nonsense inside the engine.


def _require_probability(est: Estimate) -> Estimate:
    match est:
        case ConstantEstimate(value=v) if not 0.0 <= v <= 1.0:
            raise ValueError("probability must be within [0, 1]")
        case PertEstimate(max=hi) if hi > 1.0:
            raise ValueError("probability PERT must have max <= 1")
        case UniformEstimate(high=hi) if hi > 1.0:
            raise ValueError("probability uniform must have high <= 1")
        case LognormalEstimate() | GammaEstimate() | GammaFromEventsEstimate():
            raise ValueError(
                f"'{est.dist}' is not valid for a probability; use pert, beta or beta_from_trials"
            )
    return est


def _require_frequency(est: Estimate) -> Estimate:
    if isinstance(est, BetaEstimate | BetaFromTrialsEstimate):
        raise ValueError(f"'{est.dist}' is bounded to [0, 1] and is not valid for an annual frequency")
    return est


def _require_magnitude(est: Estimate) -> Estimate:
    if isinstance(est, BetaEstimate | BetaFromTrialsEstimate | GammaEstimate | GammaFromEventsEstimate):
        raise ValueError(f"'{est.dist}' is not valid for a loss magnitude; use lognormal, pert or uniform")
    return est


ProbabilityEstimate = Annotated[Estimate, AfterValidator(_require_probability)]
FrequencyEstimate = Annotated[Estimate, AfterValidator(_require_frequency)]
MagnitudeEstimate = Annotated[Estimate, AfterValidator(_require_magnitude)]


def provenance_of(est: Estimate) -> Provenance:
    """Return the provenance category of an estimate."""
    return est.provenance
