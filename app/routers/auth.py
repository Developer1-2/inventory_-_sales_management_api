from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from app.core.db import get_conn, transaction
from app.core.errors import AppError
from app.core.limiting import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.deps import get_auth
from app.schemas.auth import (
    BusinessChoice,
    LoginBusinessChoiceResponse,
    LoginRequest,
    RegisterBusinessRequest,
    TokenResponse,
)
from app.schemas.me import AuthMeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register-business", response_model=TokenResponse)
@limiter.limit("10/minute")
def register_business(
    request: Request,
    payload: RegisterBusinessRequest,
    conn=Depends(get_conn),
) -> TokenResponse:
    normalized_email = payload.email.lower()
    existing = conn.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": normalized_email},
    ).fetchone()
    if existing is not None:
        raise AppError(409, "email_taken", "Email already registered")

    try:
        with transaction(conn) as tx:
            business_result = tx.execute(
                text("INSERT INTO businesses (name, is_active) VALUES (:name, 1)"),
                {"name": payload.business_name.strip()},
            )
            business_id = business_result.lastrowid

            tx.execute(
                text("INSERT INTO business_settings (business_id) VALUES (:business_id)"),
                {"business_id": business_id},
            )

            user_result = tx.execute(
                text(
                    "INSERT INTO users (email, password_hash, full_name, is_active) "
                    "VALUES (:email, :password_hash, :full_name, 1)"
                ),
                {
                    "email": normalized_email,
                    "password_hash": hash_password(payload.password),
                    "full_name": payload.owner_name.strip(),
                },
            )
            user_id = user_result.lastrowid

            membership_result = tx.execute(
                text(
                    "INSERT INTO memberships (business_id, user_id, role, is_active) "
                    "VALUES (:business_id, :user_id, 'owner', 1)"
                ),
                {"business_id": business_id, "user_id": user_id},
            )
            membership_id = membership_result.lastrowid
    except Exception as exc:  # pragma: no cover - DB integrity fallback
        return {exc}
        raise AppError(400, "registration_failed", "Unable to create business account") from exc

    token = create_access_token(
        {
            "user_id": user_id,
            "business_id": business_id,
            "role": "owner",
            "membership_id": membership_id,
        }
    )
    return TokenResponse(
        access_token=token,
        user_id=user_id,
        business_id=business_id,
        role="owner",
        membership_id=membership_id,
    )


@router.post("/login", response_model=TokenResponse | LoginBusinessChoiceResponse)
@limiter.limit("10/minute")
def login(
    request: Request,
    payload: LoginRequest,
    conn=Depends(get_conn),
) -> TokenResponse | LoginBusinessChoiceResponse:
    normalized_email = payload.email.lower()
    membership_query = (
        "SELECT m.id AS membership_id, m.business_id, b.name AS business_name, "
        "m.role, u.id AS user_id, u.password_hash "
        "FROM memberships m "
        "JOIN businesses b ON b.id = m.business_id "
        "JOIN users u ON u.id = m.user_id "
        "WHERE u.email = :email AND m.is_active = 1"
    )
    membership_params: dict[str, object] = {"email": normalized_email}
    if payload.business_id is not None:
        membership_query += " AND m.business_id = :business_id"
        membership_params["business_id"] = payload.business_id
    memberships = conn.execute(text(membership_query), membership_params).fetchall()

    if not memberships:
        if payload.business_id is not None:
            user = conn.execute(
                text("SELECT password_hash FROM users WHERE email = :email"),
                {"email": normalized_email},
            ).fetchone()
            if user is not None and verify_password(payload.password, user[0]):
                raise AppError(404, "business_not_found", "Business not found for this user")
        raise AppError(401, "invalid_credentials", "Invalid email or password")

    user_id = memberships[0][4]
    password_hash = memberships[0][5]
    if not verify_password(payload.password, password_hash):
        raise AppError(401, "invalid_credentials", "Invalid email or password")

    if payload.business_id is not None:
        selected_membership = next(
            (row for row in memberships if int(row[1]) == int(payload.business_id)),
            None,
        )
        if selected_membership is None:
            raise AppError(404, "business_not_found", "Business not found for this user")
        business_id = int(selected_membership[1])
        membership_id = int(selected_membership[0])
        role = selected_membership[3]
        token = create_access_token(
            {
                "user_id": user_id,
                "business_id": business_id,
                "role": role,
                "membership_id": membership_id,
            }
        )
        return TokenResponse(
            access_token=token,
            user_id=user_id,
            business_id=business_id,
            role=role,
            membership_id=membership_id,
        )

    if len(memberships) > 1:
        return LoginBusinessChoiceResponse(
            businesses=[
                BusinessChoice(business_id=int(row[1]), business_name=str(row[2]))
                for row in memberships
            ]
        )

    selected = memberships[0]
    business_id = int(selected[1])
    membership_id = int(selected[0])
    role = selected[3]
    token = create_access_token(
        {
            "user_id": user_id,
            "business_id": business_id,
            "role": role,
            "membership_id": membership_id,
        }
    )
    return TokenResponse(
        access_token=token,
        user_id=user_id,
        business_id=business_id,
        role=role,
        membership_id=membership_id,
    )


@router.get("/me", response_model=AuthMeResponse)
@limiter.limit("30/minute")
def me(request: Request, auth=Depends(get_auth)) -> AuthMeResponse:
    return AuthMeResponse(
        user_id=auth.user_id,
        business_id=auth.business_id,
        role=auth.role,
        membership_id=auth.membership_id,
        location_ids=auth.location_ids,
    )
