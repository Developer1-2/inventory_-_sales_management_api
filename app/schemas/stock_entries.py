from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class StockEntryCreate(BaseModel):
    product_id: int = Field(..., gt=0)
    quantity: Decimal = Field(..., gt=0, max_digits=12, decimal_places=3)
    buying_price: Decimal = Field(..., ge=0, max_digits=12, decimal_places=2)
    entry_date: date


class StockEntryOut(BaseModel):
    id: int
    business_id: int
    location_id: int
    period_id: int
    product_id: int
    quantity: Decimal
    buying_price: Decimal
    entry_date: date
    recorded_by: int
