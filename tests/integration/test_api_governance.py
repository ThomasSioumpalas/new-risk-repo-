"""End-to-end governance behaviour through the HTTP API and a migrated database."""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from sextant.clock import utc_today
from sextant.db.session import make_engine
from tests.integration.conftest import Api

TRIALS = {"trials": 2000, "seed": 7, "as_of": "2026-09-01"}
JUSTIFICATION = "Within appetite after review; compensating monitoring is in place and owners agree."


def _assess(api: Api, risk_id: str, user: str = "ana") -> dict[str, Any]:
    r = api.post(user, f"/api/v1/risks/{risk_id}/assessments", TRIALS)
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def _final(api: Api, risk_id: str, user: str = "ana") -> dict[str, Any]:
    a = _assess(api, risk_id, user)
    r = api.post(user, f"/api/v1/assessments/{a['id']}/finalize")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_health_and_authentication(api: Api) -> None:
    assert api.client.get("/health").json() == {"status": "ok"}
    unauth = api.client.get("/api/v1/risks")
    assert unauth.status_code == 401
    assert unauth.json()["error"] == "unauthenticated"
    assert api.client.get("/api/v1/risks", headers={"X-API-Key": "sxt_wrong"}).status_code == 401
    r = api.get("vera", "/api/v1/risks")
    assert r.status_code == 200
    assert len(r.json()) == 8
    assert r.headers["X-Request-ID"]
    me = api.get("adam", "/api/v1/me").json()
    assert "accept_risk" not in me["permissions"]  # admin has no business-decision rights


def test_role_based_access(api: Api) -> None:
    risk = api.get("ana", "/api/v1/risks/RSK-003").json()
    assert (
        api.put(
            "vera", "/api/v1/risks/RSK-003", {"version": risk["version"], "scenario": risk["scenario"]}
        ).status_code
        == 403
    )
    assert api.post("colin", "/api/v1/risks/RSK-003/assessments", TRIALS).status_code == 403
    assert api.get("vera", "/api/v1/audit").status_code == 403
    assert api.get("audrey", "/api/v1/audit").status_code == 200


def test_optimistic_concurrency(api: Api) -> None:
    risk = api.get("ana", "/api/v1/risks/RSK-003").json()
    scenario = risk["scenario"] | {"owner": "Chief People Officer"}
    assert (
        api.put(
            "ana", "/api/v1/risks/RSK-003", {"version": risk["version"], "scenario": scenario}
        ).status_code
        == 200
    )
    stale = api.put("andy", "/api/v1/risks/RSK-003", {"version": risk["version"], "scenario": scenario})
    assert stale.status_code == 409


def test_assessment_lifecycle_override_and_immutability(api: Api) -> None:
    a = _assess(api, "RSK-001")
    assert a["status"] == "draft"
    # Overrides need the right role and a real justification.
    body = {"level": "High", "justification": "Threat intelligence indicates active targeting of our sector."}
    assert api.post("ana", f"/api/v1/assessments/{a['id']}/override", body).status_code == 403
    assert (
        api.post(
            "mira", f"/api/v1/assessments/{a['id']}/override", body | {"justification": "short"}
        ).status_code
        == 422
    )
    r = api.post("mira", f"/api/v1/assessments/{a['id']}/override", body)
    assert r.status_code == 200
    assert r.json()["effective_level"] == "High"
    assert r.json()["computed_level"] != "High" or r.json()["override_level"] == "High"

    assert api.post("ana", f"/api/v1/assessments/{a['id']}/finalize").status_code == 200
    assert api.post("ana", f"/api/v1/assessments/{a['id']}/finalize").status_code == 409
    assert api.post("mira", f"/api/v1/assessments/{a['id']}/override", body).status_code == 409

    detail = api.get("vera", f"/api/v1/assessments/{a['id']}").json()
    assert detail["result"]["explanation"]["headline"].startswith("RSK-001")
    assert api.get("vera", "/api/v1/risks/RSK-001").json()["next_review_due"] is not None

    # The database itself refuses to alter a finalised assessment.
    engine = make_engine(api.url)
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(sa.text("UPDATE assessments SET computed_level='Very Low' WHERE id=:i"), {"i": a["id"]})


def test_reproduction_by_auditor(api: Api) -> None:
    a = _final(api, "RSK-004")
    r = api.post("audrey", f"/api/v1/assessments/{a['id']}/reproduce")
    assert r.status_code == 200
    assert r.json()["reproduced"] is True
    assert r.json()["recomputed_result_fingerprint"] == a["result_fingerprint"]


def test_acceptance_requires_authority_and_segregation(api: Api) -> None:
    # RSK-006 is outside appetite (ALE above threshold) → executive authority required.
    a = _final(api, "RSK-006", user="mira")
    req = {"assessment_id": a["id"], "justification": JUSTIFICATION}
    denied = api.post("olga", "/api/v1/risks/RSK-006/acceptances", req)
    assert denied.status_code == 403
    assert "executive" in denied.json()["message"]
    # The risk manager prepared the assessment: segregation of duties forbids self-acceptance.
    sod = api.post("mira", "/api/v1/risks/RSK-006/acceptances", req)
    assert sod.status_code == 403
    assert "segregation" in sod.json()["message"]
    ok = api.post("eve", "/api/v1/risks/RSK-006/acceptances", req)
    assert ok.status_code == 201, ok.text
    assert ok.json()["required_authority"] == "executive"
    assert ok.json()["effective_status"] == "active"


def test_acceptance_is_time_limited_and_invalidated_by_higher_level(api: Api) -> None:
    a = _final(api, "RSK-003")
    acc = api.post(
        "olga",
        "/api/v1/risks/RSK-003/acceptances",
        {"assessment_id": a["id"], "justification": JUSTIFICATION, "duration_days": 5000},
    )
    assert acc.status_code == 201, acc.text
    from datetime import date

    days = (date.fromisoformat(acc.json()["expires_on"]) - utc_today()).days
    assert days <= 730  # capped at the methodology maximum for the level

    # A new assessment that raises the level invalidates the acceptance automatically.
    b = _assess(api, "RSK-003")
    api.post(
        "mira",
        f"/api/v1/assessments/{b['id']}/override",
        {"level": "High", "justification": "New provider breach reported; exposure re-evaluated upward."},
    )
    assert api.post("ana", f"/api/v1/assessments/{b['id']}/finalize").status_code == 200
    accs = api.get("vera", "/api/v1/risks/RSK-003/acceptances").json()
    assert accs[0]["status"] == "invalidated"
    # And an acceptance must reference the latest final assessment.
    stale = api.post(
        "eve", "/api/v1/risks/RSK-003/acceptances", {"assessment_id": a["id"], "justification": JUSTIFICATION}
    )
    assert stale.status_code == 409


def test_treatment_approval(api: Api) -> None:
    a = _final(api, "RSK-008")
    bad = api.post(
        "olga",
        "/api/v1/risks/RSK-008/treatment-approvals",
        {"assessment_id": a["id"], "option_id": "NOPE", "comment": "approve"},
    )
    assert bad.status_code == 422
    ok = api.post(
        "olga",
        "/api/v1/risks/RSK-008/treatment-approvals",
        {"assessment_id": a["id"], "option_id": "T1", "comment": "Approved; deliver in Q4."},
    )
    assert ok.status_code == 201
    assert api.get("vera", "/api/v1/risks/RSK-008").json()["status"] == "treatment_planned"


def test_control_tests_are_append_only(api: Api) -> None:
    test = {
        "kind": "operating",
        "performed_on": "2026-08-30",
        "performed_by": "Colin",
        "procedure": "sample",
        "samples": 10,
        "exceptions": 0,
    }
    r = api.post("colin", "/api/v1/controls/CTL-TPR-01/tests", test)
    assert r.status_code == 201
    assert r.json()["samples"] == 30  # 20 earlier + 10 new within the look-back window
    control = api.get("ana", "/api/v1/controls/CTL-TPR-01").json()
    control["tests"] = control["tests"][:1]
    assert api.put("ana", "/api/v1/controls/CTL-TPR-01", control).status_code == 409


def test_audit_chain_detects_tampering(api: Api) -> None:
    _final(api, "RSK-002")
    ok = api.get("audrey", "/api/v1/audit/verify").json()
    assert ok["ok"] is True
    assert ok["entries"] > 10
    engine = make_engine(api.url)
    # Triggers block ordinary updates...
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(sa.text("UPDATE audit_log SET actor='mallory' WHERE seq=3"))
    # ...so a tamperer with DBA rights drops the trigger first. The hash chain still exposes it.
    drop = (
        "DROP TRIGGER audit_log_append_only ON audit_log"
        if engine.dialect.name == "postgresql"
        else "DROP TRIGGER audit_log_no_update"
    )
    with engine.begin() as conn:
        conn.execute(sa.text(drop))
        conn.execute(sa.text("UPDATE audit_log SET actor='mallory' WHERE seq=3"))
    broken = api.get("audrey", "/api/v1/audit/verify").json()
    assert broken["ok"] is False
    assert broken["first_invalid_seq"] == 3


def test_analysis_and_compliance_endpoints(api: Api) -> None:
    risk = api.get("ana", "/api/v1/risks/RSK-001").json()
    stress = [{"name": "TEF x3", "description": "Campaign surge", "tef_multiplier": 3.0}]
    r = api.post(
        "vera",
        "/api/v1/analysis/what-if",
        {"scenario": risk["scenario"], "stress_tests": stress, "trials": 2000, "as_of": "2026-09-01"},
    )
    assert r.status_code == 200
    assert r.json()["stress_tests"][0]["ale_change_pct"] > 1.0
    too_big = api.post(
        "vera", "/api/v1/analysis/what-if", {"scenario": risk["scenario"], "trials": 10_000_000}
    )
    assert too_big.status_code == 422

    rd = api.get("vera", "/api/v1/compliance/readiness/nis2_2022_2555").json()
    assert "NOT an audit opinion" in rd["disclaimer"]
    assert len(api.get("vera", "/api/v1/compliance/soa").json()) == 93
    assert api.get("vera", "/api/v1/compliance/readiness/unknown").status_code == 422

    items = api.get("vera", "/api/v1/monitoring").json()
    assert any(i["kind"] == "not_assessed" for i in items)

    _final(api, "RSK-004")
    _final(api, "RSK-007")
    port = api.get("vera", "/api/v1/analysis/portfolio", params={"trials": 2000})
    assert port.status_code == 200
    assert {s["scenario_id"] for s in port.json()["shares"]} == {"RSK-004", "RSK-007"}


def test_resource_limits_on_what_if(api: Api) -> None:
    scenario = api.get("ana", "/api/v1/risks/RSK-001").json()["scenario"]
    huge = scenario | {"threat_event_frequency": {"dist": "constant", "value": 100000}}
    r = api.post("vera", "/api/v1/analysis/what-if", {"scenario": huge, "trials": 20000})
    assert r.status_code == 422
    assert r.json()["error"] == "simulation_too_large"
    many = scenario | {"primary_losses": scenario["primary_losses"] * 5}
    assert api.post("vera", "/api/v1/analysis/what-if", {"scenario": many}).status_code == 422
