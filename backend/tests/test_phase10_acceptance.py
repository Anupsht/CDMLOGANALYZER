"""Phase 10 — final acceptance & performance.

Runs P2600N, P2800N and P2600L through the complete chain as an
authenticated TECHNICIAN:

    Upload → Parse → Normalize → Correlate → Analyze → Display → Report

plus a coarse performance smoke (per-stage wall-clock ceilings, generous
enough to stay deterministic on shared CI hardware).
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ACCEPTANCE = [
    # (fixture dir, model code, expected >= transactions)
    ("p2600n", "P2600N", 3),
    ("p2800n_hw", "P2800N", 3),
    ("p2600l", "P2600L", 3),
]


def _login(client, username="technician", password="Tech#12345") -> dict:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _zip_fixture(dirname: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in sorted((FIXTURES / dirname).iterdir()):
            if f.is_file() and not f.name.endswith(".md"):
                zf.writestr(f"{dirname}/{f.name}", f.read_bytes())
    return buf.getvalue()


def _full_chain(client, headers: dict, dirname: str, model: str, min_txns: int, serial: str):
    t0 = time.monotonic()
    machine = client.post(
        "/api/machines",
        headers=headers,
        json={"serial_number": serial, "model_code": model},
    )
    assert machine.status_code == 201, machine.text

    upload = client.post(
        "/api/logs/upload",
        headers=headers,
        files={"file": (f"{dirname}.zip", _zip_fixture(dirname), "application/zip")},
        data={"model_code": model, "machine_id": machine.json()["id"]},
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]

    # pipeline runs synchronously in tests (CDM_TASK_EAGER) — verify completion
    status = client.get(f"/api/logs/{file_id}/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["status"] == "COMPLETED", status.json()

    parse_time = time.monotonic() - t0
    assert parse_time < 15, f"pipeline too slow: {parse_time:.1f}s"

    # ---- display: list + detail + timeline (normalization/correlation output)
    listed = client.get("/api/transactions", headers=headers, params={"model_code": model})
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) >= min_txns, f"{model}: expected ≥{min_txns} transactions"
    txn = items[0]

    detail = client.get(f"/api/transactions/{txn['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["transaction_id"]

    timeline = client.get(f"/api/transactions/{txn['id']}/timeline", headers=headers)
    assert timeline.status_code == 200
    assert len(timeline.json()["entries"]) > 0

    diagnostics = client.get(f"/api/transactions/{txn['id']}/diagnostics", headers=headers)
    assert diagnostics.status_code == 200

    # ---- analyze (AI explanation layer over deterministic results)
    analysis = client.post(f"/api/transactions/{txn['id']}/ai-explanation", headers=headers)
    assert analysis.status_code == 201, analysis.text

    # ---- report: PDF + Excel
    pdf = client.get(f"/api/transactions/{txn['id']}/report.pdf", headers=headers)
    assert pdf.status_code == 200
    assert pdf.content[:5] == b"%PDF-"
    xlsx = client.get(f"/api/transactions/{txn['id']}/report.xlsx", headers=headers)
    assert xlsx.status_code == 200
    assert xlsx.content[:2] == b"PK"

    total = time.monotonic() - t0
    return total


@pytest.mark.parametrize("dirname,model,min_txns", ACCEPTANCE)
def test_acceptance_full_chain_per_model(auth_client, dirname, model, min_txns):
    headers = _login(auth_client)
    elapsed = _full_chain(
        auth_client, headers, dirname, model, min_txns, serial=f"ACC-{model}-001"
    )
    assert elapsed < 30, f"{model} full chain too slow: {elapsed:.1f}s"


def test_acceptance_supervisor_can_generate_reports(auth_client):
    headers = _login(auth_client, "supervisor", "Super#12345")
    listed = auth_client.get("/api/transactions", headers=headers)
    if listed.json()["total"] == 0:
        pytest.skip("no transactions seeded by earlier acceptance tests")
    txn = listed.json()["items"][0]
    resp = auth_client.get(f"/api/transactions/{txn['id']}/report.pdf", headers=headers)
    assert resp.status_code == 200


def test_performance_analytics_and_dashboard(auth_client):
    """Coarse regression smoke: aggregates stay responsive on the test corpus."""
    # seed an upload as technician, then measure analyst reads
    tech = _login(auth_client)
    auth_client.post(
        "/api/logs/upload",
        headers=tech,
        files={"file": ("perf.zip", _zip_fixture("p2600l"), "application/zip")},
        data={"model_code": "P2600L"},
    )
    headers = _login(auth_client, "analyst", "Analyst#12345")
    t0 = time.monotonic()
    resp = auth_client.get("/api/analytics/overview", headers=headers, params={"window_days": 90})
    overview_ms = (time.monotonic() - t0) * 1000
    assert resp.status_code == 200
    t0 = time.monotonic()
    resp = auth_client.get("/api/dashboard/summary", headers=headers)
    dashboard_ms = (time.monotonic() - t0) * 1000
    assert resp.status_code == 200
    assert overview_ms < 5000, f"analytics overview too slow: {overview_ms:.0f}ms"
    assert dashboard_ms < 5000, f"dashboard too slow: {dashboard_ms:.0f}ms"


def test_performance_repeated_timeline_queries(auth_client):
    headers = _login(auth_client)
    listed = auth_client.get("/api/transactions", headers=headers)
    if listed.json()["total"] == 0:
        pytest.skip("no transactions available")
    txn = listed.json()["items"][0]
    t0 = time.monotonic()
    for _ in range(10):
        resp = auth_client.get(f"/api/transactions/{txn['id']}/timeline", headers=headers)
        assert resp.status_code == 200
    avg_ms = (time.monotonic() - t0) * 1000 / 10
    assert avg_ms < 500, f"timeline avg too slow: {avg_ms:.0f}ms"
