"""按节点规则裁剪工具目录。

线上实测：availableRuntimeTools 占 31169 字符 ≈ 9740 tokens，是 24000 预算的
41%——挂 0 份资料就吃掉近一半。节点 24 那次 REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED
就是这么来的。

这些用例钉的不是「省了多少」，是**裁错时必须退回全量**：模型少一个取证工具不会
报错，只会基于残缺事实给出一个看起来正常的错结论。那比 token 超限危险得多——
超限是响亮的失败，看得见、能修。
"""

from __future__ import annotations

from libs.review_orchestrator.tool_scope import (
    ALWAYS_AVAILABLE_TOOLS,
    MIN_TRUSTWORTHY_TOOL_COUNT,
    rule_ids_for_node,
    scoped_runtime_tool_catalog,
)

# 造一个够大的目录：通用 8 个 + R24 专用 4 个 + 别的规则 40 个
CATALOG = [
    *({"name": name, "inputSchema": {}} for name in sorted(ALWAYS_AVAILABLE_TOOLS)),
    *({"name": f"evaluate_r24_item{i}", "inputSchema": {}} for i in range(4)),
    *({"name": f"evaluate_r23_valve{i}", "inputSchema": {}} for i in range(40)),
]

PACK = {
    "atomicChecks": [
        {"nodeId": 24, "sourceRuleId": "R24"},
        {"nodeId": 24, "sourceRuleId": "R24"},
        {"nodeId": 23, "sourceRuleId": "R23"},
    ],
    "atomicCheckToolBindings": [
        {"sourceRuleId": "R24", "tools": [f"evaluate_r24_item{i}" for i in range(4)]},
        {"sourceRuleId": "R23", "tools": [f"evaluate_r23_valve{i}" for i in range(40)]},
    ],
}


def test_other_rules_tools_are_dropped() -> None:
    """节点 24 不该拿到 R23 的阀门抽样工具——那正是撑爆预算的东西。"""
    scoped, meta = scoped_runtime_tool_catalog(CATALOG, PACK, 24)
    names = {t["name"] for t in scoped}
    assert meta["scoped"] is True
    assert not any(n.startswith("evaluate_r23_") for n in names), "别的规则的工具必须裁掉"
    assert {f"evaluate_r24_item{i}" for i in range(4)} <= names, "本节点规则的工具一个不能少"
    assert len(scoped) < len(CATALOG)


def test_generic_tools_are_always_kept() -> None:
    """通用取证工具不在绑定表里，但少了它们模型连原文都读不到。"""
    scoped, _ = scoped_runtime_tool_catalog(CATALOG, PACK, 24)
    names = {t["name"] for t in scoped}
    assert ALWAYS_AVAILABLE_TOOLS <= names


def test_unknown_node_falls_back_to_full_catalog() -> None:
    """认不出节点就送全量。

    裁错了不会报错，只会让模型基于残缺事实给出看起来正常的错结论——
    宁可 token 超限响亮地失败。
    """
    scoped, meta = scoped_runtime_tool_catalog(CATALOG, PACK, 999)
    assert scoped == CATALOG
    assert meta["scoped"] is False
    assert meta["reason"] == "node_has_no_atomic_checks"


def test_missing_pack_falls_back_to_full_catalog() -> None:
    scoped, meta = scoped_runtime_tool_catalog(CATALOG, None, 24)
    assert scoped == CATALOG
    assert meta["reason"] == "business_pack_unavailable"


def test_non_numeric_node_falls_back() -> None:
    for node_id in (None, "", "abc", 0):
        scoped, meta = scoped_runtime_tool_catalog(CATALOG, PACK, node_id)
        assert scoped == CATALOG, node_id
        assert meta["scoped"] is False, node_id


def test_stale_binding_names_fall_back_instead_of_crippling_the_model() -> None:
    """绑定表里的工具名与运行时目录对不上时退回全量。

    工具改名或未实现，命中就会异常少。这种时候硬裁，等于悄悄削掉模型的手；
    宁可送全量让预算去报错。
    """
    stale_pack = {
        "atomicChecks": [{"nodeId": 24, "sourceRuleId": "R24"}],
        "atomicCheckToolBindings": [
            {"sourceRuleId": "R24", "tools": ["tool_that_was_renamed"]}
        ],
    }
    tiny_catalog = [{"name": "get_document_ocr_result"}, {"name": "evaluate_r23_valve0"}]
    scoped, meta = scoped_runtime_tool_catalog(tiny_catalog, stale_pack, 24)
    assert scoped == tiny_catalog
    assert meta["reason"] == "scoped_set_too_small"
    assert len(tiny_catalog) < MIN_TRUSTWORTHY_TOOL_COUNT


def test_node_with_multiple_rules_gets_all_of_them() -> None:
    """一个节点可以挂多条规则，工具要取并集，不能只认第一条。"""
    pack = {
        "atomicChecks": [
            {"nodeId": 7, "sourceRuleId": "R07"},
            {"nodeId": 7, "sourceRuleId": "R60"},
        ],
        "atomicCheckToolBindings": [
            {"sourceRuleId": "R07", "tools": ["evaluate_r24_item0"]},
            {"sourceRuleId": "R60", "tools": ["evaluate_r24_item1"]},
        ],
    }
    assert rule_ids_for_node(pack, 7) == {"R07", "R60"}
    names = {t["name"] for t in scoped_runtime_tool_catalog(CATALOG, pack, 7)[0]}
    assert {"evaluate_r24_item0", "evaluate_r24_item1"} <= names


def test_scope_decision_is_recorded_for_audit() -> None:
    """裁剪影响判定，必须可追溯——复盘可疑结论时要知道当时模型手里有什么。"""
    _, meta = scoped_runtime_tool_catalog(CATALOG, PACK, 24)
    assert meta["nodeId"] == 24
    assert meta["ruleIds"] == ["R24"]
    assert meta["fullToolCount"] == len(CATALOG)
    assert meta["toolCount"] < meta["fullToolCount"]
