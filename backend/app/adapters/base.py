"""Model adapter interface.

An adapter bundles everything that is *specific to one CDM model*:

* how to detect that a log set belongs to this model (``detect``)
* which log sources the model produces (``get_log_sources``)
* which parser should be used for a file (``get_parser``)
* how raw events are normalized (``normalize_event`` — Phase 2+)

Adapters self-register with :mod:`app.core.registry`; the rest of the
application never hard-codes a model.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Any, ClassVar

from app.parsers.base import FileContext


@dataclass
class ModelDetection:
    """Result of asking an adapter whether a file belongs to its model."""

    model_code: str
    confidence: float  # 0.0 .. 1.0
    method: str  # filename | content | metadata | …
    matched_on: str  # what matched (pattern, signature, …)


class BaseModelAdapter(ABC):
    """Contract every model adapter must fulfill."""

    # ---- identity (ClassVars set by subclasses) ----
    code: ClassVar[str] = "BASE"
    display_name: ClassVar[str] = "Base model"
    vendor: ClassVar[str] = "GRG Banking"
    description: ClassVar[str] = ""
    is_placeholder: ClassVar[bool] = False
    # Registration order for list views.
    sort_order: ClassVar[int] = 100

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def detect(self, ctx: FileContext) -> ModelDetection | None:
        """Return a ModelDetection if the file looks like this model.

        Default: no detection. Subclasses override with filename and/or
        content-signature heuristics.
        """
        return None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def get_model_info(self) -> dict[str, Any]:
        """Metadata for the model registry / API."""
        return {
            "code": self.code,
            "display_name": self.display_name,
            "vendor": self.vendor,
            "description": self.description,
            "placeholder": self.is_placeholder,
            "enabled": True,
            "supported_sources": self.get_log_sources(),
            "parser_code": self._parser_code_hint(),
            "analysis_status": "placeholder" if self.is_placeholder else "pending",
        }

    def _parser_code_hint(self) -> str | None:
        """Preferred parser code, if the adapter declares one."""
        return getattr(self, "preferred_parser_code", None)

    # ------------------------------------------------------------------
    # Log sources & parsing
    # ------------------------------------------------------------------
    def get_log_sources(self) -> list[str]:
        """Log source codes this model is known to produce (empty = TBD)."""
        return []

    def get_parser(self, ctx: FileContext):
        """Return a parser instance for this file, or None to use the
        global parser registry selection (Phase 2 adds model parsers)."""
        return None

    def normalize_event(self, raw_event: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw event into the model's canonical structure.

        Not part of Phase 1 — model-specific normalization arrives with
        transaction analysis in Phase 2.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.normalize_event() is not implemented yet; "
            "model-specific event normalization ships in Phase 2."
        )

    # ------------------------------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} {self.code}>"


def None_or_dummy() -> Any:  # pragma: no cover - legacy helper kept private
    return None
