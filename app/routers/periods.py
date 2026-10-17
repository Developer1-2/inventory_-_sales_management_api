from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.core.db import get_conn, transaction
from app.core.errors import AppError
from app.deps import AuthContext, get_auth, require_location_access, require_role
from app.schemas.period_close import PeriodCloseResponse
from app.schemas.periods import PeriodCreate, PeriodCountOut, PeriodDetailOut, PeriodOut
from app.services.calculations import compute_product_result

router = APIRouter(tags=["periods"])


def calculate_end_date(start_date: date, period_length: str) -> date:
    if period_length == "weekly":
        return start_date + timedelta(days=6)
    if period_length == "monthly":
        return start_date.replace(day=calendar.monthrange(start_date.year, start_date.month)[1])
    raise AppError(500, "invalid_period_length", "Business has an unsupported period length")


def _period_out(row) -> PeriodOut:
    return PeriodOut(
        id=int(row["id"]),
        business_id=int(row["business_id"]),
        location_id=int(row["location_id"]),
        start_date=row["start_date"],
        end_date=row["end_date"],
        status=str(row["status"]),
    )


@router.post(
    "/locations/{location_id}/periods",
    response_model=PeriodOut,
    status_code=201,
)
def create_period(
    location_id: int,
    payload: PeriodCreate,
    auth: AuthContext = Depends(require_location_access),
    conn=Depends(get_conn),
) -> PeriodOut:
    location = conn.execute(
        text(
            "SELECT id FROM locations "
            "WHERE id = :location_id AND business_id = :business_id"
        ),
        {"location_id": location_id, "business_id": auth.business_id},
    ).fetchone()
    if location is None:
        raise AppError(404, "location_not_found", "Location not found")

    settings_row = conn.execute(
        text(
            "SELECT period_length FROM business_settings "
            "WHERE business_id = :business_id"
        ),
        {"business_id": auth.business_id},
    ).fetchone()
    if settings_row is None:
        raise AppError(500, "business_settings_missing", "Business settings not found")

    end_date = calculate_end_date(payload.start_date, settings_row[0])

    with transaction(conn) as tx:
        tx.execute(
            text(
                "SELECT id FROM locations "
                "WHERE id = :location_id AND business_id = :business_id FOR UPDATE"
            ),
            {"business_id": auth.business_id, "location_id": location_id},
        )
        open_period = tx.execute(
            text(
                "SELECT id FROM periods "
                "WHERE business_id = :business_id AND location_id = :location_id "
                "AND status = 'open' FOR UPDATE"
            ),
            {"business_id": auth.business_id, "location_id": location_id},
        ).fetchone()
        if open_period is not None:
            raise AppError(409, "open_period_exists", "An open period already exists for this location")

        duplicate_start = tx.execute(
            text(
                "SELECT id FROM periods WHERE business_id = :business_id "
                "AND location_id = :location_id AND start_date = :start_date"
            ),
            {
                "business_id": auth.business_id,
                "location_id": location_id,
                "start_date": payload.start_date,
            },
        ).fetchone()
        if duplicate_start is not None:
            raise AppError(409, "period_start_exists", "A period already exists with this start date")

        result = tx.execute(
            text(
                "INSERT INTO periods "
                "(business_id, location_id, start_date, end_date, status) "
                "VALUES (:business_id, :location_id, :start_date, :end_date, 'open')"
            ),
            {
                "business_id": auth.business_id,
                "location_id": location_id,
                "start_date": payload.start_date,
                "end_date": end_date,
            },
        )
        period_id = int(result.lastrowid)
        tx.execute(
            text(
                "INSERT INTO period_counts "
                "(business_id, location_id, period_id, product_id, opening_qty, "
                "opening_unit_cost, selling_price) "
                "SELECT :business_id, :location_id, :period_id, id, 0, 0, selling_price "
                "FROM products WHERE business_id = :business_id AND is_active = 1"
            ),
            {
                "business_id": auth.business_id,
                "location_id": location_id,
                "period_id": period_id,
            },
        )

    row = conn.execute(
        text(
            "SELECT id, business_id, location_id, start_date, end_date, status "
            "FROM periods WHERE id = :period_id AND business_id = :business_id"
        ),
        {"period_id": period_id, "business_id": auth.business_id},
    ).mappings().one()
    return _period_out(row)


@router.get("/locations/{location_id}/periods", response_model=list[PeriodOut])
def list_periods(
    location_id: int,
    auth: AuthContext = Depends(require_location_access),
    conn=Depends(get_conn),
) -> list[PeriodOut]:
    location = conn.execute(
        text(
            "SELECT id FROM locations "
            "WHERE id = :location_id AND business_id = :business_id"
        ),
        {"location_id": location_id, "business_id": auth.business_id},
    ).fetchone()
    if location is None:
        raise AppError(404, "location_not_found", "Location not found")

    rows = conn.execute(
        text(
            "SELECT id, business_id, location_id, start_date, end_date, status "
            "FROM periods WHERE business_id = :business_id AND location_id = :location_id "
            "ORDER BY start_date DESC, id DESC"
        ),
        {"business_id": auth.business_id, "location_id": location_id},
    ).mappings().all()
    return [_period_out(row) for row in rows]


@router.get("/periods/{period_id}", response_model=PeriodDetailOut)
def get_period(
    period_id: int,
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
) -> PeriodDetailOut:
    row = conn.execute(
        text(
            "SELECT id, business_id, location_id, start_date, end_date, status "
            "FROM periods WHERE id = :period_id AND business_id = :business_id"
        ),
        {"period_id": period_id, "business_id": auth.business_id},
    ).mappings().one_or_none()
    if row is None:
        raise AppError(404, "period_not_found", "Period not found")

    if auth.location_ids != "all" and row["location_id"] not in auth.location_ids:
        raise AppError(404, "period_not_found", "Period not found")

    count_rows = conn.execute(
        text(
            "SELECT product_id, opening_qty, opening_unit_cost, selling_price, "
            "unsold_qty, lost_damaged_qty FROM period_counts "
            "WHERE period_id = :period_id AND business_id = :business_id "
            "ORDER BY product_id"
        ),
        {"period_id": period_id, "business_id": auth.business_id},
    ).mappings().all()
    period = _period_out(row)
    return PeriodDetailOut(
        **period.model_dump(),
        counts=[PeriodCountOut(**dict(count)) for count in count_rows],
    )


@router.post("/periods/{period_id}/close", response_model=PeriodCloseResponse)
def close_period(
    period_id: int,
    auth: AuthContext = Depends(require_role("owner", "manager")),
    conn=Depends(get_conn),
) -> PeriodCloseResponse:
    if auth.location_ids != "all":
        period_access = conn.execute(
            text(
                "SELECT location_id FROM periods "
                "WHERE id = :period_id AND business_id = :business_id"
            ),
            {"period_id": period_id, "business_id": auth.business_id},
        ).fetchone()
        if period_access is None:
            raise AppError(404, "period_not_found", "Period not found")
        if int(period_access[0]) not in auth.location_ids:
            raise AppError(404, "period_not_found", "Period not found")

    with transaction(conn) as tx:
        period = tx.execute(
            text(
                "SELECT id, business_id, location_id, start_date, end_date, status "
                "FROM periods WHERE id = :period_id AND business_id = :business_id FOR UPDATE"
            ),
            {"period_id": period_id, "business_id": auth.business_id},
        ).mappings().one_or_none()
        if period is None:
            raise AppError(404, "period_not_found", "Period not found")
        if period["status"] != "open":
            raise AppError(409, "period_already_closed", "Period is already closed")

        count_rows = tx.execute(
            text(
                "SELECT pc.id, pc.product_id, pc.opening_qty, pc.opening_unit_cost, "
                "pc.lost_damaged_qty, pc.unsold_qty, pc.selling_price "
                "FROM period_counts pc "
                "WHERE pc.period_id = :period_id AND pc.business_id = :business_id "
                "ORDER BY pc.product_id"
            ),
            {"period_id": period_id, "business_id": auth.business_id},
        ).mappings().all()

        missing = []
        for count in count_rows:
            if count["unsold_qty"] is None:
                missing.append(int(count["product_id"]))

        if missing:
            raise AppError(
                422,
                "missing_unsold_qty",
                f"Missing unsold quantity for products: {missing}",
            )

        closed_summary = []
        next_period_products = []
        for count in count_rows:
            product_id = int(count["product_id"])
            opening_qty = Decimal(str(count["opening_qty"]))
            opening_unit_cost = Decimal(str(count["opening_unit_cost"]))
            unsold_qty = Decimal(str(count["unsold_qty"]))
            lost_damaged_qty = Decimal(str(count["lost_damaged_qty"]))
            selling_price = Decimal(str(count["selling_price"]))

            entries = tx.execute(
                text(
                    "SELECT quantity, buying_price FROM stock_entries "
                    "WHERE period_id = :period_id AND product_id = :product_id "
                    "AND business_id = :business_id"
                ),
                {"period_id": period_id, "product_id": product_id, "business_id": auth.business_id},
            ).fetchall()
            entry_values = [(Decimal(str(item[0])), Decimal(str(item[1]))) for item in entries]
            result = compute_product_result(
                opening_qty,
                opening_unit_cost,
                entry_values,
                unsold_qty,
                lost_damaged_qty,
                selling_price,
            )

            tx.execute(
                text(
                    "UPDATE period_counts SET sold_qty = :sold_qty, unit_cost_used = :unit_cost_used "
                    "WHERE id = :count_id AND business_id = :business_id"
                ),
                {
                    "sold_qty": result.sold,
                    "unit_cost_used": result.unit_cost,
                    "count_id": count["id"],
                    "business_id": auth.business_id,
                },
            )

            closed_summary.append(
                {
                    "product_id": product_id,
                    "available": str(result.available),
                    "sold": str(result.sold),
                    "unit_cost": str(result.unit_cost),
                    "revenue": str(result.revenue),
                    "cost_of_sold": str(result.cost_of_sold),
                    "profit": str(result.profit),
                }
            )
            next_period_products.append(
                {
                    "product_id": product_id,
                    "opening_qty": str(unsold_qty),
                    "opening_unit_cost": str(result.unit_cost),
                    "selling_price": str(selling_price),
                }
            )

        settings_row = tx.execute(
            text("SELECT period_length FROM business_settings WHERE business_id = :business_id"),
            {"business_id": auth.business_id},
        ).fetchone()
        if settings_row is None:
            raise AppError(500, "business_settings_missing", "Business settings not found")

        next_start = period["end_date"] + timedelta(days=1)
        next_end = calculate_end_date(next_start, settings_row[0])
        next_period_result = tx.execute(
            text(
                "INSERT INTO periods (business_id, location_id, start_date, end_date, status) "
                "VALUES (:business_id, :location_id, :start_date, :end_date, 'open')"
            ),
            {
                "business_id": auth.business_id,
                "location_id": period["location_id"],
                "start_date": next_start,
                "end_date": next_end,
            },
        )
        next_period_id = int(next_period_result.lastrowid)

        for product in next_period_products:
            tx.execute(
                text(
                    "INSERT INTO period_counts (business_id, location_id, period_id, product_id, "
                    "opening_qty, opening_unit_cost, entries_qty, entries_cost, lost_damaged_qty, "
                    "selling_price) VALUES (:business_id, :location_id, :period_id, :product_id, "
                    ":opening_qty, :opening_unit_cost, 0, 0, 0, :selling_price)"
                ),
                {
                    "business_id": auth.business_id,
                    "location_id": period["location_id"],
                    "period_id": next_period_id,
                    "product_id": product["product_id"],
                    "opening_qty": Decimal(str(product["opening_qty"])),
                    "opening_unit_cost": Decimal(str(product["opening_unit_cost"])),
                    "selling_price": Decimal(str(product["selling_price"])),
                },
            )

        tx.execute(
            text(
                "UPDATE periods SET status = 'closed', closed_at = CURRENT_TIMESTAMP, closed_by = :closed_by "
                "WHERE id = :period_id AND business_id = :business_id"
            ),
            {"closed_by": auth.user_id, "period_id": period_id, "business_id": auth.business_id},
        )

    return {
        "closed_period_id": period_id,
        "new_period_id": next_period_id,
        "summary": closed_summary,
    }
