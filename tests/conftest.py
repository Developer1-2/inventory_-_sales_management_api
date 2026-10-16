from __future__ import annotations

from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.core.db import get_conn
from app.main import app

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


@pytest.fixture(scope="session")
def mysql_engine():
    admin_url = (
        f"mysql+pymysql://{settings.db_user}:{settings.db_password}@"
        f"{settings.db_host}:{settings.db_port}/"
    )
    admin_engine = create_engine(admin_url, pool_pre_ping=True)

    try:
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{settings.test_db_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
                )
            )
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"MySQL is not available for test setup: {exc}")

    test_url = (
        f"mysql+pymysql://{settings.db_user}:{settings.db_password}@"
        f"{settings.db_host}:{settings.db_port}/{settings.test_db_name}"
        f"?charset=utf8mb4&autocommit=false"
    )
    test_engine = create_engine(test_url, pool_pre_ping=True)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    schema_sql = re.sub(
        r"CREATE DATABASE IF NOT EXISTS .*?;\s*USE .*?;\s*",
        "",
        schema_sql,
        flags=re.DOTALL,
    )

    try:
        with test_engine.begin() as conn:
            for statement in schema_sql.split(";"):
                statement = statement.strip()
                if not statement or all(
                    line.lstrip().startswith("--")
                    for line in statement.splitlines()
                    if line.strip()
                ):
                    continue
                conn.execute(text(statement))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Test schema could not be applied: {exc}")

    return test_engine


@pytest.fixture(scope="function")
def client(mysql_engine):
    with mysql_engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        table_names = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :db_name"
            ),
            {"db_name": settings.test_db_name},
        ).scalars().all()
        for table_name in table_names:
            conn.execute(text(f"TRUNCATE TABLE `{table_name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

    def override_get_conn():
        with mysql_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_conn] = override_get_conn
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
