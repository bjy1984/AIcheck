"""按需剖析只给平台管理员、只在带 ?_profile=1 时开，结果写日志不进响应。"""
from __future__ import annotations

import logging
from types import SimpleNamespace

from libs import request_profile as rp


def _request(profile: str | None, user: dict | None):
    return SimpleNamespace(query_params={"_profile": profile} if profile else {}, state=SimpleNamespace(auth_user=user))


def test_只有平台管理员带参数才剖析(monkeypatch, caplog):
    monkeypatch.setattr("libs.security.auth.is_platform_admin", lambda user: bool(user and user.get("platform")))
    caplog.set_level(logging.WARNING, logger="aicheck.request_profile")
    for request in (_request(None, {"platform": True}), _request("1", {"platform": False}), _request("1", None)):
        with rp.request_profile(request, "x"):
            sum(range(1000))
    assert not caplog.records, "普通请求、非平台管理员都不剖析"
    with rp.request_profile(_request("1", {"platform": True}), "audit-overview P-1"):
        sum(range(1000))
    assert len(caplog.records) == 1 and "audit-overview P-1" in caplog.records[0].getMessage()


def test_目录树与节点资料包可以线上剖析():
    """2026-11-12 无损检测首屏：先等目录树（0.6–2.3 秒）再等节点资料包，两处都要能在生产上剖析。"""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1].joinpath("apps/api/routes.py").read_text(encoding="utf-8")
    assert 'request_profile(request, f"project-tree {project_id}")' in source
    assert 'request_profile(request, f"node-package {project_id}#{node_id}")' in source
