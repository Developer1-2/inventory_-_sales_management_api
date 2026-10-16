from collections.abc import Generator
from contextlib import contextmanager

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from app.core.config import settings

DATABASE_URL = (
    f"mysql+pymysql://{settings.db_user}:{settings.db_password}@"
    f"{settings.db_host}:{settings.db_port}/{settings.db_name}"
    f"?charset=utf8mb4&autocommit=false"
)

engine: Engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def get_conn() -> Generator[Connection, None, None]:
    with engine.begin() as conn:
        yield conn


@contextmanager
def transaction(conn: Connection | None = None) -> Generator[Connection, None, None]:
    if conn is None:
        with engine.begin() as transaction_conn:
            yield transaction_conn
        return

    if conn.in_transaction():
        with conn.begin_nested():
            yield conn
    else:
        with conn.begin():
            yield conn


__all__ = ["engine", "get_conn", "transaction"]
