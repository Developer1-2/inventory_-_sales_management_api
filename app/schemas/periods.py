from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class PeriodCreate(BaseModel):
    start_date: date


class PeriodCountOut(BaseModel):
    product_id: int
    opening_qty: Decimal
    opening_unit_cost: Decimal
    selling_price: Decimal
    unsold_qty: Decimal | None
    lost_damaged_qty: Decimal


class PeriodOut(BaseModel):
    id: int
    business_id: int
    location_id: int
    start_date: date
    end_date: date
    status: str


class PeriodDetailOut(PeriodOut):
    counts: list[PeriodCountOut] = Field(default_factory=list)
