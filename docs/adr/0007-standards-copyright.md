# ADR 0007: Copyright-aware handling of standards

**Status:** Accepted

## Context
ISO/IEC standards are copyrighted, and redistributing their text in a public
repository is not appropriate. NIST publications are US-government works in
the public domain. EU legislation may be reused.

## Decision
Each catalog declares `license` and `text_policy`:
* ISO/IEC 27001: clause and Annex A **identifiers** with **short topic labels
  written for this project**. No normative text.
* NIST CSF 2.0 and AI RMF: verbatim. CSF is generated from NIST's official
  OSCAL release.
* NIS2: abridged article text, with the Official Journal referenced as
  authoritative.

## Consequences
Users need a licensed copy of ISO/IEC 27001/27002 for the control
requirements. The mapping and readiness logic does not depend on the text.
