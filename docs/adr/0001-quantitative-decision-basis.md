# ADR 0001: Quantitative analysis is the decision basis; the matrix is retained

**Status:** Accepted

## Context
Most registers use a 5×5 matrix and often multiply ordinal ranks. The
literature (Cox 2008; Thomas, Bratvold & Bickel 2014; Hubbard & Seiersen)
documents range compression, ranking reversals and false precision. However,
auditors, boards and ISO-based programmes expect matrix levels, and
qualitative rating is legitimate for screening.

## Decision
* Every scenario has a FAIR-aligned quantitative model, which is the decision
  basis (`Evaluation.decision_level`).
* Quantitative results are *banded* onto the methodology's scales, so levels
  remain comparable and can be communicated.
* Analysts may add qualitative ratings. Disagreements of two or more levels
  raise `METHODS-DISAGREE`.
* The L × I ordinal product is shown only as a reference, with an explanation.

## Alternatives
* Matrix only: rejected because of its known ranking errors.
* Quantitative only: rejected. It breaks comparability with ISO-style
  programmes, and some risks are better screened qualitatively.

## Consequences
Every scenario needs frequency and magnitude estimates. Wide calibrated
intervals are acceptable, and they are part of the honest answer.
