"""P2600L adapter — registration placeholder only (model not supported yet)."""

from __future__ import annotations

from app.adapters.base import BaseModelAdapter, ModelDetection
from app.core.registry import model_registry
from app.parsers.base import FileContext


class P2600LAdapter(BaseModelAdapter):
    code = "P2600L"
    display_name = "GRG P2600L"
    description = (
        "Reserved for the P2600L family. Registered as a placeholder so the "
        "architecture and database are ready; detection and parsing are "
        "deliberately not implemented yet."
    )
    is_placeholder = True
    sort_order = 30

    def detect(self, ctx: FileContext) -> ModelDetection | None:
        # Intentionally returns None: P2600L support is a future phase.
        return None

    def get_log_sources(self) -> list[str]:
        return []


model_registry.register_model(P2600LAdapter.code, P2600LAdapter)
