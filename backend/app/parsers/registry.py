"""Parser registry and selection logic.

Selection order:
1. Preferred parser codes (e.g. suggested by a model adapter)
2. All registered parsers ordered by ``priority``
3. The generic fallback parser, if nothing else matches
"""

from __future__ import annotations

import logging

from app.parsers.base import BaseParser, FileContext

logger = logging.getLogger(__name__)

GENERIC_FALLBACK_CODE = "generic_text"


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, BaseParser] = {}

    # ---- registration ------------------------------------------------------

    def register(self, parser_cls: type[BaseParser]) -> type[BaseParser]:
        """Class decorator: register a parser implementation."""
        instance = parser_cls()
        existing = self._parsers.get(instance.code)
        if existing is not None and type(existing) is not parser_cls:
            raise ValueError(f"Parser code already registered: {instance.code}")
        self._parsers[instance.code] = instance
        logger.debug(
            "Registered parser", extra={"parser_code": instance.code, "version": instance.version}
        )
        return parser_cls

    # ---- lookup -------------------------------------------------------------

    def get(self, code: str) -> BaseParser | None:
        return self._parsers.get(code)

    def require(self, code: str) -> BaseParser:
        parser = self.get(code)
        if parser is None:
            from app.core.errors import NotFoundError

            raise NotFoundError(f"Unknown parser: {code}")
        return parser

    def all(self) -> list[BaseParser]:
        return sorted(self._parsers.values(), key=lambda p: (p.priority, p.code))

    # ---- selection ------------------------------------------------------------

    def select(self, ctx: FileContext, preferred_codes: list[str] | None = None) -> BaseParser:
        """Pick the first parser whose ``can_parse`` accepts the file."""
        candidates: list[BaseParser] = []
        for code in preferred_codes or []:
            parser = self.get(code)
            if parser is not None:
                candidates.append(parser)
        candidates.extend(p for p in self.all() if p not in candidates)

        for parser in candidates:
            try:
                if parser.can_parse(ctx):
                    return parser
            except Exception:  # a broken can_parse must not break selection
                logger.exception("can_parse() failed", extra={"parser_code": parser.code})

        fallback = self.get(GENERIC_FALLBACK_CODE)
        if fallback is None:
            raise RuntimeError(f"No fallback parser registered ('{GENERIC_FALLBACK_CODE}')")
        return fallback


parser_registry = ParserRegistry()


def load_builtin_parsers() -> ParserRegistry:
    """Register the built-in parsers (idempotent).

    Model-specific parsers (Phase 2) register themselves from their own
    modules or from model adapters.
    """
    from app.parsers.generic_text_parser import GenericTextParser

    parser_registry.register(GenericTextParser)
    return parser_registry
