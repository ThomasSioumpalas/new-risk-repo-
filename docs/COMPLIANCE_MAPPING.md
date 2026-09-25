# Compliance Mapping

## 1. Six activities that must not be confused

| Activity | Question it answers | Sextant output | Who concludes |
|---|---|---|---|
| **Risk assessment** | How likely and how bad is this scenario, and how sure are we? | Assessment (ALE, VaR, level, intervals) | Risk owner, informed by the analyst |
| **Control assessment** | Is the control designed adequately, and did it operate over the period? | Test conclusion (Beta posterior, Clopper-Pearson bound) | Tester (2nd or 3rd line) |
| **Evidence collection** | What proves it? | Evidence metadata with SHA-256, validity date | Control owner |
| **Compliance mapping** | Which controls address which requirement, and how completely? | STRM mappings (equal / subset / superset / intersects) | Compliance function |
| **Readiness / gap assessment** | Where are the gaps before an audit? | Readiness status per requirement plus indicators | Compliance function (planning) |
| **Certification / audit opinion** | Does the ISMS conform to ISO/IEC 27001? | **Not produced** | Accredited certification body (ISO/IEC 17021-1, 27006) |

The readiness report opens with this disclaimer:

> Readiness indicators summarise mapped controls, test results and evidence
> currency. They are NOT an audit opinion, a conformity assessment or a
> certification.

## 2. Frameworks included

| Catalog id | Framework | Coverage | Text policy | Licence / source |
|---|---|---|---|---|
| `iso27001_2022` | ISO/IEC 27001:2022 | Clauses 4–10 (25 items) + Annex A (93 controls) | **Identifiers + paraphrased topic labels only** | Copyrighted. No normative text is reproduced. Consult a licensed copy. |
| `nist_csf_2_0` | NIST CSF 2.0 | 6 functions, 22 categories, 106 subcategories | Verbatim | Public domain. **Generated** from NIST's official OSCAL catalog by `scripts/build_csf_catalog.py`; withdrawn CSF 1.1 items are excluded. |
| `nis2_2022_2555` | NIS2 Directive | Art. 20(1–2), 21(1), 21(2)(a–j), 23(4) | Abridged | EU law, reusable; the Official Journal is authoritative. National transposition can add requirements. |
| `nist_ai_rmf_1_0` | NIST AI RMF 1.0 | 19 categories (GOVERN, MAP, MEASURE, MANAGE) | Verbatim | Public domain (NIST AI 100-1 §5) |

**Why ISO clauses are included.** A common misconception is that ISO/IEC 27001
"is Annex A". Certification audits examine the *management system* (clauses
4–10) at least as closely: risk criteria, risk assessment and treatment
processes, internal audit, management review. Sextant maps its own
capabilities and governance controls to those clauses. Examples: CTL-GOV-01 →
C.6.1.2 and C.8.2; CTL-GOV-02 → C.6.1.3 and C.8.3.

## 3. Mapping relationships (NIST IR 8477 STRM)

A mapping reads: **"the control is \<relationship\> the requirement"**.

| Relationship | Meaning | Can address the requirement alone? |
|---|---|---|
| `equal` | Same scope | Yes |
| `superset_of` | The control covers the requirement and more | Yes |
| `subset_of` | The control covers only part of the requirement | No (partial) |
| `intersects_with` | Partial overlap | No (partial) |

Example: MFA (CTL-IAM-01) is `subset_of` NIS2 Art. 21(2)(j). That point also
requires secured voice, video and text, and secured emergency communications.
A 1:1 "MFA = 21(2)(j)" mapping would overstate compliance, which is exactly
the error auditors find in spreadsheet mappings.

## 4. Readiness status rules

For each requirement, each mapped control is first classified:

* **verified**: in operation, operating test conclusion *effective*, and at
  least one current (unexpired) evidence item;
* **unverified**: in operation, but untested, inconclusive or without current
  evidence;
* **ineffective**: the design test failed, or the operating test was *not
  effective*;
* **planned**: not yet in operation.

The requirement status is then assigned by the first rule that matches:

| Status | Rule |
|---|---|
| `not_applicable` | Excluded with a documented justification and an approver (SoA exclusion) |
| `gap` | No mapped control |
| `addressed` | A fully-covering (equal / superset) control is **verified** |
| `implemented_not_evidenced` | A fully-covering control is in operation but unverified |
| `partially_addressed` | Only partially-covering controls are in operation |
| `control_ineffective` | Mapped controls failed testing |
| `planned` | Only planned controls |

The **readiness indicator** is `addressed / applicable`. The **coverage
indicator** is `(addressed + not evidenced + partial) / applicable`. Both are
planning heuristics for the compliance function. The example register
deliberately contains only the 21 controls relevant to its eight scenarios, so
its indicators are low by construction.

## 5. Statement of Applicability (draft)

ISO/IEC 27001 6.1.3 d) requires an SoA: the necessary controls, the
justification for including them, whether they are implemented, and the
justification for any exclusions. Sextant derives a **draft** from the
readiness report:

* *Included because it treats assessed risk(s) RSK-…*: the traceability from
  risk to control that auditors test;
* *Implemented; no linked risk*: flagged, so the ISMS owner documents the
  driver (legal, contractual or baseline);
* *TO DECIDE*: neither a linked risk nor an implementing control;
* *Excluded*: with the recorded justification (e.g. A.8.30 outsourced
  development, because no development is outsourced).

The ISMS owner must review the draft. It is not a finished SoA.

## 6. NIST AI RMF and AI risks

AI risks are handled as **risk scenarios** like any other (see RSK-008:
prompt-injection disclosure). They are mapped to AI RMF categories and
quantified from **evaluation evidence**: the red-team success rate becomes a
Beta posterior for susceptibility. The trustworthiness evaluation itself (the
MEASURE 2 activities) belongs to a dedicated evaluation harness. See
[`proposals/LLM_EVALUATION_PROJECT.md`](proposals/LLM_EVALUATION_PROJECT.md).

## 7. Adding a framework

1. Add `src/sextant/compliance/catalogs/<id>.yaml` with `license`,
   `text_policy`, `source`, `groups` and `requirements`.
2. Respect copyright: reproduce text only if it is public domain or reusable
   legislation, and otherwise use identifiers with your own labels.
3. Register the file in `CATALOG_FILES` and add a size test.
4. Map controls with explicit STRM relationships and rationale.

Candidates on the roadmap: DORA (Regulation (EU) 2022/2554) ICT risk
management articles, ISO/IEC 42001:2023 (identifiers only), CIS Controls v8,
and SOC 2 Trust Services Criteria (identifiers only).
