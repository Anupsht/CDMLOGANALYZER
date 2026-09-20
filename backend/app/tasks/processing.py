"""Task entry points (shared by Celery and the inline queue)."""

from __future__ import annotations

from app.services.pipeline import run_pipeline


def process_upload(file_id: str) -> dict:
    """Process one uploaded file through the Phase 1 pipeline."""
    return run_pipeline(file_id)
