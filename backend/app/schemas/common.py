from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InputModel(BaseModel):
    """Entradas: rechaza campos desconocidos (evita asignaciones masivas como `role` o `is_active`)."""

    model_config = ConfigDict(extra="forbid", str_max_length=2000)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    message: str


class ImageOut(ORMModel):
    """Foto de una galería (producto o servicio). `url` es la ruta pública de la imagen."""

    id: int
    url: str


class ImageOrderIn(InputModel):
    """Orden completo de la galería: todos los ids de foto, el primero es la portada."""

    image_ids: list[int] = Field(min_length=1, max_length=50)
