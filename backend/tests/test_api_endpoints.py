"""API endpoint tests: logs, models, machines, health, error envelopes."""

from __future__ import annotations


# ---- health ---------------------------------------------------------------


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_details(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["queue"] == "eager"
    assert body["version"]


def test_request_id_header_present(client):
    resp = client.get("/healthz")
    assert resp.headers.get("X-Request-ID")


# ---- models -----------------------------------------------------------------


def test_list_models(client):
    body = client.get("/api/models").json()
    codes = {m["code"] for m in body}
    assert {"P2600N", "P2800N", "P2600L"} <= codes
    p26 = next(m for m in body if m["code"] == "P2600N")
    assert p26["is_active"] is True
    assert p26["name"] == "GRG P2600N"


def test_get_model_by_code(client):
    body = client.get("/api/models/P2800N").json()
    assert body["code"] == "P2800N"
    # Phase 3: P2800N has its own source set (not P2600N terminology).
    assert {"app", "ifm", "jrn", "siu"}.issubset(set(body["supported_sources"]))
    assert "ecat" not in body["supported_sources"]


def test_get_unknown_model_404_envelope(client):
    resp = client.get("/api/models/NOPE999")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "stack" not in resp.text.lower()
    assert body["request_id"]


def test_model_enable_disable_flow(client):
    resp = client.post("/api/models/P2600N/disable")
    assert resp.status_code == 200
    assert resp.json() == {"model_code": "P2600N", "enabled": False}

    assert client.get("/api/models/P2600N").json()["is_active"] is False

    resp = client.post("/api/models/P2600N/enable")
    assert resp.json()["enabled"] is True


# ---- machines -----------------------------------------------------------------


def test_create_and_get_machine(client):
    resp = client.post(
        "/api/machines",
        json={
            "serial_number": "GRG-P2600N-000123",
            "model_code": "P2600N",
            "location": "Mall A, Floor 2",
            "status": "active",
        },
    )
    assert resp.status_code == 201, resp.text
    machine = resp.json()
    assert machine["machine_model"]["code"] == "P2600N"

    fetched = client.get(f"/api/machines/{machine['id']}").json()
    assert fetched["serial_number"] == "GRG-P2600N-000123"


def test_duplicate_serial_rejected(client):
    payload = {"serial_number": "GRG-DUP-1", "model_code": "P2600N"}
    assert client.post("/api/machines", json=payload).status_code == 201
    resp = client.post("/api/machines", json=payload)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "duplicate_resource"


def test_machine_with_unknown_model_422(client):
    resp = client.post("/api/machines", json={"serial_number": "SN-1", "model_code": "XXXX"})
    assert resp.status_code == 422


def test_list_machines(client):
    client.post("/api/machines", json={"serial_number": "SN-A"})
    client.post("/api/machines", json={"serial_number": "SN-B"})
    body = client.get("/api/machines").json()
    assert body["total"] == 2
    assert {m["serial_number"] for m in body["items"]} == {"SN-A", "SN-B"}


# ---- logs -----------------------------------------------------------------------


def test_get_unknown_log_404(client):
    resp = client.get("/api/logs/nonexistent-id")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_list_logs_filters(client, upload_txt):
    ok = upload_txt("ok.log", b"data")
    resp = client.get("/api/logs", params={"status": "COMPLETED"})
    assert resp.json()["total"] >= 1
    resp = client.get("/api/logs", params={"status": "FAILED"})
    assert resp.json()["total"] == 0
    resp = client.get("/api/logs", params={"machine_id": "nope"})
    assert resp.json()["total"] == 0
    _ = ok


def test_status_endpoint_shape_for_zip(client):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ecat.log", b"2026-02-01 10:00:00 INFO x\n")
    buf.seek(0)
    upload = client.post("/api/logs/upload", files={"file": ("logs.zip", buf, "application/zip")}).json()

    status = client.get(f"/api/logs/{upload['id']}/status").json()
    assert status["status"] in {"COMPLETED", "PARTIAL"}
    assert len(status["files"]) == 1
    assert status["files"][0]["status"] == "COMPLETED"
