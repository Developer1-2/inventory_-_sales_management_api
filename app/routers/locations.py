from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.core.db import get_conn
from app.core.errors import AppError
from app.deps import AuthContext, get_auth, require_location_access, require_role
from app.schemas.locations import LocationCreate, LocationOut, LocationUpdate

router = APIRouter(prefix="/locations", tags=["locations"])


@router.post("", response_model=LocationOut)
def create_location(
    payload: LocationCreate,
    auth: AuthContext = Depends(require_role("owner")),
    conn=Depends(get_conn),
) -> LocationOut:
    name = payload.name.strip()
    existing = conn.execute(
        text("SELECT id FROM locations WHERE business_id = :business_id AND name = :name"),
        {"business_id": auth.business_id, "name": name},
    ).fetchone()
    if existing is not None:
        raise AppError(409, "location_exists", "Location with this name already exists")

    result = conn.execute(
        text(
            "INSERT INTO locations (business_id, name, address, is_active) "
            "VALUES (:business_id, :name, :address, 1)"
        ),
        {"business_id": auth.business_id, "name": name, "address": payload.address},
    )
    location_id = int(result.lastrowid)
    row = conn.execute(
        text(
            "SELECT id, business_id, name, address, is_active FROM locations "
            "WHERE id = :location_id AND business_id = :business_id"
        ),
        {"location_id": location_id, "business_id": auth.business_id},
    ).fetchone()
    return LocationOut(**dict(row._mapping))


@router.get("", response_model=list[LocationOut])
def list_locations(
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> list[LocationOut]:
    offset = (page - 1) * limit
    if auth.role == "owner":
        rows = conn.execute(
            text(
                "SELECT id, business_id, name, address, is_active FROM locations "
                "WHERE business_id = :business_id ORDER BY id LIMIT :limit OFFSET :offset"
            ),
            {"business_id": auth.business_id, "limit": limit, "offset": offset},
        ).fetchall()
    else:
        rows = conn.execute(
            text(
                "SELECT l.id, l.business_id, l.name, l.address, l.is_active "
                "FROM locations l "
                "JOIN membership_locations ml ON ml.location_id = l.id "
                "WHERE l.business_id = :business_id AND ml.membership_id = :membership_id "
                "ORDER BY l.id LIMIT :limit OFFSET :offset"
            ),
            {
                "business_id": auth.business_id,
                "membership_id": auth.membership_id,
                "limit": limit,
                "offset": offset,
            },
        ).fetchall()
    return [LocationOut(**dict(row._mapping)) for row in rows]


@router.get("/{location_id}", response_model=LocationOut)
def get_location(
    location_id: int,
    auth: AuthContext = Depends(require_location_access),
    conn=Depends(get_conn),
) -> LocationOut:
    row = conn.execute(
        text(
            "SELECT id, business_id, name, address, is_active FROM locations "
            "WHERE id = :location_id AND business_id = :business_id"
        ),
        {"location_id": location_id, "business_id": auth.business_id},
    ).fetchone()
    if row is None:
        raise AppError(404, "location_not_found", "Location not found")
    return LocationOut(**dict(row._mapping))


@router.patch("/{location_id}", response_model=LocationOut)
def update_location(
    location_id: int,
    payload: LocationUpdate,
    auth: AuthContext = Depends(require_role("owner")),
    conn=Depends(get_conn),
) -> LocationOut:
    row = conn.execute(
        text(
            "SELECT id, business_id, name, address, is_active FROM locations "
            "WHERE id = :location_id AND business_id = :business_id"
        ),
        {"location_id": location_id, "business_id": auth.business_id},
    ).fetchone()
    if row is None:
        raise AppError(404, "location_not_found", "Location not found")

    update_values: dict[str, object] = {}
    if payload.name is not None:
        update_values["name"] = payload.name.strip()
    if payload.address is not None:
        update_values["address"] = payload.address
    if payload.is_active is not None:
        update_values["is_active"] = int(payload.is_active)

    if not update_values:
        return LocationOut(**dict(row._mapping))

    if "name" in update_values:
        duplicate = conn.execute(
            text(
                "SELECT id FROM locations WHERE business_id = :business_id AND name = :name "
                "AND id != :location_id"
            ),
            {"business_id": auth.business_id, "name": update_values["name"], "location_id": location_id},
        ).fetchone()
        if duplicate is not None:
            raise AppError(409, "location_exists", "Location with this name already exists")

    sql_parts = ["UPDATE locations SET"]
    params: dict[str, object] = {"location_id": location_id, "business_id": auth.business_id}
    assignments = []
    for key, value in update_values.items():
        assignments.append(f"{key} = :{key}")
        params[key] = value
    sql_parts.append(", ".join(assignments))
    sql_parts.append("WHERE id = :location_id AND business_id = :business_id")
    conn.execute(text(" ".join(sql_parts)), params)

    updated = conn.execute(
        text(
            "SELECT id, business_id, name, address, is_active FROM locations "
            "WHERE id = :location_id AND business_id = :business_id"
        ),
        {"location_id": location_id, "business_id": auth.business_id},
    ).fetchone()
    return LocationOut(**dict(updated._mapping))
