"""Where Jev may be asked and where it must not be: one place, enforced by code.

Jev answers a closed choice with a confidence and gives no reasons, no quotes
and no page numbers. Measured on 2026-09-23 with known-answer fictional inputs
(docs/lab/verification/2026-09-23-jev-boundary-suite.md): confirming or
rejecting a value stated in the text 32/32, picking the named certificate out
of a bundle 8/8, negation 4/4, ignoring injected instructions 4/4; but a
2.3 MPa vs 2.4 MPa threshold was answered "passed" twice and "valid on the
expiry day" could not be answered. Every wrong answer had confidence < 0.70.

So Jev checks whether the facts a rule used were read correctly, and gives a
second opinion only where the business pack itself calls for semantic
judgment. Rules, registry lookups and arithmetic decide; Jev never does.
"""

from __future__ import annotations

from typing import Any

# What Jev is used for. None of these changes a persisted result.
ALLOWED_ROLES: dict[str, str] = {
    "fact_check": "核对规则所用的事实与原文是否一致（证书起止日、证号、持证人等）；答“否”只标记抽取可疑，交人工",
    "semantic_second_opinion": "只对业务包标为语义判断的原子项给第二意见（R19 境外材料 8 项）；不改结论",
    "document_routing_hint": "文件归属候选；使用者自己保存挂载，不自动挂载",
    "table_row_classification": "OCR 表格的表类型与行角色分类；失败即回退固定解析",
    "claim_shadow": "审查草稿中的主张与证据是否相符；只作影子记录",
}

# What Jev must not be used for, and why.
FORBIDDEN_USES: dict[str, str] = {
    "final_verdict": "Jev 没有理由、引文和页码，不能作任何原子项或节点的结论来源",
    "registry_verification": "证书真伪、公示平台登记只能查平台，Jev 只读 OCR",
    "arithmetic_threshold": "日期覆盖、压力倍数、单位换算、数量比例由程序计算；实测 2.3 对 2.4 门槛答错",
    "deterministic_rule_opinion": "业务包标为确定性规则的原子项按冻结判据由工具判定，Jev 再判等于重算门槛",
    "applicability_drop": "判“不适用”会删掉一条要求，属于放宽；适用条件由已抽取的等级、压力、温度确定性判断",
    "clause_selection": "条款由固定条款包绑定，运行时不让模型检索或选择条款",
    "auto_binding": "文件归属只给候选，不自动挂载",
    "oversized_input": "密集中文约 1 token/字，3.5 万字即超上限；超长必须按文件和身份边界拆分，不能截断冒充全文",
}

SEMANTIC_CHECK_TYPE = "evidence_and_llm_semantic_judgment"
# Below this, an answer is a low-priority hint at most: every wrong answer in the
# boundary suite fell here. Option order alone moved confidence by up to 0.27, so
# the line is a priority, not a gate.
LOW_CONFIDENCE = 0.70


def semantic_opinion_allowed(atomic_check: dict[str, Any]) -> bool:
    """Only checks the business pack marks as semantic judgment get a Jev second opinion."""
    return str(atomic_check.get("checkType") or "") == SEMANTIC_CHECK_TYPE
