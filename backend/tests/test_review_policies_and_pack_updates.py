"""院级审查口径开关（第二阶段）与平台规则送达既有项目（第三阶段），2026-11-04。

夹具来自 test_platform_institutes：每个用例收尾都跑一遍落库前的院标记检查。
"""
from __future__ import annotations

from copy import deepcopy

from libs import review_policies as rp
from libs.business_pack import DEFAULT_BUSINESS_PACK_ID, load_business_pack
from libs.business_pack_diff import pack_diff
from libs.db.repository import repo
from libs.review_orchestrator.deterministic_tools import check_certificate_validity
from libs.review_tools.business_tools import check_standard_version_active
from libs.review_tools.executor import build_tool_arguments
from tests.test_platform_institutes import (  # noqa: F401 -- isolated 是自动夹具
    PLATFORM,
    bearer,
    client,
    code_of,
    data,
    isolated,
    open_gdtj,
)

EXPIRED_CERT = {"certificates": [{"certificateNo": "TS3-1", "holder": "某安装公司", "validFrom": "2020-01-01",
                                  "validUntil": "2021-01-01"}], "referenceDateSource": "business_today"}


def put(headers: dict, path: str, value, key: str):
    return client.put(path, headers={**headers, "Idempotency-Key": key}, json={"value": value})


# ── 第二阶段：口径开关 ──────────────────────────────────────────────────────────

def test_生效顺序_本院优先_其次平台默认_最后代码默认():
    key = "certificate_expired_without_construction_period"
    assert rp.resolve({}, {})[key] == {"value": "evidence_insufficient", "source": "code"}
    assert rp.resolve({}, {key: "failed"})[key] == {"value": "failed", "source": "platform"}
    assert rp.resolve({key: "human_review_required"}, {key: "failed"})[key]["source"] == "institute"
    assert rp.resolve({key: "passed"}, {})[key]["source"] == "code", "「符合」不是合法选项，忽略"


def test_证书过期无施工期_按口径判_并记下按哪个口径():
    default = check_certificate_validity(dict(EXPIRED_CERT))
    assert default["result"] == "evidence_insufficient"
    assert default["facts"]["policyApplied"] == {"certificate_expired_without_construction_period": "evidence_insufficient"}
    human = check_certificate_validity({**EXPIRED_CERT, "expiredWithoutPeriodPolicy": "human_review_required"})
    assert human["result"] == "human_review_required", "原来没有这一档会落到「符合」"
    assert check_certificate_validity({**EXPIRED_CERT, "expiredWithoutPeriodPolicy": "failed"})["result"] == "failed"
    assert check_certificate_validity({**EXPIRED_CERT, "expiredWithoutPeriodPolicy": "passed"})["result"] == "evidence_insufficient"


def test_标准已发布未实施_按口径判():
    args = {"reviewDate": "2021-03-01", "standardReferences": [
        {"standardRef": "GB/T 20801.1-2020", "status": "active", "effectiveFrom": "2021-06-01"}]}
    assert check_standard_version_active(dict(args))["result"] == "human_review_required"
    strict = check_standard_version_active({**args, "notYetEffectivePolicy": "failed"})
    assert strict["result"] == "failed"
    assert strict["facts"]["input"]["policyApplied"] == {"standard_not_yet_effective_on_review_date": "failed"}


def test_审查时读当前院的口径():
    rp.invalidate()
    repo.state.setdefault("admin_config", {})["reviewPolicies"] = {"certificate_expired_without_construction_period": "failed"}
    rp.invalidate()
    arguments = build_tool_arguments("check_certificate_validity", {}, facts={}, explicit={}, document_version_ids=[],
                                     evidence_facts=[], evidence_refs=[])
    assert arguments["expiredWithoutPeriodPolicy"] == "failed"
    repo.state["admin_config"]["reviewPolicies"] = {}
    rp.invalidate()


def test_院管理员改本院口径_平台管理员改默认并看各院分布():
    gd = bearer(open_gdtj())
    key = "standard_not_yet_effective_on_review_date"
    assert code_of(put(gd, f"/api/admin/review-policies/{key}", "passed", "p0")) != 0, "选项里没有「符合」"
    data(put(gd, f"/api/admin/review-policies/{key}", "failed", "p1"))
    item = next(row for row in data(client.get("/api/admin/review-policies", headers=gd))["items"] if row["key"] == key)
    assert item["effective"] == {"value": "failed", "source": "institute"} and "adoption" not in item
    assert code_of(put(gd, f"/api/platform/review-policy-defaults/{key}", "failed", "p2")) != 0, "院管理员不能改平台默认"
    data(put(PLATFORM, f"/api/platform/review-policy-defaults/{key}", "human_review_required", "p3"))
    platform_item = next(row for row in data(client.get("/api/admin/review-policies", headers=PLATFORM))["items"]
                         if row["key"] == key)
    assert platform_item["platformDefault"] == "human_review_required"
    assert [who["name"] for who in platform_item["adoption"]["failed"]] == ["广东特检院"]
    data(put(gd, f"/api/admin/review-policies/{key}", None, "p4"))
    item = next(row for row in data(client.get("/api/admin/review-policies", headers=gd))["items"] if row["key"] == key)
    assert item["effective"] == {"value": "human_review_required", "source": "platform"}, "跟随平台默认"


# ── 第三阶段：平台规则送达既有项目 ──────────────────────────────────────────────

def _older(pack: dict) -> dict:
    old = deepcopy(pack)
    old["version"] = "2026.08.07"
    old["ruleSets"][0]["severity"] = "旧值"
    old["atomicChecks"] = [item for item in old["atomicChecks"] if item.get("id") != pack["atomicChecks"][-1]["id"]]
    return old


def test_差异列出改了哪些段和影响的节点():
    current = load_business_pack(DEFAULT_BUSINESS_PACK_ID)
    diff = pack_diff(_older(current), current)
    sections = {row["name"]: row for row in diff["sections"]}
    assert sections["ruleSets"]["changed"] == 1 and sections["atomicChecks"]["added"] == 1
    assert set(current["ruleSets"][0]["nodeIds"]) <= set(diff["affectedNodeIds"])
    assert int(current["atomicChecks"][-1]["nodeId"]) in diff["affectedNodeIds"]
    assert pack_diff(current, current)["upToDate"] is True


def test_旧项目列出差异_选中升级后就是最新():
    current = load_business_pack(DEFAULT_BUSINESS_PACK_ID)
    created = data(client.post("/api/projects", headers={**PLATFORM, "Idempotency-Key": "np1"}, json={"name": "规则升级试点"}))
    project_id = (created.get("project") or created)["id"]
    project = repo.require_project(project_id)
    project.update({"businessPackId": DEFAULT_BUSINESS_PACK_ID, "businessPackSnapshot": _older(current),
                    "businessPackSnapshotHash": "old-hash", "businessPackVersion": "2026.08.07"})
    listing = data(client.get("/api/admin/business-pack/updates", headers=PLATFORM))
    row = next(item for item in listing["items"] if item["projectId"] == project_id)
    assert row["upToDate"] is False and row["frozenVersion"] == "2026.08.07" and row["diff"]["affectedNodeIds"]
    assert code_of(client.post("/api/admin/business-pack/updates/apply", headers={**PLATFORM, "Idempotency-Key": "a0"},
                               json={"projectIds": []})) != 0
    result = data(client.post("/api/admin/business-pack/updates/apply", headers={**PLATFORM, "Idempotency-Key": "a1"},
                              json={"projectIds": [project_id]}))
    assert result["appliedCount"] == 1 and result["results"][0]["toVersion"] == current["version"]
    after = next(item for item in data(client.get("/api/admin/business-pack/updates", headers=PLATFORM))["items"]
                 if item["projectId"] == project_id)
    assert after["upToDate"] is True


def test_非管理员不能看也不能升级():
    gd = bearer(open_gdtj())
    data(client.post("/api/admin/users", headers={**gd, "If-Match": "*", "Idempotency-Key": "u1"},
                     json={"username": "gd-insp", "name": "广东监检", "role": "inspection", "password": "gd-pass-1",
                           "orgId": "ORG-GDTJ"}))
    token = data(client.post("/api/auth/login", json={"username": "gd-insp", "password": "gd-pass-1"}))["token"]
    assert code_of(client.get("/api/admin/business-pack/updates", headers=bearer(token))) != 0
    assert code_of(client.get("/api/admin/review-policies", headers=bearer(token))) != 0
