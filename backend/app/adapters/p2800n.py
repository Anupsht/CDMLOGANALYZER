"""P2800N adapter — architecture placeholder (full logic ships in Phase 2)."""

from __future__ import annotations

import re

from app.adapters.base import BaseModelAdapter, ModelDetection
from app.core.registry import model_registry
from app.parsers.base import FileContext

_FILENAME_RE = re.compile(r"p\s?-?2800\s?n", re.IGNORECASE)
_CONTENT_RE = re.compile(r"\bP2800N\b")


class P2800NAdapter(BaseModelAdapter):
    code = "P2800N"
    display_name = "GRG P2800N"
    description = (
        "GRG P2800N cash dispenser adapter. Detection only in Phase 1; "
        "transaction-level parsing and diagnosis arrive in Phase 2."
    )
    # Model is supported; parsing/analysis logic arrives in Phase 2.
    is_placeholder = False
    sort_order = 20

    LOG_SOURCES = ["ecat", "cim", "keeper", "jou", "noteinfo"]

    def detect(self, ctx: FileContext) -> ModelDetection | None:
        haystack = " ".join([ctx.filename, str(ctx.hints.get("original_path", ""))])
        if _FILENAME_RE.search(haystack):
            return ModelDetection(self.code, 0.6, "filename", "P2800N in name/path")
        if _CONTENT_RE.search(ctx.head_text[:8192]):
            return ModelDetection(self.code, 0.5, "content", "P2800N token in content")
        return None

    def get_log_sources(self) -> list[str]:
        return list(self.LOG_SOURCES)


model_registry.register_model(P2800NAdapter.code, P2800NAdapter)
