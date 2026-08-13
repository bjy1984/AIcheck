"""按节点规则裁剪下发给模型的工具目录。

线上实测：一次审查的提示词里，`availableRuntimeTools` 占 31169 字符 ≈ 9740
tokens，是**整个 24000 预算的 41%**——而且这是挂 0 份资料时的数字。111 个工具
全量下发，其中包含 R13–R23 各条规则的专用工具（阀门抽样、制造监检…），而当时
审查的是节点 24 焊工资格证，一个都用不上。

节点 24 那次失败（REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED）就是这么来的：固定开销
先吃掉近一半预算，资料再一挂就超。

业务包里本来就有依据：atomic_checks.yaml 给出 nodeId → sourceRuleId，
atomic_check_tool_bindings.yaml 给出 sourceRuleId → tools。按它裁剪后，
单条规则中位数 442 tokens，省 95%。

## 为什么必须 fail-open

裁错了比不裁更糟：模型少一个取证工具，不会报错，只会给出一个「证据不足」或
更糟——基于残缺事实的判定。那是静默的错误结论，比 token 超限这种响亮的失败
危险得多。

所以这里的每一条路径都往「送全量」倒：认不出节点、查不到绑定、结果异常小，
一律退回完整目录。宁可偶尔超预算失败（看得见、能修），也不要悄悄削掉模型的手。
"""

from __future__ import annotations

from typing import Any

# 与具体规则无关、任何一次审查都可能用到的工具。
# 绑定表只声明规则专用工具，这些通用能力（取 OCR、定位证据、校验锚定）不在其中，
# 但少了它们模型连原文都读不到——必须无条件保留。
ALWAYS_AVAILABLE_TOOLS = frozenset(
    {
        "get_document_ocr_result",
        "recognize_document_seals",
        "recognize_signatures_and_seals",
        "extract_structured_fields",
        "extract_document_fields",
        "extract_table_records",
        "locate_evidence_fragment",
        "validate_evidence_grounding",
    }
)

# 裁剪后工具数低于这个值就判定「映射多半不对」，退回全量。
# 通用工具本身就有 8 个，再加规则专用的，正常不会低于 10。
MIN_TRUSTWORTHY_TOOL_COUNT = 10


def rule_ids_for_node(pack: dict[str, Any], node_id: int) -> set[str]:
    """节点用到的规则号（R01 这种）。

    走 atomic_checks 而不是 rules：rules.yaml 的 nodeIds 是一对多的反向索引，
    而 atomic_checks 每条都直接带 nodeId + sourceRuleId，是更直接的事实。
    """
    rule_ids: set[str] = set()
    for item in pack.get("atomicChecks") or []:
        if not isinstance(item, dict):
            continue
        try:
            if int(item.get("nodeId") or 0) != int(node_id):
                continue
        except (TypeError, ValueError):
            continue
        source_rule = str(item.get("sourceRuleId") or "").strip()
        if source_rule:
            rule_ids.add(source_rule)
    return rule_ids


def tool_names_for_rules(pack: dict[str, Any], rule_ids: set[str]) -> set[str]:
    """这些规则声明需要的工具名。"""
    names: set[str] = set()
    for binding in pack.get("atomicCheckToolBindings") or []:
        if not isinstance(binding, dict):
            continue
        if str(binding.get("sourceRuleId") or "").strip() not in rule_ids:
            continue
        for tool in binding.get("tools") or []:
            tool_name = str(tool or "").strip()
            if tool_name:
                names.add(tool_name)
    return names


def scoped_runtime_tool_catalog(
    catalog: list[dict[str, Any]],
    pack: dict[str, Any] | None,
    node_id: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """返回 (裁剪后的目录, 说明本次怎么裁的元信息)。

    元信息会进 promptAudit：裁剪影响模型能调什么工具，属于会改变判定结果的
    输入，必须可追溯——否则日后复盘一个可疑结论时，没人知道当时模型手里有什么。
    """
    full_count = len(catalog)

    def keep_all(reason: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return catalog, {"scoped": False, "reason": reason, "toolCount": full_count}

    if not pack:
        return keep_all("business_pack_unavailable")
    try:
        node_number = int(node_id or 0)
    except (TypeError, ValueError):
        return keep_all("node_id_not_numeric")
    if node_number <= 0:
        return keep_all("node_id_missing")

    rule_ids = rule_ids_for_node(pack, node_number)
    if not rule_ids:
        return keep_all("node_has_no_atomic_checks")

    wanted = tool_names_for_rules(pack, rule_ids) | set(ALWAYS_AVAILABLE_TOOLS)
    scoped = [item for item in catalog if str(item.get("name") or "") in wanted]

    # 绑定表里的工具名可能与运行时目录对不上（改名、未实现）。命中太少就说明
    # 映射不可信——这种时候送全量，让 token 超限去响亮地失败，也不要让模型
    # 带着残缺的工具集给出一个看起来正常的错结论。
    if len(scoped) < MIN_TRUSTWORTHY_TOOL_COUNT:
        return keep_all("scoped_set_too_small")

    return scoped, {
        "scoped": True,
        "reason": "node_rule_bindings",
        "nodeId": node_number,
        "ruleIds": sorted(rule_ids),
        "toolCount": len(scoped),
        "fullToolCount": full_count,
    }
