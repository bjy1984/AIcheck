"""2026-11-04 深度审计第三组（小问题）的回归测试。"""
from __future__ import annotations

from types import SimpleNamespace

from apps.api import main as api_main
from apps.api import routes
from libs import institutes, request_profile
from libs.audit_context import reset_request_audit_context, set_request_audit_context
from libs.db.repository import repo
from libs.probe_projects import is_probe_project
from tests.test_platform_institutes import (  # noqa: F401 -- isolated 是自动夹具
    GD,
    PLATFORM,
    bearer,
    client,
    code_of,
    data,
    isolated,
    open_gdtj,
)


def test_硬删的账号也让出全平台用户名():
    gd = bearer(open_gdtj())
    created = data(client.post("/api/admin/users", headers={**gd, "If-Match": "*", "Idempotency-Key": "u1"},
                               json={"username": "gd-temp", "name": "临时", "role": "inspection", "password": "gd-pass-1",
                                     "orgId": "ORG-GDTJ"}))["user"]
    assert institutes.username_conflict_message("gd-temp", institutes.platform_tenant_id()), "建好后全平台占名"
    deleted = data(client.delete(f"/api/admin/users/{created['id']}", headers={**gd, "If-Match": created["etag"],
                                                                                "Idempotency-Key": "u2"}))
    assert deleted["deleted"] is True
    assert institutes.username_conflict_message("gd-temp", institutes.platform_tenant_id()) is None, "硬删后名字让出"


def test_让名的账号不再占手机号(monkeypatch):
    monkeypatch.setattr(routes, "list_admin_users", lambda: [
        {"id": "U-OLD", "username": "qdns~已删除-1", "releasedUsername": "qdns", "mobile": "13800000000"}])
    assert routes.unique_admin_value_conflict(None, username="qdns", mobile="13800000000") is None
    monkeypatch.setattr(routes, "list_admin_users", lambda: [{"id": "U-LIVE", "username": "qdns", "mobile": "13800000000"}])
    assert routes.unique_admin_value_conflict(None, mobile="13800000000")


def test_目录让名等请求落库成功后才做(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(institutes, "unregister_username", lambda name, tenant: calls.append((name, tenant)))
    request = SimpleNamespace(state=SimpleNamespace())
    institutes.unregister_username_after_save(request, "qdns", GD)
    assert calls == [], "不立刻落库"
    api_main.run_after_save_callbacks(request)
    assert calls == [("qdns", GD)]


def test_两个剖析请求同时来_第二个跳过不报错(monkeypatch):
    monkeypatch.setattr(request_profile, "_enabled", lambda request: True)
    with request_profile.request_profile(object(), "a"), request_profile.request_profile(object(), "b"):
        pass
    with request_profile.request_profile(object(), "c"):
        pass  # 锁已释放，能再剖


def test_探针项目要名字格式和地区都对上():
    assert is_probe_project({"name": "写操作审计-勿动-11040410", "region": "审计专用-已改"})
    assert is_probe_project({"name": "写操作审计-勿动-11040410", "region": "审计专用"})
    assert is_probe_project({"name": "任意", "probe": True})
    assert not is_probe_project({"name": "写操作审计-勿动-广州燃气二期", "region": "审计专用-已改"})
    assert not is_probe_project({"name": "写操作审计-勿动-11040410", "region": "广州"})


def test_一键分析的证书核验按本院口径(monkeypatch):
    from libs import review_policies
    from libs.project_analysis import prompt
    from libs.review_orchestrator import certificate_facts, deterministic_tools

    seen: dict = {}
    monkeypatch.setattr(certificate_facts, "certificate_profile_for_node", lambda node_id: {"type": "welder"})
    monkeypatch.setattr(certificate_facts, "build_certificate_facts", lambda *a, **k: {"certificateFacts": {}})
    monkeypatch.setattr(deterministic_tools, "check_certificate_validity",
                        lambda arguments: seen.update(arguments) or {"result": "failed", "facts": {}})
    monkeypatch.setattr(review_policies, "effective_value", lambda key, tenant_id=None: "failed")
    prompt._certificate_verification_for_node({}, "P-1", 24, [])
    assert seen["expiredWithoutPeriodPolicy"] == "failed"


def test_平台切进某院写审计_序号接在库里的链尾后面(monkeypatch):
    open_gdtj()
    monkeypatch.setattr(repo, "_stored_audit_chain_tail",
                        lambda tenant_id: {"id": "AUD-FROM-WORKER", "sequence": 9999, "eventHash": "sha256:worker"})
    token = set_request_audit_context({"tenantId": institutes.platform_tenant_id(), "actorId": "ADMIN"})
    try:
        with institutes.tenant_scope(GD) as state:
            audit_id = repo.add_audit("测试跨院审计", "Institute", GD)
            event = next(row for row in state["audit_logs"] if row["id"] == audit_id)
    finally:
        reset_request_audit_context(token)
    assert event["sequence"] == 10000 and event["previousHash"] == "sha256:worker"


def test_院管理员看平台队列_提示说的是改进任务():
    gd = bearer(open_gdtj())
    refused = client.get("/api/platform/improvement-tasks", headers=gd).json()
    assert refused["code"] != 0 and "改进任务" in refused["message"]
