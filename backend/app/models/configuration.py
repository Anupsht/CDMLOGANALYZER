"""Model-level configuration storage (key/value JSON per machine model)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.machine import MachineModel


class ModelConfiguration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A configuration entry for a machine model (e.g. parsing options)."""

    __tablename__ = "model_configurations"
    __table_args__ = (
        UniqueConstraint("machine_model_id", "key", name="uq_model_configurations_model_key"),
    )

    machine_model_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("machine_models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[dict | list] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    machine_model: Mapped["MachineModel"] = relationship(back_populates="configurations")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ModelConfiguration {self.key}>"
