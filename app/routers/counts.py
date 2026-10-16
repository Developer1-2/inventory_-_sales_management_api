from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.core.db import get_conn, transaction
from app.core.errors import AppError
from app.deps import AuthContext, get_auth
from app.schemas.counts import (
    BulkCountUpdate,
    CountUpdate,
    PeriodCountResult,
)
from app.services.calculations import (
    compute_available,
    compute_product_result,
    compute_sold,
    compute_weighted_average_cost,
)

router = APIRouter(tags=["counts"])
ZERO = Decimal("0")


def _period_for_user(conn, period_id: int, auth: AuthContext):
    period = conn.execute(
        text(
            "SELECT id, business_id, location_id, status FROM periods "
            "WHERE id = :period_id AND business_id = :business_id"
        ),
        {"period_id": period_id, "business_id": auth.business_id},
    ).mappings().one_or_none()
    if period is None:
        raise AppError(404, "period_not_found", "Period not found")
    if auth.location_ids != "all" and period["location_id"] not in auth.location_ids:
        raise AppError(404, "period_not_found", "Period not found")
    return period


def _count_rows(conn, period_id: int, auth: AuthContext) -> list[PeriodCountResult]:
    counts = conn.execute(
        text(
            "SELECT pc.product_id, p.name AS product_name, pc.opening_qty, "
            "pc.opening_unit_cost, pc.unsold_qty, pc.lost_damaged_qty, "
            "pc.selling_price, pc.recorded_by "
            "FROM period_counts pc "
            "JOIN products p ON p.id = pc.product_id AND p.business_id = pc.business_id "
            "WHERE pc.period_id = :period_id AND pc.business_id = :business_id "
            "ORDER BY pc.product_id"
        ),
        {"period_id": period_id, "business_id": auth.business_id},
    ).mappings().all()
    if not counts:
        return []

    entries = conn.execute(
        text(
            "SELECT product_id, quantity, buying_price FROM stock_entries "
            "WHERE period_id = :period_id AND business_id = :business_id "
            "ORDER BY product_id, id"
        ),
        {"period_id": period_id, "business_id": auth.business_id},
    ).mappings().all()
    entries_by_product: dict[int, list[tuple[Decimal, Decimal]]] = {}
    for entry in entries:
        entries_by_product.setdefault(int(entry["product_id"]), []).append(
            (Decimal(entry["quantity"]), Decimal(entry["buying_price"]))
        )

    results: list[PeriodCountResult] = []
    for count in counts:
        product_id = int(count["product_id"])
        product_entries = entries_by_product.get(product_id, [])
        opening_qty = Decimal(count["opening_qty"])
        opening_unit_cost = Decimal(count["opening_unit_cost"])
        lost_qty = Decimal(count["lost_damaged_qty"])
        selling_price = Decimal(count["selling_price"])
        available = compute_available(opening_qty, product_entries)
        unit_cost = compute_weighted_average_cost(
            opening_qty,
            opening_unit_cost,
            product_entries,
        )
        unsold_qty = (
            Decimal(count["unsold_qty"])
            if count["unsold_qty"] is not None
            else None
        )

        sold = revenue = cost_of_sold = profit = None
        if unsold_qty is not None:
            result = compute_product_result(
                opening_qty,
                opening_unit_cost,
                product_entries,
                unsold_qty,
                lost_qty,
                selling_price,
            )
            sold = result.sold
            unit_cost = result.unit_cost
            revenue = result.revenue
            cost_of_sold = result.cost_of_sold
            profit = result.profit

        results.append(
            PeriodCountResult(
                product_id=product_id,
                product_name=str(count["product_name"]),
                opening_qty=opening_qty,
                opening_unit_cost=opening_unit_cost,
                entries_qty=sum((qty for qty, _ in product_entries), ZERO),
                unsold_qty=unsold_qty,
                lost_damaged_qty=lost_qty,
                available=available,
                sold=sold,
                unit_cost=unit_cost,
                selling_price=selling_price,
                revenue=revenue,
                cost_of_sold=cost_of_sold,
                profit=profit,
                recorded_by=(
                    int(count["recorded_by"])
                    if count["recorded_by"] is not None
                    else None
                ),
            )
        )
    return results


def _apply_count(
    tx,
    period_id: int,
    product_id: int,
    payload: CountUpdate,
    auth: AuthContext,
) -> None:
    count = tx.execute(
        text(
            "SELECT id, opening_qty, opening_unit_cost, lost_damaged_qty, selling_price "
            "FROM period_counts WHERE period_id = :period_id AND product_id = :product_id "
            "AND business_id = :business_id FOR UPDATE"
        ),
        {
            "period_id": period_id,
            "product_id": product_id,
            "business_id": auth.business_id,
        },
    ).mappings().one_or_none()
    if count is None:
        raise AppError(404, "count_not_found", "Product count not found for this period")

    entry_rows = tx.execute(
        text(
            "SELECT quantity, buying_price FROM stock_entries "
            "WHERE period_id = :period_id AND product_id = :product_id "
            "AND business_id = :business_id"
        ),
        {
            "period_id": period_id,
            "product_id": product_id,
            "business_id": auth.business_id,
        },
    ).fetchall()
    entries = [(Decimal(row[0]), Decimal(row[1])) for row in entry_rows]
    available = compute_available(Decimal(count["opening_qty"]), entries)
    lost_qty = (
        payload.lost_damaged_qty
        if payload.lost_damaged_qty is not None
        else Decimal(count["lost_damaged_qty"])
    )
    compute_sold(available, payload.unsold_qty, lost_qty)

    tx.execute(
        text(
            "UPDATE period_counts SET unsold_qty = :unsold_qty, "
            "lost_damaged_qty = :lost_damaged_qty, "
            "selling_price = :selling_price, recorded_by = :recorded_by "
            "WHERE id = :count_id AND business_id = :business_id"
        ),
        {
            "unsold_qty": payload.unsold_qty,
            "lost_damaged_qty": lost_qty,
            "selling_price": (
                payload.selling_price
                if payload.selling_price is not None
                else count["selling_price"]
            ),
            "recorded_by": auth.user_id,
            "count_id": count["id"],
            "business_id": auth.business_id,
        },
    )


@router.get(
    "/periods/{period_id}/counts",
    response_model=list[PeriodCountResult],
)
def list_counts(
    period_id: int,
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
) -> list[PeriodCountResult]:
    _period_for_user(conn, period_id, auth)
    return _count_rows(conn, period_id, auth)


@router.put(
    "/periods/{period_id}/counts/{product_id}",
    response_model=PeriodCountResult,
)
def update_count(
    period_id: int,
    product_id: int,
    payload: CountUpdate,
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
) -> PeriodCountResult:
    _period_for_user(conn, period_id, auth)
    with transaction(conn) as tx:
        period = tx.execute(
            text(
                "SELECT status FROM periods WHERE id = :period_id "
                "AND business_id = :business_id FOR UPDATE"
            ),
            {"period_id": period_id, "business_id": auth.business_id},
        ).fetchone()
        if period is None:
            raise AppError(404, "period_not_found", "Period not found")
        if period[0] != "open":
            raise AppError(409, "period_closed", "Cannot update counts for a closed period")
        _apply_count(tx, period_id, product_id, payload, auth)
    rows = _count_rows(conn, period_id, auth)
    result = next((row for row in rows if row.product_id == product_id), None)
    if result is None:
        raise AppError(404, "count_not_found", "Product count not found for this period")
    return result


@router.put(
    "/periods/{period_id}/counts",
    response_model=list[PeriodCountResult],
)
def update_counts_bulk(
    period_id: int,
    payload: list[BulkCountUpdate],
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
) -> list[PeriodCountResult]:
    _period_for_user(conn, period_id, auth)
    product_ids = [item.product_id for item in payload]
    if len(product_ids) != len(set(product_ids)):
        raise AppError(422, "duplicate_products", "A product may only appear once in bulk counts")

    with transaction(conn) as tx:
        period = tx.execute(
            text(
                "SELECT status FROM periods WHERE id = :period_id "
                "AND business_id = :business_id FOR UPDATE"
            ),
            {"period_id": period_id, "business_id": auth.business_id},
        ).fetchone()
        if period is None:
            raise AppError(404, "period_not_found", "Period not found")
        if period[0] != "open":
            raise AppError(409, "period_closed", "Cannot update counts for a closed period")
        for item in payload:
            _apply_count(
                tx,
                period_id,
                item.product_id,
                CountUpdate(
                    unsold_qty=item.unsold_qty,
                    lost_damaged_qty=item.lost_damaged_qty,
                    selling_price=item.selling_price,
                ),
                auth,
            )
    return _count_rows(conn, period_id, auth)
