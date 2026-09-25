# Statistical Methods

This document gives the mathematics behind every number Sextant reports, and
why each method was chosen. The code is in [`src/sextant/engine/`](../src/sextant/engine/),
and each claim below is covered by a test in [`tests/validation/`](../tests/validation/)
or [`tests/unit/`](../tests/unit/).

**Design principle.** Use the simplest method that is *statistically
defensible* for sparse, non-stationary, expert-heavy risk data, and that a risk
committee can have explained to it. That leads to conjugate Bayesian models,
Monte Carlo simulation and closed-form checks, and it rules out black-box
models (§12).

---

## 1. Notation

| Symbol | Meaning |
|---|---|
| $T$ | Threat event frequency (events / year) |
| $s$ | Susceptibility: P(threat event → loss event) without the linked controls |
| $\lambda_0 = T s$ | Inherent loss event rate |
| $e_j = r_j o_j c_j$ | Effect of control *j*: design reduction × operating rate × coverage |
| $m_F = \prod_{j \in F}(1-e_j)$ | Frequency multiplier (controls acting on $T$ or $s$) |
| $X_k$ | Loss of form *k* in one event (primary) |
| $Y_k$, $p$ | Secondary loss forms, and the probability of secondary loss |
| $L$ | Annual loss |
| $\theta$ | All *epistemic* parameters of one simulated year ($T, s, p, r_j, o_j$) |

## 2. Expressing uncertainty: estimate types

| Type | Parameterisation | Use | Key formula |
|---|---|---|---|
| **Lognormal from a CI** | 90 % interval $[a, b]$ | Losses, frequencies (positive, right-skewed) | $\mu = \tfrac{\ln a + \ln b}{2}$, $\sigma = \tfrac{\ln b - \ln a}{2 z_{0.95}}$ with $z_{0.95}=1.645$ |
| **PERT** | min $a$, mode $m$, max $b$, shape $\gamma=4$ | Bounded estimates | $\alpha = 1+\gamma\tfrac{m-a}{b-a}$, $\beta = 1+\gamma\tfrac{b-m}{b-a}$, mean $=\tfrac{a+\gamma m+b}{\gamma+2}$ |
| **Uniform** | $[a,b]$ | Maximum ignorance within bounds | |
| **Beta** / **Beta from trials** | $\alpha,\beta$ / $k$ of $n$ | Probabilities | posterior $\text{Beta}(\alpha_0+k,\ \beta_0+n-k)$ |
| **Gamma** / **Gamma from events** | shape, rate / $k$ events in $t$ years | Rates | posterior $\text{Gamma}(a_0+k,\ b_0+t)$ |
| **Constant** | value | Known facts only | |

**Why lognormal for losses?** Losses are positive, multiplicative (days × cost
per day × sites) and right-skewed. A calibrated expert can state a 90 %
interval, and the lognormal is the maximum-entropy distribution for a positive
quantity with given log-moments. Its median is the geometric mean
$\sqrt{ab}$, so "€200k to €5M" has a median of about €1M, not €2.6M. This often
surprises people and is worth explaining.

**Caps.** Where a hard ceiling exists, for example a statutory maximum fine, the
lognormal is censored at the cap $c$. The mean then uses the *limited expected
value*:

$$E[\min(X,c)] = e^{\mu+\sigma^2/2}\,\Phi\!\left(\tfrac{\ln c-\mu-\sigma^2}{\sigma}\right) + c\left(1-\Phi\!\left(\tfrac{\ln c-\mu}{\sigma}\right)\right)$$

**Semantic validation.** A probability cannot be lognormal, and a loss cannot
be a Beta. These are rejected when the input is loaded (`ProbabilityEstimate`,
`FrequencyEstimate`, `MagnitudeEstimate`).

## 3. Frequencies: Gamma-Poisson

Loss events are modelled as a Poisson process with an uncertain rate
$\lambda \sim \text{Gamma}(a, b)$. Observing $k$ events in $t$ years gives the
conjugate posterior

$$\lambda \mid k \sim \text{Gamma}(a+k,\; b+t), \qquad E[\lambda\mid k] = Z\,\frac{k}{t} + (1-Z)\,\frac{a}{b}, \qquad Z = \frac{t}{b+t}.$$

$Z$ is the **credibility weight** of the data, exactly Bühlmann credibility.
It answers the question every risk committee asks: *"how much did the data move
us away from expert opinion?"*. Reports print it next to every data-derived
input.

* **Expert prior from an interval.** $\text{Gamma}(a, b)$ is fitted so that its
  5th and 95th percentiles equal the expert's interval. The ratio
  $q_{0.95}/q_{0.05}$ depends only on the shape $a$ and decreases strictly in
  it, so $a$ is found by one-dimensional root finding (Brent), and then
  $b = G^{-1}_a(0.05) / \text{low}$.
* **No prior.** Jeffreys, $\text{Gamma}(\tfrac12, 0)$: the data speaks for
  itself.
* **Predictive distribution** for the count over a horizon $h$:
  $N \sim \text{NegBin}\!\left(a',\ \tfrac{b'}{b'+h}\right)$. It is wider than
  a Poisson because the rate itself is uncertain.

*Example (RSK-003).* The expert prior is 0.02–0.25 breaches per year, and there
were 0 breaches in 6 years. The posterior mean falls modestly: six clean years
are weak evidence against a rare event. The model says this explicitly instead
of treating "no incidents" as "no risk".

## 4. Proportions: Beta-Binomial and audit sampling

Control operating effectiveness, phishing click rates and red-team success
rates are all proportions estimated from trials.

$$\pi \mid (k \text{ of } n) \sim \text{Beta}(\alpha_0 + k,\; \beta_0 + n - k)$$

**Link to audit sampling.** With zero exceptions in $n$ samples, the classical
one-sided upper confidence bound on the deviation rate is
$1-(1-C)^{1/n}$. For 25 samples at 95 % this is 11.3 %: *zero exceptions in 25
samples cannot show that a control works more than about 89 % of the time*.
Sextant reports the exact Clopper-Pearson bound next to the Bayesian posterior.

Required clean samples for an "effective" conclusion (TDR 10 %, 90 % confidence):

| Rule | Condition | n |
|---|---|---|
| Classical attribute sampling | $(1-\text{TDR})^n \le 1-C$ | 22 |
| Bayesian, uniform prior | $P(\delta \le \text{TDR}) = 1-(1-\text{TDR})^{n+1} \ge C$ | 21 |

The two frameworks agree to within one sample. The uniform prior is worth
exactly one "free" observation. The test suite checks both values.

## 5. Monte Carlo simulation

### 5.1 Two kinds of uncertainty

* **Epistemic** (what we do not know): $T, s, p, r_j, o_j$. These are drawn
  **once per simulated year**.
* **Aleatory** (what varies even with perfect knowledge): how many events occur
  and how large each one is. These are drawn **per event**.

This separation produces two different answers, and both are reported:

* the **predictive distribution of annual loss** ("how bad can a year be?"),
  which gives VaR, ES and the LEC;
* the **distribution of the expected annual loss** $E[L\mid\theta]$ ("how
  confident are we in the ALE?"), which gives the 90 % credible interval for
  the ALE.

$E[L \mid \theta]$ is computed in **closed form** for every trial:

$$E[L\mid\theta] = \lambda_0 m_F \left(\sum_k E[X_k]\, m_k + p\, m_P \sum_k E[Y_k]\, m_k\right)$$

By the law of total expectation, its mean equals the simulated ALE. This is
checked on every state in `test_simulated_mean_matches_conditional_expectation`.

### 5.2 The coupled simulation

For each trial *i*:

1. Draw $\theta_i$ and set $\lambda_{0,i} = T_i s_i$.
2. Draw $N_i \sim \text{Poisson}(\lambda_{0,i})$ **inherent** loss events.
3. For each event, draw the loss forms (§5.4), a survival uniform $V$ and a
   secondary-trigger uniform $W$.
4. For **every control state** (inherent, current, target, each option, and
   current minus each control), compute the multipliers. Then an event survives
   if $V < m_F$, secondary loss occurs if $W < p\,m_P$, and each loss form is
   scaled by its magnitude multiplier.

**Why this is valid (the Poisson thinning theorem).** If
$N \sim \text{Poisson}(\lambda)$ and each event is kept independently with
probability $m$, the kept events are $\text{Poisson}(\lambda m)$. Every state
therefore has the correct marginal distribution. This is tested by
`test_thinning_gives_reduced_poisson_rate`.

**Why it is useful (common random numbers).** All states share the same years
and events, so the difference between two states reflects *only* the
difference in controls:

$$\operatorname{Var}(L_A - L_B) = \operatorname{Var} L_A + \operatorname{Var} L_B - 2\operatorname{Cov}(L_A, L_B)$$

The covariance is large and positive, so paired differences are much more
precise than independent runs. Reports print both standard errors. In the
examples the paired standard error is typically less than half of the
independent one. **Monotonicity** also holds exactly: adding or strengthening a
control can never increase the loss in any simulated year. A Hypothesis
property test checks this.

**Named random streams.** Each input draws from its own stream, seeded by
`SHA-256(scenario id / input name)` and the global seed. Adding a treatment
option or a control does not change the draws of any other input. Results are
therefore reproducible *and* comparable across model revisions
(`test_adding_a_treatment_option_does_not_change_other_results`).

### 5.3 Inverse-transform sampling

Every distribution is sampled as $x = F^{-1}(u)$. That makes coupling
(same $u$, different $F$), copulas and stress tests uniform operations, and
every quantile function is a documented SciPy special function.

### 5.4 Dependence between loss forms: a one-factor Gaussian copula

Large incidents tend to be large in several ways at once: longer outage, more
response effort, more churn. Independent sampling would understate the spread
of event losses. For each event:

$$Z_k = \sqrt{\rho}\,F + \sqrt{1-\rho}\,\varepsilon_k,\qquad U_k = \Phi(Z_k),\qquad X_k = F_k^{-1}(U_k)$$

$\rho$ (default 0.5) is a *methodology* setting. It changes the tails, not the
mean (`test_copula_changes_tail_not_mean`). The rank correlation between forms
is $\tfrac{6}{\pi}\arcsin(\rho/2) \approx 0.48$ for $\rho = 0.5$.

### 5.5 Resource limits

The expected number of simulated events $\sum_i \lambda_{0,i}$ is checked
before allocation. Scenarios above the budget are rejected with guidance to
model at a coarser granularity, e.g. campaigns rather than individual emails.
This also protects the API against resource exhaustion.

## 6. Risk measures

| Measure | Definition | Notes |
|---|---|---|
| **ALE** | $E[L]$ | With Monte Carlo SE $= \text{sd}(L)/\sqrt{N}$, which is simulation precision only |
| **ALE credible interval** | 5th–95th percentile of $E[L\mid\theta]$ | Parameter uncertainty |
| **P(any loss)**, **P(≥1 event)** | $P(L>0)$; $E[1-e^{-\lambda}]$ | |
| **VaR$_q$** | $q$-quantile of $L$ | "A 1-in-20 year costs at least …" |
| **ES$_q$** | Mean of the worst $\lceil N(1-q)\rceil$ years | Coherent (sub-additive); describes *how bad* the tail is |
| **LEC** | $x \mapsto P(L \ge x)$ | The risk committee's view; compared with the tolerance curve |
| **Quantile MC interval** | Order statistics at ranks $Nq \pm z\sqrt{Nq(1-q)}$ | Distribution-free |

**Why ES as well as VaR?** VaR is not sub-additive: the VaR of a portfolio can
exceed the sum of the individual VaRs. VaR also says nothing about losses
beyond the quantile. With 20,000 trials the 99 % tail rests on 200 years, and
it depends heavily on the assumed severity distribution. Reports therefore
label VaR99 and ES99 as sensitive.

## 7. Combining controls

Controls on the same factor combine as $\prod_j (1-e_j)$. This is the
probability that a threat gets through *all* of them if the layers fail
independently. When failures are correlated (for example, two controls
depending on the same identity provider), the combined effect is overstated.
The leave-one-out contribution and "control fails" stress tests bound this
effect. Explicit correlation between controls is on the roadmap.

## 8. Sensitivity analysis

**Tornado (analytic, one at a time).** The ALE is *multilinear* in independent
inputs, and for independent variables $E[\prod X_i] = \prod E[X_i]$. The
baseline evaluated at the input means therefore equals the simulated ALE
exactly (`test_tornado_baseline_equals_simulated_ale`). Each input is moved to
its P10 and P90, and the closed-form ALE is recomputed. The chart has no
simulation noise. For loss-magnitude inputs, the swing is labelled as a
*severity stress* ("every event at P10 / P90"), because severity spread is
event variability rather than parameter uncertainty.

**Global rank sensitivity (value of information).** This is Spearman's
$\rho$ between each epistemic draw and $E[L\mid\theta]$, *not* $L$. Using
$E[L\mid\theta]$ removes the aleatory noise, so the ranking shows which
*uncertainty* drives the uncertainty of the ALE. The top input is the one
where better measurement would narrow the estimate most. It is often an
untested control, which is a quantitative argument for control testing.

**Stress tests.** Named what-if cases (TEF × 2, magnitude × 2, "control X
fails") are re-simulated with the same random streams. A "control fails"
stress equals the leave-one-out state exactly, and this is tested.

## 9. Treatment economics and portfolio

* **ROSI** $= (\Delta\text{ALE} - C_{\text{annualised}})/C_{\text{annualised}}$,
  with $C_{\text{annualised}} = C_{\text{annual}} + C_{\text{one-time}}/\text{amortisation years}$.
  It is reported *alongside* ΔVaR, ΔES and appetite status; it is never used
  alone.
* **Portfolio** $L = \sum_s L_s$ per trial. Scenarios are aggregated as
  independent in v1.
* **Tolerance check.** For each tolerance point, $\hat P(L \ge x)$ has a
  Jeffreys 95 % interval, $\text{Beta}(k+\tfrac12, N-k+\tfrac12)$. The status
  is *exceeds* only if the whole interval lies above the limit, and
  *borderline* if the interval straddles it. Monte Carlo noise alone never
  decides a breach.
* **Tail allocation (Euler / ES contributions).** Scenario $s$ contributes
  $E[L_s \mid L \ge \text{VaR}_{95}(L)]$. The contributions sum *exactly* to
  the portfolio ES (tested). Comparing ALE shares with tail shares shows
  which risks drive average years (budget) and which drive bad years
  (capital, insurance and appetite).

## 10. Forecasting KRIs and incident counts

* **Model.** Counts per period are Poisson with a Gamma-distributed rate. An
  observation $a$ periods old is down-weighted by $\delta^a$ (exponential
  forgetting, or power prior):
  $a' = a_0 + \sum_t \delta^{T-1-t}k_t$ and $b' = b_0 + \sum_t \delta^{T-1-t}e_t$.
  $\delta=1$ assumes stationarity. $\delta<1$ adapts to level shifts at the
  cost of wider intervals. $\delta$ is an explicit assumption, and its effect
  is tested.
* **Forecast.** The negative-binomial predictive gives the mean, the 50 % and
  90 % intervals, and $P(N > \text{threshold})$, the probability that the KRI
  breaches its red line next period.
* **Trend test.** Poisson log-linear regression
  $\log E[k_t] = \log e_t + \beta_0 + \beta_1 t$, fitted by Newton-Raphson,
  with a likelihood-ratio test of $\beta_1 = 0$ ($\chi^2_1$) and a Wald 95 %
  interval for the rate ratio $e^{\beta_1}$. Under a constant rate the test
  rejects about 5 % of the time (checked by simulation).
* **Validation by backtesting.** Rolling-origin one-step-ahead forecasts: each
  period is forecast only from earlier data. The report shows the empirical
  coverage of the 50 % and 90 % intervals and the mean log predictive score (a
  proper scoring rule). On data that satisfies the model, coverage is close to
  nominal (tested). Coverage well below nominal means the model is
  overconfident.

## 11. Verification and validation

| Property | Test |
|---|---|
| Compound Poisson: $E[L]=\lambda E[X]$, $\text{Var}[L]=\lambda E[X^2]$ | `test_compound_poisson_mean_and_variance` |
| Counts are Poisson (mean = variance) | `test_event_counts_are_poisson` |
| Thinning gives rate $\lambda(1-roc)$ | `test_thinning_gives_reduced_poisson_rate` |
| Insurance layer matches numerical integration | `test_insurance_recovery_matches_numerical_integral` |
| Law of total expectation holds in every state | `test_simulated_mean_matches_conditional_expectation` |
| Monotonicity for any control strength (property-based) | `test_adding_any_control_never_increases_loss` |
| Reproducibility and stream isolation | `test_reproducible_and_seed_sensitive`, `test_adding_a_treatment_option_...` |
| Conjugate updates, credibility, NB predictive | `test_bayes_and_distributions.py` |
| Audit-sampling thresholds (21 vs 22) | `test_bayesian_threshold_close_to_classical_plan` |
| ES allocation sums to portfolio ES | `test_portfolio_tail_contributions_sum_to_expected_shortfall` |
| Backtest coverage; trend-test size | `test_backtest_coverage_is_calibrated_...`, `test_trend_test_false_positive_rate_is_nominal` |
| End-to-end reproduction from a stored snapshot | `test_reproduction_by_auditor` (integration) |

Tolerances are derived from Monte Carlo standard errors (4–5 SE) with fixed
seeds. They are not tuned until the tests pass.

## 12. Methods deliberately not used

| Not used | Why |
|---|---|
| Machine-learning classifiers or regressors | Incident data is small-n, censored and non-stationary. There is no ground truth to train on, and the outputs cannot be explained to a risk owner. |
| Averaging or multiplying ordinal scores | Ordinal scales do not support arithmetic (§3.3 of the methodology) |
| Normal distributions for losses | Losses are positive and skewed. A normal distribution assigns probability to negative losses and underweights the tail. |
| VaR alone | Not coherent, and silent about the tail beyond the quantile |
| Point estimates without intervals | They hide the most decision-relevant fact: how little we may know |

## References

* Freund, J., Jones, J. (2014). *Measuring and Managing Information Risk: A FAIR Approach.*
* Hubbard, D., Seiersen, R. (2023). *How to Measure Anything in Cybersecurity Risk* (2nd ed.).
* Klugman, Panjer, Willmot. *Loss Models: From Data to Decisions* (compound distributions, limited expected value, credibility).
* Glasserman, P. (2003). *Monte Carlo Methods in Financial Engineering* (common random numbers).
* Artzner et al. (1999). *Coherent Measures of Risk.* Tasche (2008), *Capital Allocation to Business Units: the Euler Principle.*
* Gneiting & Raftery (2007). *Strictly Proper Scoring Rules, Prediction, and Estimation.*
* Clopper & Pearson (1934); AICPA *Audit Guide: Audit Sampling.*
* Cox, L. A. (2008). *What's Wrong with Risk Matrices?* Risk Analysis 28(2).
