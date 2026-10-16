from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.core.errors import AppError, app_error_handler, validation_error_handler
from app.routers.auth import router as auth_router
from app.routers.counts import router as counts_router
from app.routers.locations import router as locations_router
from app.routers.periods import router as periods_router
from app.routers.products import router as products_router
from app.routers.staff import router as staff_router
from app.routers.stock_entries import router as stock_entries_router

app = FastAPI(title="Inventory & Sales Management API")

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(auth_router)
app.include_router(counts_router)
app.include_router(locations_router)
app.include_router(periods_router)
app.include_router(products_router)
app.include_router(staff_router)
app.include_router(stock_entries_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
