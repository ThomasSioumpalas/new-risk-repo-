# Roadmap

Items are ordered by how much they strengthen the *methodology and governance*
story, not by how impressive they look.

## Done (v0.1: MVP)

- [x] FAIR-aligned coupled Monte Carlo engine (inherent, current, target,
      options, leave-one-out)
- [x] Evidence-driven estimates (Gamma-Poisson, Beta-Binomial) with
      credibility weights
- [x] Test-based control effectiveness (statistical and judgemental
      conventions)
- [x] Qualitative method (SP 800-30 matrix) with automated quality checks
- [x] Sensitivity (analytic tornado, rank correlation, stress tests), treatment
      economics, portfolio ES allocation
- [x] KRI forecasting with backtests and trend tests
- [x] Compliance catalogs (ISO 27001 identifiers, CSF 2.0 from OSCAL, NIS2,
      AI RMF); readiness and draft SoA
- [x] Governance API: immutable reproducible assessments, overrides, authority
      and SoD, time-limited acceptance, hash-chained audit log with DB triggers
- [x] Risk-as-code CLI with committed example reports; CI on SQLite and
      PostgreSQL

## Phase 2: deepen the methodology

- [ ] **Expert calibration tracking.** Record estimators' 90 % intervals
      against later outcomes. Report hit rates and Brier scores per estimator,
      and optionally widen the intervals of poorly calibrated estimators.
- [ ] **Dependence between scenarios.** A common-shock model (e.g. a shared
      supplier or identity provider) or a Gaussian/t copula on annual losses,
      with a sensitivity report on how much the portfolio tail moves.
- [ ] **Correlated control failures.** Group controls by shared dependencies.
- [ ] **Combined treatment options**, e.g. EDR + insurance, with
      Shapley-value attribution of risk reduction.
- [ ] **Hierarchical severity model.** Partially pool internal loss data with
      external loss data.
- [ ] **KRI ingestion API**, with automatic reassessment triggers on a
      forecast breach probability.

## Phase 3: productisation

- [ ] OIDC / SSO, with user groups mapped to roles; per-risk ownership bound
      to identities
- [ ] Evidence file storage with object-lock (WORM) semantics and automatic
      digesting
- [ ] Anchoring the audit hash head externally (RFC 3161 timestamps or WORM)
- [ ] Exclusions and SoA decisions managed through the API (currently YAML only)
- [ ] OSCAL export: assessment results and SoA as OSCAL Assessment Results /
      Component Definitions
- [ ] A minimal review UI (register, approval queue, monitoring)
- [ ] Additional catalogs: DORA ICT risk management, ISO/IEC 42001
      (identifiers only), CIS Controls v8
- [ ] Rate limiting and multi-tenancy

## Separate project

- [ ] **LLM evaluation harness** (`calipers`), which feeds evaluation evidence
      into Sextant. See [`proposals/LLM_EVALUATION_PROJECT.md`](proposals/LLM_EVALUATION_PROJECT.md).
