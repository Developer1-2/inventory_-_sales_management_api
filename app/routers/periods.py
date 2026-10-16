from __future__ import annotations

import calendar
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.core.db import get_conn, transaction
from app.core.errors import AppError
from app.deps import AuthContext, get_auth, require_location_access
from app.schemas.periods import PeriodCreate, PeriodCountOut, PeriodDetailOut, PeriodOut

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
