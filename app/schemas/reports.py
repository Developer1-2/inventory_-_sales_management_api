from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ReportMetrics(BaseModel):
    sold: Decimal
    revenue: Decimal
    cost_of_sold: Decimal
    profit: Decimal


class ProductReport(ReportMetrics):
    product_id: int
    product_name: str


class LocationReport(ReportMetrics):
    location_id: int
    location_name: str


class SummaryReport(BaseModel):
    date_from: date
    date_to: date
    totals: ReportMetrics
    products: list[ProductReport]
    locations: list[LocationReport]
