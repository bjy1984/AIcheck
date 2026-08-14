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
