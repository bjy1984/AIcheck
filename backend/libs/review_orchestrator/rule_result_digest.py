"""把工具输出压成能进提示词的体积。

## 线上实测（2026-08-14，节点 2「施工单位许可资质」）

正式 ReviewRun 首次接上真模型后立刻失败：`REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED`，
提示词 103,308 字符 ≈ 29,554 token，预算 24,000。拆开看：

    ruleResults          52,828 字符  55.0%
      └ atomicCheckResults 52,108
          └ AC-R02-04     38,340
              └ locate_evidence_fragment  37,829
    groundedOcrEvidence  30,750 字符  32.0%
    availableRuntimeTools 1,877 字符   2.0%   ← 工具裁剪是生效的

那 37,829 字符是 200 条证据片段，每条 188 字符，而每条真正的内容
（quotedText）只有 9 个字：「工艺设计说明书」。其余全是 evidenceRefId、
documentVersionId、bbox、confidence 的包装开销。

## 根因：同一份数据两条路，只有一条有护栏

组装提示词时：

    "runtimeToolResults": {k: compact_tool_output(v) for ...},   ← 压了，1,053 字符
    "ruleResults": context.get("ruleResults") or [],             ← 没压，52,828 字符

`compact_tool_output` 的白名单里有 `fragmentCount`（计数）而没有 `evidenceRefs`
（全量列表），所以走它的那条路天然是安全的。规则结果这条路绕过了它。

`refs[:200]` 这个上限本身没错——它是**工具返回**的上限，对工具调用是合理的。
错在把工具返回原样当成提示词内容。

## 为什么是「截断并说明」而不是「删掉」

删掉证据引用，模型就没法在 finding 里给出 evidenceRefs，护栏会把结论降级为
「证据不足」。那是一个**看起来完成了的错误结论**，比 token 超限这种响亮失败
危险得多（同 tool_scope 的取舍）。

所以保留前 N 条、并把省略了多少写进去。模型据此知道「还有更多，可以用
locate_evidence_fragment 再查」，而不是以为总共就这些。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# 每个工具结果里最多带几条证据引用进提示词。
#
# 20 条 ≈ 3.8k 字符，足够模型引用取证；200 条 ≈ 37.6k 字符，等于整个预算的 39%。
# 出结论需要的是「指得出几条像样的证据」，不是把候选池全部背下来。
MAX_EVIDENCE_REFS_IN_PROMPT = 20

# 带证据引用列表的工具。列出来而不是「凡是 list 就截」——后者会误伤
# warnings、standardReferences 这类本来就该完整给出的短列表。
_REF_LIST_KEYS = ("evidenceRefs", "fragments", "candidates")


def _digest_tool_result(result: dict[str, Any], max_refs: int) -> dict[str, Any]:
    compacted = deepcopy(result)
    for key in _REF_LIST_KEYS:
        refs = compacted.get(key)
        if not isinstance(refs, list) or len(refs) <= max_refs:
            continue
        omitted = len(refs) - max_refs
        compacted[key] = refs[:max_refs]
        # 明说省了多少。不说的话模型会把这 20 条当成全部，
        # 进而得出「只找到 20 条证据」这种基于残缺事实的判断。
        compacted[f"{key}Omitted"] = omitted
        compacted[f"{key}Note"] = (
            f"仅列出前 {max_refs} 条，另有 {omitted} 条未列出；"
            "需要更多可再次调用对应取证工具。"
        )
    return compacted


def compact_rule_results(
    rule_results: list[dict[str, Any]] | None,
    max_refs: int = MAX_EVIDENCE_REFS_IN_PROMPT,
) -> list[dict[str, Any]]:
    """压缩规则结果里嵌套的工具输出，供提示词使用。

    只动 `atomicCheckResults[].toolResults[]` 里的引用列表，其余原样保留——
    结论、告警、条款关联都是模型判断要用的，一个字都不能少。
    """
    compacted: list[dict[str, Any]] = []
    for rule in rule_results or []:
        if not isinstance(rule, dict):
            continue
        item = deepcopy(rule)
        checks = item.get("atomicCheckResults")
        if isinstance(checks, list):
            item["atomicCheckResults"] = [
                {
                    **check,
                    "toolResults": [
                        _digest_tool_result(tool, max_refs) if isinstance(tool, dict) else tool
                        for tool in check.get("toolResults") or []
                    ],
                }
                if isinstance(check, dict) and isinstance(check.get("toolResults"), list)
                else check
                for check in checks
            ]
        compacted.append(item)
    return compacted


# ── 单个工具输出的摘要 ─────────────────────────────────────────────
#
# 从 execution.py 搬过来，与 compact_rule_results 放在一起。
#
# 分处两地正是今天这个 bug 的结构性原因：组装提示词时
# runtimeToolResults 走了 compact_tool_output（1,053 字符），
# ruleResults 直接原样进（52,828 字符）。两个函数做的是同一件事——
# 「把工具输出压到能进提示词」——却没有任何地方让人看出漏了一条路。
# 放在同一个模块里，下次再漏一眼就能看见。
def compact_tool_output(result: dict[str, Any]) -> dict[str, Any]:
    summary_keys = [
        "toolCallId",
        "toolName",
        "status",
        "result",
        "ruleVersion",
        "errorCode",
        "candidateCount",
        "fieldCount",
        "tableCount",
        "sealCount",
        "fragmentCount",
        "welderCertificateCount",
        "verificationCount",
        "qualifiedItemCount",
        "matchedIssuerSealCount",
        "recognizedSealCount",
        "groundingStatus",
        "summary",
        "warnings",
        "keyword",
        "total",
        "rowCount",
        "idNumber",
        "personName",
        "issuer",
        "qualifiedItems",
        "validUntil",
        "citedRef",
        "canonicalRef",
        "verdict",
        "standardReferences",
        "matched",
        "currentExecution",
        "query",
    ]
    summary = {key: result.get(key) for key in summary_keys if key in result}
    if result.get("verificationCount") is not None:
        summary["riskFlags"] = [
            flag
            for item in result.get("verifications") or []
            if isinstance(item, dict)
            for flag in item.get("riskFlags") or []
        ][:12]
    return summary
