from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Table,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

barber_services = Table(
    "barber_services",
    Base.metadata,
    Column("barber_id", ForeignKey("barbers.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)


class Barber(TimestampMixin, Base):
    __tablename__ = "barbers"
    __table_args__ = (CheckConstraint("rating >= 0 AND rating <= 5", name="rating_range"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    full_name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    photo_url: Mapped[str | None] = mapped_column(String(500))
    rating: Mapped[Decimal] = mapped_column(Numeric(2, 1), nullable=False, default=Decimal("5.0"))
    # is_active = baja lógica; is_available = acepta reservas temporalmente.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    user = relationship("User", back_populates="barber")
    services = relationship("Service", secondary=barber_services, order_by="Service.id")
    schedules = relationship(
        "BarberSchedule", back_populates="barber", cascade="all, delete-orphan", order_by="BarberSchedule.weekday"
    )


class BarberSchedule(Base):
    """Horario semanal. weekday: 0=lunes … 6=domingo. Sin fila = día no laborable."""

    __tablename__ = "barber_schedules"
    __table_args__ = (
        UniqueConstraint("barber_id", "weekday", name="uq_barber_schedules_barber_weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="time_order"),
        CheckConstraint(
            "(break_start IS NULL AND break_end IS NULL) OR "
            "(break_start IS NOT NULL AND break_end IS NOT NULL AND break_start >= start_time "
            "AND break_end <= end_time AND break_end > break_start)",
            name="break_inside",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    barber_id: Mapped[int] = mapped_column(ForeignKey("barbers.id", ondelete="CASCADE"), nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_start: Mapped[time | None] = mapped_column(Time)
    break_end: Mapped[time | None] = mapped_column(Time)

    barber = relationship("Barber", back_populates="schedules")


class BarberTimeOff(Base):
    """Bloqueos: vacaciones, días no laborables puntuales, permisos."""

    __tablename__ = "barber_time_off"
    __table_args__ = (CheckConstraint("end_at > start_at", name="range_order"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    barber_id: Mapped[int] = mapped_column(ForeignKey("barbers.id", ondelete="CASCADE"), nullable=False, index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
