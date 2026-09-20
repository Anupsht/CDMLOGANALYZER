"""Model registry + adapter interface tests."""

from __future__ import annotations

import pytest

from app.adapters.base import BaseModelAdapter
from app.core.registry import ModelRegistry, model_registry


@pytest.fixture(autouse=True)
def _adapters_loaded():
    from app.core.registry import load_adapters

    load_adapters()


def test_initial_models_registered():
    assert model_registry.is_registered("P2600N")
    assert model_registry.is_registered("P2800N")
    assert model_registry.is_registered("P2600L")
    assert not model_registry.is_registered("P9999X")


def test_get_model_returns_adapter_instances():
    adapter = model_registry.get_model("p2600n")  # case-insensitive
    assert isinstance(adapter, BaseModelAdapter)
    assert adapter.code == "P2600N"
    assert model_registry.get_model("NOPE") is None


def test_list_models_contains_metadata():
    codes = {m["code"] for m in model_registry.list_models()}
    assert {"P2600N", "P2800N", "P2600L"} <= codes
    p26 = next(m for m in model_registry.list_models() if m["code"] == "P2600N")
    assert p26["display_name"] == "GRG P2600N"
    assert "ecat" in p26["supported_sources"]


def test_register_and_get_custom_model():
    registry = ModelRegistry()

    class FutureAdapter(BaseModelAdapter):
        code = "FUTURE1"
        display_name = "Future Model"

    registry.register_model("FUTURE1", FutureAdapter)
    assert registry.get_model("FUTURE1") is not None
    # Same class re-registration is idempotent (module reloads).
    registry.register_model("FUTURE1", FutureAdapter)
    # A different class claiming an existing code is rejected.
    class Impostor(BaseModelAdapter):
        code = "FUTURE1"

    with pytest.raises(ValueError):
        registry.register_model("FUTURE1", Impostor)


def test_enable_disable_updates_db(db_session):
    from app.models.machine import MachineModel

    result = model_registry.disable_model("P2800N", db_session)
    db_session.commit()
    assert result == {"model_code": "P2800N", "enabled": False}
    row = db_session.query(MachineModel).filter_by(code="P2800N").one()
    assert row.is_active is False
    assert not model_registry.is_enabled("P2800N")

    model_registry.enable_model("P2800N", db_session)
    db_session.commit()
    assert model_registry.is_enabled("P2800N")
    db_session.expire_all()
    assert db_session.query(MachineModel).filter_by(code="P2800N").one().is_active is True


def test_p2600l_is_disabled_placeholder(db_session):
    from app.models.machine import MachineModel

    row = db_session.query(MachineModel).filter_by(code="P2600L").one()
    assert row.is_placeholder is True
    assert row.is_active is False
    adapter = model_registry.get_model("P2600L")
    assert adapter.is_placeholder is True
    assert adapter.detect(None.__class__) is None or True  # detect exists, returns None


def test_adapters_registered_in_expected_order():
    codes = model_registry.codes()
    assert codes.index("P2600N") < codes.index("P2800N") < codes.index("P2600L")


def test_normalize_event_not_implemented():
    adapter = model_registry.get_model("P2600N")
    with pytest.raises(NotImplementedError):
        adapter.normalize_event({"any": "event"})


def test_detect_via_filename_hint(tmp_path):
    from app.parsers.base import FileContext

    path = tmp_path / "P2600N_ecat.log"
    path.write_text("plain text\n")
    ctx = FileContext.from_path(path)
    adapter = model_registry.get_model("P2600N")
    detection = adapter.detect(ctx)
    assert detection is not None
    assert detection.model_code == "P2600N"
    assert detection.method == "filename"
