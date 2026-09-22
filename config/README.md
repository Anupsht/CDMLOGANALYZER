# =====================================================================
# Configuration management
# =====================================================================
# All runtime configuration is environment-driven and validated by
# `pydantic-settings` at startup (see `backend/app/core/config.py`).
#
# Every variable is prefixed with `CDM_` and is documented in the root
# `.env.example` file. Copy `.env.example` to `.env` and adjust values.
#
# Priority order (highest first):
#   1. Process environment variables (CDM_*)
#   2. `.env` file in the project root
#   3. Built-in defaults in `backend/app/core/config.py`
#
# This directory may also hold deployment-specific extra configuration
# (e.g. nginx site overrides, log shipper configs) in future phases.
# =====================================================================
