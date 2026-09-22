"""Model adapters.

Importing this package triggers registration of every shipped adapter
with the model registry. New models are added by creating a new module
here — see docs/model-adapter-development.md.
"""

from app.adapters.base import BaseModelAdapter, ModelDetection
from app.adapters.p2600n import P2600NAdapter
from app.adapters.p2800n import P2800NAdapter
from app.adapters.p2600l import P2600LAdapter

__all__ = [
    "BaseModelAdapter",
    "ModelDetection",
    "P2600NAdapter",
    "P2800NAdapter",
    "P2600LAdapter",
]
