from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

from sextant.domain.controls import Control
from sextant.domain.methodology import Methodology, default_methodology
from sextant.domain.scenario import Scenario

AS_OF = date(2026, 9, 1)


@pytest.fixture(scope="session")
def methodology() -> Methodology:
    return default_methodology()


@pytest.fixture
def as_of() -> date:
    return AS_OF


def make_control(cid: str, status: str = "implemented", tests: list[dict[str, Any]] | None = None) -> Control:
    return Control.model_validate(
        {
            "id": cid,
            "name": f"Control {cid}",
            "description": "test control",
            "type": "preventive",
            "owner": "Owner",
            "status": status,
            "tests": tests or [],
        }
    )


def operating_test(samples: int, exceptions: int, on: str = "2026-06-01") -> dict[str, Any]:
    return {
        "kind": "operating",
        "performed_on": on,
        "performed_by": "Internal Audit",
        "procedure": "inspection of samples",
        "samples": samples,
        "exceptions": exceptions,
    }


@pytest.fixture
def library() -> dict[str, Control]:
    controls = [
        make_control("CTL-MFA", tests=[operating_test(40, 0)]),
        make_control("CTL-BKP"),
        make_control("CTL-EDR", status="planned"),
    ]
    return {c.id: c for c in controls}


def scenario_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "RSK-T01",
        "title": "Ransomware on ERP",
        "description": "Test scenario",
        "category": "malware_ransomware",
        "owner": "COO",
        "assets": ["ERP"],
        "threat": {"source_type": "adversarial", "source": "Crime group", "event": "Ransomware deployment"},
        "vulnerabilities": ["Flat network"],
        "properties": ["availability"],
        "threat_event_frequency": {"dist": "lognormal", "low": 0.5, "high": 6},
        "susceptibility": {"dist": "pert", "min": 0.05, "mode": 0.2, "max": 0.5},
        "primary_losses": [
            {
                "name": "outage",
                "form": "productivity",
                "magnitude": {"dist": "lognormal", "low": 2e5, "high": 5e6},
            },
            {
                "name": "ir",
                "form": "response",
                "magnitude": {"dist": "pert", "min": 5e4, "mode": 1.5e5, "max": 6e5},
            },
        ],
        "secondary_loss": {
            "probability": {"dist": "pert", "min": 0.1, "mode": 0.3, "max": 0.6},
            "components": [
                {
                    "name": "fine",
                    "form": "fines_judgments",
                    "magnitude": {"dist": "lognormal", "low": 1e5, "high": 3e6},
                }
            ],
        },
        "controls": [
            {
                "control_id": "CTL-MFA",
                "target": "susceptibility",
                "reduction": {"dist": "pert", "min": 0.5, "mode": 0.8, "max": 0.95},
                "coverage": 0.85,
                "rationale": "MFA blocks credential reuse for initial access",
            },
            {
                "control_id": "CTL-BKP",
                "target": "primary_loss",
                "loss_forms": ["productivity"],
                "reduction": {"dist": "pert", "min": 0.3, "mode": 0.6, "max": 0.8},
                "rationale": "Immutable backups shorten the outage",
            },
        ],
        "treatments": [
            {
                "id": "T1",
                "title": "Deploy EDR",
                "type": "modify",
                "description": "EDR on all servers",
                "add_controls": [
                    {
                        "control_id": "CTL-EDR",
                        "target": "susceptibility",
                        "reduction": {"dist": "pert", "min": 0.3, "mode": 0.5, "max": 0.7},
                        "operating_rate": {"dist": "pert", "min": 0.85, "mode": 0.95, "max": 0.99},
                        "rationale": "EDR blocks encryption behaviour",
                    }
                ],
                "annual_cost": 80000,
            },
            {
                "id": "T2",
                "title": "Cyber insurance",
                "type": "share",
                "description": "Per-occurrence policy",
                "insurance": {"deductible": 250000, "limit": 5000000},
                "annual_cost": 60000,
            },
        ],
        "selected_treatment": "T1",
    }
    data.update(overrides)
    return data


@pytest.fixture
def scenario_factory() -> Callable[..., Scenario]:
    def factory(**overrides: Any) -> Scenario:
        return Scenario.model_validate(scenario_data(**overrides))

    return factory


@pytest.fixture
def scenario(scenario_factory: Callable[..., Scenario]) -> Scenario:
    return scenario_factory()
