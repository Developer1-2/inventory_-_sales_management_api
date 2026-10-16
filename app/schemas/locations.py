from pydantic import BaseModel, Field


class LocationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    address: str | None = None


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    address: str | None = None
    is_active: bool | None = None


class LocationOut(BaseModel):
    id: int
    business_id: int
    name: str
    address: str | None = None
    is_active: bool
