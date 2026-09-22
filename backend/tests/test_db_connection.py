"""Database connectivity and schema tests."""

from __future__ import annotations

from sqlalchemy import inspect, text


def test_engine_connects(db_session):
    result = db_session.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_all_phase1_tables_exist(db_session):
    inspector = inspect(db_session.connection())
    tables = set(inspector.get_table_names())
    expected = {
        "users",
        "machines",
        "machine_models",
        "machine_components",
        "log_files",
        "log_sources",
        "log_lines",
        "parser_versions",
        "model_configurations",
        "audit_logs",
    }
    assert expected.issubset(tables), f"missing tables: {expected - tables}"


def test_seeded_reference_data(db_session):
    from app.models.log_file import LogSource
    from app.models.machine import MachineModel
    from app.models.parser import ParserVersion

    codes = {m.code for m in db_session.query(MachineModel).all()}
    assert {"P2600N", "P2800N", "P2600L"}.issubset(codes)

    sources = {s.code for s in db_session.query(LogSource).all()}
    assert {"ecat", "cim", "keeper", "jou", "noteinfo", "application", "host", "unknown"} == sources

    assert db_session.query(ParserVersion).filter_by(code="generic_text").count() == 1


def test_timestamps_and_uuid_pks(db_session):
    from app.models.machine import MachineModel

    row = MachineModel(code="TESTX", name="Test model")
    db_session.add(row)
    db_session.commit()

    assert len(row.id) == 36  # UUID
    assert row.created_at is not None
    assert row.updated_at is not None
