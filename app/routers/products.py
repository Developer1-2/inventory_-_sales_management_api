from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.core.db import get_conn
from app.core.errors import AppError
from app.deps import AuthContext, get_auth, require_role
from app.schemas.products import ProductCreate, ProductOut, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductOut)
def create_product(
    payload: ProductCreate,
    auth: AuthContext = Depends(require_role("owner", "manager")),
    conn=Depends(get_conn),
) -> ProductOut:
    name = payload.name.strip()
    duplicate = conn.execute(
        text("SELECT id FROM products WHERE business_id = :business_id AND LOWER(name) = LOWER(:name)"),
        {"business_id": auth.business_id, "name": name},
    ).fetchone()
    if duplicate is not None:
        raise AppError(409, "product_exists", "Product name already exists for this business")

    result = conn.execute(
        text(
            "INSERT INTO products (business_id, name, sku, unit, selling_price, is_active) "
            "VALUES (:business_id, :name, :sku, :unit, :selling_price, :is_active)"
        ),
        {
            "business_id": auth.business_id,
            "name": name,
            "sku": payload.sku,
            "unit": payload.unit,
            "selling_price": payload.selling_price,
            "is_active": int(payload.is_active),
        },
    )
    product_id = int(result.lastrowid)
    row = conn.execute(
        text(
            "SELECT id, business_id, name, sku, unit, selling_price, is_active FROM products "
            "WHERE id = :product_id AND business_id = :business_id"
        ),
        {"product_id": product_id, "business_id": auth.business_id},
    ).fetchone()
    return ProductOut(**dict(row._mapping))


@router.get("", response_model=list[ProductOut])
def list_products(
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = None,
) -> list[ProductOut]:
    offset = (page - 1) * limit
    sql = (
        "SELECT id, business_id, name, sku, unit, selling_price, is_active FROM products "
        "WHERE business_id = :business_id"
    )
    params: dict[str, object] = {"business_id": auth.business_id}
    if search:
        sql += " AND LOWER(name) LIKE LOWER(:search)"
        params["search"] = f"%{search}%"
    sql += " ORDER BY id LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset
    rows = conn.execute(text(sql), params).fetchall()
    return [ProductOut(**dict(row._mapping)) for row in rows]


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int,
    auth: AuthContext = Depends(get_auth),
    conn=Depends(get_conn),
) -> ProductOut:
    row = conn.execute(
        text(
            "SELECT id, business_id, name, sku, unit, selling_price, is_active FROM products "
            "WHERE id = :product_id AND business_id = :business_id"
        ),
        {"product_id": product_id, "business_id": auth.business_id},
    ).fetchone()
    if row is None:
        raise AppError(404, "product_not_found", "Product not found")
    return ProductOut(**dict(row._mapping))


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    auth: AuthContext = Depends(require_role("owner", "manager")),
    conn=Depends(get_conn),
) -> ProductOut:
    row = conn.execute(
        text(
            "SELECT id, business_id, name, sku, unit, selling_price, is_active FROM products "
            "WHERE id = :product_id AND business_id = :business_id"
        ),
        {"product_id": product_id, "business_id": auth.business_id},
    ).fetchone()
    if row is None:
        raise AppError(404, "product_not_found", "Product not found")

    update_values: dict[str, object] = {}
    if payload.name is not None:
        name = payload.name.strip()
        update_values["name"] = name
    if payload.sku is not None:
        update_values["sku"] = payload.sku
    if payload.unit is not None:
        update_values["unit"] = payload.unit
    if payload.selling_price is not None:
        update_values["selling_price"] = payload.selling_price
    if payload.is_active is not None:
        update_values["is_active"] = int(payload.is_active)

    if not update_values:
        return ProductOut(**dict(row._mapping))

    if "name" in update_values:
        duplicate = conn.execute(
            text(
                "SELECT id FROM products WHERE business_id = :business_id AND LOWER(name) = LOWER(:name) "
                "AND id != :product_id"
            ),
            {"business_id": auth.business_id, "name": update_values["name"], "product_id": product_id},
        ).fetchone()
        if duplicate is not None:
            raise AppError(409, "product_exists", "Product name already exists for this business")

    assignments = [f"{key} = :{key}" for key in update_values]
    params = {"product_id": product_id, "business_id": auth.business_id, **update_values}
    conn.execute(
        text(f"UPDATE products SET {', '.join(assignments)} WHERE id = :product_id AND business_id = :business_id"),
        params,
    )

    updated = conn.execute(
        text(
            "SELECT id, business_id, name, sku, unit, selling_price, is_active FROM products "
            "WHERE id = :product_id AND business_id = :business_id"
        ),
        {"product_id": product_id, "business_id": auth.business_id},
    ).fetchone()
    return ProductOut(**dict(updated._mapping))
