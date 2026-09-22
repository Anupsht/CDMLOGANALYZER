"""GRG P2800N model package.

Proves the architecture is model-independent: P2800N shares **zero**
parsing/mapping code with P2600N — its formats differ deliberately — yet
flows through the same universal engine using only its own YAML
configuration package (``config/models/p2800n``).

⚠️ Same SYNTHETIC caveat as P2600N: filename inventory is real
(P2800N export), line formats are documented templates pending real
logs. See docs/model-integrations.md.
"""

from app.adapters.p2800n.adapter import P2800NAdapter

__all__ = ["P2800NAdapter"]
