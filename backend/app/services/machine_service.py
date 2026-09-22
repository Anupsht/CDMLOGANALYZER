"""Machine & model services (registry-backed, no hard-coded models)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.models.machine import Machine, MachineModel
from app.schemas.machine import MachineCreate

logger = logging.getLogger(__name__)


class MachineService:
    # ---- machines ---------------------------------------------------------

    def get(self, session: Session, machine_id: str) -> Machine:
        machine = session.get(Machine, machine_id)
        if machine is None:
            raise NotFoundError(f"Machine not found: {machine_id}")
        return machine

    def list(self, session: Session, *, limit: int = 100, offset: int = 0) -> tuple[list[Machine], int]:
        query = session.query(Machine).order_by(Machine.serial_number.asc())
        total = query.count()
        return list(query.offset(offset).limit(limit)), total

    def create(self, session: Session, payload: MachineCreate) -> Machine:
        existing = (
            session.query(Machine).filter(Machine.serial_number == payload.serial_number).one_or_none()
        )
        if existing is not None:
            from app.core.errors import DuplicateResourceError

            raise DuplicateResourceError(
                f"A machine with serial number {payload.serial_number} already exists."
            )

        machine_model_id = payload.machine_model_id
        if machine_model_id is None and payload.model_code:
            model = (
                session.query(MachineModel)
                .filter(MachineModel.code == payload.model_code.upper())
                .one_or_none()
            )
            if model is None:
                raise ValidationError(f"Unknown machine model code: {payload.model_code}")
            machine_model_id = model.id

        machine = Machine(
            serial_number=payload.serial_number,
            name=payload.name,
            machine_model_id=machine_model_id,
            location=payload.location,
            status=payload.status,
            commissioned_at=payload.commissioned_at,
        )
        session.add(machine)
        session.flush()
        logger.info(
            "Machine created",
            extra={"operation": "machine.create", "machine_id": machine.id, "serial": machine.serial_number},
        )
        return machine

    # ---- model registry --------------------------------------------------------

    def get_model_by_code(self, session: Session, code: str) -> MachineModel:
        model = session.query(MachineModel).filter(MachineModel.code == code.upper()).one_or_none()
        if model is None:
            raise NotFoundError(f"Machine model not found: {code}")
        return model

    def list_models(self, session: Session) -> list[dict]:
        """Merge the in-process adapter registry with DB state."""
        from app.core.registry import model_registry

        def entry(code: str, name: str, vendor: str, description, placeholder: bool,
                  is_active: bool, row_id: str | None, sources: list[str],
                  parser_code: str | None, analysis_status: str | None) -> dict:
            return {
                "id": row_id,
                "code": code,
                "name": name,
                "vendor": vendor,
                "description": description,
                "is_active": is_active,
                "is_placeholder": placeholder,
                "supported": not placeholder,
                "supported_sources": sources,
                "parser_code": parser_code,
                "analysis_status": analysis_status,
            }

        db_models = {m.code.upper(): m for m in session.query(MachineModel).all()}
        results: list[dict] = []
        for info in model_registry.list_models():
            db_row = db_models.get(info["code"])
            results.append(
                entry(
                    code=info["code"],
                    name=info["display_name"],
                    vendor=info["vendor"],
                    description=info["description"],
                    placeholder=info["placeholder"],
                    is_active=model_registry.is_enabled(info["code"])
                    and (db_row.is_active if db_row else True),
                    row_id=db_row.id if db_row else None,
                    sources=info["supported_sources"],
                    parser_code=info["parser_code"],
                    analysis_status=info["analysis_status"],
                )
            )
        # Include DB-only models (seeded but no adapter yet, e.g. future models).
        for code, row in db_models.items():
            if not model_registry.is_registered(code):
                results.append(
                    entry(
                        code=row.code,
                        name=row.name,
                        vendor=row.vendor,
                        description=row.description,
                        placeholder=row.is_placeholder,
                        is_active=row.is_active,
                        row_id=row.id,
                        sources=[],
                        parser_code=None,
                        analysis_status="registered",
                    )
                )
        results.sort(key=lambda r: r["code"])
        return results


machine_service = MachineService()
