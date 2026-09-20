"""Parser framework.

Parsers convert raw log text into a normalized preliminary structure.
Model-specific parsers (P2600N / P2800N) arrive in Phase 2 — this
package only defines the interfaces, the registry, and the generic
fallback parser.
"""

from app.parsers.base import BaseParser, FileContext, ParsedLine, ParseResult
from app.parsers.registry import ParserRegistry, load_builtin_parsers, parser_registry
from app.parsers.generic_text_parser import GenericTextParser

__all__ = [
    "BaseParser",
    "FileContext",
    "ParsedLine",
    "ParseResult",
    "ParserRegistry",
    "load_builtin_parsers",
    "parser_registry",
    "GenericTextParser",
]
