"""P8 H3：守卫语料补齐——四类误杀的回归用例（2026-09-06 六模型实测）。"""

from __future__ import annotations

from libs.review_grounding import (
    _canonicalize_dates,
    apply_grounding_guardrails,
    supplemental_grounding_identifiers,
    unsupported_claims,
)


def _grounding_input(evidence_text: str, **extra) -> dict:
    return {
        "groundingStatus": "grounded",
        "documentVersionIds": ["DV-1"],
        "evidenceTextCorpus": [evidence_text],
        "fragments": [
            {
                "id": "FRAG-1",
                "documentVersionId": "DV-1",
                "text": evidence_text,
                "pageNo": 1,
                "bbox": [10, 10, 200, 40],
            }
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "evidenceLinks": [
            {
                "id": "EVL-1",
                "documentVersionId": "DV-1",
                "pageNo": 1,
                "bbox": [10, 10, 200, 40],
                "quotedText": evidence_text[:20],
            }
        ],
        **extra,
    }


def test_date_variants_are_the_same_fact() -> None:
    assert _canonicalize_dates("有效期至2026年12月25日") == "有效期至2026-12-25"
    assert _canonicalize_dates("2026.9.6 与 2026/09/06") == "2026-09-06 与 2026-09-06"
    assert _canonicalize_dates("2025年05月至2029年04月") == "2025-05至2029-04"
    # 证据是 ISO 写法，模型写中文日期：不再是无据断言
    assert (
        unsupported_claims(
            "许可证有效期至2026年12月25日，覆盖工期，符合要求", ["许可证 有效期至 2026-12-25"]
        )
        == []
    )
    # 真正不在证据里的日期仍然被抓
    assert unsupported_claims(
        "许可证有效期至2027年12月25日，符合要求", ["许可证 有效期至 2026-12-25"]
    ) == [{"claim": "2027年12月25日", "reason": "not_present_in_supplied_evidence"}]


def test_regulation_codes_and_project_metadata_become_supplied_identifiers() -> None:
    context = {
        "project": {
            "name": "地上甲类储罐区2（含泵区）",
            "contractorOrgName": "中石化安装有限公司",
            "designOrgName": "广东政和工程有限公司",
            "pipelineGrade": "GC2",
            "constructionStart": "2026-03-01",
        },
        "rule": {
            "criteria": "《特种设备焊接操作人员考核细则》(TSG Z6002-2010)；TSG D7006-2020 附件 D",
            "checkMethod": "核查 NB/T 47014-2023 覆盖",
        },
        "clausePackageSnapshot": {
            "clauses": [
                {
                    "clauseId": "CREF-1",
                    "standardRef": "GB/T 20801.4-2025",
                    "text": "焊材应符合 GB/T 5117",
                }
            ]
        },
    }
    identifiers = supplemental_grounding_identifiers(context)
    for expected in (
        "中石化安装有限公司",
        "广东政和工程有限公司",
        "GC2",
        "TSG Z6002-2010",
        "TSG D7006-2020",
        "NB/T 47014-2023",
        "GB/T 20801.4-2025",
        "GB/T 5117",
        "CREF-1",
    ):
        assert expected in identifiers, expected


def test_guard_no_longer_downgrades_correct_citations_of_supplied_inputs() -> None:
    draft = {
        "id": "FND-1",
        "title": "焊工证项目按 TSG Z6002-2010 判定覆盖",
        "description": "按 TSG Z6002-2010 表 A-6，持证单位中石化安装有限公司的焊工姜军 6G 项目覆盖全位置，有效期至2026年12月25日，符合要求。",
        "severity": "low",
        "evidenceRefs": [
            {
                "evidenceLinkId": "EVL-1",
                "documentVersionId": "DV-1",
                "pageNo": 1,
                "bbox": [10, 10, 200, 40],
                "quotedText": "姓名 姜军",
            }
        ],
        "suggestedAction": "human_confirm",
    }
    evidence = "姓名 姜军 考核单位 江苏科圣智能装备股份有限公司 项目代号 GTAW-FeⅡ-6G-3/57 有效期至 2026-12-25"
    without = apply_grounding_guardrails(
        [dict(draft)], _grounding_input(evidence, reviewMode="gap_precheck")
    )
    assert without[0]["groundingStatus"] == "insufficient_evidence"
    claims = {claim["claim"] for claim in without[0]["unsupportedClaims"]}
    assert "Z6002-2010" in claims
    assert any("中石化安装有限公司" in claim for claim in claims)

    with_supplements = apply_grounding_guardrails(
        [dict(draft)],
        _grounding_input(
            evidence,
            reviewMode="gap_precheck",
            supplementalIdentifiers=["TSG Z6002-2010", "中石化安装有限公司"],
        ),
    )
    assert with_supplements[0]["groundingStatus"] == "grounded", with_supplements[0].get(
        "unsupportedClaims"
    )
    assert with_supplements[0]["title"] == draft["title"]


def test_supplements_do_not_whitelist_conclusion_words() -> None:
    # 补进语料的是标识符，不是结论词：证据里没有的许可证号仍然是无据断言，
    # 即使规则文本里写着"覆盖 GC2"也不能替模型背书。
    draft = {
        "id": "FND-2",
        "title": "安装许可证 TS3832083-2026 覆盖 GC2 管道",
        "description": "许可证 TS3832083-2026 许可范围覆盖 GC2，符合要求。",
        "severity": "low",
        "evidenceRefs": [
            {
                "evidenceLinkId": "EVL-1",
                "documentVersionId": "DV-1",
                "pageNo": 1,
                "bbox": [10, 10, 200, 40],
                "quotedText": "许可范围",
            }
        ],
        "suggestedAction": "human_confirm",
    }
    downgraded = apply_grounding_guardrails(
        [dict(draft)],
        _grounding_input(
            "许可证 许可范围：工业管道安装 GC2",
            reviewMode="gap_precheck",
            supplementalIdentifiers=["覆盖 GC2", "GC2 或 GC1 或 GCD 的资质"],
        ),
    )
    assert downgraded[0]["groundingStatus"] == "insufficient_evidence"
    assert any("TS3832083-2026" in claim["claim"] for claim in downgraded[0]["unsupportedClaims"])

    grounded = apply_grounding_guardrails(
        [dict(draft, id="FND-3")],
        _grounding_input(
            "许可证 TS3832083-2026 许可范围：工业管道安装 GC2", reviewMode="gap_precheck"
        ),
    )
    assert grounded[0]["groundingStatus"] == "grounded"
