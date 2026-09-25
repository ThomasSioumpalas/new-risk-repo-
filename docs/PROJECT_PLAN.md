# Sextant — Project Plan and Design Brief

> Status: **approved design baseline (v1)**. Later changes are recorded as
> Architecture Decision Records in [`docs/adr/`](adr/).
>
> A sextant is a navigation instrument. It estimates a position under
> uncertainty from careful, calibrated measurement. It does not claim certainty.
> That is the idea behind this project.

---

## 1. Project name and concept

**Sextant** is an evidence-based information-security risk register with a
quantitative risk engine.

It covers the whole risk-management cycle. The cycle starts with a threat
scenario. It ends with a residual risk that an accountable person has accepted.
Every number on the way can be traced to its inputs, its assumptions, its
evidence and its method, and every number can be re-calculated:

```
Asset ─┐
Threat ─┼─► Risk scenario ─► Inherent risk ─► Controls (design × operation × coverage)
Vuln. ─┘                          │                        │
                                  ▼                        ▼
                          Current (residual) risk ─► Evaluation vs. criteria/appetite
                                                           │
                           Treatment options ◄─────────────┘
                                  │
                                  ▼
                 Target risk ─► Acceptance (authority + SoD) ─► Monitoring (KRIs, reviews)
```

The project is intentionally **not** a CRUD application with a score column.
Its core is a documented, tested and reproducible risk model. Governance
controls sit around that model: approval, segregation of duties, an immutable
audit trail and time-limited acceptance.

## 2. The real-world problem

Most organisations run their information-security risk register in a
spreadsheet. The typical register has these weaknesses:

| Typical weakness | Consequence | What Sextant does instead |
|---|---|---|
| Ordinal 1–5 × 1–5 scores multiplied together | Ranking errors, range compression, false precision (Cox 2008) | Uses a matrix *lookup* for communication, and a quantitative model for decisions. The two are compared openly. |
| "Control effectiveness = 70 %" with no basis | The residual risk cannot be defended to an auditor | Effectiveness = design reduction × operating rate from **test results** (Beta-Binomial) × coverage |
| No uncertainty | A point estimate hides how little is known | Every estimate is a distribution. Outputs are reported with credible intervals. |
| No link between risks, controls and compliance | The Statement of Applicability is maintained separately and drifts | One control library is mapped to ISO 27001 Annex A, NIST CSF 2.0, NIS2 Art. 21 and NIST AI RMF |
| Overwritten cells, no history | No audit trail and no accountability | Append-only, hash-chained audit log. Finalised assessments are immutable. |
| Acceptance without authority | Risks accepted by people who are not entitled to accept them | An authority matrix and segregation-of-duties checks are enforced, and acceptance expires |
| Cannot answer "what if?" | Treatment spending is not prioritised by risk reduction | Coupled Monte Carlo compares treatment options: ΔALE, ΔVaR, ROSI |

## 3. Target users

| User | What they do in Sextant |
|---|---|
| **Risk analyst / GRC analyst (1st/2nd line)** | Models scenarios, runs assessments, documents rationale, links evidence |
| **Risk owner** (business) | Reviews assessments, approves treatment plans, accepts residual risk within their authority |
| **CISO / risk manager (2nd line)** | Maintains the methodology (risk criteria, scales, appetite) and reviews portfolio exposure |
| **Executive / risk committee** | Accepts risks above the owner's authority and reads the portfolio loss-exceedance view |
| **Internal / external auditor (3rd line)** | Uses read-only access to the audit trail and evidence hashes, re-runs assessments, reviews readiness |
| **Control owner** | Records control tests and evidence |

## 4. Why this is valuable for a Compliance / GRC portfolio

For each role, the project shows the following:

- **Compliance / GRC analyst**: You can tell *risk assessment*, *control
  assessment*, *evidence*, *compliance mapping*, *readiness* and *certification*
  apart. You can also build a Statement of Applicability that is traceable to
  risks.
- **Technology / information security risk analyst**: You apply FAIR-aligned
  quantitative risk analysis (Monte Carlo, loss-exceedance curves, VaR / expected
  shortfall). You also know when a qualitative matrix is still appropriate.
- **IT auditor**: You reason about control testing the way audit sampling
  does, for example "0 deviations in 25 samples → the upper bound on the
  deviation rate is about 11 % at 95 % confidence". You understand evidence
  integrity, reproducibility and segregation of duties.
- **Security governance specialist**: You implement risk criteria, an authority
  matrix, time-limited acceptance and review cycles, as ISO 27001 clause 6.1
  and ISO 31000 describe them.
- **AI governance / AI risk**: You model AI-system risk scenarios, for example
  prompt injection or unreliable outputs. They are mapped to the NIST AI RMF and
  quantified from red-team or evaluation evidence. The deeper evaluation
  platform is scoped as a *separate* project (see §15).

The most important message for an interview: **risk management is decision
support under uncertainty with accountability, not score generation.**

## 5. Standards and frameworks

| Standard / framework | Role in Sextant | How it is used (copyright-aware) |
|---|---|---|
| **ISO 31000:2018** | Process backbone: context → identification → analysis → evaluation → treatment → monitoring and review, plus recording and reporting | Concepts and process only. No text is reproduced. |
| **ISO/IEC 27005:2022** | Event-based (scenario) risk identification, likelihood/consequence analysis, treatment options, and retain/accept | Concepts only |
| **ISO/IEC 27001:2022** | 6.1.2 (risk assessment), 6.1.3 (treatment, SoA, risk-owner approval and acceptance), 8.2/8.3, 9.1 | Clause *numbers* are referenced. The Annex A control **identifiers** have **short topic labels written for this project**. The normative control text is not reproduced. |
| **ISO/IEC 27002:2022** | Control themes (organisational, people, physical, technological) and control types (preventive, detective, corrective) | Only the attribute concepts are used |
| **NIST CSF 2.0** | Outcome taxonomy (GV/ID/PR/DE/RS/RC) for control mapping and readiness | US Government work, public domain. Imported from NIST's official OSCAL catalog (106 active subcategories). |
| **NIST SP 800-30 Rev. 1** | Threat source/event taxonomy, and the default qualitative risk matrix (Table I-2 structure) | Public domain |
| **NIST SP 800-37 Rev. 2 (RMF)** | Borrowed concepts: *authorisation* as an explicit risk-acceptance decision by an accountable official, and continuous monitoring | This is **not** a full RMF implementation. That would require SP 800-53 baselines and federal context, which do not fit here. |
| **NIST IR 8477** | Set-theory relationship types for mappings (*subset of, intersects with, equal, superset of*) | Public domain |
| **FAIR (Open Group O-RT / O-RA)** | Quantitative ontology: LEF = TEF × susceptibility, and loss magnitude as primary plus secondary loss with six loss forms | "FAIR-aligned". This is not a certified FAIR implementation. |
| **NIST AI RMF 1.0 (AI 100-1)** | AI risk scenario mapping (GOVERN/MAP/MEASURE/MANAGE categories) | Public domain |
| **NIS2 Directive (EU) 2022/2555, Art. 21(2)** | An example of a regulatory requirement set for the readiness assessment | EU legislation, reusable |

**Explicit non-goal**: Sextant never outputs "ISO 27001 compliant" or
"certified". Only an accredited certification body can certify an ISMS
(ISO/IEC 17021-1, ISO/IEC 27006). Sextant produces separate outputs for each
of these activities:

1. **Risk assessment**: the likelihood and consequence of a scenario.
2. **Control assessment**: design and operating effectiveness, from tests.
3. **Evidence**: artefacts with provenance, integrity hash and validity period.
4. **Compliance mapping**: which internal controls address which requirement,
   and how closely (STRM).
5. **Readiness / gap assessment**: indicators such as "mapped, implemented,
   tested and evidenced". This is readiness, not conformity.
6. **Certification / audit opinion**: out of scope. The report says so.

## 6. Risk methodology

The full specification is in [`RISK_METHODOLOGY.md`](RISK_METHODOLOGY.md).

- **Methodology as versioned configuration.** Risk criteria are versioned and
  hashed data, never hard-coded constants. This covers likelihood and impact
  scales, the risk matrix, appetite and the tolerance curve, the acceptance
  authority matrix and review cycles (ISO 27001 6.1.2 a, ISO 31000 6.3.4). Every
  assessment records the methodology version it used.
- **Event-based scenarios** (ISO 27005). Each scenario has a threat source and
  event (SP 800-30 taxonomy), the vulnerability or predisposing condition, the
  affected assets, the consequences, and a risk owner.
- **Three explicit risk states**, because the word "inherent" is ambiguous in
  practice:
  - *Inherent*: the risk without the controls linked to the scenario. The
    ambient environment still exists.
  - *Current*: the residual risk with the controls **as implemented and as
    tested**.
  - *Target*: the projected residual risk after the proposed treatment.
- **Two assessment methods, used side by side:**
  1. **Qualitative / semi-quantitative** (ISO 27005, NIST SP 800-30). The
     assessor rates likelihood and impact levels with a written rationale. The
     risk level comes from a *lookup matrix*. The common L×I product is shown
     only as a legacy reference, and the report explains why it is unreliable.
     Automated **quality checks** flag red flags that auditors look for, for
     example "risk reduced but no implemented control linked".
  2. **Quantitative, FAIR-aligned Monte Carlo** for material risks. It reports
     the annual loss distribution, ALE, VaR / expected shortfall and the
     loss-exceedance curve.

  Quantitative results are *banded* into the same qualitative levels with
  documented rules. The report shows where the two methods disagree.
- **Controls** affect a specific factor: threat event frequency,
  susceptibility, primary or secondary loss, or the probability of a secondary
  loss. Effectiveness = *reduction if operating* × *operating rate (from tests)*
  × *coverage*. Each term is documented and evidenced.
- **Evaluation** compares results against the risk criteria: the matrix level,
  the ALE appetite, and the loss-exceedance tolerance curve for the portfolio.
- **Treatment** options follow ISO 31000 and ISO 27005: modify, share, avoid,
  retain. Options are compared quantitatively. The report states that
  accountability cannot be transferred when a risk is "shared".
- **Acceptance** is a formal record. It needs the right authority for the risk
  level, and the acceptor must differ from the assessor (segregation of
  duties). It references a specific finalised assessment and has an expiry date.
  It is automatically invalidated when a later assessment raises the level.
- **Monitoring**: review due dates by risk level, acceptance expiry, evidence
  staleness, and KRIs with probabilistic forecasts.

## 7. Mathematical and statistical methodology

The full specification is in [`STATISTICAL_METHODS.md`](STATISTICAL_METHODS.md).
Only methods that make sense for sparse, non-stationary, expert-dependent risk
data are used:

| Question | Method |
|---|---|
| How often? | Threat event frequency as a lognormal (from a calibrated 90 % CI) or a PERT; loss events are Poisson given the rate |
| Updating with incident history | **Gamma-Poisson conjugate** Bayesian update, including a credibility weight ("how far did the data move us from expert opinion?") and a negative-binomial predictive distribution |
| Is the control really working? | **Beta-Binomial** posterior of the operating rate from control-test samples, compared with the Clopper-Pearson (audit sampling) bound |
| How susceptible are we? | Beta posterior from phishing-simulation or red-team data (e.g. 7/200 prompt injections succeeded) |
| How bad? | Lognormal or PERT loss components per FAIR loss form, correlated through a one-factor Gaussian copula |
| Estimated risk | Compound-Poisson Monte Carlo that reports the annual loss distribution, **ALE**, P(any loss), and the **loss-exceedance curve** |
| Bad-year view | **VaR** (a quantile of annual loss) and **expected shortfall** (a coherent tail measure). A Monte Carlo confidence interval is reported for the quantile. |
| How confident are we? | *Epistemic* (parameter) uncertainty is separated from *aleatory* (event) variability. The report gives a credible interval for the ALE itself and the Monte Carlo standard error. |
| What if assumptions change? | One-at-a-time tornado (analytic) plus rank-correlation global sensitivity. The latter doubles as a "value of information" hint. |
| Which mitigation is best? | **Coupled simulation** (Poisson thinning plus common random numbers). Every control state is evaluated on the same simulated threat events, so the differences between options are precise. Also: leave-one-out control contribution and ROSI. |
| Portfolio | Trial-wise aggregation, portfolio loss-exceedance curve against the tolerance curve, and tail contribution by scenario (Euler / expected-shortfall allocation) |
| Forecasting KRIs / incidents | Discounted Gamma-Poisson predictive intervals, a Poisson log-linear trend test (likelihood-ratio), and **rolling-origin backtests** of interval coverage |
| Is the implementation right? | Validation tests against closed-form results (compound-Poisson mean and variance, NB predictive, lognormal quantiles, thinning) |

**Machine learning is deliberately excluded.** Incident data is small-n,
non-stationary and heavily censored. Decision-makers need to know *why* a
number is what it is. Conjugate Bayesian models and Monte Carlo are
explainable, auditable and statistically defensible. A classifier trained on
tiny data is none of these. (See ADR-0002.)

## 8. Architecture and technology stack

See [`ARCHITECTURE.md`](ARCHITECTURE.md). The architecture has layers
(ports-and-adapters style). The risk engine is a pure library with no I/O.

| Layer | Technology | Reasoning |
|---|---|---|
| Language | Python 3.12+ | The best ecosystem for numerical work and a common GRC-automation language |
| Engine | NumPy, SciPy | Mature, vectorised, and well-tested distributions and special functions |
| Domain schemas | Pydantic v2 | Typed validation of scenario and methodology inputs. The same schemas serve YAML, the API and snapshots. |
| API | FastAPI | Typed, OpenAPI documentation generated automatically, easy dependency injection for auth |
| Persistence | SQLAlchemy 2.0 + Alembic | Migrations, portability. **SQLite** for a zero-setup demo, **PostgreSQL** in Docker Compose. |
| CLI | Typer | "Risk-as-code": assess YAML scenarios and produce reports without a server |
| Reports | Jinja2 Markdown and matplotlib | Reports are committed, so reviewers can read them on GitHub without installing anything |
| Logging | structlog (JSON) | Structured, correlation IDs |
| Tooling | uv, ruff, mypy (strict), pytest, hypothesis, pip-audit, pre-commit | Fast, reproducible (lockfile), and quality gates in CI |
| Delivery | Docker (multi-stage, non-root) and GitHub Actions | Lint → type-check → tests with coverage → dependency audit → image build |

What was deliberately **left out**:

- A SPA front-end. It would add cost without showing more risk knowledge. The
  API documentation and the generated reports are enough.
- Message queues and microservices. They are over-engineering at this scale.
- Machine learning. See §7.

## 9. Major modules and features

1. `engine.distributions`: estimate types with provenance (expert CI, PERT,
   data-derived Beta or Gamma).
2. `engine.simulation`: coupled FAIR-aligned Monte Carlo (inherent, current,
   target, options).
3. `engine.bayes`: Gamma-Poisson and Beta-Binomial updates, credibility, and
   predictive distributions.
4. `engine.controls`: the control effect model and test-based effectiveness
   conclusions.
5. `engine.qualitative`: scales, matrix lookup, banding and assessment quality
   checks.
6. `engine.sensitivity`: tornado, rank correlation and stress scenarios.
7. `engine.treatment`: option comparison, leave-one-out and ROSI.
8. `engine.portfolio`: aggregation, tolerance curve and tail allocation.
9. `engine.forecasting`: KRI or incident forecasts, trend test and backtest.
10. `engine.explain`: structured answers to the seven reviewer questions.
11. `compliance`: framework catalogs, STRM mappings, readiness and a draft SoA.
12. `governance` (services): immutable assessments, overrides with
    justification, SoD and authority checks, acceptance lifecycle, review
    scheduling.
13. `audit`: an append-only, SHA-256 hash-chained log with verification.
14. `api`, `cli` and `reporting`.

## 10. Repository structure

```
.
├── README.md
├── SECURITY.md  CONTRIBUTING.md  LICENSE
├── pyproject.toml  uv.lock  Makefile  Dockerfile  docker-compose.yml  alembic.ini
├── .github/workflows/ci.yml  .github/dependabot.yml  .pre-commit-config.yaml
├── docs/
│   ├── PROJECT_PLAN.md  ARCHITECTURE.md  RISK_METHODOLOGY.md
│   ├── STATISTICAL_METHODS.md  COMPLIANCE_MAPPING.md  ROADMAP.md  STATUS.md
│   ├── INTERVIEW_GUIDE.md          # how to discuss the design choices
│   ├── adr/                        # architecture decision records
│   └── proposals/LLM_EVALUATION_PROJECT.md
├── src/sextant/
│   ├── domain/        # Pydantic schemas: scenario, estimates, methodology
│   ├── engine/        # pure maths: no I/O, no framework imports
│   ├── compliance/    # catalogs (YAML) + readiness logic
│   ├── db/            # SQLAlchemy models, session
│   ├── services/      # use cases: assessment, acceptance, audit, compliance
│   ├── api/           # FastAPI app, routers, auth
│   ├── cli/           # Typer CLI
│   └── reporting/     # Markdown/PNG report generation
├── migrations/        # Alembic
├── examples/          # fictional company: methodology, register, data, reports
└── tests/  unit/  validation/  integration/
```

## 11. MVP scope (this iteration)

In scope:

- The complete engine (§9, items 1–10) with statistical validation tests.
- Risk-as-code YAML for a fictional organisation, *Halcyon Logistics (fictional)*,
  with eight scenarios: ransomware, credential compromise, third-party SaaS
  breach, cloud storage misconfiguration, insider data leakage, service outage,
  regulatory (breach-notification) failure, and LLM-assistant prompt injection.
- Synthetic incident, control-test and KRI data.
- A CLI that assesses scenarios and generates committed Markdown reports with
  charts: a register report, a per-risk explanation, a portfolio report and a
  readiness report.
- Compliance catalogs (CSF 2.0 full; ISO 27001 Annex A identifiers; NIS2
  Art. 21(2); AI RMF categories), mappings, readiness and a draft SoA.
- Persistence with Alembic migrations. The REST API covers risks, controls,
  tests, evidence, assessments (create, finalise, override, reproduce), treatment,
  acceptance, portfolio, readiness and the audit log (query and verify).
- API-key authentication with role-based access, and segregation-of-duties
  rules.
- Documentation set, CI, Docker.

Out of scope for the MVP (see the roadmap): UI, SSO/OIDC, file upload storage,
multi-tenancy, correlated scenario aggregation, and the full SP 800-53 catalog.

## 12. Later roadmap

See [`ROADMAP.md`](ROADMAP.md). In summary:

- **Phase 2**: expert calibration tracking (the Brier score or hit rate of each
  estimator's 90 % intervals); a common-shock or copula dependence between
  scenarios; evidence file storage with object-lock semantics; KRI ingestion
  API; an OSCAL export of the SoA and assessment results.
- **Phase 3**: OIDC/SSO; a minimal review UI; DORA and ISO/IEC 42001 catalogs;
  a hierarchical (partially pooled) severity model using external loss data;
  scheduled re-assessment jobs.
- **Separate project**: an LLM evaluation harness that *feeds* evidence into
  Sextant (§15).

## 13. Testing and validation strategy

| Level | What is tested | Examples |
|---|---|---|
| Unit | Pure functions and schema validation | Matrix lookup, lognormal fit from a CI, the PERT mean, rejecting invalid probabilities |
| Property-based (Hypothesis) | Invariants | Current ≤ inherent trial-wise, target ≤ current, quantiles monotone, adding a control never increases loss, results reproducible for a given seed |
| **Statistical validation** | The implementation against closed-form mathematics | Simulated compound-Poisson mean and variance within a Monte Carlo tolerance of λE[X] and λE[X²]; the thinning rate; conjugate posteriors against scipy; NB predictive against simulation; Clopper-Pearson against known audit-sampling values |
| Backtest | Calibration of the forecasting model | The 90 % interval coverage of rolling-origin forecasts on synthetic stationary data is close to 90 % |
| Integration | API plus DB end-to-end | Assessment lifecycle, acceptance blocked without authority or by SoD, tampering detected by audit-chain verification, reproduction of a finalised assessment giving identical hashes |
| Reproducibility | Determinism | The same inputs, seed and engine version give a byte-identical result hash |

All tests run in CI on every push. Coverage is reported.

## 14. Security considerations

See [`../SECURITY.md`](../SECURITY.md). Summary:

- API keys are random 256-bit values. Only a SHA-256 hash is stored, and the
  comparison is constant-time. Role-based authorisation applies per endpoint.
  Least privilege: admin ≠ risk acceptor.
- Input validation for every payload (Pydantic), with bounded simulation sizes
  to prevent resource-exhaustion DoS. The API applies no `eval`, no YAML
  `load` (only `safe_load`) and no pickle.
- Audit log: append-only, enforced by database triggers, and hash-chained so
  tampering is *evident*. The report states that a hash chain is not
  tamper-*proof*; that would need external anchoring.
- Evidence integrity through SHA-256 digests.
- Secrets only come from the environment. No secrets are committed. Docker runs
  as a non-root user.
- CI runs the dependency vulnerability audit (pip-audit) and the static
  security rules (ruff `S` / bandit rules).
- The data in examples is synthetic. No personal data is in the repository.

## 15. Does LLM evaluation belong here?

**Decision: no. It would be stronger as a separate repository, integrated
through evidence.**

A serious LLM evaluation platform differs on every axis:

| | Sextant (this repo) | LLM evaluation platform |
|---|---|---|
| Purpose | Decide and govern: which risks, how large, who accepts | Measure model or system behaviour |
| Users | GRC, risk owners, auditors | ML engineers, AI assurance, red teams |
| Methodology | Risk analysis, actuarial-style frequency and severity | Test design, metrics, inter-rater reliability, statistical comparison of model versions |
| Architecture | Register, workflow, audit trail | Dataset and prompt versioning, model adapters, evaluation runners, judge models |

Adding it here would dilute both projects. The credible design is **integration
through evidence**. The evaluation harness produces measured outcomes, such as
"7 of 200 prompt-injection attempts succeeded" or "hallucination rate on a
policy-QA set". Sextant consumes them as data-derived Beta distributions for
*susceptibility*, and those feed a quantified AI risk scenario mapped to the
NIST AI RMF.

This repo therefore includes AI *risk scenarios* and the AI RMF mapping, but
not an evaluation platform. The follow-up project is proposed in
[`proposals/LLM_EVALUATION_PROJECT.md`](proposals/LLM_EVALUATION_PROJECT.md).

## 16. Assumptions, limitations and methodological concerns

1. **Garbage in, garbage out, but visibly.** Quantitative outputs depend on
   expert estimates. Sextant records the source of every input (expert or data)
   and shows how sensitive the result is to each input. It does not remove
   judgement; it makes judgement explicit and testable.
2. **Independence assumptions.** Controls combine multiplicatively (independent
   layers), and scenarios aggregate independently in v1. Both assumptions can
   underestimate tail risk when failures are correlated. This is documented,
   tested with sensitivity analysis, and on the roadmap.
3. **Heavy tails.** Cyber losses can be heavier-tailed than lognormal. VaR and
   ES at 99 % are sensitive to the choice of distribution. Users can set caps,
   and the report states the limitation.
4. **Non-stationarity.** Threat landscapes change. Forecasts use discounting,
   are backtested, and are always shown with intervals.
5. **Risk matrices.** They are kept because auditors, boards and ISO-based
   programmes expect them. However, Cox (2008) and Thomas, Bratvold & Bickel
   (2014) show that they can misrank risks, so decisions on material risks
   should use the quantitative view.
6. **"Inherent risk"** is defined explicitly: the risk *without the linked
   controls*. Any other definition is ambiguous.
7. **Compliance ≠ security ≠ certification.** Readiness indicators are
   heuristics for planning. They are not conformity statements.
8. **ISO copyright.** No normative ISO text is reproduced. Users with licensed
   copies should consult the standards.
9. **Synthetic data.** All example figures are fictional and illustrate the
   method. They are not benchmarks.

## Challenges to the original brief

- *"Implement NIST RMF."* The full RMF is a federal authorisation process built
  on SP 800-53 baselines. Implementing it would be large and would look like
  box-ticking. Sextant borrows the parts that transfer: authorisation as
  accountable risk acceptance, and continuous monitoring.
- *"Consider scikit-learn / prediction."* Prediction here means probabilistic
  forecasting with calibrated intervals and backtests. It does not mean ML
  classifiers. That approach is more defensible in front of a risk committee.
- *"Likelihood × impact."* It is implemented, but mainly to show why its
  limitations matter.
- *"Value at Risk."* It is reported, alongside expected shortfall, because VaR
  is not subadditive and ignores what happens beyond the quantile.
- *Repository name.* `new-risk-repo-` does not read well on a CV. Suggestion:
  rename the GitHub repository to `sextant-risk` (Settings → General →
  Repository name). GitHub redirects the old URL.

## References

- Cox, L. A. (2008). *What's Wrong with Risk Matrices?* Risk Analysis 28(2).
- Thomas, P., Bratvold, R., Bickel, J. E. (2014). *The Risk of Using Risk
  Matrices.* SPE Economics & Management.
- Hubbard, D., Seiersen, R. (2016/2023). *How to Measure Anything in
  Cybersecurity Risk.* Wiley.
- Freund, J., Jones, J. (2014). *Measuring and Managing Information Risk: A
  FAIR Approach.* Butterworth-Heinemann.
- NIST SP 800-30 Rev. 1; SP 800-37 Rev. 2; CSWP 29 (CSF 2.0); AI 100-1; IR 8477.
- ISO 31000:2018; ISO/IEC 27001:2022; 27002:2022; 27005:2022 (referenced, not
  reproduced).
- Directive (EU) 2022/2555 (NIS2), Article 21.
