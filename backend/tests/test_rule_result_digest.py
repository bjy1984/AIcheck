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
    # 实测推理一次就用掉 1600，上限必须高于它，否则正文永远没份
    assert policy["maxOutputTokens"] > 1600


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
        assert review_max_output_tokens() == 6000
    finally:
        if old is None:
            os.environ.pop("AICHECK_QWEN_REVIEW_MAX_TOKENS", None)
        else:
            os.environ["AICHECK_QWEN_REVIEW_MAX_TOKENS"] = old
