# ADR 0004: Immutable assessments with full input snapshots

**Status:** Accepted

## Context
An auditor must be able to see exactly what was assessed, with which criteria
and by whom, and must be able to re-perform the calculation, even after the
register has changed. The domain schema (scenario, estimates, controls) is
rich and evolves.

## Decision
* Store domain objects as **validated JSON documents**. The Pydantic schema is
  the single source of truth. Relational columns hold identity, workflow state
  and query keys.
* Every assessment stores a **complete snapshot** of its inputs (scenario, the
  referenced controls with their test history, the methodology, the as-of
  date, seed and trials), together with SHA-256 fingerprints of inputs and
  result, and the engine and library versions.
* Finalised assessments are immutable. The application refuses changes, and
  database triggers do too. Changes require a new assessment that supersedes
  the old one.

## Alternatives
A fully normalised scenario schema was rejected: it would duplicate the domain
model and drift from it, for little query benefit.

## Consequences
Snapshots take space (roughly tens of KB per assessment), which is acceptable.
`POST /assessments/{id}/reproduce` gives a mechanical re-performance test.
