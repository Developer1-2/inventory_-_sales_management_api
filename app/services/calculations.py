from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, TypeAlias

from app.core.errors import AppError

StockEntry: TypeAlias = tuple[Decimal, Decimal]

MONEY_QUANTUM = Decimal("0.01")
ZERO = Decimal("0")


@dataclass(frozen=True)
class ProductResult:
    available: Decimal
    sold: Decimal
    unit_cost: Decimal
    revenue: Decimal
    cost_of_sold: Decimal
    profit: Decimal


def compute_available(
    opening_qty: Decimal,
    entries: Iterable[StockEntry],
) -> Decimal:
    return opening_qty + sum((quantity for quantity, _ in entries), ZERO)


def _weighted_average_cost(
    opening_qty: Decimal,
    opening_unit_cost: Decimal,
    entries: Iterable[StockEntry],
) -> Decimal:
    entries = tuple(entries)
    available = opening_qty + sum((quantity for quantity, _ in entries), ZERO)
    if available == ZERO:
        return ZERO

    total_cost = opening_qty * opening_unit_cost + sum(
        (quantity * buying_price for quantity, buying_price in entries),
        ZERO,
    )
    return total_cost / available


def compute_weighted_average_cost(
    opening_qty: Decimal,
    opening_unit_cost: Decimal,
    entries: Iterable[StockEntry],
) -> Decimal:
    return _weighted_average_cost(
        opening_qty,
        opening_unit_cost,
        entries,
    ).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def compute_sold(
    available: Decimal,
    unsold_qty: Decimal,
    lost_damaged_qty: Decimal,
) -> Decimal:
    sold = available - unsold_qty - lost_damaged_qty
    if sold < ZERO:
        raise AppError(
            422,
            "invalid_stock_count",
            "Unsold and lost/damaged quantities cannot exceed available stock",
        )
    return sold


def compute_product_result(
    opening_qty: Decimal,
    opening_unit_cost: Decimal,
    entries: Iterable[StockEntry],
    unsold_qty: Decimal,
    lost_damaged_qty: Decimal,
    selling_price: Decimal,
) -> ProductResult:
    entries = tuple(entries)
    available = compute_available(opening_qty, entries)
    sold = compute_sold(available, unsold_qty, lost_damaged_qty)
    unit_cost = _weighted_average_cost(opening_qty, opening_unit_cost, entries)

    return ProductResult(
        available=available,
        sold=sold,
        unit_cost=unit_cost.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP),
        revenue=(sold * selling_price).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP),
        cost_of_sold=(sold * unit_cost).quantize(
            MONEY_QUANTUM,
            rounding=ROUND_HALF_UP,
        ),
        profit=((sold * selling_price) - (sold * unit_cost)).quantize(
            MONEY_QUANTUM,
            rounding=ROUND_HALF_UP,
        ),
    )
