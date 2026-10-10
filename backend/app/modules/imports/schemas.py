from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import Field, field_validator

from app.core.schemas import ApiModel


class ColumnMapping(ApiModel):
    """Maps CSV header names to execution fields. Either `timestamp` or `date` (+ optional `time`) is required."""

    timestamp: str | None = None
    date: str | None = None
    time: str | None = None
    symbol: str
    side: str | None = None
    quantity: str
    price: str
    commission: str | None = None
    fees: str | None = None
    execution_id: str | None = None
    asset_class: str | None = None
    currency: str | None = None
    multiplier: str | None = None


class ImportOptions(ApiModel):
    timezone: str = "America/New_York"
    datetime_format: str | None = Field(None, description="strptime format; auto-detected when omitted")
    side_from_quantity_sign: bool = False
    default_asset_class: Literal["stock", "etf", "option", "future", "forex", "crypto"] | None = None
    side_aliases: dict[str, Literal["buy", "sell"]] = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def tz(cls, v: str) -> str:
        if v not in available_timezones() and v != "UTC":
            raise ValueError("Unknown IANA timezone")
        return v


class PreviewIn(ApiModel):
    mapping: ColumnMapping
    options: ImportOptions = Field(default_factory=ImportOptions)
    preset: str | None = None


class ImportJobOut(ApiModel):
    id: UUID
    account_id: UUID
    filename: str
    file_size: int
    status: str
    headers: list[str]
    mapping: dict | None
    total_rows: int
    valid_rows: int
    rejected_rows: int
    duplicate_rows: int
    imported_rows: int
    error_message: str | None
    summary: dict | None
    created_at: datetime
    committed_at: datetime | None


class UploadOut(ImportJobOut):
    suggested_mapping: dict
    detected_preset: str | None
    sample_rows: list[dict]


class RawRecordOut(ApiModel):
    id: UUID
    row_number: int
    raw: dict
    normalized: dict | None
    status: str
    errors: list
    warnings: list
    duplicate_of_execution_id: UUID | None


class PreviewOut(ApiModel):
    job: ImportJobOut
    rows: list[RawRecordOut]


class PresetOut(ApiModel):
    key: str
    name: str
    description: str
    mapping: dict
    options: dict
