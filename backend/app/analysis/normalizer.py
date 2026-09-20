"""Event normalization: raw parsed lines → universal NormalizedEvents.

The normalizer applies, in order:

1. the model's ``events.yaml`` patterns for the detected source
   (first match wins, patterns are ordered by specificity in the YAML);
2. the model's ``errors.yaml`` patterns (→ ``ERROR`` + error code);
3. ``devices.yaml`` (device naming, applied to any matched event);
4. fallback: ``UNMAPPED``.

Nothing here knows about specific models — everything comes from the
adapter's configuration package.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.analysis.events import ERROR, UNMAPPED, NormalizedEvent, default_severity

logger = logging.getLogger(__name__)


def _substitute_groups(value: str, match: "re.Match[str]") -> str:
    """Substitute ``$1``..``$9`` with the match's capture groups."""
    return re.sub(
        r"\$(\d)",
        lambda m: match.group(int(m.group(1))) or "UNKNOWN",
        value,
    )


class _Compiled:
    """Per-source compiled mapping cache (built once per adapter)."""

    def __init__(self, events: list[dict], errors: list[dict], devices: list[dict]):
        self.events = [(re.compile(e["pattern"], re.IGNORECASE), e) for e in events]
        self.errors = [(re.compile(e["pattern"], re.IGNORECASE), e) for e in errors]
        self.devices = [(re.compile(d["pattern"], re.IGNORECASE), d) for d in devices]


class EventNormalizer:
    """Compile once, normalize many. Bound to one adapter's config."""

    def __init__(self, adapter) -> None:
        self.adapter = adapter
        config = adapter.model_config
        events_cfg = config.get("events", {})
        errors_cfg = config.get("errors", {})
        devices_cfg = config.get("devices", {})
        # events.yaml / errors.yaml shape: {source_code: [ {pattern, event|code, ...} ]}
        self._per_source: dict[str, _Compiled] = {}
        self._default: _Compiled = _Compiled(
            events_cfg.get("default", []),
            errors_cfg.get("default", []),
            devices_cfg if isinstance(devices_cfg, list) else devices_cfg.get("patterns", []),
        )
        for source, entries in events_cfg.items():
            if source == "default":
                continue
            self._per_source[source] = _Compiled(
                entries,
                errors_cfg.get(source, []),
                [],  # devices are source-independent
            )
        # Devices are global per model.
        self._device_rules = self._default.devices

    # ------------------------------------------------------------------
    def normalize_line(self, parsed, source_code: str, model_code: str) -> NormalizedEvent:
        raw_text = parsed.raw_text
        compiled = self._per_source.get(source_code, self._default)

        event: str | None = None
        entry: dict[str, Any] = {}
        event_match: re.Match | None = None
        for pattern, candidate in compiled.events:
            event_match = pattern.search(raw_text)
            if event_match:
                event, entry = candidate.get("event", UNMAPPED), candidate
                break
        if event is None:
            for pattern, candidate in compiled.errors:
                match = pattern.search(raw_text)
                if match:
                    event = ERROR
                    code = candidate.get("code", "UNKNOWN")
                    # Substitute captured groups ($1, $2…) into the code.
                    if match.groups() and "$" in code:
                        code = _substitute_groups(code, match)
                    entry = {
                        "severity": candidate.get("severity", "ERROR"),
                        "error_code": code,
                        "error_description": candidate.get("description"),
                    }
                    break

        if event is None:
            event = UNMAPPED

        severity = entry.get("severity") or self._level_severity(parsed.level) or default_severity(event)
        device = self._resolve_device(parsed, raw_text)

        detail: dict[str, Any] = {
            k: v for k, v in entry.items() if k not in {"pattern", "event", "severity"}
        }
        if event_match is not None and event_match.groups():
            # Events.yaml entries may reference capture groups ($1, $2…) in
            # string values, e.g. error_code: 'P28IFM-$1' for rc=(41|42|43).
            detail = {
                k: _substitute_groups(v, event_match) if isinstance(v, str) else v
                for k, v in detail.items()
            }
        if event == UNMAPPED:
            detail["pattern"] = "UNKNOWN"

        keys = self.adapter.extract_correlation_keys(raw_text, source_code)

        return NormalizedEvent(
            model_code=model_code,
            source_code=source_code,
            event=event,
            timestamp=parsed.timestamp,
            device=device,
            severity=severity,
            detail=detail,
            keys=keys,
            raw=getattr(parsed, "raw_row", None),
        )

    # ------------------------------------------------------------------
    def _resolve_device(self, parsed, raw_text: str) -> str | None:
        device = (parsed.normalized or {}).get("device")
        if device:
            return device
        for pattern, rule in self._device_rules:
            if pattern.search(raw_text):
                return rule.get("device") or rule.get("name")
        return None

    @staticmethod
    def _level_severity(level: str | None) -> str | None:
        if not level:
            return None
        level = level.upper()
        if level in {"ERROR", "ERR", "FATAL", "CRITICAL"}:
            return "ERROR"
        if level in {"WARN", "WARNING"}:
            return "WARNING"
        if level in {"DEBUG", "TRACE"}:
            return "DEBUG"
        if level == "INFO":
            return "INFO"
        return None
