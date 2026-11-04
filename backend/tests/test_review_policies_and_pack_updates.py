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


# ── 2026-11-04 审计：差异盲区、归档项目、资料清单行 ────────────────────────────

def test_资料类型_标准目录_试点规则_字符串清单改了也能看出影响哪些节点():
    current = load_business_pack(DEFAULT_BUSINESS_PACK_ID)
    old = deepcopy(current)
    material = current["nodeTemplates"][0]["requiredMaterials"][0]["materialTypeCode"]
    next(item for item in old["materialTypes"] if item["code"] == material)["name"] = "旧资料名"
    diff = pack_diff(old, current)
    assert diff["sections"][0]["name"] == "materialTypes" and int(current["nodeTemplates"][0]["nodeId"]) in diff["affectedNodeIds"]

    old = deepcopy(current)
    standard = current["standardCatalog"][0]
    old["standardCatalog"][0]["name"] = "旧标准名"
    bound = {int(item["nodeId"]) for item in current["standardClauseBindings"]
             if item.get("documentVersionId") == standard["documentVersionId"]}
    assert bound and bound <= set(pack_diff(old, current)["affectedNodeIds"])

    old = deepcopy(current)
    dropped = old["atomicCheckToolBindingSet"]["pilotRules"].pop(0)
    diff = pack_diff(old, current)
    assert diff["otherChanges"] == ["atomicCheckToolBindingSet"] and diff["otherChangeLabels"] == ["检查工具绑定配置"]
    rule = next(item for item in current["ruleSets"] if item["id"].endswith(f"-{dropped}"))
    assert set(rule["nodeIds"]) <= set(diff["affectedNodeIds"]) and len(diff["affectedNodeIds"]) < len(current["nodeTemplates"])

    old = deepcopy(current)
    old["atomicCheckToolBindingSet"]["version"] = "2026.01.01"
    assert pack_diff(old, current)["upToDate"] is True, "只改版本号不算"

    old = deepcopy(current)
    old["workflowActions"] = old["workflowActions"][:-1]
    section = pack_diff(old, current)["sections"][0]
    assert section["name"] == "workflowActions" and section["added"] == 1


def _old_project(name: str, key: str, **fields) -> str:
    created = data(client.post("/api/projects", headers={**PLATFORM, "Idempotency-Key": key}, json={"name": name}))
    project_id = (created.get("project") or created)["id"]
    current = load_business_pack(DEFAULT_BUSINESS_PACK_ID)
    repo.require_project(project_id).update({"businessPackId": DEFAULT_BUSINESS_PACK_ID, "businessPackSnapshot": deepcopy(current),
                                             "businessPackSnapshotHash": "old-hash", **fields})
    return project_id


def test_指纹不同就算旧版_算不出差异也能升级():
    project_id = _old_project("只有指纹不同", "np2")
    row = next(item for item in data(client.get("/api/admin/business-pack/updates", headers=PLATFORM))["items"]
               if item["projectId"] == project_id)
    assert row["upToDate"] is False and row["upgradable"] is True and row["diff"]["upToDate"] is True


def test_归档项目不算可升级_强行升级给出真实原因():
    project_id = _old_project("已归档项目", "np3", status="已归档")
    listing = data(client.get("/api/admin/business-pack/updates", headers=PLATFORM))
    row = next(item for item in listing["items"] if item["projectId"] == project_id)
    assert row["archived"] is True and row["upgradable"] is False
    assert listing["outdatedCount"] == sum(1 for item in listing["items"] if item["upgradable"])
    result = data(client.post("/api/admin/business-pack/updates/apply", headers={**PLATFORM, "Idempotency-Key": "a3"},
                              json={"projectIds": [project_id]}))
    assert result["appliedCount"] == 0 and "归档" in result["results"][0]["reason"]


def test_升级时没挂资料的清单行跟着新版改_挂了资料的不动_新版没有的标出来():
    project_id = _old_project("清单行升级", "np4")
    rows = [item for item in repo.state["requirements"] if item.get("projectId") == project_id]
    assert len(rows) >= 2
    unbound, bound = rows[0], rows[1]
    unbound["name"], bound["name"] = "旧名称甲", "旧名称乙"
    repo.state["bindings"].append({"id": "BIND-REQ-TEST", "projectId": project_id, "nodeId": bound["nodeId"],
                                   "requirementId": bound["id"], "requirementName": "旧名称乙"})
    repo.state["requirements"].append({"id": "REQ-GONE-01", "projectId": project_id, "nodeId": unbound["nodeId"],
                                       "name": "新版已删除的资料", "requiredType": "必传"})
    result = data(client.post("/api/admin/business-pack/updates/apply", headers={**PLATFORM, "Idempotency-Key": "a4"},
                              json={"projectIds": [project_id]}))["results"][0]
    assert result["applied"] is True
    assert unbound["id"] in result["updatedRequirementIds"] and unbound["name"] != "旧名称甲"
    assert result["boundRequirementIdsNotUpdated"] == [bound["id"]] and bound["name"] == "旧名称乙"
    assert result["retiredRequirementIds"] == ["REQ-GONE-01"]
    from apps.api.routes import project_requirements_for_node

    names = {item["name"] for item in project_requirements_for_node(project_id, int(unbound["nodeId"]))}
    assert "新版已删除的资料" not in names or repo.state["admin_config"].get("materialReviewPoints")
