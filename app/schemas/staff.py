from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Role = Literal["manager", "salesperson"]


class StaffCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=150)
    role: Role
    location_ids: list[int]
    password: str = "Welcome123!"


class StaffUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    location_ids: list[int] | None = None


class StaffMemberOut(BaseModel):
    membership_id: int
    user_id: int
    business_id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    location_ids: list[int]
