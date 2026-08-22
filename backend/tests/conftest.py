from __future__ import annotations

import os
from collections.abc import Iterator
from re import search
from uuid import uuid4

import pytest

# AICHECK_REQUIRE_AUTH 的代码默认值是 true（漏配必须表现为「登不进去」而不是「谁都能进」）。
# 测试套件跑的是业务逻辑，用 X-Dev-Role 头直接扮演角色，因此在这里显式声明本地开发姿态。
# 专门验认证的用例会自行 monkeypatch 回 "true"；authentication_enforced() 的默认值另有用例钉住。
os.environ.setdefault("AICHECK_REQUIRE_AUTH", "false")
# 同理：高风险写端点默认强制 If-Match（N-6）。测试验的是业务逻辑而非乐观锁协议，
# 逐个调用补头只会淹没断言；默认值与拦截行为另有专门用例钉住。
os.environ.setdefault("AICHECK_REQUIRE_IF_MATCH", "false")
os.environ.setdefault("AICHECK_ENABLE_DEMO_DATA", "true")
os.environ.setdefault("AICHECK_ENABLE_COMPATIBILITY_MOCKS", "true")
# 测试环境没有 embedding 服务，向量化走字符哈希伪向量。这是离线自测的正当用法，
# 但必须显式声明——静默使用会让生产环境的配置错误无人察觉（D-2 / issue #8）。
os.environ.setdefault("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", "true")
os.environ.setdefault("AICHECK_OCR_PROVIDER_MODE", "local")
os.environ.setdefault("AICHECK_OCR_DEFAULT_PROVIDER", "local")

from libs.security.session import security_sessions


def _normalized_postgres_host(value: object) -> str:
    host = str(value or "localhost").strip().lower().strip("[]")
    if host in {"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"}:
        return "loopback"
    return host.rstrip(".")


def _postgres_target(dsn: str) -> tuple[str, str, str]:
    """Return a password-free identity for comparing application and test DSNs."""
    from psycopg.conninfo import conninfo_to_dict

    values = conninfo_to_dict(dsn)
    return (
        _normalized_postgres_host(values.get("host")),
        str(values.get("port") or "5432"),
        str(values.get("dbname") or values.get("database") or "").lower(),
    )


def _isolated_test_schema(dsn: str) -> str | None:
    from psycopg.conninfo import conninfo_to_dict

    options = str(conninfo_to_dict(dsn).get("options") or "")
    matched = search(r"(?:^|\s)-c\s*search_path=([^\s]+)", options)
    if not matched:
        return None
    schema = matched.group(1).split(",", 1)[0]
    return schema if schema.startswith("aicheck_test_") else None


def pytest_configure() -> None:
    """Refuse a test URL that resolves to the live database without test schema isolation.

    The check intentionally reports only a password-free target and never echoes either DSN.
    A dedicated test database remains valid, and ``isolated_postgres_url`` still creates and
    drops a unique schema for every fixture invocation.
    """
    test_dsn = str(os.getenv("AICHECK_TEST_POSTGRES_URL") or "").strip()
    if not test_dsn:
        return
    try:
        test_target = _postgres_target(test_dsn)
    except Exception as exc:
        raise pytest.UsageError(
            "AICHECK_TEST_POSTGRES_URL is not a valid PostgreSQL connection string."
        ) from exc

    isolated_schema = _isolated_test_schema(test_dsn)
    for variable in ("AICHECK_DATABASE_URL", "DATABASE_URL"):
        live_dsn = str(os.getenv(variable) or "").strip()
        if not live_dsn:
            continue
        try:
            same_target = _postgres_target(live_dsn) == test_target
        except Exception:
            continue
        if same_target and not isolated_schema:
            host, port, database = test_target
            raise pytest.UsageError(
                "Unsafe PostgreSQL integration test configuration: "
                f"AICHECK_TEST_POSTGRES_URL resolves to the live application target "
                f"{host}:{port}/{database} without an aicheck_test_* search_path. "
                "Use a dedicated test database or options='-c search_path=aicheck_test_<run>,public'."
            )


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
