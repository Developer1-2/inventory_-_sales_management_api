from decimal import Decimal

import pytest

from app.core.errors import AppError
from app.services.calculations import (
    ProductResult,
    compute_available,
    compute_product_result,
    compute_sold,
    compute_weighted_average_cost,
)


def test_weighted_average_product_result():
    result = compute_product_result(
        opening_qty=Decimal("10"),
        opening_unit_cost=Decimal("100"),
        entries=[(Decimal("20"), Decimal("130"))],
        unsold_qty=Decimal("5"),
        lost_damaged_qty=Decimal("1"),
        selling_price=Decimal("200"),
    )

    assert result == ProductResult(
        available=Decimal("30"),
        sold=Decimal("24"),
        unit_cost=Decimal("120.00"),
        revenue=Decimal("4800.00"),
        cost_of_sold=Decimal("2880.00"),
        profit=Decimal("1920.00"),
    )


def test_no_entries_keeps_opening_available_and_cost():
    assert compute_available(Decimal("0"), []) == Decimal("0")
    assert compute_weighted_average_cost(Decimal("0"), Decimal("0"), []) == Decimal(
        "0.00"
    )

    result = compute_product_result(
        opening_qty=Decimal("0"),
        opening_unit_cost=Decimal("0"),
        entries=[],
        unsold_qty=Decimal("0"),
        lost_damaged_qty=Decimal("0"),
        selling_price=Decimal("25"),
    )
    assert result.available == Decimal("0")
    assert result.sold == Decimal("0")
    assert result.revenue == Decimal("0.00")
    assert result.cost_of_sold == Decimal("0.00")
    assert result.profit == Decimal("0.00")


def test_rejects_count_above_available_stock():
    with pytest.raises(AppError) as error:
        compute_sold(
            available=Decimal("10"),
            unsold_qty=Decimal("8"),
            lost_damaged_qty=Decimal("3"),
        )

    assert error.value.status_code == 422
    assert error.value.code == "invalid_stock_count"


def test_money_rounds_half_up_only_for_result_values():
    result = compute_product_result(
        opening_qty=Decimal("0"),
        opening_unit_cost=Decimal("0"),
        entries=[(Decimal("3"), Decimal("0.335"))],
        unsold_qty=Decimal("0"),
        lost_damaged_qty=Decimal("0"),
        selling_price=Decimal("1.005"),
    )

    assert result.unit_cost == Decimal("0.34")
    assert result.revenue == Decimal("3.02")
    assert result.cost_of_sold == Decimal("1.01")
    assert result.profit == Decimal("2.01")
