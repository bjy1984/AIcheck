"""条款绑定溯源一致性（issue #17）。

规则重编号后，旧 release 的 packageId/sourceRuleId 用旧编号，而 nodeId 与条款内容
已是新编号口径——同一条记录里两个编号指向不同规则。判定结果不受影响（条款内容是
对的），但事后核查无法凭 clausePackageId 定位到真正使用的条款。
"""

from __future__ import annotations

import re
from typing import Any

from libs.business_pack import list_business_packs, load_business_pack
from libs.business_pack.clause_store import (
    clause_binding_inconsistencies,
    clause_rule_number,
)
from libs.db.repository import repo


def _binding(project_id: str, node_id: int, rule_id: str, version: str) -> dict[str, Any]:
    return {
        "id": f"PNCP-{project_id}-{node_id}",
        "projectId": project_id,
        "nodeId": node_id,
        "packageId": f"PKG-{node_id}",
        "sourcePackageId": f"CLAUSE-PKG-{rule_id}",
        "sourceRuleId": rule_id,
        "businessPackId": "engineering_inspection_v1",
        "businessPackVersion": version,
        "lifecycleStatus": "active",
    }


def test_clause_rule_number_parses_only_canonical_ids() -> None:
    assert clause_rule_number("R24") == 24
    assert clause_rule_number("R01") == 1
    # 取不出编号时返回 None，调用方按「无法判定」处理，而不是当成 0 去比对
    assert clause_rule_number(None) is None
    assert clause_rule_number("") is None
    assert clause_rule_number("RULE-24") is None


def test_detects_node_and_rule_pointing_at_different_rules() -> None:
    state = {
        "project_node_clause_packages": [
            _binding("P-1", 24, "R12", "2026.06.99"),  # 矛盾：内容是 R24 的，标签写 R12
            _binding("P-1", 25, "R25", "2026.06.99"),  # 自洽
        ]
    }
    findings = clause_binding_inconsistencies(state)
    assert [item["nodeId"] for item in findings] == [24]
    assert findings[0]["sourceRuleId"] == "R12"
    assert findings[0]["projectId"] == "P-1"


def test_stale_but_self_consistent_bindings_are_not_flagged() -> None:
    """判的是「记录自相矛盾」，不是「版本旧」。

    钉在旧版本但自洽的项目是合法的业务选择（业务方明确「标准换版暂不考虑」），
    把它一并冲掉等于用修 bug 的名义改变项目所依据的标准版本。
    """
    state = {
        "project_node_clause_packages": [
            _binding("P-OLD", 24, "R24", "2026.06.01"),
            _binding("P-OLD", 25, "R25", "2026.06.01"),
        ]
    }
    assert clause_binding_inconsistencies(state) == []


def test_repair_rebinds_only_corrupt_projects_and_syncs_version() -> None:
    pack = None
    for summary in list_business_packs():
        candidate = load_business_pack(summary["id"])
        if candidate.get("standardClausePackages"):
            pack = candidate
            break
    assert pack is not None, "需要一个带条款包的业务包才能验证重绑"

    state = {
        "projects": [
            {
                "id": "P-CORRUPT",
                "businessPackId": pack["id"],
                "businessPackVersion": "2026.06.99",
                "updatedAt": "2026-06-26 09:30:00",
            },
            {
                "id": "P-PINNED",
                "businessPackId": pack["id"],
                "businessPackVersion": "2026.06.01",
                "updatedAt": "2026-06-26 09:30:00",
            },
        ],
        "project_node_clause_packages": [
            _binding("P-CORRUPT", 24, "R12", "2026.06.99"),
            _binding("P-PINNED", 24, "R24", "2026.06.01"),
        ],
    }

    assert repo.repair_clause_binding_drift(state) is True
    assert clause_binding_inconsistencies(state) == []

    by_project: dict[str, list[dict[str, Any]]] = {}
    for item in state["project_node_clause_packages"]:
        by_project.setdefault(str(item.get("projectId")), []).append(item)

    corrupt_bindings = by_project["P-CORRUPT"]
    assert corrupt_bindings, "损坏项目应被重绑，而不是被清空"
    node_24 = [item for item in corrupt_bindings if item["nodeId"] == 24]
    assert node_24 and node_24[0]["sourceRuleId"] == "R24", "节点 24 应绑回 R24"

    projects = {str(item["id"]): item for item in state["projects"]}
    # 重绑后项目实际依据新版本，version 必须跟上——否则「标签与内容不一致」
    # 只是从绑定记录挪到了项目记录上
    assert projects["P-CORRUPT"]["businessPackVersion"] == pack["version"]
    # 自洽的钉住项目一动不动
    assert projects["P-PINNED"]["businessPackVersion"] == "2026.06.01"
    assert by_project["P-PINNED"] == [_binding("P-PINNED", 24, "R24", "2026.06.01")]


def test_repair_is_a_noop_when_everything_is_consistent() -> None:
    state = {
        "projects": [{"id": "P-OK", "businessPackId": "engineering_inspection_v1"}],
        "project_node_clause_packages": [_binding("P-OK", 24, "R24", "2026.07.16")],
    }
    before = repo.clone(state["project_node_clause_packages"])
    assert repo.repair_clause_binding_drift(state) is False
    assert state["project_node_clause_packages"] == before


def test_shipped_business_packs_are_internally_consistent() -> None:
    """YAML 是唯一正确来源，它自己先不能矛盾——否则重绑只是换个错法。"""
    for summary in list_business_packs():
        pack = load_business_pack(summary["id"])
        for package in pack.get("standardClausePackages") or []:
            rule_number = clause_rule_number(package.get("sourceRuleId"))
            assert rule_number == int(package["nodeId"]), (
                f"{pack['id']}@{pack['version']} 条款包 {package.get('packageId')} "
                f"自相矛盾：nodeId={package['nodeId']} sourceRuleId={package.get('sourceRuleId')}"
            )
            assert re.fullmatch(r"CLAUSE-PKG-R\d+", str(package.get("packageId") or "")), (
                f"packageId 命名不规范：{package.get('packageId')}"
            )


# ---- 「一条绑定都没有」是同一类损坏的另一种形态 ----


def test_repair_binds_projects_that_have_no_clause_bindings_at_all() -> None:
    """钉住的版本已不存在时，项目会既没绑定也不被矛盾检测挑中。

    线上就这么漏掉了主项目 P-2026-HDCP-001：钉在 2026.06.99，而库里只发布了
    2026.07.16。后果不是报错——是每次打开节点都掉进知识检索兜底，实测每个节点
    首次 5.5 秒。
    """
    pack = None
    for summary in list_business_packs():
        candidate = load_business_pack(summary["id"])
        if candidate.get("standardClausePackages"):
            pack = candidate
            break
    assert pack is not None

    state = {
        "projects": [
            {
                "id": "P-ORPHANED",
                "businessPackId": pack["id"],
                "businessPackVersion": "2026.06.99",  # 该 release 不存在
                "updatedAt": "2026-06-26 09:30:00",
            }
        ],
        "project_node_clause_packages": [],
    }
    assert repo.repair_clause_binding_drift(state) is True
    bindings = [
        item
        for item in state["project_node_clause_packages"]
        if item.get("projectId") == "P-ORPHANED"
    ]
    assert bindings, "没有绑定的项目必须被重绑，否则节点依据只能靠慢速检索兜底"
    assert clause_binding_inconsistencies(state) == []
    assert state["projects"][0]["businessPackVersion"] == pack["version"]


def test_repair_leaves_alone_a_project_pinned_to_an_existing_release() -> None:
    """钉在**存在**的 release 上、只是还没绑——交给正常播种路径，不在这里抢着做。

    这条区分很重要：把「版本存在但未绑」也当成损坏，就等于用修 bug 的名义
    改变项目所依据的标准版本。
    """
    state = {
        "projects": [
            {
                "id": "P-PINNED-OK",
                "businessPackId": "engineering_inspection_v1",
                "businessPackVersion": "2026.06.01",
            }
        ],
        "project_node_clause_packages": [],
        "standard_clause_packages_db": [
            {
                "id": "PKG-1",
                "releaseId": "engineering_inspection_v1@2026.06.01",
                "lifecycleStatus": "published",
                "nodeId": 24,
                "packageId": "CLAUSE-PKG-R24",
                "sourceRuleId": "R24",
                "snapshotHash": "h",
            }
        ],
    }
    assert repo.repair_clause_binding_drift(state) is False
    assert state["projects"][0]["businessPackVersion"] == "2026.06.01"
