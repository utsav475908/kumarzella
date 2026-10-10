from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.core.schemas import ApiModel


class TagIn(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    category: Literal["general", "setup", "mistake", "emotion"] = "general"
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class TagPatch(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    category: Literal["general", "setup", "mistake", "emotion"] | None = None
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class TagOut(ApiModel):
    id: UUID
    name: str
    category: str
    color: str | None
    trade_count: int = 0


class DayNoteIn(ApiModel):
    body: str = Field(min_length=0, max_length=50000)


class DayNoteOut(ApiModel):
    day: date
    body: str
    updated_at: datetime
