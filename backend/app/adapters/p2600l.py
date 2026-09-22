"""P2600L adapter — configuration-driven, code kept minimal.

⚠️ NO REAL P2600L LOGS OR DOCUMENTATION HAVE BEEN RECEIVED. The adapter
wiring below is production-shaped, but every pattern in
``config/models/p2600l/`` is a labeled SYNTHETIC template — deliberately
NOT derived from P2600N (P2600L has its own sources apl/jal/dgn and its
own token vocabulary). When real P2600L material arrives, only the YAML
package changes; this adapter and the universal engine do not.

Deliberately structured exactly like the P2600N/P2800N adapters: if this
file grows model-specific branches, the architecture is wrong.
"""

from __future__ import annotations

from app.adapters.base import BaseModelAdapter
from app.core.registry import model_registry


class P2600LAdapter(BaseModelAdapter):
    code = "P2600L"
    display_name = "GRG P2600L"
    description = (
        "GRG P2600L cash dispenser adapter. Sources (SYNTHETIC until real "
        "documentation arrives): apl application log, jal journal, dgn "
        "diagnostics. Configuration-driven (config/models/p2600l)."
    )
    is_placeholder = False
    sort_order = 30

    _filename_patterns = (r"(?:^|[^a-z0-9])p[-_]?2600[-_]?l",)
    _content_patterns = (r"\bP2600L\b",)


model_registry.register_adapter(P2600LAdapter.code, P2600LAdapter)
