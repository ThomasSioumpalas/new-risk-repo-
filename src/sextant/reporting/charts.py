"""Deterministic, colour-blind-safe charts for the report.

Matplotlib is used with the non-interactive ``Agg`` backend. Every chart is
saved at a fixed DPI with the ``Software`` PNG metadata tag cleared, so that
running the report twice on the same inputs produces byte-identical images.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator

from sextant.domain.methodology import Methodology
from sextant.engine.assessment import QuantitativeAssessment
from sextant.engine.explain import input_label, money
from sextant.engine.portfolio import PortfolioResult
from sextant.reporting.pipeline import RegisterAnalysis

# Deterministic rendering: no hostname/timestamp-derived hash salt, fixed DPI.
plt.rcParams["svg.hashsalt"] = "sextant"
DPI = 120
_PNG_METADATA = {"Software": None}

# Okabe-Ito colour-blind-safe palette.
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
GRID_COLOR = "#D9D9D9"
TEXT_COLOR = "#222222"

STATE_ORDER = ["inherent", "current", "target"]
STATE_COLOR = {"inherent": "#D55E00", "current": "#0072B2", "target": "#009E73"}


def _style_axes(ax: Any) -> None:
    ax.set_facecolor("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#888888")
    ax.spines["bottom"].set_color("#888888")
    ax.grid(True, which="major", axis="both", color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.title.set_color(TEXT_COLOR)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)


def _money_formatter(currency: str) -> FuncFormatter:
    return FuncFormatter(lambda value, _pos: money(float(value), currency))


def _save(fig: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white", metadata=dict(_PNG_METADATA))
    plt.close(fig)
    return path


def scenario_lec(result: QuantitativeAssessment, path: Path) -> Path:
    """Loss-exceedance curves P(annual loss >= x) for every state of a scenario."""
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    _style_axes(ax)
    for i, name in enumerate([n for n in STATE_ORDER if n in result.states]):
        state = result.states[name]
        xs = [pt[0] for pt in state.stats.lec]
        ys = [pt[1] for pt in state.stats.lec]
        ax.plot(
            xs,
            ys,
            label=f"{state.label} (ALE {money(state.stats.ale, result.currency)})",
            color=STATE_COLOR.get(name, PALETTE[i % len(PALETTE)]),
            linewidth=2,
        )
    ax.set_xscale("log")
    ax.set_xlabel(f"Annual loss ({result.currency})")
    ax.set_ylabel("P(annual loss ≥ x)")
    ax.set_ylim(0, 1)
    ax.xaxis.set_major_formatter(_money_formatter(result.currency))
    ax.set_title(f"{result.scenario_id}: loss-exceedance curve", fontsize=11, loc="left")
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    fig.tight_layout()
    return _save(fig, path)


def tornado(result: QuantitativeAssessment, path: Path, top: int = 8) -> Path:
    """Horizontal tornado chart: ALE at each input's P10 and P90, around the current ALE."""
    bars = result.tornado[:top]
    baseline = result.states["current"].stats.ale
    fig, ax = plt.subplots(figsize=(7.5, max(3.0, 0.5 * len(bars) + 1.0)))
    _style_axes(ax)
    labels = [input_label(b.input) for b in bars][::-1]
    los = [min(b.ale_at_low, b.ale_at_high) for b in bars][::-1]
    his = [max(b.ale_at_low, b.ale_at_high) for b in bars][::-1]
    directions = [b.ale_at_high >= b.ale_at_low for b in bars][::-1]
    y = np.arange(len(bars))
    for yi, lo, hi, up in zip(y, los, his, directions, strict=True):
        color = PALETTE[0] if up else PALETTE[1]
        ax.barh(yi, hi - lo, left=lo, height=0.6, color=color, zorder=3)
    ax.axvline(baseline, color=TEXT_COLOR, linewidth=1.2, linestyle="--", zorder=4)
    ax.text(
        baseline,
        1.01,
        f"baseline ALE {money(baseline, result.currency)}",
        transform=ax.get_xaxis_transform(),
        fontsize=8,
        color=TEXT_COLOR,
        ha="center",
        va="bottom",
    )
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel(f"Current-state ALE if the input is at its P10 / P90 ({result.currency})")
    ax.xaxis.set_major_formatter(_money_formatter(result.currency))
    ax.xaxis.set_major_locator(MaxNLocator(6))
    ax.set_title(f"{result.scenario_id}: sensitivity (tornado)", fontsize=11, loc="left", pad=16)
    fig.tight_layout()
    return _save(fig, path)


def portfolio_lec(portfolio: PortfolioResult, currency: str, path: Path) -> Path:
    """Portfolio loss-exceedance curve plus the appetite tolerance-curve points."""
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    _style_axes(ax)
    xs = [pt[0] for pt in portfolio.lec]
    ys = [pt[1] for pt in portfolio.lec]
    ax.plot(
        xs, ys, color=PALETTE[0], linewidth=2, label=f"Portfolio LEC (ALE {money(portfolio.ale, currency)})"
    )
    tol_x = [c.loss for c in portfolio.tolerance]
    tol_y = [c.max_probability for c in portfolio.tolerance]
    status_color = {"within": PALETTE[2], "borderline": PALETTE[4], "exceeds": PALETTE[1]}
    ax.step(
        tol_x, tol_y, where="post", color="#555555", linewidth=1.2, linestyle=":", label="Appetite tolerance"
    )
    for check in portfolio.tolerance:
        ax.scatter(
            [check.loss],
            [check.max_probability],
            color=status_color.get(check.status, "#555555"),
            s=36,
            zorder=5,
            edgecolor="white",
            linewidth=0.6,
        )
    ax.set_xscale("log")
    ax.set_xlabel(f"Annual loss ({currency})")
    ax.set_ylabel("P(annual loss ≥ x)")
    ax.set_ylim(0, 1)
    ax.xaxis.set_major_formatter(_money_formatter(currency))
    ax.set_title("Portfolio loss-exceedance vs. tolerance", fontsize=11, loc="left")
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    fig.tight_layout()
    return _save(fig, path)


@dataclass(frozen=True)
class MatrixPlacement:
    """Where one scenario sits on the 5x5 risk matrix."""

    scenario_id: str
    likelihood: int
    impact: int
    qualitative_likelihood: int | None = None
    qualitative_impact: int | None = None


def risk_matrix(methodology: Methodology, placements: Sequence[MatrixPlacement], path: Path) -> Path:
    """5x5 heat map: rows are likelihood 1..5 (bottom to top), columns impact 1..5."""
    levels = methodology.risk_levels
    rank = {name: i for i, name in enumerate(levels)}
    n = max(len(levels) - 1, 1)
    cmap = plt.get_cmap("RdYlGn_r")

    fig, ax = plt.subplots(figsize=(6.2, 6.0))
    for li in range(5):
        for ii in range(5):
            level = methodology.matrix[li][ii]
            color = cmap(rank[level] / n)
            ax.add_patch(Rectangle((ii, li), 1, 1, facecolor=color, edgecolor="white", linewidth=1.5))

    # Scenario IDs sit in the upper part of their cell, and qualitative-rating markers
    # in the lower part, so the two never overlap even when they land in the same cell.
    by_cell: dict[tuple[int, int], list[str]] = {}
    for p in placements:
        by_cell.setdefault((p.likelihood, p.impact), []).append(p.scenario_id)
    for (lk, im), ids in by_cell.items():
        ax.text(
            im - 0.5,
            lk - 0.28,
            "\n".join(ids),
            ha="center",
            va="top",
            fontsize=8,
            color="black",
            fontweight="bold",
        )
    for p in placements:
        if p.qualitative_likelihood is not None and p.qualitative_impact is not None:
            ax.scatter(
                [p.qualitative_impact - 0.5],
                [p.qualitative_likelihood - 0.78],
                s=110,
                facecolors="none",
                edgecolors="black",
                linewidths=1.4,
                marker="o",
                zorder=5,
            )

    ax.set_xlim(0, 5)
    ax.set_ylim(0, 5)
    ax.set_xticks([i + 0.5 for i in range(5)])
    ax.set_xticklabels(
        [methodology.impact_scale[i].name for i in range(5)], fontsize=8, rotation=20, ha="right"
    )
    ax.set_yticks([i + 0.5 for i in range(5)])
    ax.set_yticklabels([methodology.likelihood_scale[i].name for i in range(5)], fontsize=8)
    ax.set_xlabel("Impact")
    ax.set_ylabel("Likelihood")
    ax.set_title(
        "Risk matrix: scenario IDs at their current quantitative cell\n"
        "(hollow circle = qualitative rating, where given)",
        fontsize=10,
        loc="left",
    )
    fig.tight_layout()
    return _save(fig, path)


def ale_by_scenario(analysis: RegisterAnalysis, path: Path) -> Path:
    """Horizontal bars of current ALE with 90% credible interval and the appetite threshold."""
    rows = sorted(analysis.runs.values(), key=lambda r: r.result.states["current"].stats.ale)
    currency = analysis.methodology.currency
    threshold = analysis.methodology.appetite.scenario_ale_threshold
    fig, ax = plt.subplots(figsize=(7.5, max(3.0, 0.45 * len(rows) + 1.0)))
    _style_axes(ax)
    y = np.arange(len(rows))
    ale = [r.result.states["current"].stats.ale for r in rows]
    lo = [r.result.states["current"].stats.ale_credible_interval_90[0] for r in rows]
    hi = [r.result.states["current"].stats.ale_credible_interval_90[1] for r in rows]
    err_lo = [max(0.0, a - lo_) for a, lo_ in zip(ale, lo, strict=True)]
    err_hi = [max(0.0, hi_ - a) for a, hi_ in zip(ale, hi, strict=True)]
    colors = [PALETTE[1] if not r.result.evaluation.within_appetite else PALETTE[0] for r in rows]
    ax.barh(y, ale, color=colors, height=0.6, zorder=3)
    ax.errorbar(
        ale, y, xerr=[err_lo, err_hi], fmt="none", ecolor="#333333", elinewidth=1.2, capsize=3, zorder=4
    )
    ax.axvline(threshold, color=TEXT_COLOR, linewidth=1.2, linestyle="--", zorder=4)
    ax.text(
        threshold,
        len(rows) - 0.4 if rows else 0,
        f" appetite {money(threshold, currency)}",
        fontsize=8,
        color=TEXT_COLOR,
        va="bottom",
    )
    ax.set_yticks(y)
    ax.set_yticklabels([r.result.scenario_id for r in rows], fontsize=8)
    ax.set_xscale("log")
    # Bars start at 0, which log scale cannot show; clip the visible range instead of
    # letting matplotlib try (and fail) to autoscale down to zero.
    positive = [v for v in [*lo, *ale, threshold] if v > 0]
    if positive:
        ax.set_xlim(min(positive) * 0.5, max([*hi, threshold]) * 1.6)
    ax.set_xlabel(f"Current ALE, 90% credible interval ({currency})")
    ax.xaxis.set_major_formatter(_money_formatter(currency))
    ax.set_title(
        "Current ALE by scenario (blue = within appetite, orange = outside)", fontsize=11, loc="left"
    )
    fig.tight_layout()
    return _save(fig, path)
