from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest

# AICHECK_REQUIRE_AUTH 的代码默认值是 true（漏配必须表现为「登不进去」而不是「谁都能进」）。
# 测试套件跑的是业务逻辑，用 X-Dev-Role 头直接扮演角色，因此在这里显式声明本地开发姿态。
# 专门验认证的用例会自行 monkeypatch 回 "true"；authentication_enforced() 的默认值另有用例钉住。
os.environ.setdefault("AICHECK_REQUIRE_AUTH", "false")
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


@pytest.fixture(autouse=True)
def isolate_repository_persistence_backend():
    """每个用例结束后关掉 repo 上的持久化后端。

    多数用例跑在纯内存态上，只有少数会 configure_sqlite/配置 Postgres 来验证持久化。
    这些开关挂在全局 repo 单例上，开启后不会自己关闭，于是后续用例会意外走进
    SQLite 写入路径并因缺少 baseline 而失败——表现为「单跑通过、全量跑失败」，
    掩盖真实回归。只有部分测试文件自带 setup_function 做重置，这里统一兜底。
    """
    from libs.db.repository import repo

    yield
    repo.sqlite_enabled = False
    repo.sqlite_path = None
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
