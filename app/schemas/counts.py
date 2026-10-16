from decimal import Decimal

from pydantic import BaseModel, Field


class CountUpdate(BaseModel):
    unsold_qty: Decimal = Field(..., ge=0, max_digits=12, decimal_places=3)
    lost_damaged_qty: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=3,
    )
    selling_price: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )


class BulkCountUpdate(CountUpdate):
    product_id: int = Field(..., gt=0)


class PeriodCountResult(BaseModel):
    product_id: int
    product_name: str
    opening_qty: Decimal
    opening_unit_cost: Decimal
    entries_qty: Decimal
    unsold_qty: Decimal | None
    lost_damaged_qty: Decimal
    available: Decimal
    sold: Decimal | None
    unit_cost: Decimal
    selling_price: Decimal
    revenue: Decimal | None
    cost_of_sold: Decimal | None
    profit: Decimal | None
    recorded_by: int | None
