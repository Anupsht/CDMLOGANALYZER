"""P2600N adapter — configuration-driven, code kept minimal.

P2600N parsers are adapter-scoped (never registered in the global parser
registry): only files identified as P2600N can use them.
"""

from __future__ import annotations

from app.adapters.base import BaseModelAdapter
from app.core.registry import model_registry


class P2600NAdapter(BaseModelAdapter):
    code = "P2600N"
    display_name = "GRG P2600N"
    description = (
        "GRG P2600N cash dispenser adapter. Sources per provided export: eCAT, CIM30, "
        "Keeper, JOU (journal), NoteInfo (CSV), ReceiptPrinter, GRGCA10DEV host log. "
        "Mappings are configuration-driven (config/models/p2600n) — see SYNTHETIC note."
    )
    is_placeholder = False
    sort_order = 10

    _filename_patterns = (r"(?:^|[^a-z0-9])p[-_]?2600[-_]?n",)
    _content_patterns = (r"\bP2600N\b",)


model_registry.register_model(P2600NAdapter.code, P2600NAdapter)
