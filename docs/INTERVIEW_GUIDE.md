# Interview Guide: discussing Sextant

This guide helps you explain the project to reviewers in Compliance, GRC,
Technology Risk, IT Audit, Security Governance and AI Governance roles. Each
answer points to where the project demonstrates it.

## 60-second pitch

> "Most risk registers are spreadsheets with a 1-to-25 score. The score can't
> be defended: nobody can say where the 'likelihood 3' came from, control
> effectiveness is a guess, and nothing is reproducible. I built Sextant to
> show what an evidence-based register looks like. Each risk is an ISO 27005
> event scenario, modelled the FAIR way, with every input as a range that
> records where it came from. Control effectiveness comes from actual test
> samples, the way audit sampling works. The output is an expected annual loss
> with a confidence interval, a bad-year figure and a clear list of
> assumptions. Around the maths I built the governance: immutable,
> reproducible assessments; an authority matrix; segregation of duties;
> acceptances that expire; and a hash-chained audit log. It also maps controls
> to ISO 27001, NIST CSF 2.0, NIS2 and the AI RMF, but it deliberately reports
> *readiness*, never 'compliance', because only a certification body can
> conclude that."

## Questions you should expect

**"Why not just use a 5×5 matrix?"**
Matrices are fine for communication and screening, so Sextant keeps one (the
NIST SP 800-30 Table I-2 lookup). But multiplying ordinal ranks is not valid
arithmetic, and matrices can rank risks in the wrong order (Cox 2008). The
example report shows RSK-008: the matrix rates it *Low*, yet its expected
annual loss is above the appetite threshold. That is range compression in
action. I use the quantitative result for decisions and band it onto the
matrix for communication.

**"Where do the numbers come from? Isn't this garbage in, garbage out?"**
Every input records its source and rationale and is either an expert range or
a data-derived posterior. The report states how many inputs are data-backed
and which uncertainty drives the result (rank sensitivity). The model does not
remove judgement. It makes judgement explicit, attributable and testable, and
it tells you which measurement would be most valuable next.

**"How do you know the model is correct?"**
There are two layers. *Verification*: the simulator is tested against
closed-form results (compound-Poisson mean and variance, thinning, the
insurance layer computed by numerical integration, the law of total
expectation) and against property-based invariants. *Validation*: forecasts
are backtested for interval coverage, and assessments can be re-performed from
their snapshot to give an identical fingerprint.

**"How do you measure control effectiveness?"**
As design × operation × coverage. Design is the expert-estimated reduction
when the control works. Operation comes from test samples via a Beta
posterior. Coverage is a measured fact. Zero exceptions in 25 samples only
shows the deviation rate is below about 11 %, and the tool prints exactly
that. For annual or quarterly controls I apply the audit convention of small
judgemental samples, but the model still carries the uncertainty.

**"Inherent versus residual risk?"**
The term "inherent" is used inconsistently, so I define it: the risk without
the controls *linked to the scenario*. *Current* is the residual with those
controls as tested, and *target* is the projected residual after the approved
treatment.

**"Is the organisation ISO 27001 compliant according to your tool?"**
No, and it never says so. It separates risk assessment, control assessment,
evidence, mapping, readiness and certification. Mappings use NIST IR 8477
relationships (MFA is a *subset* of NIS2 21(2)(j), not equal to it), and the
readiness output carries an explicit "not an audit opinion" disclaimer.

**"Who can accept a risk?"**
It depends on the methodology's authority matrix, and it is enforced in code.
Retaining a risk outside appetite escalates to an executive. Whoever prepared
or finalised the assessment can't accept it (segregation of duties). Admins
have no acceptance rights. Acceptances expire and are invalidated
automatically if a reassessment raises the level.

**"Why is ROSI not your decision rule?"**
ROSI rests on the expected loss only. Insurance often has the best ROSI but
does nothing for the likelihood of disruption. Some controls are required by
regulation whatever their ROSI. I report ΔALE, ΔVaR, ΔES, cost and residual
appetite status side by side, and the risk owner decides.

**"How would you explain VaR and expected shortfall to a board?"**
VaR95: "In a 1-in-20 bad year we lose at least €X." Expected shortfall: "and
when such a year happens, the average loss is €Y." ES is the more honest tail
measure, because VaR says nothing about how bad the worst years are.

**"What about AI risk and LLMs?"**
AI risks are ordinary risk scenarios mapped to the NIST AI RMF, and their
likelihood comes from evaluation evidence, for example red-team success
rates. Building the evaluation platform itself is a different discipline, so
I scoped it as a separate project that feeds evidence into this one (ADR 0006).

**"What would you change for production?"**
SSO/OIDC instead of API keys; external anchoring of the audit hash; evidence
storage with WORM retention; correlated-scenario aggregation; expert
calibration tracking; and a small review UI. These are all in the roadmap.

**"What was the hardest design decision?"**
Evaluating every control state on the *same* simulated events (Poisson
thinning with common random numbers). It makes treatment comparisons precise
and guarantees that adding a control can never increase the loss in any
simulated year. The alternative, independent runs, produces noisy and
sometimes contradictory differences.

## Map to role requirements

| Role | Talk about |
|---|---|
| Compliance analyst | Readiness versus compliance, STRM mappings, SoA traceability, NIS2 Art. 21/23 |
| GRC analyst | The methodology as versioned criteria, the treatment and acceptance workflow, monitoring |
| Technology / IS risk analyst | FAIR decomposition, Monte Carlo, LEC, VaR/ES, sensitivity, portfolio tail allocation |
| IT auditor | Test of design versus operating effectiveness, sampling maths, evidence integrity, reproducibility, SoD, audit trail |
| Security governance | Authority matrix, appetite and tolerance, the ISO 27001 clause 6.1 implementation, review cycles |
| AI governance | AI scenarios, AI RMF mapping, evaluation evidence as the likelihood input, the separate evaluation proposal |
