"""Model registry — dynamic registry of supported CDM machine models.

The registry decouples the core application from specific models
(P2600N / P2800N / P2600L …). Adapters self-register at import time;
enabled/disabled state is mirrored in the ``machine_models`` database
table so it survives restarts.

The core application code never hard-codes a model: it always goes
through this registry (``list_models`` / ``get_model``) or the
``machine_models`` table.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterator

from app.core.config import get_settings

if TYPE_CHECKING:  # pragma: no cover
    from app.adapters.base import BaseModelAdapter
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ModelRegistry:
    """In-process registry of :class:`BaseModelAdapter` implementations."""

    def __init__(self) -> None:
        self._adapters: dict[str, type["BaseModelAdapter"]] = {}
        self._disabled: set[str] = set()

    # ---- registration -------------------------------------------------

    def register_model(self, code: str, adapter_cls: type["BaseModelAdapter"]) -> None:
        """Register an adapter class under a model code (e.g. ``P2600N``)."""
        code = code.upper()
        existing = self._adapters.get(code)
        if existing is adapter_cls:
            return  # idempotent (module re-imports)
        if existing is not None:
            raise ValueError(f"Model code already registered: {code}")
        self._adapters[code] = adapter_cls
        logger.info(
            "Registered machine model adapter",
            extra={"operation": "registry.register", "model_code": code, "adapter": adapter_cls.__name__},
        )

    # ---- lookup ---------------------------------------------------------

    def get_model(self, code: str) -> "BaseModelAdapter | None":
        """Return an adapter instance for ``code`` (or None if unknown)."""
        adapter_cls = self._adapters.get(code.upper())
        return adapter_cls() if adapter_cls else None

    def require_model(self, code: str) -> "BaseModelAdapter":
        adapter = self.get_model(code)
        if adapter is None:
            from app.core.errors import NotFoundError

            raise NotFoundError(f"Unknown machine model: {code}")
        return adapter

    def codes(self) -> list[str]:
        """Registered codes in insertion (registration) order."""
        return list(self._adapters)

    def list_models(self) -> list[dict]:
        """Metadata for every registered model."""
        return [self.get_model(code).get_model_info() for code in self.codes()]  # type: ignore[union-attr]

    def is_registered(self, code: str) -> bool:
        return code.upper() in self._adapters

    def is_enabled(self, code: str) -> bool:
        return code.upper() not in self._disabled

    # ---- enable / disable ------------------------------------------------

    def enable_model(self, code: str, session: "Session | None" = None) -> dict:
        return self._set_enabled(code, True, session)

    def disable_model(self, code: str, session: "Session | None" = None) -> dict:
        return self._set_enabled(code, False, session)

    def _set_enabled(self, code: str, enabled: bool, session: "Session | None") -> dict:
        code = code.upper()
        if not self.is_registered(code):
            from app.core.errors import NotFoundError

            raise NotFoundError(f"Unknown machine model: {code}")

        if enabled:
            self._disabled.discard(code)
        else:
            self._disabled.add(code)

        # Mirror state into the database when possible.
        own_session = session is None
        if own_session:
            from app.database.session import database

            session = database.session_scope()
        try:
            from app.models.machine import MachineModel

            row = session.query(MachineModel).filter(MachineModel.code == code).one_or_none()
            if row is not None:
                row.is_active = enabled
                if own_session:
                    session.commit()
        finally:
            if own_session and session is not None:
                session.close()

        logger.info(
            "Model %s", "enabled" if enabled else "disabled",
            extra={"operation": "registry.toggle", "model_code": code, "enabled": enabled},
        )
        return {"model_code": code, "enabled": enabled}

    def sync_from_database(self, session: "Session") -> None:
        """Initialize disabled set from ``machine_models.is_active``."""
        from app.models.machine import MachineModel

        self._disabled = {
            row.code.upper()
            for row in session.query(MachineModel).filter(MachineModel.is_active.is_(False)).all()
            if self.is_registered(row.code)
        }

    def __iter__(self) -> Iterator["BaseModelAdapter"]:
        """Iterate adapter *instances* (registration order)."""
        return iter(adapter_cls() for adapter_cls in self._adapters.values())

    def __len__(self) -> int:
        return len(self._adapters)


model_registry = ModelRegistry()


def load_adapters() -> ModelRegistry:
    """Import the adapters package so adapters self-register (idempotent)."""
    get_settings()  # ensure settings are loaded first
    import app.adapters  # noqa: F401  (side-effect: registration)

    return model_registry
