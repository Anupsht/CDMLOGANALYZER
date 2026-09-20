"""GRG P2600N model package.

Everything P2600N-specific lives here: adapter, configured parsers,
filename patterns. Format mappings come from ``config/models/p2600n/``.

⚠️ The YAML mappings were established from the *file inventory* of the
provided log export (eCAT/CIM30/Keeper/JOU/NoteInfo/ReceiptPrinter/
GRGCA10DEV, 2026-07-03) because sanitized log *contents* were not yet
available to the build. They are marked SYNTHETIC in the YAML and
summarized in docs/model-integrations.md — validate against real logs
before trusting field semantics. Everything not confidently mappable is
marked UNKNOWN/UNMAPPED by design.
"""

from app.adapters.p2600n.adapter import P2600NAdapter

__all__ = ["P2600NAdapter"]
