"""Per-model YAML configuration loader.

Each supported model ships a data package under::

    config/models/<lower-case model code>/
        model.yaml         identity + correlation rules + key extraction
        devices.yaml       device-name patterns
        log_sources.yaml   source detection + parser definitions
        errors.yaml        error-code patterns (per source)
        events.yaml        message patterns → universal event codes
        hardware.yaml      Phase 4: hardware extraction (sensors, motors,
                           gates/shutters, transport, jam indications,
                           temporal windows) — optional

The universal engine (analysis/, parsers/configured.py) interprets this
data; it contains **no** model-specific conditionals. Adding or fixing a
model is therefore a data change, not a code change.

All pattern definitions are expected to be validated against *real*
logs. Mappings established without real log evidence are marked
``SYNTHETIC`` in the YAML files and listed in
docs/model-integrations.md.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CONFIG_FILES = ("model", "devices", "log_sources", "errors", "events", "hardware")


def _default_config_root() -> Path:
    """Locate <repo>/config/models without depending on the CWD."""
    # backend/app/core/model_config.py → parents: [core, app, backend, repo]
    repo_root = Path(__file__).resolve().parents[3]
    candidates = [repo_root / "config" / "models", Path.cwd() / "config" / "models"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def config_root() -> Path:
    override = get_settings().config_dir
    if override:
        path = Path(override).expanduser().resolve()
        if path.exists():
            return path
        logger.warning("CDM_CONFIG_DIR does not exist, using default", extra={"path": override})
    return _default_config_root()


def model_config_dir(model_code: str) -> Path:
    return config_root() / model_code.lower()


@functools.lru_cache(maxsize=32)
def load_model_config(model_code: str) -> dict[str, Any]:
    """Load all YAML files for a model. Missing files/keys yield empty dicts."""
    directory = model_config_dir(model_code)
    result: dict[str, Any] = {}
    if not directory.exists():
        logger.info(
            "No model configuration package", extra={"model_code": model_code, "path": str(directory)}
        )
        return result
    for name in CONFIG_FILES:
        path = directory / f"{name}.yaml"
        if path.exists():
            try:
                result[name] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                logger.error(
                    "Invalid model YAML", extra={"model_code": model_code, "file": path.name, "error": str(exc)}
                )
                result[name] = {}
    logger.debug("Loaded model config", extra={"model_code": model_code, "files": sorted(result)})
    return result


def reload_model_configs() -> None:
    """Drop cached configs (tests / hot reload)."""
    load_model_config.cache_clear()
