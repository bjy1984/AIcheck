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

# 会撑爆提示词的列表字段 → 各自的条数上限。
#
# 列出来而不是「凡是 list 就截」——后者会误伤 warnings、standardReferences
# 这类本来就该完整给出的短列表。
#
# 2026-08-15 实测（节点 1，提示词 1,371,194 字符、ruleResults 占 98.9%）：
#
#     extract_table_records.tables            983,208 字符  44 张表
#     extract_document_fields.fields          314,440
#     locate_evidence_fragment.evidenceRefs    42,784
#     recognize_signatures_and_seals.seals      9,905
#
# 第一版只截了 evidenceRefs（42,784），漏掉的 130 万一点没动，
# 于是这个节点每次发起复核必然 REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED。
# **只堵最显眼的那个洞，等于没堵。**
#
# 上限按单项体积反着定：表格单张就 8,765 字符，给 5 张已是 4 万；
# 字段单条几十字符，给 60 条才三千。
_LIST_CAPS = {
    "evidenceRefs": 20,
    "fragments": 20,
    "candidates": 20,
    "tables": 5,
    "fields": 60,
    "seals": 10,
    "verifications": 20,
    "records": 30,
}

# 表格里 html 与 cells / normalizedRows 是同一份内容的三种写法。
# 模型读 cells 就够了，html 纯属重复付费——单张表里它占 1,314 字符。
_DROP_IN_TABLE = ("html",)


def _strip_table_duplicates(tables: list[Any]) -> list[Any]:
    """去掉表格里与 cells 重复的表述。"""
    out = []
    for table in tables:
        if isinstance(table, dict):
            table = {k: v for k, v in table.items() if k not in _DROP_IN_TABLE}
        out.append(table)
    return out


def _digest_tool_result(result: dict[str, Any], max_refs: int) -> dict[str, Any]:
    compacted = deepcopy(result)
    for key, default_cap in _LIST_CAPS.items():
        refs = compacted.get(key)
        if not isinstance(refs, list):
            continue
        # evidenceRefs 沿用调用方传入的上限（既有测试按它断言）；
        # 其余用各自的默认上限。
        # 收紧轮次里 max_refs 会被逐次减半，各字段上限跟着同比例收，
        # 否则只有 evidenceRefs 在缩，其余纹丝不动。
        ratio = max_refs / MAX_EVIDENCE_REFS_IN_PROMPT
        cap = max_refs if key == "evidenceRefs" else max(1, int(default_cap * ratio))
        if key == "tables":
            refs = _strip_table_duplicates(refs)
            compacted[key] = refs
        if len(refs) <= cap:
            continue
        omitted = len(refs) - cap
        compacted[key] = refs[:cap]
        # 明说省了多少。不说的话模型会把这几条当成全部，
        # 进而得出「只找到 N 条证据」这种基于残缺事实的判断。
        compacted[f"{key}Omitted"] = omitted
        compacted[f"{key}Note"] = (
            f"仅列出前 {cap} 条，另有 {omitted} 条未列出；"
            "需要更多可再次调用对应取证工具。"
        )
    return compacted


# 规则结果在提示词里的总字符预算。
#
# 逐字段设上限治标不治本：单条 field 只有 1,054 字符，但每份文档都会调一次
# extract_document_fields，177 条加起来仍有 18.6 万。**该管的是总量。**
#
# 60,000 字符 ≈ 17k token，给 24,000 token 的输入预算留出条款、证据、
# 工具目录的位置。
MAX_RULE_RESULTS_CHARS = 60000


def _measure(value: Any) -> int:
    import json as _json

    return len(_json.dumps(value, ensure_ascii=False))


def compact_rule_results(
    rule_results: list[dict[str, Any]] | None,
    max_refs: int = MAX_EVIDENCE_REFS_IN_PROMPT,
    max_chars: int = MAX_RULE_RESULTS_CHARS,
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
    # 逐字段截完仍超总量预算，就整体收紧到能装下为止。
    #
    # 2026-08-15 实测：节点 1 只做逐字段截断后仍有 254,571 字符（超预算 3 倍），
    # 因为大头不在单条有多大，而在调用次数有多少。
    shrink = max_refs
    while _measure(compacted) > max_chars and shrink > 1:
        shrink = max(1, shrink // 2)
        compacted = [
            {
                **rule,
                "atomicCheckResults": [
                    {
                        **check,
                        "toolResults": [
                            _digest_tool_result(tool, shrink) if isinstance(tool, dict) else tool
                            for tool in check.get("toolResults") or []
                        ],
                    }
                    if isinstance(check, dict) and isinstance(check.get("toolResults"), list)
                    else check
                    for check in rule.get("atomicCheckResults") or []
                ],
            }
            if isinstance(rule.get("atomicCheckResults"), list)
            else rule
            for rule in compacted
        ]
    if _measure(compacted) > max_chars:
        compacted = _trim_by_shape(compacted, max_chars)
    return compacted


#: 兜底裁剪一轮里，列表最多留几项、字符串最多留多少字。逐轮收紧。
_FALLBACK_ROUNDS = ((20, 600), (10, 300), (5, 200), (3, 120), (1, 80))


def _trim_generic(value: Any, max_items: int, max_text: int) -> Any:
    """与形状无关地裁剪：列表截断、超长字符串截断，其余原样。"""
    if isinstance(value, dict):
        return {key: _trim_generic(item, max_items, max_text) for key, item in value.items()}
    if isinstance(value, list):
        kept = [_trim_generic(item, max_items, max_text) for item in value[:max_items]]
        dropped = len(value) - len(kept)
        if dropped > 0:
            kept.append(f"…（另有 {dropped} 条同类记录已省略）")
        return kept
    if isinstance(value, str) and len(value) > max_text:
        return value[:max_text] + f"…（原文 {len(value)} 字）"
    return value


def _trim_by_shape(compacted: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    """按键名裁剪之后仍然超预算时的兜底。

    2026-08-15 实测：节点 24（R24 焊工资格证）逐字段截断后仍有 103,660 字符，
    整场提示词 137,869 字符，运行报 REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED。
    大头在 `atomicCheckResults[].toolResults[].input.facts`（112,089 字符）
    和 `certificates`——这两个键名都不在按键名裁剪的白名单里。

    白名单能修好今天这个节点，但下一条规则换一组键名又会漏。所以再加一道
    **不认键名**的兜底：只按「列表太长、字符串太长」收，形状怎么变都收得住。

    代价是可能截到判断要用的内容，所以它排在按键名裁剪之后——
    能靠语义收住就不动这一刀；真到这一步，截断处会明说省略了多少。
    """
    for max_items, max_text in _FALLBACK_ROUNDS:
        compacted = _trim_generic(compacted, max_items, max_text)
        if _measure(compacted) <= max_chars:
            break
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
