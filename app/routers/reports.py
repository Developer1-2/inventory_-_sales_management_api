from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import bindparam, text

from app.core.db import get_conn
from app.core.errors import AppError
from app.deps import AuthContext, get_auth
from app.schemas.reports import (
    LocationReport,
    ProductReport,
    ReportMetrics,
    SummaryReport,
)
from app.services.calculations import compute_product_result

router = APIRouter(tags=["reports"])
METRIC_FIELDS = ("sold", "revenue", "cost_of_sold", "profit")


def _empty_metrics() -> dict[str, Decimal]:
    return {field: Decimal("0") for field in METRIC_FIELDS}


def _add_result(target: dict[str, Decimal], result) -> None:
    for field in METRIC_FIELDS:
        target[field] += getattr(result, field)


@router.get("/reports/summary", response_model=SummaryReport)
def get_summary_report(
    date_from: date,
    date_to: date,
    location_id: int | None = Query(default=None, gt=0),
    product_id: int | None = Query(default=None, gt=0),
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
) -> SummaryReport:
    if date_from > date_to:
        raise AppError(422, "invalid_date_range", "date_from must be on or before date_to")

    if product_id is not None:
        product = conn.execute(
            text(
                "SELECT id FROM products "
                "WHERE id = :product_id AND business_id = :business_id"
            ),
            {"product_id": product_id, "business_id": auth.business_id},
        ).fetchone()
        if product is None:
            raise AppError(404, "product_not_found", "Product not found")

    if location_id is not None:
        if auth.location_ids != "all" and location_id not in auth.location_ids:
            raise AppError(404, "location_not_found", "Location not found")
        location = conn.execute(
            text(
                "SELECT id FROM locations "
                "WHERE id = :location_id AND business_id = :business_id"
            ),
            {"location_id": location_id, "business_id": auth.business_id},
        ).fetchone()
        if location is None:
            raise AppError(404, "location_not_found", "Location not found")
        accessible_location_ids = None
    elif auth.location_ids == "all":
        accessible_location_ids = None
    else:
        accessible_location_ids = auth.location_ids
        if not accessible_location_ids:
            return _empty_report(date_from, date_to)

    query = (
        "SELECT p.id AS period_id, p.location_id, l.name AS location_name, "
        "pc.product_id, pr.name AS product_name, pc.opening_qty, "
        "pc.opening_unit_cost, pc.unsold_qty, pc.lost_damaged_qty, pc.selling_price "
        "FROM periods p "
        "JOIN period_counts pc ON pc.period_id = p.id AND pc.business_id = p.business_id "
        "JOIN products pr ON pr.id = pc.product_id AND pr.business_id = pc.business_id "
        "JOIN locations l ON l.id = p.location_id AND l.business_id = p.business_id "
        "WHERE p.business_id = :business_id AND p.status = 'closed' "
        "AND p.start_date >= :date_from AND p.end_date <= :date_to"
    )
    params: dict[str, object] = {
        "business_id": auth.business_id,
        "date_from": date_from,
        "date_to": date_to,
    }
    if location_id is not None:
        query += " AND p.location_id = :location_id"
        params["location_id"] = location_id
    elif accessible_location_ids is not None:
        query += " AND p.location_id IN :location_ids"
        params["location_ids"] = accessible_location_ids
    if product_id is not None:
        query += " AND pc.product_id = :product_id"
        params["product_id"] = product_id
    query += " ORDER BY p.location_id, pc.product_id, p.id"

    statement = text(query)
    if accessible_location_ids is not None and location_id is None:
        statement = statement.bindparams(bindparam("location_ids", expanding=True))
    rows = conn.execute(statement, params).mappings().all()
    if not rows:
        return _empty_report(date_from, date_to)

    period_ids = sorted({int(row["period_id"]) for row in rows})
    entries = conn.execute(
        text(
            "SELECT period_id, product_id, quantity, buying_price FROM stock_entries "
            "WHERE business_id = :business_id AND period_id IN :period_ids "
            "ORDER BY period_id, product_id, id"
        ).bindparams(bindparam("period_ids", expanding=True)),
        {"business_id": auth.business_id, "period_ids": period_ids},
    ).mappings().all()
    entries_by_period_product: dict[tuple[int, int], list[tuple[Decimal, Decimal]]] = defaultdict(list)
    for entry in entries:
        key = (int(entry["period_id"]), int(entry["product_id"]))
        entries_by_period_product[key].append(
            (Decimal(str(entry["quantity"])), Decimal(str(entry["buying_price"])))
        )

    totals = _empty_metrics()
    products: dict[int, dict[str, object]] = {}
    locations: dict[int, dict[str, object]] = {}
    for row in rows:
        current_product_id = int(row["product_id"])
        current_location_id = int(row["location_id"])
        result = compute_product_result(
            Decimal(str(row["opening_qty"])),
            Decimal(str(row["opening_unit_cost"])),
            entries_by_period_product[(int(row["period_id"]), current_product_id)],
            Decimal(str(row["unsold_qty"])),
            Decimal(str(row["lost_damaged_qty"])),
            Decimal(str(row["selling_price"])),
        )

        product = products.setdefault(
            current_product_id,
            {"product_name": str(row["product_name"]), **_empty_metrics()},
        )
        location = locations.setdefault(
            current_location_id,
            {"location_name": str(row["location_name"]), **_empty_metrics()},
        )
        _add_result(totals, result)
        _add_result(product, result)
        _add_result(location, result)

    return SummaryReport(
        date_from=date_from,
        date_to=date_to,
        totals=ReportMetrics(**totals),
        products=[
            ProductReport(
                product_id=current_product_id,
                **values,
            )
            for current_product_id, values in sorted(products.items())
        ],
        locations=[
            LocationReport(
                location_id=current_location_id,
                **values,
            )
            for current_location_id, values in sorted(locations.items())
        ],
    )


def _empty_report(date_from: date, date_to: date) -> SummaryReport:
    return SummaryReport(
        date_from=date_from,
        date_to=date_to,
        totals=ReportMetrics(**_empty_metrics()),
        products=[],
        locations=[],
    )
