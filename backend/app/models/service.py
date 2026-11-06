from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import StoredImageMixin, TimestampMixin


class Service(TimestampMixin, Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("price >= 0.10", name="price_min"),
        CheckConstraint("duration_minutes BETWEEN 5 AND 480", name="duration_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="fa-scissors", server_default="fa-scissors")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Ficha del servicio (la edita el personal): en qué consiste, qué incluye y oferta informativa.
    details: Mapped[str | None] = mapped_column(String(1000))
    includes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    offer: Mapped[str | None] = mapped_column(String(120))

    images = relationship("ServiceImage", lazy="selectin", order_by="ServiceImage.position",
                          cascade="all, delete-orphan", passive_deletes=True)


class ServiceImage(StoredImageMixin, Base):
    __tablename__ = "service_images"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_service_images_service_position", "service_id", "position"),
    )
    url_base = "/api/service-images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
