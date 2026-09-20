"""Machine fleet models: model registry rows, physical machines, components."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.configuration import ModelConfiguration
    from app.models.log_file import LogFile


class MachineModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A supported CDM product family (e.g. P2600N)."""

    __tablename__ = "machine_models"

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    vendor: Mapped[str] = mapped_column(String(64), default="GRG Banking", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Disabled models remain registered but are not processed.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Placeholder models (e.g. P2600L in Phase 1) accept registration only.
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    machines: Mapped[list["Machine"]] = relationship(
        back_populates="machine_model", foreign_keys="Machine.machine_model_id"
    )
    configurations: Mapped[list["ModelConfiguration"]] = relationship(
        back_populates="machine_model", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MachineModel {self.code}>"


class Machine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A physical CDM device in the fleet."""

    __tablename__ = "machines"

    serial_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    machine_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("machine_models.id", ondelete="SET NULL"), nullable=True
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # unknown | active | inactive | maintenance | retired
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    commissioned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column("extra_metadata", JSON, nullable=True)

    machine_model: Mapped[MachineModel | None] = relationship(back_populates="machines")
    components: Mapped[list["MachineComponent"]] = relationship(
        back_populates="machine", cascade="all, delete-orphan"
    )
    log_files: Mapped[list["LogFile"]] = relationship(back_populates="machine")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Machine {self.serial_number}>"


class MachineComponent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Physical/logical component of a machine (dispenser, sensor, motor, …).

    Future phases attach faults / sensor_events / motor_events to these rows.
    """

    __tablename__ = "machine_components"

    machine_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("machines.id", ondelete="CASCADE"), nullable=True, index=True
    )
    machine_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("machine_models.id", ondelete="CASCADE"), nullable=True, index=True
    )
    component_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    part_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    position: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column("extra_metadata", JSON, nullable=True)

    machine: Mapped[Machine | None] = relationship(back_populates="components")
    machine_model_ref: Mapped[MachineModel | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MachineComponent {self.component_type}:{self.name}>"
