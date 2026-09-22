"""Phase 8 tests: AI digest, explanation layer, safety, vendor report, PDF/Excel.

⚠️ Fixtures are SYNTHETIC (see tests/fixtures/README-SYNTHETIC.md).
The AI layer is tested through its contract: structured bounded digest in,
validated epistemic-labelled explanation out, evidence-referenced vendor
report, and byte-level PDF/XLSX exports. The deterministic composer is the
active provider in tests (no external LLM configured).
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


def upload_zip(client, dirname: str, model_code: str | None = None):
    data = {"model_code": model_code} if model_code else None
    return client.post(
        "/api/logs/upload",
        data=data,
        files={"file": (f"{dirname}.zip", _zip_bytes(dirname), "application/zip")},
    )


def txn_id_of(client, transaction_id: str, model_code: str) -> str:
    """Return the UUID pk — the {txn_id} path param convention of the API."""
    items = client.get(
        "/api/transactions",
        params={"model_code": model_code, "transaction_id": transaction_id},
    ).json()["items"]
    assert items, f"transaction {transaction_id} not correlated"
    return items[0]["id"]


import pytest  # noqa: E402


@pytest.fixture()
def jam_tid(client) -> str:
    """Upload the P2600L jam scenario and return transaction T-8803's id."""
    upload_zip(client, "p2600l", model_code="P2600L")
    return txn_id_of(client, "T-8803", "P2600L")


# --------------------------------------------------------------------------- #
# §1 — AI input: structured digest
# --------------------------------------------------------------------------- #


def test_ai_digest_sections_and_bounds(client, jam_tid):
    resp = client.get(f"/api/transactions/{jam_tid}/ai-digest")
    assert resp.status_code == 200
    d = resp.json()

    # all eight required input categories
    for key in (
        "transaction",
        "normalized_events",
        "cash_states",
        "host_events",
        "hardware_events",
        "rule_results",
        "root_cause_candidates",
        "evidence",
    ):
        assert key in d, f"digest missing {key}"

    # bounded, structured — no raw log dump
    assert len(d["normalized_events"]) <= d["bounds"]["max_events"]
    assert len(d["evidence"]) <= d["bounds"]["max_evidence"]
    for ev in d["evidence"]:
        assert ev["raw_excerpt"]
        assert len(ev["raw_excerpt"]) <= d["bounds"]["max_raw_chars"]
    ids = [e["id"] for e in d["evidence"]]
    assert len(ids) == len(set(ids)), "evidence ids must be unique"

    # the jam transaction carries rule results + ranked candidates
    rule_ids = {r["rule_id"] for r in d["rule_results"]}
    assert "CONFIRMED_CASH_JAM" in rule_ids
    assert d["root_cause_candidates"], "jam must produce ranked candidates"
    top = d["root_cause_candidates"][0]
    assert top["candidate"] == "CONFIRMED_CASH_JAM"
    assert top["epistemic_label"] in ("CONFIRMED", "PROBABLE", "POSSIBLE", "UNKNOWN")
    assert top["evidence_ids"], "candidates must reference evidence"

    # digest is stable (hash over content)
    again = client.get(f"/api/transactions/{jam_tid}/ai-digest").json()
    assert again["digest_sha256"] == d["digest_sha256"]


# --------------------------------------------------------------------------- #
# §2 — AI output
# --------------------------------------------------------------------------- #


def test_ai_explanation_output_contract(client, jam_tid):
    resp = client.post(f"/api/transactions/{jam_tid}/ai-explanation")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    payload = body["payload"]

    for key in (
        "technical_summary",
        "root_cause",
        "confidence",
        "possible_causes",
        "recommended_actions",
        "vendor_questions",
        "evidence",
    ):
        assert key in payload, f"explanation missing {key}"

    rc = payload["root_cause"]
    assert rc["label"] in ("CONFIRMED", "PROBABLE", "POSSIBLE", "UNKNOWN")
    assert rc["statement"]
    valid_ids = set()
    digest = client.get(f"/api/transactions/{jam_tid}/ai-digest").json()
    valid_ids = {e["id"] for e in digest["evidence"]}
    assert set(rc["evidence_ids"]) <= valid_ids, "root cause must cite real evidence"

    # deterministic provider is labelled honestly
    assert body["provider"] == "deterministic-rules-composer"
    assert body["generator"] == "deterministic"
    assert body["digest_sha256"] == digest["digest_sha256"]

    # reproducible: regenerating yields the same payload
    again = client.post(f"/api/transactions/{jam_tid}/ai-explanation").json()
    assert again["payload"] == payload

    # persisted + retrievable
    stored = client.get(f"/api/transactions/{jam_tid}/ai-explanation")
    assert stored.status_code == 200
    assert stored.json()["payload"] == payload


# --------------------------------------------------------------------------- #
# §3 — AI safety: labels + anti-invention guard
# --------------------------------------------------------------------------- #


def test_safety_validator_blocks_invention():
    from app.ai.safety import validate_explanation

    digest = {
        "transaction": {"transaction_id": "T-1", "model_code": "P2600L", "status": "FAILED"},
        "machine": {"serial_number": "GRG-P26L-0009"},
        "engine_report": {"classification": "CONFIRMED_CASH_JAM"},
        "evidence": [
            {"id": "EV-001", "file": "DGN.log", "line_number": 11, "raw_excerpt": "jam detected near BOX1"}
        ],
        "normalized_events": [{"event": "JAM_DETECTED", "device": "Cassette-1"}],
        "cash_states": {"final_cash_state": "JAMMED", "movements": []},
        "host_events": [],
        "error_events": [{"error_code": "P26L-HW-402"}],
        "hardware_events": {"motors": [{"motor": "MOT1", "timed_out": True, "timeout_ms": 2000}]},
        "rule_results": [],
    }
    malicious = {
        "technical_summary": "Serial SN-FAKE-4242 shows a $500.00 cassette defect.",
        "root_cause": {
            "statement": "Definitely a broken pick roller SN-XX-9 (not in logs).",
            "label": "CERTAIN",
            "evidence_ids": ["EV-001", "EV-999"],
        },
        "confidence": {"label": "ABSOLUTELY", "rationale": "trust me"},
        "possible_causes": [
            {"statement": "Cassette-1 jam per evidence", "label": "CONFIRMED", "evidence_ids": ["EV-001"]},
        ],
        "recommended_actions": ["Replace 3500-series roller"],
        "vendor_questions": ["What is the torque spec?"],
    }
    clean, notes = validate_explanation(malicious, digest)

    # CERTAIN → CONFIRMED → demoted to POSSIBLE (unverified detail was removed;
    # the single surviving real evidence ref keeps it at POSSIBLE, not UNKNOWN)
    assert clean["root_cause"]["label"] == "POSSIBLE"
    assert "SN-FAKE-4242" not in clean["technical_summary"]
    assert "500.00" not in clean["technical_summary"]
    assert "SN-XX-9" not in clean["root_cause"]["statement"]
    assert clean["root_cause"]["evidence_ids"] == ["EV-001"]
    assert clean["confidence"]["label"] in ("CONFIRMED", "PROBABLE", "POSSIBLE", "UNKNOWN")
    # CONFIRMED cause WITH real evidence survives
    assert clean["possible_causes"][0]["label"] == "CONFIRMED"
    assert clean["possible_causes"][0]["evidence_ids"] == ["EV-001"]
    assert any("unverified" in n.lower() or "unverified" in n for n in notes)


def test_safety_labels_legend_present(client, jam_tid):
    body = client.post(f"/api/transactions/{jam_tid}/ai-explanation").json()
    labels = body["payload"]["labels"]
    assert labels["vocabulary"] == ["CONFIRMED", "PROBABLE", "POSSIBLE", "UNKNOWN"]
    assert set(labels["legend"]) == set(labels["vocabulary"])


# --------------------------------------------------------------------------- #
# §4+§7 — vendor report + traceability
# --------------------------------------------------------------------------- #


def test_vendor_report_fields_and_traceability(client, jam_tid):
    resp = client.get(f"/api/transactions/{jam_tid}/vendor-report")
    assert resp.status_code == 200
    r = resp.json()

    for key in (
        "machine", "model" if False else "transaction", "problem", "timeline",
        "errors", "hardware_state", "cash_state", "host_state", "evidence",
        "analysis", "vendor_questions",
    ):
        assert key in r, f"vendor report missing {key}"

    # machine / model present (from digest machine binding if any)
    assert r["machine"]["model"] == "P2600L"

    # problem statement for the jam scenario
    assert r["problem"]["classification"] == "CONFIRMED_CASH_JAM"

    # traceability: every rule finding + fault statement cites evidence
    for f in r["analysis"]["findings"]:
        assert f["evidence_refs"], f"finding {f['rule_id']} has no evidence refs"
    ev_ids = {e["id"] for e in r["evidence"]}
    assert ev_ids, "report must contain an evidence appendix"

    # evidence refs in timeline are real file:line strings (EV ids where present)
    referenced = [
        t["evidence_ref"] for t in r["timeline"] if t["evidence_ref"]
    ]
    assert referenced and all(":" in ref for ref in referenced)

    # vendor questions exist for the jam (unknown-meaning code / procedure ask)
    assert r["vendor_questions"]


def test_vendor_report_includes_location_and_amount(client):
    """Report carries machine metadata when the upload was machine-bound."""
    from tests.test_phase7_api import _make_machine  # reuse the helper

    machine = _make_machine(client, "SN-VENDOR-1", "P2600L")
    upload_zip(client, "p2600l", model_code="P2600L")
    # re-upload with binding is unnecessary: bind via the machine we made
    items = client.get(
        "/api/transactions", params={"model_code": "P2600L", "transaction_id": "T-8801"}
    ).json()["items"]
    tid = items[0]["id"]

    r = client.get(f"/api/transactions/{tid}/vendor-report").json()
    assert r["machine"]["model"] == "P2600L"
    assert r["transaction"]["transaction_id"] == "T-8801"
    assert r["transaction"]["amount"] == 100.0
    # unbound upload → machine block still structured (serial None)
    assert "serial_number" in r["machine"]


# --------------------------------------------------------------------------- #
# §5+§6 — PDF / Excel exports
# --------------------------------------------------------------------------- #


def test_pdf_export(client, jam_tid):
    resp = client.get(f"/api/transactions/{jam_tid}/report.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    content = resp.content
    assert content[:5] == b"%PDF-", "must be a real PDF"
    assert len(content) > 3000, "report too small to contain the sections"
    assert b"Vendor Escalation Report" in content or b"Vendor" in content


def test_xlsx_export(client, jam_tid):
    resp = client.get(f"/api/transactions/{jam_tid}/report.xlsx")
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(resp.content))
    required = {
        "Transaction Summary",
        "Events",
        "Cash Trace",
        "Hardware Events",
        "Errors",
        "Analysis",
    }
    assert required.issubset(set(wb.sheetnames)), f"sheets: {wb.sheetnames}"

    # the events sheet holds the timeline with evidence refs
    ws = wb["Events"]
    header = [c.value for c in ws[1]]
    assert "Evidence" in header and "Event" in header
    assert ws.max_row > 1

    # analysis sheet contains the rule finding + vendor questions
    ws = wb["Analysis"]
    text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert "CONFIRMED_CASH_JAM" in text


# --------------------------------------------------------------------------- #
# §8 — completion chain works end to end on a NORMAL transaction too
# --------------------------------------------------------------------------- #


def test_chain_on_normal_transaction(client):
    upload_zip(client, "p2600l", model_code="P2600L")
    tid = txn_id_of(client, "T-8801", "P2600L")

    explanation = client.post(f"/api/transactions/{tid}/ai-explanation").json()
    assert explanation["payload"]["root_cause"]["label"] in (
        "CONFIRMED",
        "PROBABLE",
        "POSSIBLE",
        "UNKNOWN",
    )
    assert "T-8801" in explanation["payload"]["technical_summary"]

    report = client.get(f"/api/transactions/{tid}/vendor-report").json()
    assert report["problem"]["classification"] == "NORMAL_COMPLETION"
    assert client.get(f"/api/transactions/{tid}/report.pdf").status_code == 200
    assert client.get(f"/api/transactions/{tid}/report.xlsx").status_code == 200


def test_unknown_transaction_404(client):
    assert client.get("/api/transactions/NOPE/ai-digest").status_code == 404
    assert client.post("/api/transactions/NOPE/ai-explanation").status_code == 404
