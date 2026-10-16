from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    sku: str | None = None
    unit: str = "pcs"
    selling_price: float = 0.0
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    sku: str | None = None
    unit: str | None = None
    selling_price: float | None = None
    is_active: bool | None = None


class ProductOut(BaseModel):
    id: int
    business_id: int
    name: str
    sku: str | None = None
    unit: str
    selling_price: float
    is_active: bool
