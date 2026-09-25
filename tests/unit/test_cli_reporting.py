"""End-to-end tests for the CLI and the reporting pipeline against the example register.

Trials are kept small (2,000) so the whole file runs quickly; determinism and correctness
of the *statistics* are already covered by the engine's own unit tests.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sextant.cli.main import app

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "halcyon"
KRI_CSV = EXAMPLE / "data" / "kri_phishing_bypass.csv"
TRIALS = "2000"
AS_OF = "2026-09-01"

runner = CliRunner()


def test_validate_succeeds_on_example_register() -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLE)])
    assert result.exit_code == 0, result.output
    assert "Scenarios" in result.output
    assert "8" in result.output


def test_validate_reports_a_readable_error_on_a_broken_register(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    shutil.copytree(EXAMPLE, broken)
    scenario_path = broken / "scenarios" / "rsk-001-ransomware.yaml"
    data = yaml.safe_load(scenario_path.read_text("utf-8"))
    data["assets"] = ["AST-DOES-NOT-EXIST"]
    scenario_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    result = runner.invoke(app, ["validate", str(broken)])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "unknown asset" in result.output


def test_assess_json_produces_eight_results(tmp_path: Path) -> None:
    out = tmp_path / "assess.json"
    result = runner.invoke(
        app,
        ["assess", str(EXAMPLE), "--trials", TRIALS, "--seed", "1", "--as-of", AS_OF, "--json", str(out)],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text("utf-8"))
    assert len(data) == 8
    assert {r["scenario_id"] for r in data} == {f"RSK-{i:03d}" for i in range(1, 9)}
    assert "ALE" in result.output or "Level" in result.output


def test_assess_single_scenario(tmp_path: Path) -> None:
    out = tmp_path / "one.json"
    result = runner.invoke(
        app,
        [
            "assess",
            str(EXAMPLE),
            "--scenario",
            "RSK-001",
            "--trials",
            TRIALS,
            "--as-of",
            AS_OF,
            "--json",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text("utf-8"))
    assert len(data) == 1
    assert data[0]["scenario_id"] == "RSK-001"


def test_report_creates_expected_files_and_charts(tmp_path: Path) -> None:
    out = tmp_path / "report"
    result = runner.invoke(
        app, ["report", str(EXAMPLE), "--out", str(out), "--trials", TRIALS, "--seed", "1", "--as-of", AS_OF]
    )
    assert result.exit_code == 0, result.output
    assert (out / "README.md").is_file()
    assert (out / "risks" / "RSK-001.md").is_file()
    assert (out / "readiness" / "iso27001_2022.md").is_file()
    assert (out / "readiness" / "soa-iso27001_2022.md").is_file()
    assert (out / "charts" / "risk-matrix.png").is_file()
    assert (out / "charts" / "portfolio-lec.png").is_file()
    assert (out / "charts" / "ale-by-scenario.png").is_file()
    assert (out / "charts" / "RSK-001-lec.png").is_file()
    assert (out / "charts" / "RSK-001-tornado.png").is_file()
    # A PNG file, not an empty placeholder.
    assert (out / "charts" / "risk-matrix.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_report_is_deterministic(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    args = ["report", str(EXAMPLE), "--trials", TRIALS, "--seed", "1", "--as-of", AS_OF]
    result_a = runner.invoke(app, [*args, "--out", str(out_a)])
    result_b = runner.invoke(app, [*args, "--out", str(out_b)])
    assert result_a.exit_code == 0, result_a.output
    assert result_b.exit_code == 0, result_b.output
    assert (out_a / "README.md").read_bytes() == (out_b / "README.md").read_bytes()
    assert (out_a / "risks" / "RSK-006.md").read_bytes() == (out_b / "risks" / "RSK-006.md").read_bytes()


def test_readiness_prints_indicators() -> None:
    result = runner.invoke(
        app, ["readiness", str(EXAMPLE), "--framework", "nis2_2022_2555", "--as-of", AS_OF]
    )
    assert result.exit_code == 0, result.output
    assert "Readiness indicator" in result.output
    assert "Coverage indicator" in result.output
    assert "%" in result.output


def test_readiness_rejects_unknown_framework() -> None:
    result = runner.invoke(app, ["readiness", str(EXAMPLE), "--framework", "not_a_catalog"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_control_test_effective_at_bayesian_threshold() -> None:
    result = runner.invoke(
        app, ["control-test", "--samples", "21", "--exceptions", "0", "--tdr", "0.10", "--confidence", "0.90"]
    )
    assert result.exit_code == 0, result.output
    assert "effective" in result.output.lower()
    assert "not effective" not in result.output.lower()
    assert "inconclusive" not in result.output.lower()


def test_control_test_rejects_more_exceptions_than_samples() -> None:
    result = runner.invoke(app, ["control-test", "--samples", "5", "--exceptions", "6"])
    assert result.exit_code != 0


def test_sample_size_matches_bayesian_and_classical_plans() -> None:
    result = runner.invoke(app, ["sample-size", "--tdr", "0.10", "--confidence", "0.90"])
    assert result.exit_code == 0, result.output
    assert "21" in result.output
    assert "22" in result.output


def test_catalogs_lists_all_four_frameworks() -> None:
    result = runner.invoke(app, ["catalogs"])
    assert result.exit_code == 0, result.output
    for cid in ("iso27001_2022", "nist_csf_2_0", "nis2_2022_2555", "nist_ai_rmf_1_0"):
        assert cid in result.output


def test_forecast_on_kri_csv(tmp_path: Path) -> None:
    out = tmp_path / "forecast_out"
    result = runner.invoke(
        app,
        [
            "forecast",
            str(KRI_CSV),
            "--column",
            "reported_phishing_bypassing_filter",
            "--discount",
            "0.9",
            "--threshold",
            "20",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Predictive" in result.output or "predictive" in result.output
    report_path = out / "forecast" / "reported_phishing_bypassing_filter.md"
    assert report_path.is_file()
    text = report_path.read_text("utf-8")
    assert "Trend test" in text
    assert "Backtest" in text
    assert "How to read this" in text


@pytest.mark.parametrize("bad_column", ["does_not_exist"])
def test_forecast_rejects_unknown_column(bad_column: str) -> None:
    result = runner.invoke(app, ["forecast", str(KRI_CSV), "--column", bad_column])
    assert result.exit_code != 0
