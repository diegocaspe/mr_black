from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

PENDIENTE = "PENDIENTE"
CONFIRMADA = "CONFIRMADA"
ATENDIDA = "ATENDIDA"
CANCELADA = "CANCELADA"
ACTIVE_STATUSES = (PENDIENTE, CONFIRMADA)

# Transiciones válidas. ATENDIDA y CANCELADA son estados finales.
TRANSITIONS: dict[str, set[str]] = {
    PENDIENTE: {CONFIRMADA, CANCELADA},
    CONFIRMADA: {ATENDIDA, CANCELADA},
    ATENDIDA: set(),
    CANCELADA: set(),
}


class AppointmentStatus(Base):
    __tablename__ = "appointment_statuses"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False)


class Appointment(TimestampMixin, Base):
    """Cita. La restricción de exclusión `ex_appointments_no_overlap` (ver migración inicial)
    impide en PostgreSQL dos citas activas del mismo barbero con rangos solapados."""

    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="range_order"),
        CheckConstraint("price >= 0", name="price_positive"),
        Index("ix_appointments_barber_start", "barber_id", "start_at"),
        Index("ix_appointments_client_start", "client_id", "start_at"),
        Index("ix_appointments_status", "status"),
        # Citas activas aún sin recordatorio (consulta de reminder_service cada minuto).
        Index("ix_appointments_reminder_due", "start_at",
              postgresql_where=text("reminder_sent_at IS NULL AND status IN ('PENDIENTE', 'CONFIRMADA')")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    barber_id: Mapped[int] = mapped_column(ForeignKey("barbers.id", ondelete="RESTRICT"), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(ForeignKey("appointment_statuses.code"), nullable=False, default=PENDIENTE)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(300))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    google_event_id: Mapped[str | None] = mapped_column(String(255))
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id", ondelete="SET NULL"), unique=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client = relationship("Client", lazy="joined")
    barber = relationship("Barber", lazy="joined")
    service = relationship("Service", lazy="joined")
    history = relationship(
        "AppointmentStatusHistory", back_populates="appointment", order_by="AppointmentStatusHistory.id"
    )


class AppointmentStatusHistory(Base):
    __tablename__ = "appointment_status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    appointment = relationship("Appointment", back_populates="history")
