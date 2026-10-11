from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.core.schemas import ApiModel


class TagRef(ApiModel):
    id: UUID
    name: str
    category: str
    color: str | None = None


class TradeOut(ApiModel):
    id: UUID
    account_id: UUID
    account_name: str
    instrument_id: UUID
    symbol: str
    asset_class: str
    multiplier: Decimal
    direction: str
    status: str
    origin: str
    currency: str
    opened_at: datetime
    closed_at: datetime | None
    session_date: date
    entry_session: str
    entry_qty: Decimal
    exit_qty: Decimal
    peak_qty: Decimal
    open_qty: Decimal
    entry_avg_price: Decimal
    exit_avg_price: Decimal | None
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    holding_seconds: int | None
    execution_count: int
    planned_stop_price: Decimal | None
    planned_target_price: Decimal | None
    planned_risk_amount: Decimal | None
    initial_risk: Decimal | None
    r_multiple: Decimal | None
    mae: Decimal | None = None
    mfe: Decimal | None = None
    playbook_id: UUID | None
    playbook_name: str | None = None
    playbook_version_id: UUID | None = None
    playbook_version: int | None = None
    followed_plan: bool | None
    rating: int | None
    tags: list[TagRef] = []
    is_demo: bool = False


class SourceRef(ApiModel):
    import_job_id: UUID | None
    filename: str | None
    row_number: int | None
    raw: dict | None


class ExecutionLeg(ApiModel):
    execution_id: UUID
    executed_at: datetime
    side: str
    quantity: Decimal
    price: Decimal
    commission: Decimal
    fees: Decimal
    source: str
    source_execution_id: str | None
    role: str
    allocated_quantity: Decimal
    fees_allocated: Decimal
    realized_pnl: Decimal
    position_after: Decimal
    shared_with_other_trade: bool
    source_ref: SourceRef | None


class NoteOut(ApiModel):
    id: UUID
    body: str
    created_at: datetime
    updated_at: datetime


class AttachmentOut(ApiModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class AuditOut(ApiModel):
    id: UUID
    action: str
    data: dict | None
    created_at: datetime


class TradeDetail(TradeOut):
    executions: list[ExecutionLeg]
    notes: list[NoteOut]
    day_note: str | None
    attachments: list[AttachmentOut]
    audit: list[AuditOut]
    prev_trade_id: UUID | None
    next_trade_id: UUID | None
    calculation: dict


class TradePatch(ApiModel):
    planned_stop_price: Decimal | None = Field(None, ge=0)
    planned_target_price: Decimal | None = Field(None, ge=0)
    planned_risk_amount: Decimal | None = Field(None, gt=0)
    playbook_id: UUID | None = None
    followed_plan: bool | None = None
    rating: int | None = Field(None, ge=1, le=5)
    tag_ids: list[UUID] | None = None


class ManualExecutionIn(ApiModel):
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    price: Decimal = Field(ge=0, max_digits=24, decimal_places=10)
    commission: Decimal = Field(Decimal(0), ge=0)
    fees: Decimal = Field(Decimal(0), ge=0)
    executed_at: datetime

    @field_validator("executed_at")
    @classmethod
    def aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must include a UTC offset")
        return v


class ManualTradeIn(ApiModel):
    account_id: UUID
    symbol: str = Field(min_length=1, max_length=64)
    asset_class: Literal["stock", "etf", "option", "future", "forex", "crypto"] | None = None
    multiplier: Decimal | None = Field(None, gt=0)
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    executions: list[ManualExecutionIn] = Field(min_length=1, max_length=200)
    planned_stop_price: Decimal | None = Field(None, ge=0)
    planned_target_price: Decimal | None = Field(None, ge=0)
    playbook_id: UUID | None = None
    note: str | None = Field(None, max_length=20000)


class NoteIn(ApiModel):
    body: str = Field(min_length=1, max_length=20000)
