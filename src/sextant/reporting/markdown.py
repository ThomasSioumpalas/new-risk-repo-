"""Markdown report writer: Jinja2 templates fed by typed, pre-formatted view rows.

Templates stay simple (loops and conditionals over already-formatted strings)
so that the layout can be reviewed without re-deriving the numbers; all
formatting decisions (currency, percentages, rounding) are made once, here, in
Python.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from sextant import ENGINE_VERSION
from sextant.compliance.catalog import Catalog
from sextant.compliance.readiness import (
    DISCLAIMER,
    STATUS_ORDER,
    ReadinessReport,
    RequirementResult,
    SoAEntry,
)
from sextant.domain.controls import Control
from sextant.engine.assessment import QuantitativeAssessment
from sextant.engine.explain import input_label, money
from sextant.engine.forecasting import BacktestResult, Forecast, TrendTest
from sextant.engine.model import CURRENT, INHERENT, TARGET
from sextant.reporting import charts
from sextant.reporting.pipeline import RankingRow, RegisterAnalysis

ISO_CATALOG_ID = "iso27001_2022"


@lru_cache(maxsize=1)
def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("sextant.reporting", "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 -- Markdown output, not HTML; escaping would corrupt it.
    )
    env.filters["money"] = lambda value, currency: money(float(value), currency)
    env.filters["ci"] = lambda interval, currency: (
        f"{money(float(interval[0]), currency)} – {money(float(interval[1]), currency)}"
    )
    env.filters["pct"] = lambda value, decimals=0: f"{float(value):.{decimals}%}"
    env.filters["pct_range"] = lambda interval, decimals=1: (
        f"{float(interval[0]):.{decimals}%} – {float(interval[1]):.{decimals}%}"
    )
    env.filters["num"] = lambda value: f"{value:,}"
    env.filters["signed_money"] = lambda value, currency: (
        f"-{money(-float(value), currency)}" if value < 0 else f"+{money(float(value), currency)}"
    )
    return env


def _render(template: str, **context: object) -> str:
    return _environment().get_template(template).render(**context)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- shared value formatting -----------------------------------------------------------


def _role_label(role: object) -> str:
    return str(role).replace("_", " ").title()


def _title_case(value: str) -> str:
    return value.replace("_", " ").title()


SEVERITY_MARK = {"error": "❌ error", "warning": "⚠️ warning", "info": "ℹ️ info"}


# --- view rows ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterRow:
    scenario_id: str
    title: str
    owner: str
    quantitative_level: str
    qualitative_level: str
    ale: float
    ale_ci: tuple[float, float]
    var_95: float
    prob_within: float
    within_appetite: bool
    authority: str
    selected_treatment: str
    target_ale: str


@dataclass(frozen=True)
class FindingRow:
    scenario_id: str
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class RankingViewRow:
    ale_rank: int
    scenario_id: str
    title: str
    ale: float
    quantitative_level: str
    ordinal_score: int
    qualitative_level: str
    within_appetite: bool


def _register_rows(analysis: RegisterAnalysis) -> list[RegisterRow]:
    rows = []
    for scenario in analysis.register.scenarios:
        run = analysis.runs[scenario.id]
        r = run.result
        cur = r.states[CURRENT]
        qual = r.qualitative.current.risk_level if r.qualitative else "—"
        treatment = "—"
        if scenario.selected_treatment is not None:
            treatment = scenario.treatment(scenario.selected_treatment).title
        target_ale = f"{money(r.states[TARGET].stats.ale, r.currency)}" if TARGET in r.states else "—"
        rows.append(
            RegisterRow(
                scenario_id=r.scenario_id,
                title=r.scenario_title,
                owner=scenario.owner,
                quantitative_level=cur.banded.risk_level,
                qualitative_level=qual,
                ale=cur.stats.ale,
                ale_ci=cur.stats.ale_credible_interval_90,
                var_95=cur.stats.var_95,
                prob_within=r.evaluation.prob_ale_within_threshold,
                within_appetite=r.evaluation.within_appetite,
                authority=_role_label(r.evaluation.acceptance_authority),
                selected_treatment=treatment,
                target_ale=target_ale,
            )
        )
    return rows


def _finding_rows(analysis: RegisterAnalysis) -> list[FindingRow]:
    rows = []
    order = {"error": 0, "warning": 1, "info": 2}
    for scenario in analysis.register.scenarios:
        r = analysis.runs[scenario.id].result
        for f in r.findings:
            rows.append(
                FindingRow(
                    scenario_id=r.scenario_id, severity=str(f.severity), code=f.code, message=f.message
                )
            )
    rows.sort(key=lambda row: (order.get(row.severity, 9), row.scenario_id))
    return rows


def _ranking_rows(analysis: RegisterAnalysis) -> list[RankingViewRow]:
    rows = []
    for row in analysis.ranking:
        within = analysis.runs[row.scenario_id].result.evaluation.within_appetite
        rows.append(
            RankingViewRow(
                ale_rank=row.ale_rank,
                scenario_id=row.scenario_id,
                title=row.title,
                ale=row.ale,
                quantitative_level=row.quantitative_level,
                ordinal_score=row.ordinal_score,
                qualitative_level=row.qualitative_level or "—",
                within_appetite=within,
            )
        )
    return rows


def _ranking_commentary(analysis: RegisterAnalysis, currency: str) -> list[str]:
    """2-3 data-driven sentences on where the ordinal L x I score misranks risks versus ALE."""
    rows = analysis.ranking
    sentences: list[str] = []

    by_score: dict[int, list[RankingRow]] = {}
    for row in rows:
        by_score.setdefault(row.ordinal_score, []).append(row)
    compressed = [group for group in by_score.values() if len(group) > 1]
    if compressed:
        group = max(compressed, key=lambda g: max(x.ale for x in g) / max(min(x.ale for x in g), 1.0))
        hi = max(group, key=lambda x: x.ale)
        lo = min(group, key=lambda x: x.ale)
        ratio = hi.ale / lo.ale if lo.ale > 0 else float("inf")
        sentences.append(
            f"**Range compression:** {hi.scenario_id} and {lo.scenario_id} share the same ordinal score "
            f"({hi.ordinal_score} = likelihood × impact), yet their current ALE differs by a factor of "
            f"{ratio:.1f} ({money(hi.ale, currency)} vs {money(lo.ale, currency)}); the ordinal score cannot "
            "tell these risks apart even though the model can."
        )

    by_ordinal = sorted(rows, key=lambda r: r.ordinal_score, reverse=True)
    for a, b in pairwise(by_ordinal):
        if a.ale < b.ale:
            sentences.append(
                f"**Ranking reversal:** {b.scenario_id} has a lower ordinal score ({b.ordinal_score}) than "
                f"{a.scenario_id} ({a.ordinal_score}) but a higher current ALE ({money(b.ale, currency)} vs "
                f"{money(a.ale, currency)}); a committee that prioritised by the ordinal score alone would "
                "treat the smaller risk first (Cox, 2008)."
            )
            break

    for row in rows:
        within = analysis.runs[row.scenario_id].result.evaluation.within_appetite
        low_half = analysis.methodology.risk_levels[: len(analysis.methodology.risk_levels) // 2 + 1]
        if row.quantitative_level in low_half and not within:
            sentences.append(
                f"**Appetite is set on ALE, not on the matrix level:** {row.scenario_id} is rated "
                f"'{row.quantitative_level}' on the risk matrix, which alone would not prompt escalation, but "
                f"its current ALE of {money(row.ale, currency)} exceeds the "
                f"{money(analysis.methodology.appetite.scenario_ale_threshold, currency)} scenario appetite "
                "threshold and is therefore outside appetite."
            )
            break

    return sentences[:3]


# --- README --------------------------------------------------------------------------


def render_readme(analysis: RegisterAnalysis) -> str:
    methodology = analysis.methodology
    currency = methodology.currency
    portfolio = analysis.portfolio
    return _render(
        "readme.md.j2",
        analysis=analysis,
        org=analysis.register.organization,
        methodology=methodology,
        currency=currency,
        engine_version=ENGINE_VERSION,
        rows=_register_rows(analysis),
        portfolio=portfolio,
        shares=portfolio.shares,
        tolerance=portfolio.tolerance,
        ranking=_ranking_rows(analysis),
        commentary=_ranking_commentary(analysis, currency),
        findings=_finding_rows(analysis),
        catalogs=analysis.readiness,
        disclaimer=DISCLAIMER,
        fingerprint=methodology.fingerprint[:12],
    )


# --- risk pages ------------------------------------------------------------------------


@dataclass(frozen=True)
class StateRow:
    name: str
    label: str
    ale: float
    ale_ci: tuple[float, float]
    var_95: float
    es_95: float
    prob_any_event: float
    loss_events_per_year: float
    expected_loss_per_event: float | None
    level: str
    likelihood: int
    impact: int


@dataclass(frozen=True)
class LossFormRow:
    form: str
    amount: float
    share: float


@dataclass(frozen=True)
class InputRow:
    label: str
    distribution: str
    provenance: str
    source: str
    rationale: str


@dataclass(frozen=True)
class ControlRow:
    control_id: str
    name: str
    conclusion: str
    basis: str
    samples: int
    exceptions: int
    operating_mean: float
    operating_ci: tuple[float, float]
    clopper_pearson_upper: str
    ale_increase: str
    explanation: str


@dataclass(frozen=True)
class TreatmentRow:
    option_id: str
    title: str
    type: str
    ale: float
    ale_reduction: float
    ale_reduction_se_paired: float
    ale_reduction_se_independent: float
    var_95_reduction: float
    annualised_cost: float
    rosi: str
    residual_level: str
    within_appetite: bool


def _state_rows(result: QuantitativeAssessment) -> list[StateRow]:
    rows = []
    for name in (n for n in (INHERENT, CURRENT, TARGET) if n in result.states):
        s = result.states[name]
        rows.append(
            StateRow(
                name=name,
                label=s.label,
                ale=s.stats.ale,
                ale_ci=s.stats.ale_credible_interval_90,
                var_95=s.stats.var_95,
                es_95=s.stats.es_95,
                prob_any_event=s.stats.prob_at_least_one_event,
                loss_events_per_year=s.stats.expected_loss_events,
                expected_loss_per_event=s.stats.expected_loss_per_event,
                level=s.banded.risk_level,
                likelihood=s.banded.likelihood,
                impact=s.banded.impact,
            )
        )
    return rows


def _loss_form_rows(result: QuantitativeAssessment) -> list[LossFormRow]:
    current = result.states[CURRENT].stats
    ale = current.ale
    rows = [
        LossFormRow(form=_title_case(form), amount=amount, share=(amount / ale if ale > 0 else 0.0))
        for form, amount in current.loss_by_form.items()
    ]
    return sorted(rows, key=lambda r: r.amount, reverse=True)


def _input_rows(result: QuantitativeAssessment) -> list[InputRow]:
    return [
        InputRow(
            label=input_label(i.input),
            distribution=i.distribution,
            provenance=_title_case(i.provenance),
            source=i.source or "—",
            rationale=i.rationale or "—",
        )
        for i in result.inputs
    ]


def _control_rows(result: QuantitativeAssessment, controls: Mapping[str, Control]) -> list[ControlRow]:
    contributions = {c.control_id: c for c in result.controls}
    rows = []
    for a in result.control_assessments:
        control = controls.get(a.control_id)
        name = control.name if control is not None else a.control_id
        contribution = contributions.get(a.control_id)
        ale_increase = (
            money(contribution.ale_increase_if_failed, result.currency) if contribution else "not credited"
        )
        cp = (
            f"{a.deviation_upper_bound_clopper_pearson:.1%}"
            if a.deviation_upper_bound_clopper_pearson is not None
            else "—"
        )
        rows.append(
            ControlRow(
                control_id=a.control_id,
                name=name,
                conclusion=_title_case(str(a.conclusion)),
                basis=a.conclusion_basis,
                samples=a.samples,
                exceptions=a.exceptions,
                operating_mean=a.operating_rate_mean,
                operating_ci=a.operating_rate_interval_90,
                clopper_pearson_upper=cp,
                ale_increase=ale_increase,
                explanation=a.explanation,
            )
        )
    return rows


def _treatment_rows(result: QuantitativeAssessment) -> list[TreatmentRow]:
    rows = []
    for o in result.options:
        rosi = f"{o.rosi:+.0%}" if o.rosi is not None else "— (no cost recorded)"
        rows.append(
            TreatmentRow(
                option_id=o.option_id,
                title=o.title,
                type=_title_case(str(o.type)),
                ale=o.ale,
                ale_reduction=o.ale_reduction,
                ale_reduction_se_paired=o.ale_reduction_se_paired,
                ale_reduction_se_independent=o.ale_reduction_se_independent,
                var_95_reduction=o.var_95_reduction,
                annualised_cost=o.annualised_cost,
                rosi=rosi,
                residual_level=o.residual_level,
                within_appetite=o.within_appetite,
            )
        )
    return rows


@dataclass(frozen=True)
class QualComparisonRow:
    name: str
    quant_level: str
    quant_li: str
    qual_level: str
    qual_li: str
    agree: bool


@dataclass(frozen=True)
class ReproInfo:
    inputs_fingerprint: str
    result_fingerprint: str
    methodology_fingerprint: str
    engine_version: str
    library_versions: dict[str, str]
    seed: int
    trials: int
    as_of: date
    command: str


def render_risk_page(
    result: QuantitativeAssessment,
    controls: Mapping[str, Control],
    lec_chart: str,
    tornado_chart: str,
    register_dir: str,
) -> str:
    command = (
        f"uv run sextant assess {register_dir} --scenario {result.scenario_id} "
        f"--trials {result.trials} --seed {result.seed} --as-of {result.as_of.isoformat()}"
    )
    repro = ReproInfo(
        inputs_fingerprint=result.inputs_fingerprint,
        result_fingerprint=result.result_fingerprint,
        methodology_fingerprint=result.methodology_fingerprint,
        engine_version=result.engine_version,
        library_versions=result.library_versions,
        seed=result.seed,
        trials=result.trials,
        as_of=result.as_of,
        command=command,
    )
    qual_rows: list[QualComparisonRow] | None = None
    if result.qualitative is not None:
        by_state = {
            INHERENT: result.qualitative.inherent,
            CURRENT: result.qualitative.current,
            TARGET: result.qualitative.target,
        }
        qual_rows = []
        for name in (n for n in (INHERENT, CURRENT, TARGET) if n in result.states):
            qual = by_state.get(name)
            if qual is None:
                continue
            quant = result.states[name].banded
            qual_rows.append(
                QualComparisonRow(
                    name=name,
                    quant_level=quant.risk_level,
                    quant_li=f"{quant.likelihood}×{quant.impact}={quant.ordinal_score}",
                    qual_level=qual.risk_level,
                    qual_li=f"{qual.likelihood}×{qual.impact}={qual.ordinal_score}",
                    agree=quant.risk_level == qual.risk_level,
                )
            )
    return _render(
        "risk.md.j2",
        r=result,
        currency=result.currency,
        states=_state_rows(result),
        loss_forms=_loss_form_rows(result),
        inputs=_input_rows(result),
        controls=_control_rows(result, controls),
        treatments=_treatment_rows(result),
        rank_sensitivity=result.rank_sensitivity[:8],
        stress_tests=result.stress_tests,
        qualitative_rows=qual_rows,
        findings=result.findings,
        input_label=input_label,
        repro=repro,
        lec_chart=lec_chart,
        tornado_chart=tornado_chart,
        severity_mark=SEVERITY_MARK,
        title_case=_title_case,
        role_label=_role_label,
    )


# --- readiness pages ---------------------------------------------------------------------


@dataclass(frozen=True)
class GroupSummary:
    group_id: str
    title: str
    applicable: int
    counts: list[int]  # in STATUS_VALUES order


STATUS_VALUES = [s.value for s in STATUS_ORDER]
STATUS_LABELS = [_title_case(s) for s in STATUS_VALUES]


def _group_summaries(catalog: Catalog, report: ReadinessReport) -> list[GroupSummary]:
    order: list[str] = []
    by_group: dict[str, list[RequirementResult]] = {}
    for req in report.requirements:
        by_group.setdefault(req.group, []).append(req)
        if req.group not in order:
            order.append(req.group)
    summaries = []
    for gid in order:
        by_status: dict[str, int] = dict.fromkeys(STATUS_VALUES, 0)
        for r in by_group[gid]:
            by_status[r.status.value] += 1
        applicable = sum(c for status, c in by_status.items() if status != "not_applicable")
        summaries.append(
            GroupSummary(
                group_id=gid,
                title=catalog.group_title(gid),
                applicable=applicable,
                counts=[by_status[s] for s in STATUS_VALUES],
            )
        )
    return summaries


def render_readiness_page(catalog: Catalog, report: ReadinessReport) -> str:
    by_group: dict[str, list[RequirementResult]] = {}
    order: list[str] = []
    for req in report.requirements:
        by_group.setdefault(req.group, []).append(req)
        if req.group not in order:
            order.append(req.group)
    groups = [(gid, catalog.group_title(gid), by_group[gid]) for gid in order]
    return _render(
        "readiness.md.j2",
        catalog=catalog,
        report=report,
        disclaimer=DISCLAIMER,
        summaries=_group_summaries(catalog, report),
        groups=groups,
        status_labels=STATUS_LABELS,
        status_label=_title_case,
        is_iso=catalog.id == ISO_CATALOG_ID,
    )


def render_soa_page(report: ReadinessReport, soa: list[SoAEntry]) -> str:
    return _render("soa.md.j2", report=report, soa=soa, status_label=_title_case)


# --- forecast page -----------------------------------------------------------------------


@dataclass(frozen=True)
class ForecastParams:
    source: str
    column: str
    discount: float
    warmup: int
    horizon: float
    threshold: int | None


def render_forecast_page(
    history: list[tuple[str, int]],
    forecast: Forecast,
    trend: TrendTest,
    backtest: BacktestResult,
    params: ForecastParams,
) -> str:
    return _render(
        "forecast.md.j2",
        history=history,
        forecast=forecast,
        trend=trend,
        backtest=backtest,
        params=params,
    )


# --- orchestration -------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportPaths:
    """Where the report's files were written, relative to the output directory."""

    readme: Path
    risks: dict[str, Path]
    readiness: dict[str, Path]
    soa: Path
    charts_dir: Path


def write_report(analysis: RegisterAnalysis, out_dir: Path, register_dir: str) -> ReportPaths:
    """Render every Markdown file and chart of the report set into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = out_dir / "charts"

    placements = []
    for sid, run in analysis.runs.items():
        cur = run.result.states[CURRENT].banded
        qual = run.result.qualitative.current if run.result.qualitative else None
        placements.append(
            charts.MatrixPlacement(
                scenario_id=sid,
                likelihood=cur.likelihood,
                impact=cur.impact,
                qualitative_likelihood=qual.likelihood if qual else None,
                qualitative_impact=qual.impact if qual else None,
            )
        )
    charts.risk_matrix(analysis.methodology, placements, charts_dir / "risk-matrix.png")
    charts.ale_by_scenario(analysis, charts_dir / "ale-by-scenario.png")
    charts.portfolio_lec(analysis.portfolio, analysis.methodology.currency, charts_dir / "portfolio-lec.png")

    controls = analysis.register.control_map()
    risk_paths: dict[str, Path] = {}
    for sid, run in analysis.runs.items():
        charts.scenario_lec(run.result, charts_dir / f"{sid}-lec.png")
        charts.tornado(run.result, charts_dir / f"{sid}-tornado.png")
        text = render_risk_page(
            run.result,
            controls,
            lec_chart=f"../charts/{sid}-lec.png",
            tornado_chart=f"../charts/{sid}-tornado.png",
            register_dir=register_dir,
        )
        risk_path = out_dir / "risks" / f"{sid}.md"
        _write(risk_path, text)
        risk_paths[sid] = risk_path

    readiness_paths: dict[str, Path] = {}
    for catalog_id, report in analysis.readiness.items():
        catalog = analysis.catalogs[catalog_id]
        text = render_readiness_page(catalog, report)
        path = out_dir / "readiness" / f"{catalog_id}.md"
        _write(path, text)
        readiness_paths[catalog_id] = path

    soa_text = render_soa_page(analysis.readiness[ISO_CATALOG_ID], analysis.soa)
    soa_path = out_dir / "readiness" / "soa-iso27001_2022.md"
    _write(soa_path, soa_text)

    readme_text = render_readme(analysis)
    readme_path = out_dir / "README.md"
    _write(readme_path, readme_text)

    return ReportPaths(
        readme=readme_path,
        risks=risk_paths,
        readiness=readiness_paths,
        soa=soa_path,
        charts_dir=charts_dir,
    )
