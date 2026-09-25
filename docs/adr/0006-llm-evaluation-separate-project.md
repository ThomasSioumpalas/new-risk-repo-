# ADR 0006: LLM evaluation is a separate project, integrated through evidence

**Status:** Accepted

## Context
There is interest in LLM evaluation and AI risk. A serious evaluation platform
needs dataset and prompt versioning, model adapters, evaluation runners,
judge-model calibration, inter-rater agreement and statistical comparison of
model versions. Its purpose, users (ML engineers, AI assurance) and
architecture differ from those of a risk register.

## Decision
* Sextant handles **AI risks as risk scenarios**, mapped to the NIST AI RMF.
* The evaluation harness is a **separate repository** (see
  `docs/proposals/LLM_EVALUATION_PROJECT.md`). It *produces evidence*, such as
  "7/200 prompt injections succeeded", which Sextant consumes as
  `beta_from_trials` estimates.

## Consequences
Each project stays coherent and credible, and together they show the
measurement → risk → decision chain that AI governance needs.
