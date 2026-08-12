"""让静默的失败发出声音（issue #12 的 S-4 / D-4）。

这一类缺陷的共同点是：出错时返回一个「看起来正常」的结果——空列表、默认身份、
成功状态——调用方无从分辨「确实没有」和「根本没跑成」。
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from starlette.requests import Request

from apps.api.main import client_declared_identity


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/api/x", "headers": raw})


# ---- S-4：X-User-Id 是客户端自称的身份 ----


def test_declared_identity_is_ignored_when_auth_is_enforced(monkeypatch) -> None:
    """审计留痕、幂等作用域、授权摘要都以它为键——采信等于让调用方自选身份。"""
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    request = _request({"X-User-Id": "USER-SOMEONE-ELSE"})
    assert client_declared_identity(request) is None


def test_declared_identity_falls_back_only_when_auth_is_off(monkeypatch) -> None:
    """认证关闭是本地开发/demo 的姿态，启动时已有显式告警（S-1）。"""
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "false")
    assert client_declared_identity(_request({"X-User-Id": "USER-DEV-001"})) == "USER-DEV-001"
    # 空值与纯空白都不算身份
    assert client_declared_identity(_request({"X-User-Id": "   "})) is None
    assert client_declared_identity(_request({})) is None


def test_auth_enforced_is_the_default(monkeypatch) -> None:
    """漏配时必须是「不采信」，不能是「谁说自己是谁就是谁」。"""
    monkeypatch.delenv("AICHECK_REQUIRE_AUTH", raising=False)
    assert client_declared_identity(_request({"X-User-Id": "USER-FORGED"})) is None


# ---- D-4：embedding 维度不匹配 ----


def test_query_dimension_mismatch_is_logged_not_silent(caplog, monkeypatch) -> None:
    """空结果有两种成因，调用方必须能分辨。

    「查询向量维度与索引表不符」和「库里确实没有相关内容」都返回 []，
    不记日志的话，换过 embedding 模型档案的人只会以为知识库没覆盖到。
    """
    from libs.db import repository as repo_module

    calls: dict[str, Any] = {}

    class _FakePg:
        def execute(self, *args, **kwargs):  # pragma: no cover - 不该被调用
            calls["executed"] = True
            raise AssertionError("维度不符时不应发起查询")

    monkeypatch.setattr(repo_module.repo, "configure_sync_postgres", lambda: None)
    monkeypatch.setattr(repo_module.repo, "sync_postgres", _FakePg(), raising=False)
    monkeypatch.setattr(repo_module.repo, "ensure_pgvector_schema", lambda: True)

    wrong_dimensions = repo_module.OFFLINE_VECTOR_DIMENSIONS + 1
    with caplog.at_level(logging.ERROR, logger="aicheck.repository"):
        result = repo_module.repo.search_knowledge_vectors([0.1] * wrong_dimensions)

    assert result == []
    assert "executed" not in calls
    assert any("pgvector_query_dimension_mismatch" in record.message for record in caplog.records), (
        "维度不符导致的空结果必须留下日志，否则与「没有匹配内容」不可分辨"
    )


def test_matching_dimension_does_not_log_the_mismatch_error(caplog, monkeypatch) -> None:
    """正常检索不该被这条 error 污染——告警只有稀有时才有意义。"""
    from libs.db import repository as repo_module

    monkeypatch.setattr(repo_module.repo, "configure_sync_postgres", lambda: None)
    monkeypatch.setattr(repo_module.repo, "sync_postgres", None, raising=False)

    with caplog.at_level(logging.ERROR, logger="aicheck.repository"):
        assert repo_module.repo.search_knowledge_vectors([0.1] * repo_module.OFFLINE_VECTOR_DIMENSIONS) == []
    assert not any("pgvector_query_dimension_mismatch" in r.message for r in caplog.records)
