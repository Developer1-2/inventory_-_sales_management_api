from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app.core.db import get_conn
from app.core.errors import AppError
from app.core.security import decode_token

security_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    user_id: int
    business_id: int
    role: str
    membership_id: int
    location_ids: list[int] | str


def get_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)],
    conn=Depends(get_conn),
) -> AuthContext:
    if credentials is None:
        raise AppError(401, "unauthorized", "Authentication required")

    try:
        payload = decode_token(credentials.credentials)
    except Exception as exc:  # pragma: no cover - defensive branch
        raise AppError(401, "invalid_token", "Invalid token") from exc

    user_id = payload.get("user_id")
    business_id = payload.get("business_id")
    role = payload.get("role")
    membership_id = payload.get("membership_id")

    if user_id is None or business_id is None or role is None or membership_id is None:
        raise AppError(401, "invalid_token", "Token missing required claims")

    allowed_locations = conn.execute(
        text(
            "SELECT location_id FROM membership_locations "
            "WHERE membership_id = :membership_id AND business_id = :business_id"
        ),
        {"membership_id": membership_id, "business_id": business_id},
    ).fetchall()

    location_ids: list[int] | str = [row[0] for row in allowed_locations]
    if role == "owner":
        location_ids = "all"

    return AuthContext(
        user_id=int(user_id),
        business_id=int(business_id),
        role=str(role),
        membership_id=int(membership_id),
        location_ids=location_ids,
    )


def require_role(*allowed_roles: str):
    def dependency(auth: AuthContext = Depends(get_auth)) -> AuthContext:
        if auth.role not in allowed_roles:
            allowed = ", ".join(allowed_roles)
            raise AppError(403, "forbidden", f"Requires role: {allowed}")
        return auth

    return dependency


def require_location_access(
    location_id: int,
    auth: AuthContext = Depends(get_auth),
) -> AuthContext:
    if auth.location_ids == "all":
        return auth
    if location_id not in auth.location_ids:
        raise AppError(404, "location_not_found", "Location not found")
    return auth
