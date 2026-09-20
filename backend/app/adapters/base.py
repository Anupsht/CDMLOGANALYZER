"""Model adapter interface.

An adapter bundles everything *specific to one CDM model*:

* how to detect that a log set belongs to this model (``detect``)
* which log sources the model produces (``get_log_sources``)
* which parser should be used for a file (``get_parser``)
* how raw messages map to universal events (``normalize_event``)
* how correlation keys are extracted (``extract_correlation_keys``)
* how model errors map to severities (``map_error`` — via errors.yaml)

Since Phase 3, adapters are **configuration-driven**: the heavy lifting
(parser regexes, event patterns, error patterns, device names,
correlation rules, key extraction) lives in the model's YAML package
under ``config/models/<code>/`` (see :mod:`app.core.model_config`).
Adapters keep only what is genuinely code: detection heuristics and
wiring. Adding a model = new adapter package + new YAML package.

The universal engine (``app/analysis``) never branches on model codes;
this interface is the only place model behavior is defined.
"""

from __future__ import annotations

import logging
import re
from abc import ABC
from dataclasses import dataclass
from typing import Any, ClassVar

from app.core.model_config import load_model_config
from app.parsers.base import FileContext

logger = logging.getLogger(__name__)


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
    sort_order: ClassVar[int] = 100

    # Filename patterns for whole-model detection (compiled lazily).
    _filename_patterns: ClassVar[tuple[str, ...]] = ()
    _content_patterns: ClassVar[tuple[str, ...]] = ()

    def __init__(self) -> None:
        self.model_config = load_model_config(self.code)
        self._parser_cache: dict[str, Any] | None = None
        self._key_rules: list[tuple[str, re.Pattern, str]] | None = None

    # ------------------------------------------------------------------
    # Configuration access
    # ------------------------------------------------------------------
    def _load_parsers(self) -> dict[str, Any]:
        """source_code → configured parser instance (from log_sources.yaml)."""
        if self._parser_cache is None:
            from app.parsers.configured import build_parser

            self._parser_cache = {}
            for source_code, spec in (self.model_config.get("log_sources") or {}).items():
                parser_cfg = (spec or {}).get("parser")
                if parser_cfg and parser_cfg.get("line_pattern") or (parser_cfg or {}).get("type") == "csv":
                    self._parser_cache[source_code] = build_parser(
                        code=parser_cfg.get("code", f"{self.code.lower()}_{source_code}"),
                        source_type=source_code,
                        config=parser_cfg,
                    )
        return self._parser_cache

    @property
    def _key_extraction_rules(self) -> list[tuple[str, re.Pattern, str]]:
        """Correlation key extraction rules: (key, pattern, value type).

        Per-source rules (log_sources.yaml → ``key_extract``) are tried
        before model-level rules (model.yaml → ``key_extract``).
        """
        if self._key_rules is None:
            rules: list[tuple[str, re.Pattern, str]] = []
            for source, spec in (self.model_config.get("log_sources") or {}).items():
                for rule in (spec or {}).get("key_extract", []) or []:
                    rules.append(
                        (rule["key"], re.compile(rule["pattern"]), rule.get("type", "str"))
                    )
            for rule in (self.model_config.get("model") or {}).get("key_extract", []) or []:
                rules.append((rule["key"], re.compile(rule["pattern"]), rule.get("type", "str")))
            self._key_rules = rules
        return self._key_rules

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def detect(self, ctx: FileContext) -> ModelDetection | None:
        """Whole-model detection: filename / ZIP path, then content."""
        haystack = " ".join([ctx.filename, str(ctx.hints.get("original_path", ""))])
        for pattern in self._filename_patterns:
            if re.search(pattern, haystack, re.IGNORECASE):
                return ModelDetection(self.code, 0.6, "filename", pattern)
        for pattern in self._content_patterns:
            if re.search(pattern, ctx.head_text[:8192]):
                return ModelDetection(self.code, 0.5, "content", pattern)
        return None

    def detect_source(self, ctx: FileContext) -> ModelDetection | None:
        """Source-level detection using this model's filename patterns.

        Returns the detection with the model code replaced by the source
        code in ``matched_on`` (``source:<code>``); used by the pipeline
        when generic detection was inconclusive.
        """
        haystack = " ".join([ctx.filename, str(ctx.hints.get("original_path", ""))])
        for source_code, spec in (self.model_config.get("log_sources") or {}).items():
            for pattern in (spec or {}).get("filename_patterns", []) or []:
                if re.search(pattern, haystack):
                    return ModelDetection(self.code, 0.85, "model:filename", f"source:{source_code}")
        return None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def get_model_info(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "display_name": self.display_name,
            "vendor": self.vendor,
            "description": self.description,
            "placeholder": self.is_placeholder,
            "enabled": True,
            "supported_sources": self.get_log_sources(),
            "parser_code": self._parser_code_hint(),
            "analysis_status": "placeholder" if self.is_placeholder else "active",
        }

    def _parser_code_hint(self) -> str | None:
        parsers = self._load_parsers()
        return ",".join(sorted(parsers)) if parsers else None

    # ------------------------------------------------------------------
    # Log sources & parsing
    # ------------------------------------------------------------------
    def get_log_sources(self) -> list[str]:
        """Source codes configured for this model (data-driven)."""
        return sorted((self.model_config.get("log_sources") or {}).keys())

    def get_parser(self, ctx: FileContext):
        """First configured parser whose can_parse accepts the file."""
        for source_code, spec in (self.model_config.get("log_sources") or {}).items():
            parser = self._load_parsers().get(source_code)
            if parser is not None and parser.can_parse(ctx):
                return parser
        return None

    def source_for_parser(self, parser_code: str) -> str | None:
        for source_code, parser in self._load_parsers().items():
            if parser.code == parser_code:
                return source_code
        return None

    def iter_parsers(self) -> list:
        """All configured parser instances of this model (introspection)."""
        return list(self._load_parsers().values())

    # ------------------------------------------------------------------
    # Event normalization & mapping
    # ------------------------------------------------------------------
    def normalize_event(self, parsed, source_code: str) -> Any:
        """Map one parsed line to a universal NormalizedEvent (see
        :mod:`app.analysis.normalizer`). Implemented via events.yaml /
        errors.yaml — no model code required here."""
        from app.analysis.normalizer import EventNormalizer

        if not hasattr(self, "_normalizer"):
            self._normalizer = EventNormalizer(self)
        return self._normalizer.normalize_line(parsed, source_code, self.code)

    def map_error(self, raw_message: str) -> dict[str, Any] | None:
        """Return the errors.yaml mapping for a raw message, if any."""
        errors_cfg = (self.model_config.get("errors") or {}).get("default", [])
        for entry in errors_cfg:
            if re.search(entry["pattern"], raw_message, re.IGNORECASE):
                return {
                    "code": entry.get("code", "UNKNOWN"),
                    "severity": entry.get("severity", "ERROR"),
                    "description": entry.get("description"),
                }
        return None

    # ------------------------------------------------------------------
    # Correlation
    # ------------------------------------------------------------------
    def extract_correlation_keys(self, raw_text: str, source_code: str | None = None) -> dict[str, Any]:
        """Extract correlation keys from a raw line (config-driven)."""
        keys: dict[str, Any] = {}
        for key, pattern, value_type in self._key_extraction_rules:
            if key in keys:
                continue  # first (most specific) match wins
            match = pattern.search(raw_text)
            if match is None:
                continue
            raw_value = match.group(1) if match.groups() else match.group(0)
            try:
                if value_type == "float":
                    keys[key] = float(raw_value)
                elif value_type == "int":
                    keys[key] = int(raw_value)
                else:
                    keys[key] = raw_value
            except (TypeError, ValueError):
                keys[key] = raw_value
        return keys

    def correlation_config(self):
        from app.analysis.correlator import CorrelationConfig

        model_cfg = self.model_config.get("model") or {}
        return CorrelationConfig.from_config(model_cfg.get("correlation"))

    # ------------------------------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} {self.code}>"
