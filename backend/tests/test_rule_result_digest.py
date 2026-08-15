"""规则结果压缩：用节点 2 那次失败的真实数字。

2026-08-14 正式 ReviewRun 首次接上真模型即失败，提示词 103,308 字符 ≈ 29,554
token / 预算 24,000。其中 locate_evidence_fragment 一个工具结果就占 37,829 字符
（200 条证据引用 × 188 字符），而每条真正的内容只有 9 个字。
"""

from __future__ import annotations

import json

from libs.review_orchestrator.rule_result_digest import (
    MAX_EVIDENCE_REFS_IN_PROMPT,
    compact_rule_results,
)

# 线上单条证据引用的真实形状（RRUN-270D949AD1）。
# 实测 200 条共 37,829 字符，单条均值 189 字符——引用文本长短不一，
# 都写成最短的那条会让基线偏乐观，压缩效果看起来比实际好。
_QUOTED_SAMPLES = [
    "工艺设计说明书",
    "施工单位持有的特种设备安装改造修理许可证，许可类别为压力管道安装 GC2 级",
    "许可证编号 TS3234···，有效期至 2028 年 06 月 30 日",
    "监督检验机构核对人证相符，现场核查记录见附件三",
]


def _ref(index: int) -> dict:
    return {
        "evidenceRefId": f"EVR-{index:010X}",
        "documentVersionId": "DV-SCAN0969D121-V1",
        "pageNo": 1,
        "bbox": None,
        "quotedText": _QUOTED_SAMPLES[index % len(_QUOTED_SAMPLES)],
        "confidence": 0.9,
    }


def _rule_results(ref_count: int = 200) -> list[dict]:
    return [
        {
            "ruleCode": "R02",
            "result": "需补正",
            "ruleSetVersion": "engineering-inspection-r02-v20260703",
            "linkedClauseIds": ["LOC-AAA", "LOC-BBB"],
            "atomicCheckResults": [
                {
                    "atomicCheckId": "AC-R02-04",
                    "result": "证据不足",
                    "warnings": [],
                    "toolResults": [
                        {
                            "toolCallId": "RTC-1",
                            "toolName": "locate_evidence_fragment",
                            "status": "succeeded",
                            "evidenceRefCount": 405,
                            "evidenceRefs": [_ref(i) for i in range(ref_count)],
                        },
                        {
                            "toolCallId": "RTC-2",
                            "toolName": "validate_evidence_grounding",
                            "status": "succeeded",
                            "groundingStatus": "grounded",
                        },
                    ],
                }
            ],
        }
    ]


def _size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def test_基线数据的体量与线上同量级():
    """线上 200 条共 37,829 字符、单条均值 189。

    这条单独钉住，是因为压缩率算的是相对值：基线偏小的话，同样的压缩率
    看起来一样漂亮，但救不回真实的那次失败。
    """
    refs = _rule_results()[0]["atomicCheckResults"][0]["toolResults"][0]["evidenceRefs"]
    per_ref = _size(refs) / len(refs)
    assert 150 <= per_ref <= 230, f"单条 {per_ref:.0f} 字符，与线上实测 189 不同量级"


def test_把线上那次的体积压下来():
    before = _size(_rule_results())
    after = _size(compact_rule_results(_rule_results()))
    assert after < before * 0.2, f"压缩后仍有 {after} 字符（压缩前 {before}）"
    # 线上那次超预算 29,554 → 24,000，需要省下约 5,554 token ≈ 19,000 字符。
    # 这一处至少要够填上这个坑，否则修了也还是失败。
    assert before - after > 19000, f"只省下 {before - after} 字符，不足以让那次跑通"


def test_截断必须说明省了多少():
    """不说的话，模型会把这 20 条当成全部，得出「只找到 20 条证据」这种
    基于残缺事实的判断——那是看起来完成了的错误结论。"""
    tool = compact_rule_results(_rule_results())[0]["atomicCheckResults"][0]["toolResults"][0]
    assert len(tool["evidenceRefs"]) == MAX_EVIDENCE_REFS_IN_PROMPT
    assert tool["evidenceRefsOmitted"] == 200 - MAX_EVIDENCE_REFS_IN_PROMPT
    assert "另有" in tool["evidenceRefsNote"]
    # 总数不能丢——它是「候选池有多大」的唯一线索
    assert tool["evidenceRefCount"] == 405


def test_不截断本来就短的列表():
    tool = compact_rule_results(_rule_results(ref_count=5))[0]["atomicCheckResults"][0]["toolResults"][0]
    assert len(tool["evidenceRefs"]) == 5
    assert "evidenceRefsOmitted" not in tool, "没截断就不该出现截断说明"


def test_判断要用的字段一个都不能少():
    """结论、告警、条款关联都是模型判断的依据，压缩只该动引用列表。"""
    compacted = compact_rule_results(_rule_results())[0]
    assert compacted["result"] == "需补正"
    assert compacted["ruleCode"] == "R02"
    assert compacted["linkedClauseIds"] == ["LOC-AAA", "LOC-BBB"]
    check = compacted["atomicCheckResults"][0]
    assert check["atomicCheckId"] == "AC-R02-04"
    assert check["result"] == "证据不足"
    # 另一个工具结果不受影响
    assert compacted["atomicCheckResults"][0]["toolResults"][1]["groundingStatus"] == "grounded"


def test_不改传入的对象():
    """context["ruleResults"] 在别处还要用（写库、留痕），就地改会污染它们。"""
    original = _rule_results()
    compact_rule_results(original)
    assert len(original[0]["atomicCheckResults"][0]["toolResults"][0]["evidenceRefs"]) == 200


def test_只截认得出的引用列表():
    """凡是 list 就截会误伤 warnings、standardReferences 这类本该完整给出的短列表。"""
    rules = _rule_results(ref_count=3)
    rules[0]["atomicCheckResults"][0]["toolResults"][0]["warnings"] = [f"w{i}" for i in range(50)]
    tool = compact_rule_results(rules)[0]["atomicCheckResults"][0]["toolResults"][0]
    assert len(tool["warnings"]) == 50


def test_脏数据不炸():
    """这段在正式审查主链路上，带崩了整次审查就没了。"""
    assert compact_rule_results(None) == []
    assert compact_rule_results([]) == []
    assert compact_rule_results([None, 3]) == []  # type: ignore[list-item]
    assert compact_rule_results([{"ruleCode": "R02"}])[0]["ruleCode"] == "R02"
    assert compact_rule_results([{"atomicCheckResults": "坏数据"}]) == [
        {"atomicCheckResults": "坏数据"}
    ]
    assert compact_rule_results([{"atomicCheckResults": [{"toolResults": None}]}])


# ── 输出预算：同一个病、两条路，别只修一条 ──────────────────────────────


def test_正式审查的输出预算走统一口径():
    """2026-08-14：对话路径改用 reasoning_budget 后，正式路径仍写死 1600。

    节点 2 首次接上真模型返回 LLM_OUTPUT_TRUNCATED，用量 completion 1600 /
    reasoning 1600——推理占满 100%，正文一个字没写。与对话路径当时的症状
    完全一样，只是那次修完没有回头看还有谁在用自己的常量。
    """
    from libs.reasoning_budget import review_max_output_tokens
    from libs.review_orchestrator.execution import review_model_budget_policy

    policy = review_model_budget_policy({"modelAlias": "review-chat"})
    assert policy["maxOutputTokens"] == review_max_output_tokens()
    # 实测：成功那次 completion 5,245（推理 3,619）；6000 时又被推理占满。
    # 上限必须高过观测到的成功样本，否则「偶尔多想两步」就会被判失败。
    assert policy["maxOutputTokens"] > 6000


def test_推理占满额度要单独归因():
    """只报「截断了」等于没说。人需要知道的是「我该改什么」。"""
    from libs.reasoning_budget import truncation_caused_by_reasoning

    # 节点 2 那次的真实 usage：推理占 100%
    assert truncation_caused_by_reasoning(
        {"completion_tokens": 1600, "completion_tokens_details": {"reasoning_tokens": 1600}}, 1600
    ) is True
    # 正文写满被截断（推理 0）：调输出预算解决不了，标成推理耗尽会把人带偏。
    # 这一条是既有测试 test_generate_finding_drafts_rejects_truncated_provider_output
    # 抓出来的——它的 fixture 正是 finish_reason=length 且没有推理 token。
    assert truncation_caused_by_reasoning({"completion_tokens": 1600}, 1600) is False
    assert truncation_caused_by_reasoning(
        {"completion_tokens": 1600, "completion_tokens_details": {"reasoning_tokens": 50}}, 1600
    ) is False
    # 脏数据不炸
    assert truncation_caused_by_reasoning(None, 1600) is False
    assert truncation_caused_by_reasoning({"completion_tokens": "坏"}, 1600) is False


def test_两条路径的判据不能混用():
    """对话问「正文为什么是空的」，正式问「已经截断了，是谁占的」。

    finish_reason=length 对后者没有区分力：正文写满被截和推理吃光都报 length。
    直接复用对话那条判据，会把普通截断标成推理耗尽。
    """
    from libs.reasoning_budget import (
        output_budget_exhausted_by_reasoning,
        truncation_caused_by_reasoning,
    )

    plain_truncation = {"completion_tokens": 1600}
    # 对话路径：供应商说了 length，采信
    assert output_budget_exhausted_by_reasoning(plain_truncation, 1600, "length") is True
    # 正式路径：不看 finish_reason，只看推理占比
    assert truncation_caused_by_reasoning(plain_truncation, 1600) is False


def test_推理耗尽不进重试():
    """重试只会再被吃光一次，要改的是预算不是次数。"""
    from libs.review_orchestrator.execution import NON_RETRYABLE_REVIEW_REASONS

    assert "LLM_OUTPUT_BUDGET_EXHAUSTED_BY_REASONING" in NON_RETRYABLE_REVIEW_REASONS


def test_env_覆盖有下限():
    """低于 1600 连推理都装不下，配了等于把功能关掉。"""
    import os

    from libs.reasoning_budget import review_max_output_tokens

    old = os.environ.get("AICHECK_QWEN_REVIEW_MAX_TOKENS")
    try:
        os.environ["AICHECK_QWEN_REVIEW_MAX_TOKENS"] = "100"
        assert review_max_output_tokens() == 1600
        os.environ["AICHECK_QWEN_REVIEW_MAX_TOKENS"] = "不是数字"
        assert review_max_output_tokens() == 8000
    finally:
        if old is None:
            os.environ.pop("AICHECK_QWEN_REVIEW_MAX_TOKENS", None)
        else:
            os.environ["AICHECK_QWEN_REVIEW_MAX_TOKENS"] = old


def test_推理强度可配且认不出的取值退回默认():
    """把笔误原样透传给供应商换来的是一次 400，而那会被归因成
    「模型服务异常」——查起来完全不着边。"""
    import os

    from libs.reasoning_budget import review_reasoning_effort

    old = os.environ.get("AICHECK_REVIEW_REASONING_EFFORT")
    try:
        os.environ.pop("AICHECK_REVIEW_REASONING_EFFORT", None)
        assert review_reasoning_effort() == "low"
        os.environ["AICHECK_REVIEW_REASONING_EFFORT"] = "minimal"
        assert review_reasoning_effort() == "minimal"
        # 空串＝不下发该参数，回到供应商默认
        os.environ["AICHECK_REVIEW_REASONING_EFFORT"] = ""
        assert review_reasoning_effort() == ""
        os.environ["AICHECK_REVIEW_REASONING_EFFORT"] = "拼错了"
        assert review_reasoning_effort() == "low"
    finally:
        if old is None:
            os.environ.pop("AICHECK_REVIEW_REASONING_EFFORT", None)
        else:
            os.environ["AICHECK_REVIEW_REASONING_EFFORT"] = old


# ── 总量预算：逐字段截断不够，要管总量 ──────────────────────────────


def test_大量工具调用累加超预算时整体收紧():
    """2026-08-15 节点 1 实测：提示词 1,371,194 字符，ruleResults 占 98.9%。

    大头不在「单条有多大」而在「调了多少次」——单条 field 只有 1,054 字符，
    但每份文档都调一次 extract_document_fields，177 条加起来 18.6 万。
    只做逐字段截断后仍有 254,571 字符，超预算 3 倍。
    """
    # 仿真：多次工具调用，每次都不算大，但累加起来撑爆
    rules = [
        {
            "ruleCode": "R01",
            "result": "需补正",
            "atomicCheckResults": [
                {
                    "atomicCheckId": f"AC-{i:02d}",
                    "result": "证据不足",
                    "toolResults": [
                        {
                            "toolName": "extract_document_fields",
                            "status": "succeeded",
                            "fields": [
                                {"fieldCode": f"f{n}", "fieldValue": "x" * 300}
                                for n in range(40)
                            ],
                        }
                    ],
                }
                for i in range(20)
            ],
        }
    ]
    before = _size(rules)
    assert before > 200_000, f"基线没还原出「累加撑爆」的量级：{before}"
    after = _size(compact_rule_results(rules))
    assert after <= 60_000 + 2000, f"总量预算没生效，仍有 {after} 字符"


def test_表格里的_html_是重复内容不进提示词():
    """单张表 8,765 字符里，html 占 1,314——与 cells / normalizedRows
    是同一份内容的三种写法。模型读 cells 就够了。"""
    rules = [
        {
            "atomicCheckResults": [
                {
                    "toolResults": [
                        {
                            "toolName": "extract_table_records",
                            "tables": [{"cells": [1, 2], "html": "<table>…</table>"}],
                        }
                    ]
                }
            ]
        }
    ]
    table = compact_rule_results(rules)[0]["atomicCheckResults"][0]["toolResults"][0]["tables"][0]
    assert "cells" in table
    assert "html" not in table


def test_收紧时各字段一起缩而不是只缩一个():
    """收紧轮次里 max_refs 逐次减半，其余字段上限要按同比例跟着缩，
    否则只有 evidenceRefs 在变小，tables / fields 纹丝不动。"""
    rules = [
        {
            "atomicCheckResults": [
                {
                    "toolResults": [
                        {
                            "toolName": "mixed",
                            "evidenceRefs": [{"id": i} for i in range(50)],
                            "fields": [{"v": "y" * 800} for _ in range(60)],
                        }
                    ]
                }
            ]
        }
    ]
    tool = compact_rule_results(rules, max_chars=20_000)[0]["atomicCheckResults"][0]["toolResults"][0]
    assert len(tool["evidenceRefs"]) < 20
    assert len(tool["fields"]) < 60, "fields 没有跟着收紧"


# ── 兜底裁剪：白名单以外的键名也要收得住 ──────────────────────────
#
# 2026-08-15 实测：节点 24（R24 焊工资格证）按键名裁剪之后仍有 103,660 字符，
# 整场提示词 137,869，运行报 REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED。
# 大头在 atomicCheckResults[].toolResults[].input.facts（112,089 字符）
# 和 certificates——两个键名都不在白名单里。
#
# 白名单修得好今天这个节点，下一条规则换一组键名又会漏。


def test_白名单没覆盖的键名也能压到预算内():
    from libs.review_orchestrator.rule_result_digest import compact_rule_results

    # facts / certificates 都不在 _LIST_CAPS 里
    rule_results = [
        {
            "ruleId": "R24",
            "atomicCheckResults": [
                {
                    "atomicCheckId": f"AC-R24-{index:02d}",
                    "toolResults": [
                        {
                            "tool": "extract_document_fields",
                            "input": {
                                "facts": [{"text": "焊工资格" * 40} for _ in range(200)],
                                "certificates": [{"no": f"TS-{i}" * 20} for i in range(200)],
                            },
                        }
                    ],
                }
                for index in range(6)
            ],
        }
    ]
    import json

    raw = len(json.dumps(rule_results, ensure_ascii=False))
    compacted = compact_rule_results(rule_results)
    size = len(json.dumps(compacted, ensure_ascii=False))
    assert raw > 200000, "样本要足够大才说明问题"
    assert size <= 60000, f"压缩后仍有 {size} 字符，超预算"


def test_兜底截断要说明省略了多少():
    """截断本身不可怕，装作没截才可怕——模型和人都要看得出这里少了东西。"""
    from libs.review_orchestrator.rule_result_digest import _trim_generic

    trimmed = _trim_generic({"items": list(range(100))}, 5, 50)
    assert len(trimmed["items"]) == 6
    assert "另有 95 条" in trimmed["items"][-1]

    long_text = _trim_generic("字" * 500, 5, 50)
    assert long_text.endswith("（原文 500 字）")


def test_能收住就不多截():
    """本来就在预算内的，一个字都不该动。"""
    from libs.review_orchestrator.rule_result_digest import compact_rule_results

    small = [{"ruleId": "R01", "conclusion": "符合", "atomicCheckResults": []}]
    assert compact_rule_results(small) == small
