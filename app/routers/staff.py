from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import bindparam, text

from app.core.db import get_conn, transaction
from app.core.errors import AppError
from app.core.security import hash_password
from app.deps import AuthContext, get_auth, require_role
from app.schemas.staff import StaffCreate, StaffMemberOut, StaffUpdate

router = APIRouter(prefix="/staff", tags=["staff"])


@router.post("", response_model=StaffMemberOut)
def create_staff_member(
    payload: StaffCreate,
    auth: AuthContext = Depends(require_role("owner")),
    conn=Depends(get_conn),
) -> StaffMemberOut:
    location_ids = sorted(set(payload.location_ids))
    if not location_ids:
        raise AppError(400, "invalid_location_ids", "At least one location is required")

    valid_locations = conn.execute(
        text(
            "SELECT id FROM locations WHERE business_id = :business_id AND id IN :location_ids"
        ).bindparams(bindparam("location_ids", expanding=True)),
        {"business_id": auth.business_id, "location_ids": tuple(location_ids)},
    ).fetchall()
    valid_ids = {row[0] for row in valid_locations}
    missing = [location_id for location_id in location_ids if location_id not in valid_ids]
    if missing:
        raise AppError(404, "location_not_found", f"Location(s) not found: {missing}")

    user = conn.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": payload.email.lower()},
    ).fetchone()

    if user is None:
        result = conn.execute(
            text(
                "INSERT INTO users (email, password_hash, full_name, is_active) "
                "VALUES (:email, :password_hash, :full_name, 1)"
            ),
            {
                "email": payload.email.lower(),
                "password_hash": hash_password(payload.password),
                "full_name": payload.full_name.strip(),
            },
        )
        user_id = int(result.lastrowid)
    else:
        user_id = int(user[0])

    with transaction(conn) as tx:
        membership_result = tx.execute(
            text(
                "INSERT INTO memberships (business_id, user_id, role, is_active) "
                "VALUES (:business_id, :user_id, :role, 1)"
            ),
            {"business_id": auth.business_id, "user_id": user_id, "role": payload.role},
        )
        membership_id = int(membership_result.lastrowid)

        if location_ids:
            tx.execute(
                text(
                    "DELETE FROM membership_locations "
                    "WHERE membership_id = :membership_id AND business_id = :business_id"
                ),
                {"membership_id": membership_id, "business_id": auth.business_id},
            )
            tx.execute(
                text(
                    "INSERT INTO membership_locations (membership_id, location_id, business_id) "
                    "VALUES (:membership_id, :location_id, :business_id)"
                ),
                [
                    {
                        "membership_id": membership_id,
                        "location_id": location_id,
                        "business_id": auth.business_id,
                    }
                    for location_id in location_ids
                ],
            )

    row = conn.execute(
        text(
            "SELECT m.id AS membership_id, m.business_id, m.user_id, u.email, u.full_name, m.role, m.is_active "
            "FROM memberships m "
            "JOIN users u ON u.id = m.user_id "
            "WHERE m.id = :membership_id AND m.business_id = :business_id"
        ),
        {"membership_id": membership_id, "business_id": auth.business_id},
    ).fetchone()
    location_rows = conn.execute(
        text(
            "SELECT location_id FROM membership_locations "
            "WHERE membership_id = :membership_id AND business_id = :business_id "
            "ORDER BY location_id"
        ),
        {"membership_id": membership_id, "business_id": auth.business_id},
    ).fetchall()
    return StaffMemberOut(
        membership_id=int(row[0]),
        user_id=int(row[2]),
        business_id=int(row[1]),
        email=str(row[3]),
        full_name=str(row[4]),
        role=str(row[5]),
        is_active=bool(row[6]),
        location_ids=[int(item[0]) for item in location_rows],
    )


@router.get("", response_model=list[StaffMemberOut])
def list_staff_members(
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
) -> list[StaffMemberOut]:
    rows = conn.execute(
        text(
            "SELECT m.id AS membership_id, m.business_id, m.user_id, u.email, u.full_name, m.role, m.is_active "
            "FROM memberships m "
            "JOIN users u ON u.id = m.user_id "
            "WHERE m.business_id = :business_id ORDER BY m.id"
        ),
        {"business_id": auth.business_id},
    ).fetchall()

    members: list[StaffMemberOut] = []
    for row in rows:
        location_rows = conn.execute(
            text(
                "SELECT location_id FROM membership_locations "
                "WHERE membership_id = :membership_id AND business_id = :business_id "
                "ORDER BY location_id"
            ),
            {"membership_id": row[0], "business_id": auth.business_id},
        ).fetchall()
        members.append(
            StaffMemberOut(
                membership_id=int(row[0]),
                user_id=int(row[2]),
                business_id=int(row[1]),
                email=str(row[3]),
                full_name=str(row[4]),
                role=str(row[5]),
                is_active=bool(row[6]),
                location_ids=[int(item[0]) for item in location_rows],
            )
        )
    return members


@router.patch("/{membership_id}", response_model=StaffMemberOut)
def update_staff_member(
    membership_id: int,
    payload: StaffUpdate,
    auth: AuthContext = Depends(require_role("owner")),
    conn=Depends(get_conn),
) -> StaffMemberOut:
    membership_row = conn.execute(
        text(
            "SELECT m.id, m.business_id, m.user_id, u.email, u.full_name, m.role, m.is_active "
            "FROM memberships m "
            "JOIN users u ON u.id = m.user_id "
            "WHERE m.id = :membership_id AND m.business_id = :business_id"
        ),
        {"membership_id": membership_id, "business_id": auth.business_id},
    ).fetchone()
    if membership_row is None:
        raise AppError(404, "membership_not_found", "Membership not found")

    update_values: dict[str, Any] = {}
    if payload.role is not None:
        update_values["role"] = payload.role
    if payload.is_active is not None:
        update_values["is_active"] = int(payload.is_active)

    if update_values:
        assignments = [f"{key} = :{key}" for key in update_values]
        params = {
            "membership_id": membership_id,
            "business_id": auth.business_id,
            **update_values,
        }
        conn.execute(
            text(
                f"UPDATE memberships SET {', '.join(assignments)} "
                "WHERE id = :membership_id AND business_id = :business_id"
            ),
            params,
        )

    if payload.location_ids is not None:
        new_ids = sorted(set(payload.location_ids))
        valid = conn.execute(
            text(
                "SELECT id FROM locations WHERE business_id = :business_id AND id IN :location_ids"
            ).bindparams(bindparam("location_ids", expanding=True)),
            {"business_id": auth.business_id, "location_ids": tuple(new_ids)},
        ).fetchall()
        valid_ids = {row[0] for row in valid}
        missing = [location_id for location_id in new_ids if location_id not in valid_ids]
        if missing:
            raise AppError(404, "location_not_found", f"Location(s) not found: {missing}")
        conn.execute(
            text(
                "DELETE FROM membership_locations "
                "WHERE membership_id = :membership_id AND business_id = :business_id"
            ),
            {"membership_id": membership_id, "business_id": auth.business_id},
        )
        conn.execute(
            text(
                "INSERT INTO membership_locations (membership_id, location_id, business_id) "
                "VALUES (:membership_id, :location_id, :business_id)"
            ),
            [
                {"membership_id": membership_id, "location_id": location_id, "business_id": auth.business_id}
                for location_id in new_ids
            ],
        )

    row = conn.execute(
        text(
            "SELECT m.id AS membership_id, m.business_id, m.user_id, u.email, u.full_name, m.role, m.is_active "
            "FROM memberships m "
            "JOIN users u ON u.id = m.user_id "
            "WHERE m.id = :membership_id AND m.business_id = :business_id"
        ),
        {"membership_id": membership_id, "business_id": auth.business_id},
    ).fetchone()
    location_rows = conn.execute(
        text(
            "SELECT location_id FROM membership_locations "
            "WHERE membership_id = :membership_id AND business_id = :business_id "
            "ORDER BY location_id"
        ),
        {"membership_id": membership_id, "business_id": auth.business_id},
    ).fetchall()
    return StaffMemberOut(
        membership_id=int(row[0]),
        user_id=int(row[2]),
        business_id=int(row[1]),
        email=str(row[3]),
        full_name=str(row[4]),
        role=str(row[5]),
        is_active=bool(row[6]),
        location_ids=[int(item[0]) for item in location_rows],
    )
