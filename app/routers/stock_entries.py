from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text

from app.core.db import get_conn, transaction
from app.core.errors import AppError
from app.deps import AuthContext, get_auth, require_role
from app.schemas.stock_entries import StockEntryCreate, StockEntryOut

router = APIRouter(tags=["stock entries"])


def _ensure_location_access(auth: AuthContext, location_id: int) -> None:
    if auth.location_ids != "all" and location_id not in auth.location_ids:
        raise AppError(404, "period_not_found", "Period not found")


@router.post(
    "/periods/{period_id}/stock-entries",
    response_model=StockEntryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_stock_entry(
    period_id: int,
    payload: StockEntryCreate,
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
) -> StockEntryOut:
    period = conn.execute(
        text(
            "SELECT id, business_id, location_id, start_date, end_date, status "
            "FROM periods WHERE id = :period_id AND business_id = :business_id"
        ),
        {"period_id": period_id, "business_id": auth.business_id},
    ).mappings().one_or_none()
    if period is None:
        raise AppError(404, "period_not_found", "Period not found")
    _ensure_location_access(auth, int(period["location_id"]))

    if period["status"] != "open":
        raise AppError(409, "period_closed", "Cannot add stock to a closed period")
    if not period["start_date"] <= payload.entry_date <= period["end_date"]:
        raise AppError(422, "entry_date_outside_period", "Entry date must fall within the period")

    product = conn.execute(
        text(
            "SELECT id, selling_price FROM products "
            "WHERE id = :product_id AND business_id = :business_id"
        ),
        {"product_id": payload.product_id, "business_id": auth.business_id},
    ).mappings().one_or_none()
    if product is None:
        raise AppError(404, "product_not_found", "Product not found")

    with transaction(conn) as tx:
        locked_period = tx.execute(
            text(
                "SELECT status FROM periods "
                "WHERE id = :period_id AND business_id = :business_id FOR UPDATE"
            ),
            {"period_id": period_id, "business_id": auth.business_id},
        ).mappings().one_or_none()
        if locked_period is None:
            raise AppError(404, "period_not_found", "Period not found")
        if locked_period["status"] != "open":
            raise AppError(409, "period_closed", "Cannot add stock to a closed period")

        count = tx.execute(
            text(
                "SELECT id FROM period_counts "
                "WHERE period_id = :period_id AND product_id = :product_id "
                "AND business_id = :business_id"
            ),
            {
                "period_id": period_id,
                "product_id": payload.product_id,
                "business_id": auth.business_id,
            },
        ).fetchone()
        if count is None:
            tx.execute(
                text(
                    "INSERT INTO period_counts "
                    "(business_id, location_id, period_id, product_id, opening_qty, "
                    "opening_unit_cost, selling_price) "
                    "VALUES (:business_id, :location_id, :period_id, :product_id, 0, 0, :selling_price)"
                ),
                {
                    "business_id": auth.business_id,
                    "location_id": period["location_id"],
                    "period_id": period_id,
                    "product_id": payload.product_id,
                    "selling_price": product["selling_price"],
                },
            )

        result = tx.execute(
            text(
                "INSERT INTO stock_entries "
                "(business_id, location_id, period_id, product_id, quantity, buying_price, "
                "entry_date, recorded_by) "
                "VALUES (:business_id, :location_id, :period_id, :product_id, :quantity, "
                ":buying_price, :entry_date, :recorded_by)"
            ),
            {
                "business_id": auth.business_id,
                "location_id": period["location_id"],
                "period_id": period_id,
                "product_id": payload.product_id,
                "quantity": payload.quantity,
                "buying_price": payload.buying_price,
                "entry_date": payload.entry_date,
                "recorded_by": auth.user_id,
            },
        )
        entry_id = int(result.lastrowid)

    row = conn.execute(
        text(
            "SELECT id, business_id, location_id, period_id, product_id, quantity, "
            "buying_price, entry_date, recorded_by FROM stock_entries "
            "WHERE id = :entry_id AND business_id = :business_id"
        ),
        {"entry_id": entry_id, "business_id": auth.business_id},
    ).mappings().one()
    return StockEntryOut(**dict(row))


@router.get("/periods/{period_id}/stock-entries", response_model=list[StockEntryOut])
def list_stock_entries(
    period_id: int,
    product_id: int | None = Query(default=None, gt=0),
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
) -> list[StockEntryOut]:
    period = conn.execute(
        text(
            "SELECT id, location_id FROM periods "
            "WHERE id = :period_id AND business_id = :business_id"
        ),
        {"period_id": period_id, "business_id": auth.business_id},
    ).fetchone()
    if period is None:
        raise AppError(404, "period_not_found", "Period not found")
    _ensure_location_access(auth, int(period[1]))

    query = (
        "SELECT id, business_id, location_id, period_id, product_id, quantity, "
        "buying_price, entry_date, recorded_by FROM stock_entries "
        "WHERE period_id = :period_id AND business_id = :business_id"
    )
    params: dict[str, object] = {
        "period_id": period_id,
        "business_id": auth.business_id,
    }
    if product_id is not None:
        query += " AND product_id = :product_id"
        params["product_id"] = product_id
    query += " ORDER BY entry_date, id"
    rows = conn.execute(text(query), params).mappings().all()
    return [StockEntryOut(**dict(row)) for row in rows]


@router.delete("/stock-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stock_entry(
    entry_id: int,
    auth: AuthContext = Depends(require_role("owner", "manager")),
    conn=Depends(get_conn),
) -> None:
    row = conn.execute(
        text(
            "SELECT se.id, se.period_id, se.location_id "
            "FROM stock_entries se "
            "WHERE se.id = :entry_id AND se.business_id = :business_id"
        ),
        {"entry_id": entry_id, "business_id": auth.business_id},
    ).fetchone()
    if row is None:
        raise AppError(404, "stock_entry_not_found", "Stock entry not found")
    _ensure_location_access(auth, int(row[2]))

    with transaction(conn) as tx:
        period = tx.execute(
            text(
                "SELECT status FROM periods "
                "WHERE id = :period_id AND business_id = :business_id FOR UPDATE"
            ),
            {"period_id": row[1], "business_id": auth.business_id},
        ).fetchone()
        if period is None:
            raise AppError(404, "period_not_found", "Period not found")
        if period[0] != "open":
            raise AppError(409, "period_closed", "Cannot delete stock from a closed period")
        result = tx.execute(
            text(
                "DELETE FROM stock_entries "
                "WHERE id = :entry_id AND business_id = :business_id"
            ),
            {"entry_id": entry_id, "business_id": auth.business_id},
        )
        if result.rowcount == 0:
            raise AppError(404, "stock_entry_not_found", "Stock entry not found")
