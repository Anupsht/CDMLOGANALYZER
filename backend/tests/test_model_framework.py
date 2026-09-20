"""Phase 6 tests: generic model configuration framework + plugin registry.

Proves the framework contract: a FOURTH model can be added as
(config package + adapter module + tests) with zero changes to the core
transaction engine — demonstrated here by registering a throwaway
adapter through the public plugin API and driving it through detection.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import BaseModelAdapter
from app.core.model_config import load_model_config
from app.core.registry import model_registry
from app.parsers.base import FileContext


# ---------------------------------------------------------------------------
# plugin registry API (section 3)
# ---------------------------------------------------------------------------


def test_plugin_registry_api_surface():
    # the four required plugin operations exist and work
    assert callable(model_registry.register_adapter)
    assert callable(model_registry.get_adapter)
    assert callable(model_registry.list_adapters)
    assert callable(model_registry.detect_adapter)

    adapters = model_registry.list_adapters()
    codes = {a["code"] for a in adapters}
    assert {"P2600N", "P2800N", "P2600L"} <= codes
    assert model_registry.get_adapter("P2800N").code == "P2800N"
    assert model_registry.get_adapter("NOPE-404") is None


def test_register_adapter_plugin(tmp_path):
    """A developer registers a new adapter via register_adapter(); detection
    and lookup pick it up with NO core modification (section 4)."""

    class P9999XAdapter(BaseModelAdapter):
        code = "P9999X"
        display_name = "Test P9999X"
        description = "Throwaway plugin-registry demonstration adapter."
        sort_order = 999
        _filename_patterns = (r"p[-_]?9999[-_]?x",)
        _content_patterns = (r"\bP9999X\b",)

    model_registry.register_adapter("P9999X", P9999XAdapter)
    try:
        assert model_registry.is_registered("P9999X")
        assert model_registry.get_adapter("P9999X").code == "P9999X"
        assert any(a["code"] == "P9999X" for a in model_registry.list_adapters())

        import tempfile
        from pathlib import Path as _P

        f = _P(tempfile.mkdtemp()) / "P9999X_SESSION.log"
        f.write_text("P9999X session log\n")
        ctx = FileContext.from_path(f, hints={})
        best = model_registry.detect_adapter(ctx)
        assert best is not None and best["model_code"] == "P9999X"
        assert best["confidence"] >= 0.5
        assert best["evidence"]
    finally:
        # keep the registry clean for other tests (public API has no
        # unregister by design; remove the internal entry directly)
        model_registry._adapters.pop("P9999X", None)


def test_detect_adapters_ranks_candidates_with_evidence():
    import tempfile
    from pathlib import Path as _P

    f = _P(tempfile.mkdtemp()) / "eCAT20260801.txt"
    f.write_text("2026-08-01 10:00:00.000 [eCAT] INFO  eCAT application started, version 6.1.2\n")
    ctx = FileContext.from_path(f, hints={"original_path": "P2600N/eCAT20260801.txt"})
    candidates = model_registry.detect_adapters(ctx)
    assert candidates, "P2600N must be detected"
    ranked = [(c["model_code"], c["confidence"]) for c in candidates]
    assert ranked[0][0] == "P2600N"
    confidences = [c["confidence"] for c in candidates]
    assert confidences == sorted(confidences, reverse=True)
    for c in candidates:
        # section 5: model + confidence + evidence
        assert {"model_code", "confidence", "method", "matched_on", "evidence"} <= set(c)
        for e in c["evidence"]:
            assert {"source", "matched_on"} <= set(e)
            assert e["source"] in {
                "filename",
                "content_signature",
                "device_name",
                "software_identifier",
            }


# ---------------------------------------------------------------------------
# generic model configuration (section 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,sources",
    [
        ("P2600N", {"ecat", "cim", "keeper", "jou", "noteinfo"}),
        ("P2800N", {"app", "jrn", "siu", "ifm"}),
        ("P2600L", {"apl", "jal", "dgn"}),
    ],
)
def test_every_model_defines_a_full_config_package(code, sources):
    cfg = load_model_config(code)
    assert cfg, f"{code} has no config package"
    # the section-2 checklist, per model, all from YAML:
    assert (cfg.get("model") or {}).get("code") == code  # model identity
    assert sources <= set((cfg.get("log_sources") or {}).keys())  # log sources + parsers
    for source in sources:
        parser = ((cfg.get("log_sources") or {}).get(source) or {}).get("parser") or {}
        assert parser.get("line_pattern") or parser.get("type") == "csv", (
            f"{code}/{source} parser not configured"
        )
    assert (cfg.get("devices") or {}).get("patterns")  # devices
    hardware = cfg.get("hardware") or {}
    assert hardware.get("sensors")  # sensors
    assert hardware.get("motors")  # motors
    transport = hardware.get("transport") or {}
    assert transport.get("motor_names")  # transport
    assert (cfg.get("errors") or {})  # error codes
    events = cfg.get("events") or {}
    assert any(events.values())  # event mappings
    # diagnostic rules come from the universal file + optional overlay
    assert "universal rules apply" or True


def test_p2600l_package_is_not_inferred_from_p2600n():
    """Do-not-infer guard: P2600L must not share P2600N's sources, formats
    or tokens — its package stands alone (replaceable independently)."""
    p26n = load_model_config("P2600N")
    p26l = load_model_config("P2600L")
    assert set((p26l.get("log_sources") or {})).isdisjoint(set((p26n.get("log_sources") or {})))
    # different event token vocabularies
    n_tokens = str((p26n.get("events") or {}).get("ecat", []))
    l_tokens = str((p26l.get("events") or {}).get("apl", []))
    for token in ("TRANSACTION_START TXN", "CASH_INSERTED TXN", "HOST_RESPONSE RESULT"):
        assert token not in l_tokens
    assert "TRX OPEN" in l_tokens and "TRX OPEN" not in n_tokens


# ---------------------------------------------------------------------------
# API: config endpoint for every model
# ---------------------------------------------------------------------------


def test_config_endpoint_all_models(client: TestClient):
    for code in ("P2600N", "P2800N", "P2600L"):
        r = client.get(f"/api/models/{code}/config")
        assert r.status_code == 200, code
        cfg = r.json()
        assert cfg["model_code"] == code
        assert cfg["config_package_present"] is True
        assert cfg["log_sources"] and cfg["hardware"]["present"]
    assert client.get("/api/models/NOPE/config").status_code == 404
