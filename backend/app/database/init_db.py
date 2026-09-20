"""Database bootstrap: schema creation + reference data seeding.

* ``create_all`` is idempotent and used for dev/test convenience.
* Production upgrades go through Alembic (``alembic upgrade head``).
* Seeding is idempotent: it inserts reference rows (machine models, log
  sources, parser versions, model configurations, service user) only if
  missing.

Usage::

    python -m app.database.init_db [--with-migrations]
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

MACHINE_MODELS = [
    {
        "code": "P2600N",
        "name": "GRG P2600N",
        "description": "GRG P2600N cash dispenser. Supported in Phase 1: upload, "
        "detection, raw parsing. Transaction analysis arrives in Phase 2.",
        "is_active": True,
        "is_placeholder": False,
    },
    {
        "code": "P2800N",
        "name": "GRG P2800N",
        "description": "GRG P2800N cash dispenser. Supported in Phase 1: upload, "
        "detection, raw parsing. Transaction analysis arrives in Phase 2.",
        "is_active": True,
        "is_placeholder": False,
    },
    {
        "code": "P2600L",
        "name": "GRG P2600L",
        "description": "Placeholder — registered for architecture completeness; "
        "support is planned for a later phase.",
        "is_active": False,
        "is_placeholder": True,
    },
]

LOG_SOURCES = [
    ("ecat", "E-CAT", "E-CAT application log (present on most GRG CDM models)."),
    ("cim", "CIM", "Cash dispensing module (CIM) log."),
    ("keeper", "Keeper", "Keeper module log."),
    ("jou", "JOU", "Transaction journal log."),
    ("noteinfo", "NoteInfo", "Note/cassette information log."),
    ("application", "Application", "Generic application log."),
    ("host", "Host", "Host communication log."),
    ("unknown", "Unknown", "Source could not be determined."),
]

PARSERS = [
    {
        "code": "generic_text",
        "version": "1.0.0",
        "name": "Generic Text Parser",
        "source_type": "unknown",
        "parser_class": "app.parsers.generic_text_parser.GenericTextParser",
        "description": "Fallback line parser: preserves raw text, detects "
        "timestamps and log levels. Used until model-specific parsers ship.",
    }
]


def seed_reference_data() -> None:
    from app.database.session import database
    from app.models.log_file import LogSource
    from app.models.machine import MachineModel
    from app.models.parser import ParserVersion
    from app.models.configuration import ModelConfiguration
    from app.models.user import User

    with database.session_scope() as session:
        # Machine models
        for spec in MACHINE_MODELS:
            row = session.query(MachineModel).filter(MachineModel.code == spec["code"]).one_or_none()
            if row is None:
                session.add(MachineModel(**spec))
                logger.info("Seeded machine model", extra={"model_code": spec["code"]})

        # Log sources
        for code, name, description in LOG_SOURCES:
            row = session.query(LogSource).filter(LogSource.code == code).one_or_none()
            if row is None:
                session.add(LogSource(code=code, name=name, description=description))
                logger.info("Seeded log source", extra={"source_code": code})

        # Parser versions
        for spec in PARSERS:
            row = (
                session.query(ParserVersion)
                .filter(ParserVersion.code == spec["code"], ParserVersion.version == spec["version"])
                .one_or_none()
            )
            if row is None:
                session.add(ParserVersion(**spec))
                logger.info("Seeded parser", extra={"parser_code": spec["code"]})

        # Default per-model configuration
        for model in session.query(MachineModel).all():
            cfg = (
                session.query(ModelConfiguration)
                .filter(ModelConfiguration.machine_model_id == model.id, ModelConfiguration.key == "processing")
                .one_or_none()
            )
            if cfg is None:
                session.add(
                    ModelConfiguration(
                        machine_model_id=model.id,
                        key="processing",
                        value={
                            "phase": 1,
                            "raw_storage": True,
                            "transaction_analysis": {"enabled": False, "planned_phase": 2},
                        },
                    )
                )

        # Service account (authentication itself arrives in a later phase).
        if session.query(User).filter(User.username == "system").one_or_none() is None:
            session.add(User(username="system", role="service", full_name="System service account"))

        session.commit()
        logger.info("Reference data seeded", extra={"operation": "database.seed"})


def create_schema() -> None:
    from app.database.base import Base
    from app.database.session import database
    import app.models  # noqa: F401  (register all tables)

    Base.metadata.create_all(bind=database.engine)
    logger.info("Schema ensured (create_all)", extra={"operation": "database.create_all"})


def run_migrations() -> None:
    """Apply Alembic migrations programmatically."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(_package_root() / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    logger.info("Migrations applied", extra={"operation": "database.migrate"})


def _package_root():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent  # backend/


def init_database(with_migrations: bool = False) -> None:
    if with_migrations:
        try:
            run_migrations()
        except Exception as exc:
            logger.warning(
                "Migration run failed, falling back to create_all",
                extra={"error": str(exc)},
            )
            create_schema()
    else:
        create_schema()
    seed_reference_data()


if __name__ == "__main__":
    configure_logging()
    parser = argparse.ArgumentParser(description="Initialize the CDM database.")
    parser.add_argument(
        "--with-migrations",
        action="store_true",
        help="Apply Alembic migrations before seeding (falls back to create_all).",
    )
    args = parser.parse_args()
    init_database(with_migrations=args.with_migrations)
    print("Database initialized.")
    sys.exit(0)
