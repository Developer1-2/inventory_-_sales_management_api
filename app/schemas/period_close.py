from decimal import Decimal

from pydantic import BaseModel


class ClosedProductSummary(BaseModel):
    product_id: int
    available: Decimal
    sold: Decimal
    unit_cost: Decimal
    revenue: Decimal
    cost_of_sold: Decimal
    profit: Decimal


class PeriodCloseResponse(BaseModel):
    closed_period_id: int
    new_period_id: int
    summary: list[ClosedProductSummary]
