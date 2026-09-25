"""Control effectiveness from test evidence.

Operating effectiveness is treated as what it is statistically: an unknown
proportion estimated from an attribute sample. With ``n`` samples and ``k``
exceptions and a Beta(α₀, β₀) prior on the operating rate, the posterior is::

    operating rate ~ Beta(α₀ + n − k, β₀ + k)

The conclusion follows audit-sampling logic, expressed in Bayesian terms. Given
a *tolerable deviation rate* (TDR) and a required confidence ``c``:

* **effective** if P(deviation rate ≤ TDR) ≥ c
* **not effective** if P(deviation rate > TDR) ≥ c
* **inconclusive** otherwise. The sample is too small to conclude either way.

With a uniform prior, TDR = 10 % and c = 90 %, zero exceptions need 21 samples.
The classical (Clopper-Pearson) plan needs 22. The two frameworks agree closely,
and the Clopper-Pearson bound is reported alongside for auditors who expect it.

An untested control keeps the prior. It still receives *some* credit in the
simulation, but with maximal uncertainty, so sensitivity analysis flags it as a
driver. Testing is then the obvious next step: this is value of information in
practice.
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from sextant.domain.controls import Control, DesignConclusion, TestKind
from sextant.domain.estimates import Provenance
from sextant.domain.methodology import ControlTestingPolicy
from sextant.engine.bayes import BetaPosterior, beta_binomial_update, clopper_pearson_upper
from sextant.engine.distributions import BetaDist


class OperatingConclusion(StrEnum):
    EFFECTIVE = "effective"
    NOT_EFFECTIVE = "not_effective"
    INCONCLUSIVE = "inconclusive"
    NOT_TESTED = "not_tested"


class DesignStatus(StrEnum):
    EFFECTIVE = "effective"
    INEFFECTIVE = "ineffective"
    NOT_TESTED = "not_tested"


class ControlAssessment(BaseModel):
    """Result of evaluating a control's test evidence as of a date."""

    model_config = ConfigDict(frozen=True)

    control_id: str
    as_of: date
    design_status: DesignStatus
    tests_considered: list[str]
    samples: int
    exceptions: int
    posterior_alpha: float
    posterior_beta: float
    operating_rate_mean: float
    operating_rate_interval_90: tuple[float, float]
    prob_deviation_within_tolerance: float
    deviation_upper_bound_bayes: float
    deviation_upper_bound_clopper_pearson: float | None
    conclusion: OperatingConclusion
    conclusion_basis: str  # "statistical" or "judgemental (frequency-based)"
    additional_samples_needed: int | None
    explanation: str

    def operating_distribution(self) -> BetaDist:
        prov = Provenance.DATA if self.samples > 0 else Provenance.ASSUMPTION
        note = (
            f"control tests: {self.exceptions} exceptions in {self.samples} samples"
            if self.samples
            else "untested: uninformative prior"
        )
        return BetaDist(self.posterior_alpha, self.posterior_beta, provenance=prov, note=note)


def _conclude(post: BetaPosterior, policy: ControlTestingPolicy) -> tuple[float, OperatingConclusion]:
    p_within = post.prob_above(1.0 - policy.tolerable_deviation_rate)
    if p_within >= policy.required_confidence:
        return p_within, OperatingConclusion.EFFECTIVE
    if 1.0 - p_within >= policy.required_confidence:
        return p_within, OperatingConclusion.NOT_EFFECTIVE
    return p_within, OperatingConclusion.INCONCLUSIVE


def _samples_to_conclude(n: int, k: int, policy: ControlTestingPolicy, limit: int = 2000) -> int | None:
    """Extra exception-free samples needed to reach an 'effective' conclusion."""
    for extra in range(1, limit + 1):
        post = beta_binomial_update(n + extra - k, n + extra, policy.prior_alpha, policy.prior_beta)
        if _conclude(post, policy)[1] is OperatingConclusion.EFFECTIVE:
            return extra
    return None


def assess_control(control: Control, policy: ControlTestingPolicy, as_of: date) -> ControlAssessment:
    window_start = as_of - timedelta(days=policy.lookback_days)
    in_window = [t for t in control.tests if window_start <= t.performed_on <= as_of]

    design_tests = [t for t in in_window if t.kind is TestKind.DESIGN]
    if not design_tests:
        design = DesignStatus.NOT_TESTED
    else:
        latest = max(design_tests, key=lambda t: t.performed_on)
        design = (
            DesignStatus.EFFECTIVE
            if latest.design_conclusion is DesignConclusion.EFFECTIVE
            else DesignStatus.INEFFECTIVE
        )

    op_tests = [t for t in in_window if t.kind is TestKind.OPERATING]
    n = sum(t.samples or 0 for t in op_tests)
    k = sum(t.exceptions or 0 for t in op_tests)
    post = beta_binomial_update(n - k, n, policy.prior_alpha, policy.prior_beta)
    # Deviation rate = 1 − operating rate ~ Beta(β, α).
    dev_upper = 1.0 - post.interval(2 * policy.required_confidence - 1)[0]
    if n == 0:
        p_within, conclusion = (
            post.prob_above(1 - policy.tolerable_deviation_rate),
            OperatingConclusion.NOT_TESTED,
        )
        cp_upper = None
    else:
        p_within, conclusion = _conclude(post, policy)
        cp_upper = clopper_pearson_upper(k, n, policy.required_confidence)

    # Low-frequency controls (annual, quarterly, ...) cannot yield statistical samples. Audit
    # practice then tests a small judgemental sample: any exception is a deficiency. The
    # *conclusion* follows that convention, but the *quantitative model* still uses the Beta
    # posterior, which keeps the uncertainty of a 2-sample test visible in the risk estimate.
    basis = "statistical"
    min_n = policy.judgemental_min_samples.get(control.frequency.value)
    if min_n is not None and n > 0:
        basis = "judgemental (frequency-based)"
        if k > 0:
            conclusion = OperatingConclusion.NOT_EFFECTIVE
        elif n >= min_n:
            conclusion = OperatingConclusion.EFFECTIVE
        else:
            conclusion = OperatingConclusion.INCONCLUSIVE

    extra = None
    if basis == "statistical" and conclusion in (
        OperatingConclusion.INCONCLUSIVE,
        OperatingConclusion.NOT_TESTED,
    ):
        extra = _samples_to_conclude(n, k, policy)

    tdr = policy.tolerable_deviation_rate
    conf = policy.required_confidence
    if conclusion is OperatingConclusion.NOT_TESTED:
        text = (
            f"No operating-effectiveness tests in the last {policy.lookback_days} days. "
            f"The model uses the uninformative prior (mean operating rate {post.mean:.0%}). "
            f"{extra} exception-free samples would support an 'effective' conclusion."
        )
    elif basis != "statistical":
        text = (
            f"{control.frequency.value.capitalize()} control: {k} exception(s) in {n} samples "
            f"(audit convention: at least {min_n} samples and no exceptions). "
            f"Conclusion: {conclusion.value.replace('_', ' ')}. The risk model still uses the posterior "
            f"operating rate (mean {post.mean:.0%}), which reflects how little a small sample proves."
        )
    else:
        text = (
            f"{k} exception(s) in {n} samples. The posterior mean operating rate is {post.mean:.1%}. "
            f"P(deviation rate ≤ {tdr:.0%}) = {p_within:.1%} against a required {conf:.0%}. "
            f"Conclusion: {conclusion.value.replace('_', ' ')}."
        )
        if cp_upper is not None:
            text += f" Classical {conf:.0%} upper bound on the deviation rate: {cp_upper:.1%}."
        if extra:
            text += f" About {extra} further exception-free samples are needed to conclude."
    if design is DesignStatus.INEFFECTIVE:
        text += " The latest design test concluded INEFFECTIVE, so no risk-reduction credit is given."

    return ControlAssessment(
        control_id=control.id,
        as_of=as_of,
        design_status=design,
        tests_considered=[t.id or f"{t.kind.value}@{t.performed_on}" for t in in_window],
        samples=n,
        exceptions=k,
        posterior_alpha=post.alpha,
        posterior_beta=post.beta,
        operating_rate_mean=post.mean,
        operating_rate_interval_90=post.interval(0.90),
        prob_deviation_within_tolerance=p_within,
        deviation_upper_bound_bayes=dev_upper,
        deviation_upper_bound_clopper_pearson=cp_upper,
        conclusion=conclusion,
        conclusion_basis=basis,
        additional_samples_needed=extra,
        explanation=text,
    )
