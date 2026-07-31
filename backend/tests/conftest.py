from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest

os.environ.setdefault("AICHECK_ENABLE_DEMO_DATA", "true")
os.environ.setdefault("AICHECK_ENABLE_COMPATIBILITY_MOCKS", "true")
os.environ.setdefault("AICHECK_OCR_PROVIDER_MODE", "local")
os.environ.setdefault("AICHECK_OCR_DEFAULT_PROVIDER", "local")

from libs.security.session import security_sessions


@pytest.fixture
def isolated_postgres_url() -> Iterator[str]:
    database_url = os.getenv("AICHECK_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("AICHECK_TEST_POSTGRES_URL is required for PostgreSQL integration tests")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    schema = f"aicheck_test_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped_url = make_conninfo(
        **{
            **conninfo_to_dict(database_url),
            "options": f"-c search_path={schema},public",
        }
    )
    try:
        yield scoped_url
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture(autouse=True)
def allow_explicit_test_dev_tokens(monkeypatch):
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "true")
    monkeypatch.delenv("AICHECK_STRICT_PRODUCTION", raising=False)
    security_sessions.reset_for_tests()
    yield
    security_sessions.reset_for_tests()
