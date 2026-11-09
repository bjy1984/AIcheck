"""业务包规则以项目冻结包的版本为准（2026-11-09 生产 R01 口径不一致）。"""

from __future__ import annotations

import pytest

from libs.business_pack.loader import DEFAULT_BUSINESS_PACK_ID
from libs.db.repository import repo
from libs.review_orchestrator.execution import current_published_rule_for_node
from libs.rule_scope import select_rule_for_project

OLD = "engineering-inspection-r01-v20260714"
NEW = "engineering-inspection-r01-v20260923"


def shared_r01(version: str = OLD, **extra):
    return {
        "id": "RULE-ENG-INSP-R01",
        "sourceRuleId": "R01",
        "nodeIds": [1],
        "status": "已发布",
        "version": version,
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "publishedAt": "2026-06-26 09:12:00",
        "checkMethod": "GC2 管道要有 GC2 或 GC1 许可",
        **extra,
    }


def project_with_pack(
    project_id: str, r01_version: str, *, pack_id: str = DEFAULT_BUSINESS_PACK_ID
):
    return {
        "id": project_id,
        "businessPackId": pack_id,
        "businessPackSnapshot": {
            "version": "2026.09.23" if r01_version == NEW else "2026.07.16",
            "ruleSets": [
                {
                    "id": "RULE-ENG-INSP-R01",
                    "sourceRuleId": "R01",
                    "nodeIds": [1],
                    "status": "已发布",
                    "version": r01_version,
                    "checkMethod": "GC2 管道可由 GC2、GC1 或 GCD 许可覆盖"
                    if r01_version == NEW
                    else "GC2 管道要有 GC2 或 GC1 许可",
                }
            ],
        },
    }


def test_新包项目用冻结包里的新版本() -> None:
    rule = select_rule_for_project([shared_r01()], 1, project=project_with_pack("P-NEW", NEW))
    assert rule["version"] == NEW
    assert "GCD" in rule["checkMethod"]
    assert rule["ruleSource"] == "project-business-pack"
    assert rule["sharedRuleVersion"] == OLD
    assert rule["businessPackId"] == DEFAULT_BUSINESS_PACK_ID
    assert rule["businessPackVersion"] == "2026.09.23"


def test_老包项目版本一致时照旧用共用记录() -> None:
    shared = shared_r01()
    rule = select_rule_for_project([shared], 1, project=project_with_pack("P-OLD", OLD))
    assert rule == shared and "ruleSource" not in rule
    # 返回的是副本，改它不影响库里的记录
    rule["status"] = "changed"
    assert shared["status"] == "已发布"


def test_共用记录以后升到新版时老包项目留在旧版() -> None:
    rule = select_rule_for_project([shared_r01(NEW)], 1, project=project_with_pack("P-OLD", OLD))
    assert rule["version"] == OLD and rule["sharedRuleVersion"] == NEW


def test_项目内规则仍然最优先() -> None:
    project_rule = shared_r01(
        "project-r01-v1", id="RULE-PROJECT-R01", projectId="P-NEW", publishedAt="2026-01-01"
    )
    rule = select_rule_for_project(
        [shared_r01(), project_rule], 1, project=project_with_pack("P-NEW", NEW)
    )
    assert rule["id"] == "RULE-PROJECT-R01" and "ruleSource" not in rule


def test_管理员改版发布的规则不被冻结包覆盖() -> None:
    # 「基于正式规则创建草稿」再发布：新 id、新版本，发布时间更新
    edited = shared_r01(
        "engineering-inspection-r01-draft-20261109-1000",
        id="RULE-AB12CD34EF",
        forkedFromRuleVersionId="RULE-ENG-INSP-R01",
        publishedAt="2026-11-09 10:00:00",
    )
    rule = select_rule_for_project(
        [shared_r01(), edited], 1, project=project_with_pack("P-NEW", NEW)
    )
    assert rule["id"] == "RULE-AB12CD34EF" and "ruleSource" not in rule


@pytest.mark.parametrize(
    "project",
    [
        None,
        {"id": "P-NO-SNAPSHOT"},
        project_with_pack("P-OTHER-PACK", NEW, pack_id="other_pack"),
    ],
)
def test_没有冻结包或业务包不同时用共用记录(project) -> None:
    shared = shared_r01()
    assert select_rule_for_project([shared], 1, project=project) == shared


def test_没有已发布规则时交给调用方回落() -> None:
    assert select_rule_for_project([], 1, project=project_with_pack("P-NEW", NEW)) is None


def test_正式复核取规则的入口按项目冻结包校正(monkeypatch) -> None:
    monkeypatch.setitem(repo.state, "rule_versions", [shared_r01()])
    monkeypatch.setitem(
        repo.state,
        "projects",
        [project_with_pack("P-NEW", NEW), project_with_pack("P-OLD", OLD)],
    )
    assert current_published_rule_for_node(1, project_id="P-NEW")["version"] == NEW
    assert current_published_rule_for_node(1, project_id="P-OLD")["version"] == OLD
    # 不带项目（规则库视图等）仍是共用记录
    assert current_published_rule_for_node(1)["version"] == OLD
