"""Log source detection framework.

Detection answers: *which kind of log is this file?* (eCAT, CIM,
Keeper, JOU, NoteInfo, application, host, unknown …).

It is rule-based and deliberately conservative:

* :class:`FilenameRule` — matches filename / ZIP inner-path patterns
* :class:`ContentSignatureRule` — regex signatures over the file head

Rules are registered in priority order; the first, highest-confidence
match wins. New rules plug in via ``detection_service.register_rule``
(see docs/parser-development.md). Nothing assumes a source exists for
every model — files that match nothing are ``unknown``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.parsers.base import FileContext

logger = logging.getLogger(__name__)

# Canonical source codes (seeded into the log_sources table).
KNOWN_SOURCE_CODES = (
    "ecat",
    "cim",
    "keeper",
    "jou",
    "noteinfo",
    "application",
    "host",
    "unknown",
)


@dataclass
class SourceDetection:
    source_code: str
    confidence: float  # 0.0 .. 1.0
    method: str  # filename | content | rule:<name>
    matched_on: str


class DetectionRule:
    """Base class for detection rules."""

    name: str = "rule"
    priority: int = 100  # lower = evaluated earlier

    def detect(self, ctx: FileContext) -> SourceDetection | None:
        raise NotImplementedError


class FilenameRule(DetectionRule):
    """Match filename (and ZIP inner path) against regex patterns."""

    name = "filename"

    def __init__(self, patterns: dict[str, list[str]], confidence: float = 0.9) -> None:
        self.patterns = {
            source: [re.compile(p, re.IGNORECASE) for p in pat_list]
            for source, pat_list in patterns.items()
        }
        self.confidence = confidence

    def detect(self, ctx: FileContext) -> SourceDetection | None:
        haystack = " ".join([ctx.filename, str(ctx.hints.get("original_path", ""))])
        for source, patterns in self.patterns.items():
            for pattern in patterns:
                if pattern.search(haystack):
                    return SourceDetection(source, self.confidence, self.name, pattern.pattern)
        return None


class ContentSignatureRule(DetectionRule):
    """Match regex signatures against the decoded file head."""

    name = "content"

    def __init__(
        self,
        signatures: dict[str, list[str]],
        confidence: float = 0.7,
        scan_chars: int = 16 * 1024,
    ) -> None:
        self.signatures = {
            source: [re.compile(p, re.IGNORECASE) for p in pat_list]
            for source, pat_list in signatures.items()
        }
        self.confidence = confidence
        self.scan_chars = scan_chars

    def detect(self, ctx: FileContext) -> SourceDetection | None:
        head = ctx.head_text[: self.scan_chars]
        if not head:
            return None
        for source, patterns in self.signatures.items():
            for pattern in patterns:
                if pattern.search(head):
                    return SourceDetection(source, self.confidence, self.name, pattern.pattern)
        return None


class ExtensionRule(DetectionRule):
    """Weak hint: known GRG log filename extensions map to sources."""

    name = "extension"

    def __init__(self, mapping: dict[str, str], confidence: float = 0.3) -> None:
        self.mapping = {ext.lower(): src for ext, src in mapping.items()}
        self.confidence = confidence

    def detect(self, ctx: FileContext) -> SourceDetection | None:
        source = self.mapping.get(ctx.extension)
        if source:
            return SourceDetection(source, self.confidence, self.name, f".{ctx.extension}")
        return None


class DetectionService:
    """Ordered rule chain. First positive match wins."""

    def __init__(self) -> None:
        self._rules: list[DetectionRule] = []
        self._load_default_rules()

    # ---- rule management ------------------------------------------------

    def register_rule(self, rule: DetectionRule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)

    @property
    def rules(self) -> list[DetectionRule]:
        return list(self._rules)

    def _load_default_rules(self) -> None:
        # 1) Strong filename signals used by GRG CDM logs.
        # Patterns use "non-alphanumeric or string boundary" semantics so
        # separators like '_' and '-' count (e.g. "ECAT_2026.log").
        self.register_rule(
            FilenameRule(
                {
                    "ecat": [r"(?:^|[^a-z0-9])e[-_]?cat"],
                    "cim": [r"(?:^|[^a-z0-9])cim"],
                    "keeper": [r"(?:^|[^a-z0-9])keeper"],
                    "jou": [r"(?:^|[^a-z0-9])jou(rnal)?"],
                    "noteinfo": [r"(?:^|[^a-z0-9])note[-_]?info"],
                },
                confidence=0.9,
            )
        )
        # 2) Content signatures (generic, extended per model in Phase 2).
        self.register_rule(
            ContentSignatureRule(
                {
                    "ecat": [r"\beCAT\b", r"\bE-CAT\b"],
                    "cim": [r"\bCIM\b"],
                    "keeper": [r"\bKeeper\b"],
                    "jou": [r"\bJOURNAL\b", r"\bJOU\b"],
                    "noteinfo": [r"\bNoteInfo\b", r"\bNote Info\b"],
                },
                confidence=0.7,
            )
        )
        # 3) Weak extension hints (host/application logs).
        self.register_rule(
            ExtensionRule(
                {
                    "log": "application",
                    "txt": "application",
                },
                confidence=0.2,
            )
        )

    # ---- detection ----------------------------------------------------------

    def detect(self, ctx: FileContext) -> SourceDetection:
        """Return the best detection for the file (never None → unknown)."""
        for rule in self._rules:
            try:
                result = rule.detect(ctx)
            except Exception:  # a broken rule must not break the pipeline
                logger.exception("Detection rule failed", extra={"rule": rule.name})
                continue
            if result is not None:
                return result
        return SourceDetection("unknown", 0.0, "default", "no rule matched")

    def detect_model(self, ctx: FileContext, adapters) -> tuple[str | None, float, str]:
        """Ask all enabled adapters to detect the machine model.

        Returns ``(model_code | None, confidence, method)``.
        """
        best: tuple[str | None, float, str] = (None, 0.0, "none")
        for adapter in sorted(adapters, key=lambda a: a.sort_order):
            from app.adapters.base import ModelDetection

            try:
                detection: ModelDetection | None = adapter.detect(ctx)
            except Exception:
                logger.exception(
                    "Adapter detect() failed", extra={"adapter": type(adapter).__name__}
                )
                continue
            if detection and detection.confidence > best[1]:
                best = (detection.model_code, detection.confidence, detection.method)
        return best


def build_file_context(path, filename: str | None = None, hints: dict | None = None) -> FileContext:
    ctx = FileContext.from_path(path, hints=hints)
    if filename:
        ctx.filename = filename
    return ctx


detection_service = DetectionService()
