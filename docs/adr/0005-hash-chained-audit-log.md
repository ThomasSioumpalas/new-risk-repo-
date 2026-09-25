# ADR 0005: Append-only, hash-chained audit log enforced by database triggers

**Status:** Accepted

## Context
Accountability requires a trustworthy record of who did what and when.
Application logs are mutable and are not designed as evidence.

## Decision
* Each state change writes an audit entry **in the same transaction**.
* Each entry stores `hash = SHA-256(canonical entry ‖ previous hash)`. A
  single-row chain head is locked (`SELECT … FOR UPDATE`) to serialise
  appends.
* Triggers reject UPDATE and DELETE on `audit_log`, on SQLite and on
  PostgreSQL.
* `GET /audit/verify` recomputes the chain and reports the first invalid
  entry.

## Consequences
The log is tamper-*evident*, not tamper-*proof*: a DBA could rewrite the whole
chain. **Mitigation (roadmap):** periodically anchor the head hash outside the
database, for example in WORM storage or with an RFC 3161 timestamp. The
integration test demonstrates detection after a trigger is dropped.
