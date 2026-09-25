"""Sextant command-line interface.

A thin layer over the engine, reporting pipeline and compliance modules: it
parses arguments, calls the library functions, and formats the result for a
terminal or a file. No risk mathematics lives here.
"""

from __future__ import annotations

import csv as csv_module
import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from sextant import ENGINE_VERSION
from sextant.cli.admin import db_app, users_app
from sextant.clock import utc_today
from sextant.compliance.catalog import all_catalogs, load_catalog
from sextant.compliance.readiness import assess_readiness
from sextant.domain.methodology import Methodology
from sextant.domain.register import RiskRegister, load_register
from sextant.engine.assessment import QuantitativeAssessment, run_assessment
from sextant.engine.bayes import beta_binomial_update, clopper_pearson_upper
from sextant.engine.forecasting import backtest as run_backtest
from sextant.engine.forecasting import forecast_counts, poisson_trend_test
from sextant.engine.model import CURRENT
from sextant.reporting.markdown import ForecastParams, render_forecast_page, write_report
from sextant.reporting.pipeline import analyse_register

app = typer.Typer(
    name="sextant",
    help=(
        "Sextant: a quantitative, auditable information-security risk register. "
        "Load a risk register, run FAIR-aligned Monte Carlo assessments, check compliance "
        "readiness, forecast KRIs, and generate a full Markdown report."
    ),
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
app.add_typer(db_app, name="db")
app.add_typer(users_app, name="users")

# A fixed, generous width: tables (scenario ids, currency amounts, credible intervals)
# must never be silently truncated, in the terminal or when output is captured/piped.
console = Console(width=110)
error_console = Console(stderr=True, width=110)

RegisterDirArg = Annotated[
    Path,
    typer.Argument(exists=True, file_okay=False, readable=True, help="Path to a register directory."),
]
AsOfOption = Annotated[
    str | None,
    typer.Option("--as-of", help="Assessment date, YYYY-MM-DD. Defaults to today."),
]
TrialsOption = Annotated[
    int | None,
    typer.Option("--trials", min=100, help="Monte Carlo trials per scenario. Defaults to the methodology."),
]
SeedOption = Annotated[
    int | None,
    typer.Option("--seed", help="Random seed. Defaults to the methodology's seed."),
]


def _parse_as_of(value: str | None) -> date:
    if value is None:
        return utc_today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        error_console.print(f"[red]Invalid --as-of date '{value}': expected YYYY-MM-DD.[/red]")
        raise typer.Exit(code=1) from exc


def _load_register_or_exit(register_dir: Path) -> tuple[RiskRegister, Methodology]:
    try:
        return load_register(register_dir)
    except (ValidationError, ValueError, OSError) as exc:
        error_console.print(f"[red]Register validation failed for {register_dir}:[/red]")
        error_console.print(str(exc))
        raise typer.Exit(code=1) from None


@app.command()
def validate(register_dir: RegisterDirArg) -> None:
    """Load and validate a register directory, then print a summary."""
    register, methodology = _load_register_or_exit(register_dir)
    console.print(f"[green]OK[/green] {register_dir} validated successfully.")
    table = Table(show_header=False, box=None)
    table.add_row("Assets", str(len(register.assets)))
    table.add_row("Controls", str(len(register.controls)))
    table.add_row("Evidence", str(len(register.evidence)))
    table.add_row("Scenarios", str(len(register.scenarios)))
    table.add_row("Exclusions", str(len(register.exclusions)))
    table.add_row("Methodology", f"{methodology.id} v{methodology.version}")
    table.add_row("Methodology fingerprint", methodology.fingerprint)
    console.print(table)


def _appetite_mark(result: QuantitativeAssessment) -> str:
    return "[green]✅[/green]" if result.evaluation.within_appetite else "[red]❌[/red]"


@app.command()
def assess(
    register_dir: RegisterDirArg,
    scenario: Annotated[str | None, typer.Option("--scenario", help="Assess only this scenario id.")] = None,
    trials: TrialsOption = None,
    seed: SeedOption = None,
    as_of: AsOfOption = None,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Write the full results as JSON to this path.")
    ] = None,
) -> None:
    """Run a quantitative assessment for one or every scenario and print a summary table."""
    register, methodology = _load_register_or_exit(register_dir)
    as_of_date = _parse_as_of(as_of)
    if scenario is not None:
        try:
            scenarios = [register.scenario(scenario)]
        except KeyError:
            error_console.print(f"[red]Unknown scenario '{scenario}'.[/red]")
            raise typer.Exit(code=1) from None
    else:
        scenarios = list(register.scenarios)

    controls = register.control_map()
    results = [
        run_assessment(s, controls, methodology, as_of_date, trials=trials, seed=seed).result
        for s in scenarios
    ]

    table = Table(title=f"Assessment as of {as_of_date.isoformat()}")
    for col in ("ID", "Level", "ALE", "90% CI", "VaR 95%", "Within appetite"):
        table.add_column(col, no_wrap=True)
    for r in results:
        s = r.states[CURRENT].stats
        table.add_row(
            r.scenario_id,
            r.states[CURRENT].banded.risk_level,
            f"{r.currency} {s.ale:,.0f}",
            f"{s.ale_credible_interval_90[0]:,.0f}–{s.ale_credible_interval_90[1]:,.0f}",
            f"{r.currency} {s.var_95:,.0f}",
            _appetite_mark(r),
        )
    console.print(table)

    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps([r.model_dump(mode="json") for r in results], indent=2), encoding="utf-8"
        )
        console.print(f"Wrote {len(results)} result(s) to {json_out}")


@app.command()
def report(
    register_dir: RegisterDirArg,
    out: Annotated[Path, typer.Option("--out", help="Output directory for the report.")],
    as_of: AsOfOption = None,
    trials: TrialsOption = None,
    seed: SeedOption = None,
) -> None:
    """Generate the full Markdown report set (README, per-risk pages, readiness, SoA, charts)."""
    register, methodology = _load_register_or_exit(register_dir)
    as_of_date = _parse_as_of(as_of)
    analysis = analyse_register(register, methodology, as_of_date, trials=trials, seed=seed)
    paths = write_report(analysis, out, str(register_dir))
    console.print(f"[green]Report written to {out}[/green]")
    console.print(f"  {paths.readme}")
    console.print(f"  {len(paths.risks)} risk page(s) in {out / 'risks'}")
    console.print(f"  {len(paths.readiness)} readiness page(s) in {out / 'readiness'}")
    console.print(f"  {paths.soa}")
    console.print(f"  charts in {paths.charts_dir}")


@app.command()
def readiness(
    register_dir: RegisterDirArg,
    framework: Annotated[str, typer.Option("--framework", help="Catalog id, e.g. iso27001_2022.")],
    as_of: AsOfOption = None,
) -> None:
    """Assess compliance readiness against one catalog and print status counts and indicators."""
    register, methodology = _load_register_or_exit(register_dir)
    as_of_date = _parse_as_of(as_of)
    try:
        catalog = load_catalog(framework)
    except KeyError as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    rpt = assess_readiness(
        catalog,
        register.controls,
        register.evidence_map(),
        methodology.control_testing,
        as_of_date,
        register.exclusions,
        register.scenarios,
    )
    console.print(f"[bold]{rpt.framework_name}[/bold] as of {rpt.as_of.isoformat()}")
    console.print(f"Applicable requirements: {rpt.applicable}")
    console.print(f"Readiness indicator (addressed / applicable): {rpt.readiness_indicator:.1%}")
    console.print(f"Coverage indicator: {rpt.coverage_indicator:.1%}")
    table = Table(title="Status counts")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for status, count in rpt.counts.items():
        table.add_row(status.replace("_", " ").title(), str(count))
    console.print(table)


def _read_csv_column(csv_path: Path, column: str) -> tuple[list[str], list[int]]:
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv_module.DictReader(fh)
        if reader.fieldnames is None or column not in reader.fieldnames:
            raise typer.BadParameter(f"column '{column}' not found in {csv_path}")
        period_field = reader.fieldnames[0]
        periods: list[str] = []
        counts: list[int] = []
        for row in reader:
            periods.append(row[period_field])
            counts.append(int(row[column]))
    return periods, counts


@app.command()
def forecast(
    csv: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="CSV file with period counts.")],
    column: Annotated[str, typer.Option("--column", help="Column of period counts to forecast.")],
    discount: Annotated[
        float, typer.Option("--discount", min=0.0, max=1.0, help="Exponential-forgetting discount factor.")
    ] = 1.0,
    threshold: Annotated[
        int | None, typer.Option("--threshold", help="Report P(next-period count > threshold).")
    ] = None,
    warmup: Annotated[int, typer.Option("--warmup", help="Backtest warm-up periods.")] = 12,
    out: Annotated[Path | None, typer.Option("--out", help="Write forecast/<column>.md here.")] = None,
) -> None:
    """Forecast a KRI/incident-count CSV: predictive interval, trend test and backtest."""
    try:
        periods, counts = _read_csv_column(csv, column)
    except typer.BadParameter as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    f = forecast_counts(counts, discount=discount, threshold=threshold)
    trend = poisson_trend_test(counts)
    bt = run_backtest(counts, warmup=warmup, discount=discount)

    console.print(f"[bold]Forecast for '{column}'[/bold] ({len(counts)} periods, discount {discount})")
    console.print(f"Posterior mean rate: {f.rate_mean:.3f} per period (90% CI {f.rate_interval_90})")
    console.print(f"Next-period predictive mean: {f.predictive_mean:.2f}")
    console.print(f"  50% interval: {f.predictive_interval_50}, 90% interval: {f.predictive_interval_90}")
    if f.prob_exceed_threshold is not None:
        console.print(f"  P(count > {threshold}) = {f.prob_exceed_threshold:.1%}")
    console.print(trend.interpretation)
    console.print(
        f"Backtest ({bt.periods_evaluated} periods): 50% coverage {bt.coverage_50:.1%}, "
        f"90% coverage {bt.coverage_90:.1%} (nominal 50%/90%)"
    )

    if out is not None:
        history = list(zip(periods, counts, strict=True))
        params = ForecastParams(
            source=str(csv),
            column=column,
            discount=discount,
            warmup=warmup,
            horizon=f.horizon,
            threshold=threshold,
        )
        text = render_forecast_page(history, f, trend, bt, params)
        path = out / "forecast" / f"{column}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        console.print(f"[green]Wrote {path}[/green]")


def _min_bayes_samples(tdr: float, confidence: float, exceptions: int = 0, limit: int = 5000) -> int | None:
    """Minimal ``n`` (with ``exceptions`` deviations observed) for a Bayesian-uniform 'effective' call."""
    for n in range(max(1, exceptions), limit + 1):
        post = beta_binomial_update(n - exceptions, n, 1.0, 1.0)
        if post.prob_above(1.0 - tdr) >= confidence:
            return n
    return None


def _min_classical_samples(
    tdr: float, confidence: float, exceptions: int = 0, limit: int = 5000
) -> int | None:
    """Minimal ``n`` for the classical (Clopper-Pearson) upper bound to fall at or below the TDR."""
    for n in range(max(1, exceptions), limit + 1):
        if clopper_pearson_upper(exceptions, n, confidence) <= tdr:
            return n
    return None


@app.command(name="sample-size")
def sample_size(
    tdr: Annotated[float, typer.Option("--tdr", min=0.0, max=1.0, help="Tolerable deviation rate.")] = 0.10,
    confidence: Annotated[
        float, typer.Option("--confidence", min=0.5, max=1.0, help="Required confidence.")
    ] = 0.90,
    expected_exceptions: Annotated[
        int, typer.Option("--expected-exceptions", min=0, help="Deviations expected in the sample.")
    ] = 0,
) -> None:
    """Minimal attribute-sample size for an 'effective' conclusion (Bayesian-uniform and classical)."""
    bayes_n = _min_bayes_samples(tdr, confidence, expected_exceptions)
    classical_n = _min_classical_samples(tdr, confidence, expected_exceptions)
    console.print(
        f"Tolerable deviation rate {tdr:.0%}, required confidence {confidence:.0%}, "
        f"{expected_exceptions} expected exception(s):"
    )
    console.print(
        f"  Bayesian (uniform prior): [bold]{bayes_n}[/bold] samples → P(deviation rate ≤ {tdr:.0%}) "
        f"≥ {confidence:.0%}"
    )
    console.print(
        f"  Classical (Clopper-Pearson): [bold]{classical_n}[/bold] samples → "
        f"{confidence:.0%} upper bound on the deviation rate ≤ {tdr:.0%}"
    )
    console.print(
        "With a uniform Beta(1,1) prior and zero exceptions, the classical rule "
        "(1-tdr)^n ≤ 1-confidence and the Bayesian posterior P(deviation ≤ tdr) ≥ confidence "
        "agree closely; they diverge as more exceptions are expected."
    )


@app.command(name="control-test")
def control_test(
    samples: Annotated[int, typer.Option("--samples", min=1, help="Samples inspected.")],
    exceptions: Annotated[int, typer.Option("--exceptions", min=0, help="Exceptions found.")],
    tdr: Annotated[float, typer.Option("--tdr", min=0.0, max=1.0, help="Tolerable deviation rate.")] = 0.10,
    confidence: Annotated[
        float, typer.Option("--confidence", min=0.5, max=1.0, help="Required confidence.")
    ] = 0.90,
) -> None:
    """Evaluate one control test result (mirrors the conclusion logic in sextant.engine.controls)."""
    if exceptions > samples:
        error_console.print("[red]exceptions cannot exceed samples[/red]")
        raise typer.Exit(code=1)
    post = beta_binomial_update(samples - exceptions, samples, 1.0, 1.0)
    p_within = post.prob_above(1.0 - tdr)
    if p_within >= confidence:
        conclusion = "effective"
    elif (1.0 - p_within) >= confidence:
        conclusion = "not_effective"
    else:
        conclusion = "inconclusive"
    cp_upper = clopper_pearson_upper(exceptions, samples, confidence)

    console.print(f"{exceptions} exception(s) in {samples} sample(s).")
    console.print(f"Posterior mean operating rate: {post.mean:.1%} (90% interval {post.interval(0.90)})")
    console.print(f"P(deviation rate ≤ {tdr:.0%}) = {p_within:.1%} (required {confidence:.0%})")
    console.print(f"Classical {confidence:.0%} upper bound on the deviation rate: {cp_upper:.1%}")
    console.print(f"Conclusion: [bold]{conclusion}[/bold]")
    if conclusion == "inconclusive":
        extra = _min_bayes_samples(tdr, confidence, exceptions)
        if extra is not None:
            console.print(f"About {extra - samples} more exception-free samples would reach 'effective'.")


@app.command()
def catalogs() -> None:
    """List the compliance catalogs shipped with Sextant."""
    console.print("[bold]Compliance catalogs[/bold]")
    for cid, cat in all_catalogs().items():
        console.print(
            f"  [bold]{cid}[/bold] — {cat.name} "
            f"({len(cat.requirements)} requirements, text policy: {cat.text_policy.value})"
        )
        console.print(f"    License: {cat.license}")
    console.print(f"Engine version: {ENGINE_VERSION}")


if __name__ == "__main__":
    app()
