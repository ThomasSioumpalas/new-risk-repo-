# Walkthrough: how a risk analyst uses Sextant

This is a guided tour of Sextant through one worked example: **Halcyon Logistics S.A.**, a
**fictional** mid-sized EU freight-forwarding company (`examples/halcyon/`). Every name, figure,
control-test result and incident in this example is synthetic and written for demonstration. It
is not a benchmark, and no part of it describes a real organisation.

A full, committed report set generated from this register lives in
[`examples/reports/`](reports/README.md) — start there to see the output, then come back here for
how it was produced and how to read it.

## 1. The register: what an analyst maintains

A register is a directory of YAML files (`examples/halcyon/`), loaded by
`sextant.domain.register.load_register`. Each file is a distinct, auditable concern:

| File | Contents |
|---|---|
| `organization.yaml` | Who this register is for: name, sector, jurisdiction, revenue. Marked `fictional: true`. |
| `assets.yaml` | The 10 primary and supporting assets (the WMS, the customer portal, the LLM assistant, the payroll SaaS, …) with CIA ratings, used to scope scenarios. |
| `controls.yaml` | A library of 21 controls: what each one is, who owns it, its implementation status, its **test history** (design and operating-effectiveness tests, with samples and exceptions), and its mappings to ISO 27001, NIST CSF 2.0 and NIS2. |
| `evidence.yaml` | 15 evidence records (policy documents, test reports, configuration exports) with collection dates and validity windows — cited by controls and tests. |
| `exclusions.yaml` | One declared-not-applicable Annex A requirement (A.8.30, outsourced development), with a justification and an approver, feeding the readiness assessment and the SoA. |
| `scenarios/*.yaml` | 8 risk scenarios (`RSK-001` … `RSK-008`), one file each: the threat, the FAIR-decomposed loss model (threat event frequency, susceptibility, primary/secondary loss components), which controls are linked and to which factor, treatment options, and (for some) a qualitative likelihood/impact rating. |
| `data/*.csv` | Two KRI/incident time series used by the `forecast` command: monthly phishing-filter bypasses and warehouse-management-system outages. |

There is no `methodology.yaml` in this register, so it uses the reference methodology shipped with
Sextant (`sextant-reference` v1.0.0): the likelihood/impact scales, the 5x5 matrix, the scenario ALE
appetite threshold (EUR 500k), the portfolio tolerance curve, the acceptance-authority matrix and
the control-testing policy (10% tolerable deviation rate, 90% confidence). A register can pin its
own `methodology.yaml` instead; every assessment records the methodology's id, version and
fingerprint, so criteria drift is always visible.

## 2. The commands, in the order an analyst runs them

```bash
# 1. Check the register loads and its cross-references are intact.
uv run sextant validate examples/halcyon

# 2. Run a quick quantitative look, e.g. while iterating on one scenario's estimates.
uv run sextant assess examples/halcyon --scenario RSK-008 --trials 20000 --as-of 2026-09-01

# 3. Generate the full report set (this is what produced examples/reports/).
uv run sextant report examples/halcyon --out examples/reports --as-of 2026-09-01

# 4. Check compliance readiness against one framework on its own.
uv run sextant readiness examples/halcyon --framework nis2_2022_2555 --as-of 2026-09-01

# 5. Forecast a KRI from its incident history.
uv run sextant forecast examples/halcyon/data/kri_phishing_bypass.csv \
    --column reported_phishing_bypassing_filter --discount 0.9 --threshold 20 \
    --out examples/reports

# 6. Auditor utilities: how many test samples support an "effective" conclusion,
#    and what does a specific test result conclude?
uv run sextant sample-size --tdr 0.10 --confidence 0.90
uv run sextant control-test --samples 20 --exceptions 0 --tdr 0.10 --confidence 0.90
```

`--as-of 2026-09-01` and the methodology's default trial count and seed (20,000 trials, seed
20260101) are what produced the committed `examples/reports/`; re-running the command above
reproduces it byte-for-byte (see observation 6 below).

## 3. How to read the output

- **`examples/reports/README.md`** is the register-level view: the scenario table (current ALE, 90%
  credible interval, within-appetite status, acceptance authority), the portfolio (ALE, VaR,
  expected shortfall, the tolerance curve), the matrix-vs-ALE ranking comparison, cross-scenario
  findings, and links to readiness and the SoA.
- **`examples/reports/risks/<ID>.md`** is the full case for one scenario: a plain-language
  explanation (what the risk is, why it's at that level, how confident the model is, which
  controls matter, what happens under stress, and what the best mitigation is), then the
  supporting tables — risk states, loss breakdown, inputs, control assessment, treatment options,
  sensitivity, stress tests — and a reproducibility block with the exact command to regenerate it.
- **`examples/reports/readiness/<framework>.md`** is a gap assessment for one compliance
  framework: status counts, a per-group summary, and every requirement with its mapped controls
  and related risks. **`readiness/soa-iso27001_2022.md`** is a draft Statement of Applicability.
- **`examples/reports/forecast/<column>.md`** is a KRI forecast: the predictive interval for the
  next period, a trend test, and a backtest of how well the model's past forecasts were calibrated.

## 4. Six observations, read directly from the generated reports

1. **Two scenarios are outside appetite, for different reasons.** `RSK-006` (WMS outage, ALE EUR
   578k) and `RSK-008` (LLM prompt injection, ALE EUR 515k) both exceed the EUR 500k scenario ALE
   threshold. `RSK-006` is also rated `Moderate` on the risk matrix, so both signals agree. `RSK-008`
   is rated `Low` on the matrix — see observation 2.

2. **The matrix and the ALE disagree on `RSK-008`.** Its likelihood band is `Very High` (5.37
   expected loss events/year — the LLM assistant currently has *no* linked controls) but its impact
   band is `Low` (EUR 95k expected loss per event), and the matrix lookup for that cell is `Low`. A
   reviewer who only looked at the matrix cell would not flag it, yet its ALE of EUR 515k is
   outside the EUR 500k appetite threshold (`examples/reports/README.md`, "Matrix vs quantitative
   ranking"). The same section also shows *range compression* (`RSK-001` and `RSK-004` share an
   ordinal score of 8, but their ALEs differ by a factor of ~4) and a *ranking reversal* (`RSK-001`
   has a lower ordinal score than `RSK-005` but a higher ALE) — exactly the failure modes a
   likelihood-times-impact score is known to have (Cox, 2008).

3. **Coupling controls the treatment estimates.** In `risks/RSK-001.md`, option T3 (cyber
   insurance) shows a paired ΔALE standard error of about EUR 7k against an independent standard
   error of about EUR 13k — the paired estimate (from re-simulating the same years with and
   without the option) is nearly twice as precise, because it removes the Monte Carlo noise that
   two separately-simulated runs would carry.

4. **Some "clean" control tests are still inconclusive.** `CTL-TPR-01` (third-party due diligence,
   linked to `RSK-003`) has **zero exceptions in 20 samples**, yet its conclusion is
   `inconclusive`, not `effective`: at a 10% tolerable deviation rate and 90% confidence, a
   uniform-prior Bayesian test needs 21 clean samples (`uv run sextant sample-size --tdr 0.10
   --confidence 0.90` reports 21 for the Bayesian rule and 22 for the classical Clopper-Pearson
   rule) — one more than this control has. `CTL-IR-01` (incident-response playbook, `RSK-003` and
   `RSK-007`) has 1 exception in 6 samples and needs about 31 more exception-free samples to reach
   a conclusion either way. Both illustrate why "zero exceptions" alone is not proof of an
   effective control with a small sample.

5. **Inputs are a mix of data and judgement, and the report says which.** `RSK-008`'s
   susceptibility comes from an actual red-team result (Beta posterior from 7/200 successful
   prompt injections) — 1 of its 6 inputs is data-derived, the rest are expert judgement. `RSK-001`
   has 5 of 18 inputs data-derived, mostly control operating rates from audit test samples. The
   "How confident are we?" section of each risk page states this ratio and names the single input
   that would most narrow the ALE estimate if better measured (its rank-sensitivity leader).

6. **The portfolio's ALE and tail are driven by different scenarios.** `RSK-001` (ransomware) is
   21.5% of the portfolio ALE but 47.7% of the 95% expected-shortfall tail — a rare, severe
   scenario that dominates bad years far more than it dominates the average. `RSK-006` (WMS
   outage) is a larger 25.7% ALE share but only 10.0% of the tail — a more frequent, less extreme
   loss. A budget prioritised by ALE alone would under-weight `RSK-001`'s tail risk
   (`examples/reports/README.md`, "Scenario shares").

7. **Determinism is verified, not assumed.** `report` was run twice with the same inputs
   (`--trials 20000 --seed 20260101`, the methodology's defaults) and every Markdown file —
   including `README.md` — came out byte-identical; the PNG charts did too, because the renderer
   fixes the DPI, clears the `Software` metadata tag and never touches wall-clock time. This is
   what `tests/unit/test_cli_reporting.py::test_report_is_deterministic` checks at a smaller trial
   count for speed.

## 5. The control library is intentionally partial

`controls.yaml` has 21 controls: enough to credit, test and mostly explain the 8 risk scenarios in
this register, not a full ISO 27001 Annex A or NIST CSF 2.0 implementation. As a direct
consequence, the readiness indicators in `examples/reports/readiness/*.md` are low **by
construction** — ISO 27001 readiness is 2.6% "addressed" and 16.2% "covered" out of 117 applicable
requirements, NIS2 is 0% addressed but 57.1% covered (a smaller, more targeted requirement set),
and most Annex A controls in the draft SoA (`readiness/soa-iso27001_2022.md`) come back marked
`TO DECIDE: no linked risk and no implementing control`. That is the expected, correct output of a
register built to demonstrate eight scenarios, not a finding about the engine or the example
company. A real register's readiness would track how much of the *actual* control environment has
been entered and mapped.

## 6. Reproducing the auditor utilities

```bash
uv run sextant sample-size --tdr 0.10 --confidence 0.90
#   Bayesian (uniform prior): 21 samples
#   Classical (Clopper-Pearson): 22 samples

uv run sextant control-test --samples 21 --exceptions 0 --tdr 0.10 --confidence 0.90
#   Conclusion: effective

uv run sextant control-test --samples 20 --exceptions 0 --tdr 0.10 --confidence 0.90
#   Conclusion: inconclusive (matches CTL-TPR-01 above)
```

---

**Everything in `examples/` — the organisation, its assets, controls, incidents, test results and
figures — is fictional and synthetic, built to exercise Sextant's statistics and reporting. It is
not a benchmark and does not describe, and should not be mistaken for, any real company.**
