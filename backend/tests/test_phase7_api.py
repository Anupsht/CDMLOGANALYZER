"""Phase 7 API tests: dashboard summary, machine health, list filters, log-line search.

Exercises the read-only aggregation + server-side filtering endpoints the
technician dashboard consumes. All fixtures are SYNTHETIC (see
tests/fixtures/README-SYNTHETIC.md). No model branches — every assertion
runs through the universal endpoints.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _zip_bytes(dirname: str) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fixture in sorted((FIXTURES / dirname).iterdir()):
            if fixture.is_file() and not fixture.name.endswith(".md"):
                zf.writestr(f"{dirname}/{fixture.name}", fixture.read_bytes())
    buf.seek(0)
    return buf


def upload_zip(client, dirname: str, model_code: str | None = None, machine_id: str | None = None):
    """Upload a fixture ZIP. model_code/machine_id are multipart form fields."""
    data = {}
    if model_code:
        data["model_code"] = model_code
    if machine_id:
        data["machine_id"] = machine_id
    return client.post(
        "/api/logs/upload",
        data=data or None,
        files={"file": (f"{dirname}.zip", _zip_bytes(dirname), "application/zip")},
    )


def _make_machine(client, serial: str, model_code: str) -> dict:
    models = client.get("/api/models").json()
    model_id = next(m["id"] for m in models if m["code"] == model_code)
    resp = client.post(
        "/api/machines",
        json={
            "serial_number": serial,
            "model_code": model_code,
            "machine_model_id": model_id,
            "location": "Test branch",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# Dashboard summary
# --------------------------------------------------------------------------- #


def test_dashboard_summary_counts_three_models(client):
    upload_zip(client, "p2600n", model_code="P2600N")
    upload_zip(client, "p2800n", model_code="P2800N")
    upload_zip(client, "p2600l", model_code="P2600L")

    data = client.get("/api/dashboard/summary").json()

    assert data["transactions"]["total"] == 9
    assert data["transactions"]["completed"] == 3
    assert data["transactions"]["declined"] == 3
    assert data["transactions"]["failed"] == 1
    assert data["transactions"]["incomplete"] == 2
    # findings are evidence-based (distinct transactions)
    assert data["findings"]["confirmed_jams"] == 1  # p2800n_hw is not uploaded; p2600l T-8803
    assert data["findings"]["host_failures"] >= 2
    codes = {m["model_code"] for m in data["models"]}
    assert codes == {"P2600N", "P2800N", "P2600L"}
    assert data["generated_at"]


def test_dashboard_summary_scope_filters(client):
    upload_zip(client, "p2600n", model_code="P2600N")
    upload_zip(client, "p2600l", model_code="P2600L")

    scoped = client.get(
        "/api/dashboard/summary", params={"model_code": "P2600L"}
    ).json()
    assert scoped["transactions"]["total"] == 3
    assert {m["model_code"] for m in scoped["models"]} == {"P2600L"}

    # date window that excludes everything
    empty = client.get(
        "/api/dashboard/summary",
        params={"date_from": "1990-01-01", "date_to": "1990-12-31"},
    ).json()
    assert empty["transactions"]["total"] == 0


def test_dashboard_summary_fleet_status(client):
    _make_machine(client, "SN-HEALTH-1", "P2600N")
    data = client.get("/api/dashboard/summary").json()
    assert data["fleet"]["total"] == 1
    # No logged activity bound to the machine yet → offline by definition.
    assert data["fleet"]["online"] == 0
    assert data["fleet"]["offline"] == 1


# --------------------------------------------------------------------------- #
# Machine health
# --------------------------------------------------------------------------- #


def test_machine_health_counters(client):
    machine = _make_machine(client, "SN-HEALTH-2", "P2600L")
    # Upload bound to the machine so transactions carry machine_id.
    resp = upload_zip(client, "p2600l", model_code="P2600L", machine_id=machine["id"])
    assert resp.status_code == 201, resp.text

    data = client.get(
        f"/api/machines/{machine['id']}/health", params={"window_days": 90}
    ).json()
    assert data["transactions_total"] == 3
    assert data["completed"] == 1 and data["declined"] == 1 and data["failed"] == 1
    assert data["failure_rate"] == round(2 / 3, 4)
    assert data["jam_transactions"] == 1  # T-8803 confirmed jam
    assert data["hardware_error_transactions"] >= 1
    assert data["model_code"] == "P2600L"
    assert data["last_activity_at"] is not None
    assert "not a diagnosis" in data["note"]

    # score is NOT computed server-side
    assert "score" not in data


def test_machine_health_unknown_machine_404(client):
    resp = client.get("/api/machines/does-not-exist/health")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Transaction list filters (server-side)
# --------------------------------------------------------------------------- #


def test_transaction_filters(client):
    upload_zip(client, "p2600n", model_code="P2600N")
    upload_zip(client, "p2600l", model_code="P2600L")

    def ids(query: dict) -> set[str]:
        body = client.get("/api/transactions", params=query).json()
        return {i["transaction_id"] for i in body["items"]}

    # status
    assert ids({"status": "DECLINED", "model_code": "P2600L"}) == {"T-8802"}
    # transaction_id substring
    assert ids({"transaction_id": "T-88"}) == {"T-8801", "T-8802", "T-8803"}
    # amount range
    assert "T-8803" not in ids({"amount_min": 100})  # 60.0 below
    assert "T-8801" in ids({"amount_min": 100, "amount_max": 100})
    # host result (universal event codes)
    declined = ids({"host_result": "declined"})
    assert "T-8802" in declined
    # cash state (universal event codes)
    assert "T-8801" in ids({"cash_state": "STORED"})
    assert ids({"cash_state": "NOT_STORED", "model_code": "P2600N"}) >= set()
    # event code
    assert "T-8803" in ids({"event_code": "JAM_DETECTED"})
    # device (device-name template with capture group → Cassette-1, jam only)
    assert ids({"device": "Cassette-1", "model_code": "P2600L"}) == {"T-8803"}
    # error code (verbatim detail search)
    assert ids({"error_code": "E-402", "model_code": "P2600L"}) == {"T-8803"}
    # date + time window
    assert "T-8801" in ids({"date_from": "2026-08-01", "date_to": "2026-08-01"})
    assert "T-8801" in ids({"time_from": "09:00", "time_to": "09:05", "model_code": "P2600L"})
    assert not ids({"time_from": "23:00", "model_code": "P2600L"})
    # sorting
    asc = client.get(
        "/api/transactions", params={"model_code": "P2600L", "sort": "amount", "dir": "asc"}
    ).json()["items"]
    amounts = [i["amount"] for i in asc]
    assert amounts == sorted(a for a in amounts if a is not None)


def test_transaction_filter_validation(client):
    resp = client.get("/api/transactions", params={"host_result": "bogus"})
    assert resp.status_code == 422
    resp = client.get("/api/transactions", params={"time_from": "9x99"})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Log line search / navigation
# --------------------------------------------------------------------------- #


def test_log_line_search_and_filters(client):
    resp = upload_zip(client, "p2600l", model_code="P2600L")
    assert resp.status_code == 201
    logs = client.get("/api/logs").json()["items"]
    apl = next(l for l in logs if l["original_filename"].endswith("APL_20260801.log"))

    logs_all = client.get("/api/logs").json()["items"]
    dgn = next(l for l in logs_all if l["original_filename"].endswith("DGN_20260801.log"))

    # search ("jam" only appears in the diagnostics log)
    hits = client.get(f"/api/logs/{dgn['id']}/lines", params={"q": "jam"}).json()
    assert hits["total"] >= 1
    assert all("jam" in i["raw_text"].lower() for i in hits["items"])

    # line window + surrounding context
    window = client.get(
        f"/api/logs/{apl['id']}/lines", params={"line_from": 2, "line_to": 4}
    ).json()
    assert [i["line_number"] for i in window["items"]] == [2, 3, 4]

    # level filter — p2800n app lines carry a real level group
    upload_zip(client, "p2800n_hw", model_code="P2800N")
    logs_all = client.get("/api/logs").json()["items"]
    app_log = next(
        l for l in logs_all
        if "APP" in l["original_filename"].upper()
        and l.get("machine_model_code") == "P2800N"
    )
    infos = client.get(f"/api/logs/{app_log['id']}/lines", params={"level": "INFO"}).json()
    assert infos["total"] >= 1
    assert all((i["level"] or "").upper() == "INFO" for i in infos["items"])
    errors = client.get(f"/api/logs/{app_log['id']}/lines", params={"level": "ERROR"}).json()
    assert errors["total"] == 0  # app log of the normal-transport fixture has none

    # timestamp navigation
    ts = client.get(f"/api/logs/{apl['id']}/lines", params={"limit": 1}).json()["items"][0][
        "timestamp"
    ]
    from_ts = client.get(
        f"/api/logs/{apl['id']}/lines", params={"ts_from": ts, "limit": 5}
    ).json()
    assert from_ts["total"] >= 1
