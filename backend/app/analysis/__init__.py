"""Universal analysis engine (model-independent).

This package implements the *universal* event/transaction model:

* :mod:`.events`        — NormalizedEvent + the universal event vocabulary
* :mod:`.normalizer`    — raw parsed lines → NormalizedEvent (via model config)
* :mod:`.correlator`    — configurable multi-key event → transaction correlation
* :mod:`.reconstructor` — expected-stage reconstruction with NOT_CONFIRMED markers

Model-specific knowledge enters **only** as configuration supplied by a
model adapter (events.yaml / errors.yaml / devices.yaml / model.yaml).
No module here may branch on a model code.
"""

from app.analysis.correlator import TransactionDraft, correlate
from app.analysis.events import (
    NORMALIZED_EVENTS,
    NormalizedEvent,
    SEVERITIES,
)
from app.analysis.normalizer import EventNormalizer
from app.analysis.reconstructor import (
    STAGE_SEQUENCE,
    Reconstructor,
    StageStatus,
)

__all__ = [
    "Correlator",
    "TransactionDraft",
    "correlate",
    "NORMALIZED_EVENTS",
    "NormalizedEvent",
    "SEVERITIES",
    "EventNormalizer",
    "STAGE_SEQUENCE",
    "Reconstructor",
    "StageStatus",
]
