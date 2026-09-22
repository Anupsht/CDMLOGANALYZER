"""Machine model registry endpoints (registry-driven, never hard-coded)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.rbac import require_permission
from app.core.registry import model_registry
from app.services.audit_service import audit_service
from app.schemas.machine import MachineModelOut
from app.schemas.model import ModelToggleResponse
from app.services.machine_service import machine_service

router = APIRouter(
    prefix="/models", tags=["models"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=list[MachineModelOut])
def list_models(session: Session = Depends(get_db)) -> list[MachineModelOut]:
    """All registered machine models (adapter registry + DB state)."""
    entries = machine_service.list_models(session)
    return [MachineModelOut(**entry) for entry in entries]


@router.get("/{model_code}/config")
def get_model_config(model_code: str) -> dict:
    """Effective model configuration package (Phase 6, read-only).

    Proves the generic configuration mechanism: every model is defined by
    its YAML package (identity, log sources, parsers, devices, hardware,
    error codes, event mappings, diagnostics) — the core engine reads this
    data and contains no model-specific logic.
    """
    adapter = model_registry.get_adapter(model_code)
    if adapter is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"Machine model not found: {model_code}")

    cfg = adapter.model_config
    model_cfg = cfg.get("model") or {}
    log_sources = cfg.get("log_sources") or {}
    events = cfg.get("events") or {}
    errors = cfg.get("errors") or {}
    hardware = cfg.get("hardware") or {}
    devices = (cfg.get("devices") or {}).get("patterns") or []
    diagnostics = cfg.get("diagnostics") or {}
    # Universal diagnostic rules (config/diagnostics/rules.yaml) apply to
    # every model; the model package only overlays/adds.
    from app.analysis.diagnostics import DiagnosticConfig

    universal_cfg = DiagnosticConfig.load(None)
    model_rule_ids = {r.get("id") for r in (diagnostics.get("rules") or []) if r.get("id")}
    has_package = bool(cfg)

    return {
        "model_code": adapter.code,
        "display_name": adapter.display_name,
        "enabled": model_registry.is_enabled(adapter.code),
        "placeholder": adapter.is_placeholder,
        "config_package_present": has_package,
        "identity": {
            "code": model_cfg.get("code", adapter.code),
            "display_name": model_cfg.get("display_name", adapter.display_name),
            "vendor": model_cfg.get("vendor", adapter.vendor),
        },
        "detection": {
            "filename_patterns": list(adapter._filename_patterns),
            "content_signatures": list(adapter._content_patterns),
            "software_identifiers": (model_cfg.get("detection") or {}).get(
                "software_identifiers", []
            ),
        },
        "log_sources": [
            {
                "source": source,
                "name": (spec or {}).get("name"),
                "parser": ((spec or {}).get("parser") or {}).get("code"),
                "filename_patterns": (spec or {}).get("filename_patterns", []),
            }
            for source, spec in sorted(log_sources.items())
        ],
        "devices": [
            {"pattern": d.get("pattern"), "device": d.get("device")} for d in devices
        ],
        "hardware": {
            "present": bool(hardware),
            "sensors": len(hardware.get("sensors") or []),
            "motors": len(hardware.get("motors") or []),
            "gates": bool(hardware.get("gates")),
            "shutters": bool(hardware.get("shutters")),
            "transport": bool(hardware.get("transport")),
            "temporal_window": hardware.get("temporal_analysis") or {},
        },
        "event_mappings": {
            source: len(rules or []) for source, rules in sorted(events.items())
        },
        "error_patterns": {
            source: len(rules or []) for source, rules in sorted(errors.items())
        },
        "correlation": model_cfg.get("correlation") or {},
        "diagnostics": {
            "rules": [r.id for r in universal_cfg.rules if r.id not in model_rule_ids]
            + [r.get("id") for r in (diagnostics.get("rules") or []) if r.get("id")],
            "requirements": [
                r.get("id") for r in (diagnostics.get("requirements") or []) if r.get("id")
            ],
            "reconciliation_checks": sorted(
                ((diagnostics.get("reconciliation") or {}).get("checks") or {}).keys()
            ),
        },
    }


@router.get("/{model_id}", response_model=MachineModelOut)
def get_model(model_id: str, session: Session = Depends(get_db)) -> MachineModelOut:
    """Model detail; ``{model_id}`` is the model code (e.g. ``P2600N``)."""
    for entry in machine_service.list_models(session):
        if entry["code"].upper() == model_id.upper():
            return MachineModelOut(**entry)
    from app.core.errors import NotFoundError

    raise NotFoundError(f"Machine model not found: {model_id}")


@router.post(
    "/{model_id}/enable",
    response_model=ModelToggleResponse,
    dependencies=[Depends(require_permission("models:write"))],
)
def enable_model(model_id: str, session: Session = Depends(get_db)) -> ModelToggleResponse:
    result = model_registry.enable_model(model_id, session)
    session.commit()
    audit_service.record(
        session,
        action="model.configuration_changed",
        entity_type="machine_model",
        entity_id=model_id,
        detail={"change": "enable"},
    )
    session.commit()
    return ModelToggleResponse(**result)


@router.post(
    "/{model_id}/disable",
    response_model=ModelToggleResponse,
    dependencies=[Depends(require_permission("models:write"))],
)
def disable_model(model_id: str, session: Session = Depends(get_db)) -> ModelToggleResponse:
    result = model_registry.disable_model(model_id, session)
    session.commit()
    audit_service.record(
        session,
        action="model.configuration_changed",
        entity_type="machine_model",
        entity_id=model_id,
        detail={"change": "disable"},
    )
    session.commit()
    return ModelToggleResponse(**result)
