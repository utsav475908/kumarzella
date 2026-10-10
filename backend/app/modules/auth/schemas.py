from datetime import datetime
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import EmailStr, Field, field_validator

from app.core.schemas import ApiModel


class RegisterIn(ApiModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    timezone: str = "America/New_York"

    @field_validator("timezone")
    @classmethod
    def valid_tz(cls, v: str) -> str:
        if v not in available_timezones():
            raise ValueError("Unknown IANA timezone")
        return v

    @field_validator("password")
    @classmethod
    def strong_enough(cls, v: str) -> str:
        if v.isalpha() or v.isdigit():
            raise ValueError("Password must mix letters with digits or symbols")
        return v


class LoginIn(ApiModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(ApiModel):
    id: UUID
    email: str
    display_name: str
    role: str
    timezone: str
    created_at: datetime


class SessionOut(ApiModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None
    ip: str | None
    user_agent: str | None
    current: bool = False
