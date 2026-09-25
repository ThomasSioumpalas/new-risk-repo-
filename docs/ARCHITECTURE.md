# Architecture

## 1. Context

```mermaid
flowchart LR
    subgraph Users
        AN[Risk / GRC analyst]
        RO[Risk owner / executive]
        AU[Auditor]
        CO[Control owner]
    end
    subgraph Sextant
        CLI[CLI<br/>risk-as-code]
        API[REST API<br/>FastAPI]
        ENG[Risk engine<br/>pure library]
        DB[(PostgreSQL / SQLite)]
    end
    GIT[(Git repository<br/>YAML register)] --> CLI
    CLI --> ENG
    API --> ENG
    API --> DB
    CLI --> REP[Markdown reports<br/>+ charts]
    AN --> CLI & API
    RO & CO & AU --> API
    EVAL[LLM eval harness<br/>future project] -. evidence: trials / successes .-> API
```

Sextant has two front doors on one engine:

* **Risk-as-code (CLI).** The register lives as YAML in Git: reviewed in pull
  requests, versioned, diffable. `sextant report` produces a static,
  reproducible report set. This suits small teams and makes the whole method
  reviewable on GitHub.
* **Workflow service (API).** A multi-user register with roles, approvals,
  acceptances and an audit trail, which is the part a GRC tool must add around
  the maths.

## 2. Layers (ports and adapters)

```mermaid
flowchart TB
    subgraph Adapters
        R[api/routers] --- S[api/schemas]
        C[cli]
        RP[reporting]
    end
    subgraph Application
        SV[services<br/>register · assessments · governance · analysis · audit · security]
    end
    subgraph Domain
        D[domain<br/>estimates · scenario · controls · methodology · register]
        E[engine<br/>distributions · bayes · controls · model · simulation · metrics<br/>qualitative · sensitivity · treatment · portfolio · forecasting · explain · assessment]
        CP[compliance<br/>catalogs · readiness]
    end
    DBL[db<br/>SQLAlchemy models · session] --- SV
    R --> SV
    C --> E
    C --> CP
    RP --> E
    SV --> E
    SV --> CP
    E --> D
    CP --> D
```

| Package | Responsibility | Depends on |
|---|---|---|
| `domain` | Pydantic schemas: what a valid scenario, control, estimate, methodology or register *is* | pydantic only |
| `engine` | All mathematics. **Pure functions with no I/O, no database and no web code.** | domain, NumPy, SciPy |
| `compliance` | Framework catalogs (YAML) and readiness logic | domain, engine.controls |
| `services` | Use cases, permissions, governance rules, audit | domain, engine, compliance, db |
| `db` | Persistence (SQLAlchemy 2.0), sessions | — |
| `api` | HTTP: routing, (de)serialisation, error mapping, auth dependency | services |
| `cli`, `reporting` | Risk-as-code workflow and report generation | engine, compliance |

**Why this matters.** The engine can be reviewed, tested and re-used without a
server. That is how the statistical validation suite runs in seconds. The
governance rules live in *services*, so the API and any future UI cannot
bypass them.

## 3. Key design decisions

The full reasoning is in the ADRs in [`docs/adr/`](adr/).

| Decision | Choice | Alternative rejected |
|---|---|---|
| Decision basis for material risks | Quantitative (FAIR-aligned Monte Carlo) with the qualitative matrix retained | Matrix only (known ranking errors) |
| Prediction technique | Conjugate Bayesian and Monte Carlo methods | ML models (no data, not explainable) |
| Storage of domain objects | Validated JSON documents plus relational workflow tables | Fully normalised scenario tables (the schema would duplicate the Pydantic model and drift from it) |
| Comparing controls and treatments | Coupled simulation (thinning plus CRN) | Independent runs (noisy differences) |
| Audit trail | Append-only table, hash chain, DB triggers | Application logging (mutable, not evidential) |
| Authentication | Hashed API keys with RBAC | Session login or UI (out of scope); OIDC is on the roadmap |
| Deployment | One container plus PostgreSQL | Microservices, queues (unjustified at this scale) |

## 4. Data model

```mermaid
erDiagram
    RISKS ||--o{ ASSESSMENTS : "assessed by"
    RISKS ||--o{ RISK_ACCEPTANCES : "accepted via"
    RISKS ||--o{ TREATMENT_APPROVALS : "treatment approved via"
    ASSESSMENTS ||--o{ RISK_ACCEPTANCES : "references"
    ASSESSMENTS ||--o{ TREATMENT_APPROVALS : "references"
    ASSESSMENTS ||--o| ASSESSMENTS : supersedes
    CONTROLS }o--o{ RISKS : "linked in scenario document"
    EVIDENCE }o--o{ CONTROLS : "cited by"
    METHODOLOGIES ||--o{ ASSESSMENTS : "fingerprint (copy in snapshot)"
    AUDIT_LOG }o--|| AUDIT_HEAD : "chain tip"

    RISKS {
        string id PK
        json document
        int version
        string status
        date next_review_due
    }
    ASSESSMENTS {
        uuid id PK
        string status
        json inputs
        string inputs_fingerprint
        json result
        string result_fingerprint
        string computed_level
        string override_level
        string assessed_by
        string finalized_by
    }
    RISK_ACCEPTANCES {
        uuid id PK
        string accepted_level
        string required_authority
        string accepted_by
        date expires_on
        string status
    }
    AUDIT_LOG {
        int seq PK
        datetime ts
        string actor
        string action
        json payload
        string prev_hash
        string hash
    }
```

* A **risk** holds the current scenario definition (risk-as-code) with an
  optimistic-concurrency `version`.
* An **assessment** is an immutable result together with the *complete input
  snapshot* (scenario, referenced controls with their tests, methodology,
  as-of date, seed, trials). It can be reproduced even after the register has
  changed.
* **Acceptances** and **approvals** reference a specific final assessment.

## 5. Assessment lifecycle

```mermaid
stateDiagram-v2
    [*] --> draft: POST /risks/{id}/assessments
    draft --> draft: override (risk manager, justification ≥ 30 chars)
    draft --> final: finalize
    final --> superseded: newer assessment finalised
    final --> final: reproduce (read-only re-performance)
    note right of final
        immutable (application + DB trigger)
        schedules next review
        invalidates acceptances if level rose
    end note
```

## 6. Request flow (accepting a risk)

```mermaid
sequenceDiagram
    participant U as Executive
    participant API as FastAPI
    participant G as governance service
    participant DB as Database
    U->>API: POST /risks/RSK-006/acceptances (X-API-Key)
    API->>DB: resolve API key hash → actor, role
    API->>G: accept_risk(actor, risk, assessment, justification)
    G->>DB: load latest FINAL assessment (must match)
    G->>G: SoD: actor ∉ {assessor, overrider, finaliser}
    G->>G: authority ≥ max(level rule, outside-appetite escalation)
    G->>G: expiry = min(requested, max for level)
    G->>DB: insert acceptance + audit entry (same transaction)
    DB-->>API: commit
    API-->>U: 201 Created (expires_on, required_authority)
```

## 7. Cross-cutting concerns

| Concern | Implementation |
|---|---|
| Validation | Pydantic at every boundary (YAML, API, snapshots), `extra="forbid"`, semantic estimate checks, register cross-reference checks |
| Errors | Domain exceptions mapped centrally: 404 / 403 / 409 / 422, with a JSON body `{error, message}` and no stack traces |
| Transactions | One per request; the audit entry is written in the same transaction as the change |
| Concurrency | Optimistic versioning on risks; the audit chain head is row-locked (`SELECT … FOR UPDATE`) |
| Logging | structlog JSON with a request ID and the actor. Business events go to the audit log, not the application log. |
| Configuration | `SEXTANT_*` environment variables (pydantic-settings); there are no secrets in the repository |
| Resource limits | API trial cap, simulated-event budget |
| Reproducibility | Seeds, named streams, snapshot and fingerprints, engine and library versions, `uv.lock` |
| Time | UTC dates from a single clock module |

## 8. Deployment

```mermaid
flowchart LR
    subgraph docker compose
        API["api container<br/>non-root, read-only FS<br/>uvicorn"] -->|psycopg| PG[(postgres:16)]
    end
    ENTRY["entrypoint: alembic upgrade head"] --> API
    GW["reverse proxy / API gateway<br/>(TLS, rate limiting)"] --> API
```

The container binds to localhost in Compose. TLS termination, rate limiting and
SSO are expected in front of it (see [`SECURITY.md`](../SECURITY.md)).

## 9. Testing architecture

| Suite | Scope | Speed |
|---|---|---|
| `tests/unit` | Engine functions, schemas, compliance, CLI/reporting | seconds |
| `tests/validation` | Simulator against closed-form mathematics, property-based invariants | seconds |
| `tests/integration` | HTTP → services → migrated DB (SQLite locally, PostgreSQL 16 in CI) | seconds |
