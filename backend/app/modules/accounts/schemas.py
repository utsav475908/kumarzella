from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import Field, field_validator

from app.core.schemas import ApiModel


class AccountIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    broker: str | None = Field(None, max_length=120)
    account_type: Literal["live", "paper", "demo"] = "live"
    base_currency: str = Field("USD", pattern=r"^[A-Z]{3}$")
    timezone: str = "America/New_York"
    accounting_policy: Literal["average_cost", "fifo"] = "average_cost"
    starting_balance: Decimal | None = Field(None, ge=0)
    max_risk_per_trade: Decimal | None = Field(None, gt=0)
    daily_loss_limit: Decimal | None = Field(None, gt=0)

    @field_validator("timezone")
    @classmethod
    def tz(cls, v: str) -> str:
        if v not in available_timezones():
            raise ValueError("Unknown IANA timezone")
        return v


class AccountPatch(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    broker: str | None = Field(None, max_length=120)
    accounting_policy: Literal["average_cost", "fifo"] | None = None
    starting_balance: Decimal | None = Field(None, ge=0)
    max_risk_per_trade: Decimal | None = Field(None, gt=0)
    daily_loss_limit: Decimal | None = Field(None, gt=0)
    archived: bool | None = None


class AccountOut(ApiModel):
    id: UUID
    name: str
    broker: str | None
    account_type: str
    base_currency: str
    timezone: str
    accounting_policy: str
    starting_balance: Decimal | None
    max_risk_per_trade: Decimal | None
    daily_loss_limit: Decimal | None
    is_demo: bool
    archived_at: datetime | None
    created_at: datetime


class CashTransactionIn(ApiModel):
    kind: Literal["deposit", "withdrawal"]
    amount: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    occurred_at: datetime
    note: str | None = Field(None, max_length=1000)

    @field_validator("occurred_at")
    @classmethod
    def aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must include a UTC offset")
        return v


class CashTransactionOut(ApiModel):
    id: UUID
    kind: str
    amount: Decimal
    currency: str
    occurred_at: datetime
    note: str | None
