"""P2800N adapter — configuration-driven, code kept minimal.

Deliberately structured exactly like the P2600N adapter: if this file
grows model-specific branches, the architecture is wrong. Parsers are
adapter-scoped (never in the global parser registry).
"""

from __future__ import annotations

from app.adapters.base import BaseModelAdapter
from app.core.registry import model_registry


class P2800NAdapter(BaseModelAdapter):
    code = "P2800N"
    display_name = "GRG P2800N"
    description = (
        "GRG P2800N cash dispenser adapter. Sources per provided export naming: "
        "application log, journal (JRN), SIU (sensor input unit), IFM (host interface). "
        "Mappings are configuration-driven (config/models/p2800n) — see SYNTHETIC note."
    )
    is_placeholder = False
    sort_order = 20

    _filename_patterns = (r"(?:^|[^a-z0-9])p[-_]?2800[-_]?n",)
    _content_patterns = (r"\bP2800N\b",)


model_registry.register_model(P2800NAdapter.code, P2800NAdapter)
