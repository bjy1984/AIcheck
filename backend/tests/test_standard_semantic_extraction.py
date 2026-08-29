from __future__ import annotations

import json
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from libs.standard_knowledge_canonical import (
    merge_canonical_semantic_candidates,
    select_canonical_field,
    structured_identity,
)
from libs.standard_semantic_extraction import (
    PROMPT_VERSION,
    canonical_page_digest,
    extract_deterministic_standard_metadata,
    extract_standard_semantics,
    semantic_extraction_hashes,
)
from scripts import enrich_standard_knowledge_canonical as enrich_script
from scripts import verify_standard_knowledge_canonical as verify_script


class FakeLiteLLMClient:
    def __init__(self, content: dict[str, Any] | str) -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    def chat_sync(self, messages, model="review-chat", **kwargs):
        self.calls.append({"messages": messages, "model": model, **kwargs})
        content = (
            self.content
            if isinstance(self.content, str)
            else json.dumps(self.content, ensure_ascii=False)
        )
        return {"choices": [{"message": {"content": content}}]}

    @staticmethod
    def first_message_text(response):
        return str(response["choices"][0]["message"]["content"])


def semantic_record_fixture(
    *,
    pages: dict[int, str],
    page_contexts: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blocks = [
        {
            "id": f"B-{page_no}",
            "text": text,
            "pageNo": page_no,
            "authority": "current",
            "selectedSourceId": "PARSE-NEW",
            "sources": [
                {
                    "sourceType": "new_mineru",
                    "sourceId": "PARSE-NEW",
                    "documentVersionId": "KDV-TEST-V1",
                }
            ],
            **((page_contexts or {}).get(page_no) or {}),
        }
        for page_no, text in sorted(pages.items())
    ]
    return {
        "id": "SKR-KF-KB-TEST",
        "knowledgeFileId": "KF-KB-TEST",
        "documentVersionId": "KDV-TEST-V1",
        "activeParseResultId": "PARSE-NEW",
        "canonicalVersion": "standard-knowledge-canonical@1",
        "identity": {},
        "version": {},
        "metadata": {},
        "blocks": blocks,
        "clauses": [],
        "tables": [],
        "equations": [],
        "images": [],
        "seals": [],
        "normativeReferences": [],
        "replacementRelations": [],
        "businessRelations": [],
        "evidence": [],
        "provenance": [],
        "history": [],
        "completeness": {
            "overall": "partial",
            "missingCategories": ["version", "metadata", "normativeReferences"],
        },
        "sourceFingerprint": "sha256:test",
        "generatedAt": "2026-08-29T12:00:00+00:00",
    }


def test_deterministic_metadata_extracts_code_dates_authority_and_replacement():
    record = semantic_record_fixture(
        pages={
            1: (
                "中华人民共和国能源行业标准 NB/T 47013.10-2015 承压设备无损检测 第10部分。"
                "发布日期：2015-04-02；实施日期：2015-09-01；发布机构：国家能源局。"
                "代替 NB/T 47013.10-2010。"
            )
        },
        page_contexts={1: {"blockType": "title", "sectionPath": ["封面"]}},
    )

    extracted = extract_deterministic_standard_metadata(record)

    assert extracted["standardCode"][0]["value"] == "NB/T 47013.10-2015"
    assert extracted["publicationDate"][0]["value"] == "2015-04-02"
    assert extracted["effectiveDate"][0]["value"] == "2015-09-01"
    assert extracted["issuingAuthority"][0]["value"] == "国家能源局"
    assert extracted["replaces"][0]["value"] == "NB/T 47013.10-2010"
    assert all(item["sourceId"] == "PARSE-NEW" for values in extracted.values() for item in values)


def test_replacement_target_is_not_inferred_as_the_current_standard_code():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(pages={1: "本标准代替 NB/T 47013.10-2010。"})
    )

    assert "standardCode" not in extracted
    assert extracted["replaces"][0]["value"] == "NB/T 47013.10-2010"


def test_typographic_replacement_target_on_cover_is_not_current_standard_code():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={1: "本标准代替HG／T 20570—2019。"},
            page_contexts={1: {"blockType": "document_title"}},
        )
    )

    assert "standardCode" not in extracted
    assert extracted["replaces"][0]["value"] == "HG/T 20570-2019"


def test_deterministic_current_code_is_not_polluted_by_later_normative_codes():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={
                1: "NB/T 47013.10-2015 承压设备无损检测。",
                7: "检测方法应符合NB/T 47013.3-2015。",
            },
            page_contexts={1: {"blockType": "document_title"}},
        )
    )

    assert [item["value"] for item in extracted["standardCode"]] == ["NB/T 47013.10-2015"]


def test_deterministic_code_prefers_the_existing_canonical_identity_when_quoted():
    record = semantic_record_fixture(
        pages={1: "依据NB/T 47013.3-2015制定 NB/T 47013.10-2015 承压设备无损检测。"},
        page_contexts={1: {"blockType": "document_title"}},
    )
    record["identity"] = {"standardCode": {"value": "NB/T 47013.10-2015"}}

    extracted = extract_deterministic_standard_metadata(record)

    assert extracted["standardCode"][0]["value"] == "NB/T 47013.10-2015"


def test_citation_only_body_does_not_infer_current_standard_code():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(pages={7: "规范性引用文件：GB/T 123-2020、GB/T 456-2021。"})
    )

    assert "standardCode" not in extracted


def test_titled_body_scans_the_title_not_its_normative_reference_text_for_identity():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={7: "GB/T 123-2020、GB/T 456-2021。"},
            page_contexts={7: {"title": "规范性引用文件"}},
        )
    )

    assert "standardCode" not in extracted


@pytest.mark.parametrize("block_type", ["title", "header"])
def test_late_title_or_header_block_is_not_verified_identity_context(block_type):
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={7: "规范性引用文件 GB/T 123-2020"},
            page_contexts={
                7: {
                    "blockType": block_type,
                    "sectionPath": ["规范性引用文件"],
                }
            },
        )
    )

    assert "standardCode" not in extracted


@pytest.mark.parametrize(
    "section_title",
    ["规范性引用文件", "引用标准", "参考文献", "目录", "术语和定义"],
)
def test_page_one_generic_title_excludes_non_identity_sections(section_title):
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={1: f"{section_title} GB/T 123-2020"},
            page_contexts={
                1: {
                    "blockType": "title",
                    "title": section_title,
                    "sectionPath": [section_title],
                }
            },
        )
    )

    assert "standardCode" not in extracted


def test_generic_title_requires_positive_identity_marker():
    without_marker = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={1: "GB/T 123-2020 技术要求"},
            page_contexts={1: {"blockType": "title", "title": "技术要求"}},
        )
    )
    with_marker = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={1: "中华人民共和国国家标准 GB/T 123-2020 技术要求"},
            page_contexts={1: {"blockType": "title", "title": "国家标准"}},
        )
    )

    assert "standardCode" not in without_marker
    assert with_marker["standardCode"][0]["value"] == "GB/T 123-2020"


def test_explicit_cover_or_front_title_context_allows_unlabeled_identity():
    cover = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={4: "GB/T 123-2020 技术要求"},
            page_contexts={4: {"blockType": "cover"}},
        )
    )
    named_cover = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={4: "GB/T 456-2021 技术要求"},
            page_contexts={4: {"title": "标准封面"}},
        )
    )

    assert cover["standardCode"][0]["value"] == "GB/T 123-2020"
    assert named_cover["standardCode"][0]["value"] == "GB/T 456-2021"


def test_section_path_must_end_with_exact_front_matter_marker():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={7: "附录说明 GB/T 123-2020"},
            page_contexts={7: {"sectionPath": ["附录", "封面要求"]}},
        )
    )

    assert "standardCode" not in extracted


def test_section_path_ending_front_matter_marker_is_verified_identity_context():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(
            pages={7: "GB/T 123-2020 标准文本"},
            page_contexts={7: {"sectionPath": ["文档", "国家标准封面"]}},
        )
    )

    assert extracted["standardCode"][0]["value"] == "GB/T 123-2020"


def test_labeled_standard_number_is_valid_identity_context():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(pages={3: "标准编号：GB/T 123-2020"})
    )

    assert extracted["standardCode"][0]["value"] == "GB/T 123-2020"


def test_identity_label_requires_the_code_immediately_after_the_label():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(pages={7: "标准编号：待确认；规范性引用 GB/T 123-2020"})
    )

    assert "standardCode" not in extracted


def test_deterministic_standard_code_uses_canonical_display_form():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(pages={3: "标准编号：GBT 5117-2012"})
    )

    assert extracted["standardCode"][0]["value"] == "GB/T 5117-2012"


def test_labeled_astm_designation_is_valid_identity_context():
    extracted = extract_deterministic_standard_metadata(
        semantic_record_fixture(pages={3: "标准编号：ASTM A106/A106M-19"})
    )

    assert extracted["standardCode"][0]["value"] == "ASTM A106/A106M-19"


def test_model_semantics_are_strict_json_and_evidence_grounded():
    client = FakeLiteLLMClient(
        {
            "standardNameZh": {
                "value": "承压设备无损检测 第10部分：衍射时差法超声检测",
                "pageNo": 1,
                "quotedText": "承压设备无损检测 第10部分：衍射时差法超声检测",
            },
            "scope": {
                "value": "适用于低碳钢或低合金钢材料。",
                "pageNo": 7,
                "quotedText": "适用于低碳钢或低合金钢材料",
            },
            "normativeReferences": [
                {
                    "standardCode": "NB/T 47013.3",
                    "clauseNo": "",
                    "pageNo": 7,
                    "quotedText": "按NB/T 47013.3检测",
                }
            ],
            "replacementRelations": [
                {
                    "relation": "replaces",
                    "standardCode": "NB/T 47013.10-2010",
                    "pageNo": 1,
                    "quotedText": "代替NB/T 47013.10-2010",
                }
            ],
        }
    )
    record = semantic_record_fixture(
        pages={
            1: (
                "NB/T 47013.10-2015。"
                "承压设备无损检测 第10部分：衍射时差法超声检测。"
                "本标准代替NB/T 47013.10-2010。"
            ),
            7: "适用于低碳钢或低合金钢材料，按NB/T 47013.3检测。",
        },
        page_contexts={1: {"blockType": "document_title"}},
    )

    extracted = extract_standard_semantics(record, client)

    assert extracted["promptVersion"] == PROMPT_VERSION
    assert extracted["scope"]["pageNo"] == 7
    assert extracted["scope"]["sourceId"] == "PARSE-NEW"
    assert extracted["normativeReferences"][0]["sourceType"] == "new_mineru_semantic"
    assert extracted["normativeReferences"][0]["quotedText"] == "按NB/T 47013.3检测"
    assert client.calls[0]["model"] == "review-chat"
    assert client.calls[0]["response_format"] == {"type": "json_object"}
    assert client.calls[0]["temperature"] == 0


def test_ungrounded_model_item_without_evidence_is_rejected():
    client = FakeLiteLLMClient({"normativeReferences": [{"standardCode": "GB/T 99999"}]})

    with pytest.raises(ValueError, match="pageNo and quotedText are required"):
        extract_standard_semantics(semantic_record_fixture(pages={1: "标准正文"}), client)


def test_model_quote_must_be_a_normalized_substring_of_selected_mineru_page():
    client = FakeLiteLLMClient(
        {
            "scope": {
                "value": "模型臆测的范围",
                "pageNo": 7,
                "quotedText": "不存在于第七页的引文",
            }
        }
    )

    with pytest.raises(ValueError, match="not grounded on page 7"):
        extract_standard_semantics(
            semantic_record_fixture(pages={7: "真实的第七页标准正文"}), client
        )


def test_scope_value_rejects_unrelated_but_page_grounded_quote():
    client = FakeLiteLLMClient(
        {
            "scope": {
                "value": "适用于低碳钢全焊透对接接头。",
                "pageNo": 7,
                "quotedText": "本标准规定了术语和定义",
            }
        }
    )

    with pytest.raises(ValueError, match="scope is not supported by quotedText"):
        extract_standard_semantics(
            semantic_record_fixture(pages={7: "本标准规定了术语和定义。"}),
            client,
        )


def test_scope_value_does_not_treat_shared_boilerplate_as_substantive_grounding():
    with pytest.raises(ValueError, match="scope is not supported by quotedText"):
        extract_standard_semantics(
            semantic_record_fixture(pages={7: "本标准规定了术语和定义。"}),
            FakeLiteLLMClient(
                {
                    "scope": {
                        "value": "本标准规定了低碳钢材料要求。",
                        "pageNo": 7,
                        "quotedText": "本标准规定了术语和定义",
                    }
                }
            ),
        )


@pytest.mark.parametrize(
    ("value", "quoted_text"),
    [
        ("适用于低碳钢材料。", "不适用于低碳钢材料"),
        ("适用于低碳钢材料。", "不适用低碳钢材料"),
        ("适用于低碳钢材料。", "不应适用于低碳钢材料"),
        ("适用于低碳钢材料。", "不应当适用于低碳钢材料"),
        ("适用于低碳钢材料。", "不得适用于低碳钢材料"),
        ("不适用于低碳钢材料。", "适用于低碳钢材料"),
        ("不应当适用于低碳钢材料。", "适用于低碳钢材料"),
    ],
)
def test_scope_value_rejects_contradictory_applicability_polarity(
    value,
    quoted_text,
):
    with pytest.raises(ValueError, match="scope is not supported by quotedText"):
        extract_standard_semantics(
            semantic_record_fixture(pages={7: quoted_text}),
            FakeLiteLLMClient(
                {
                    "scope": {
                        "value": value,
                        "pageNo": 7,
                        "quotedText": quoted_text,
                    }
                }
            ),
        )


def test_scope_value_accepts_aligned_negative_applicability_polarity():
    extracted = extract_standard_semantics(
        semantic_record_fixture(pages={7: "本标准不适用低碳钢材料。"}),
        FakeLiteLLMClient(
            {
                "scope": {
                    "value": "不适用于低碳钢材料。",
                    "pageNo": 7,
                    "quotedText": "本标准不适用低碳钢材料",
                }
            }
        ),
    )

    assert extracted["scope"]["value"] == "不适用于低碳钢材料。"
    assert extracted["scope"]["semanticEvidence"] == {
        "valuePolarity": "negative",
        "quotePolarity": "negative",
        "negationMatches": True,
        "sharedSubstantiveTokens": ["低碳钢", "碳钢材", "钢材料"],
    }


@pytest.mark.parametrize(
    "negative_predicate",
    ["不应适用于", "不应当适用于", "不得适用于", "不适用"],
)
def test_scope_value_accepts_matching_modal_negation(negative_predicate):
    phrase = f"{negative_predicate}低碳钢材料"
    extracted = extract_standard_semantics(
        semantic_record_fixture(pages={7: phrase}),
        FakeLiteLLMClient(
            {
                "scope": {
                    "value": phrase,
                    "pageNo": 7,
                    "quotedText": phrase,
                }
            }
        ),
    )

    assert extracted["scope"]["semanticEvidence"]["valuePolarity"] == "negative"
    assert extracted["scope"]["semanticEvidence"]["quotePolarity"] == "negative"
    assert extracted["scope"]["semanticEvidence"]["negationMatches"] is True


def test_scope_polarity_compares_each_shared_subject():
    aligned = extract_standard_semantics(
        semantic_record_fixture(pages={7: "本标准适用于低碳钢，但不适用铸铁。"}),
        FakeLiteLLMClient(
            {
                "scope": {
                    "value": "适用于低碳钢，不应适用于铸铁。",
                    "pageNo": 7,
                    "quotedText": "本标准适用于低碳钢，但不适用铸铁",
                }
            }
        ),
    )

    assert aligned["scope"]["semanticEvidence"]["valuePolarity"] == "mixed"
    assert aligned["scope"]["semanticEvidence"]["quotePolarity"] == "mixed"
    assert aligned["scope"]["semanticEvidence"]["negationMatches"] is True

    with pytest.raises(ValueError, match="scope is not supported by quotedText"):
        extract_standard_semantics(
            semantic_record_fixture(pages={7: "本标准不适用于低碳钢，但适用于铸铁。"}),
            FakeLiteLLMClient(
                {
                    "scope": {
                        "value": "适用于低碳钢，不应适用于铸铁。",
                        "pageNo": 7,
                        "quotedText": "本标准不适用于低碳钢，但适用于铸铁",
                    }
                }
            ),
        )


def test_scope_polarity_pairs_overlapping_subjects_one_to_one():
    extracted = extract_standard_semantics(
        semantic_record_fixture(pages={7: "本标准适用于低碳钢，但不适用于低碳钢管。"}),
        FakeLiteLLMClient(
            {
                "scope": {
                    "value": "适用于低碳钢，不应当适用于低碳钢管。",
                    "pageNo": 7,
                    "quotedText": "本标准适用于低碳钢，但不适用于低碳钢管",
                }
            }
        ),
    )

    assert extracted["scope"]["semanticEvidence"]["negationMatches"] is True


def test_scope_polarity_rejects_conflicting_predicates_for_same_subject():
    with pytest.raises(ValueError, match="scope is not supported by quotedText"):
        extract_standard_semantics(
            semantic_record_fixture(pages={7: "本标准不适用于低碳钢，但适用于低碳钢。"}),
            FakeLiteLLMClient(
                {
                    "scope": {
                        "value": "适用于低碳钢。",
                        "pageNo": 7,
                        "quotedText": "本标准不适用于低碳钢，但适用于低碳钢",
                    }
                }
            ),
        )


def test_scope_semantic_evidence_keeps_shared_token_summary_compact():
    scope = "适用于ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij材料。"
    extracted = extract_standard_semantics(
        semantic_record_fixture(pages={7: scope}),
        FakeLiteLLMClient(
            {
                "scope": {
                    "value": scope,
                    "pageNo": 7,
                    "quotedText": scope.rstrip("。"),
                }
            }
        ),
    )

    assert len(extracted["scope"]["semanticEvidence"]["sharedSubstantiveTokens"]) <= 32


def test_scope_value_accepts_substantive_partial_quote():
    extracted = extract_standard_semantics(
        semantic_record_fixture(pages={7: "适用于低碳钢或低合金钢材料。"}),
        FakeLiteLLMClient(
            {
                "scope": {
                    "value": "适用于12mm至400mm低碳钢或低合金钢全焊透对接接头。",
                    "pageNo": 7,
                    "quotedText": "适用于低碳钢或低合金钢材料",
                }
            }
        ),
    )

    assert extracted["scope"]["value"].startswith("适用于12mm至400mm")


def test_standard_code_requires_exact_reference_boundary():
    with pytest.raises(ValueError, match="standardCode is not supported by quotedText"):
        extract_standard_semantics(
            semantic_record_fixture(pages={1: "标准编号：GB/T 1234-2020"}),
            FakeLiteLLMClient(
                {
                    "standardCode": {
                        "value": "GB/T 123",
                        "pageNo": 1,
                        "quotedText": "标准编号：GB/T 1234-2020",
                    }
                }
            ),
        )


def test_relation_standard_code_requires_exact_reference_boundary():
    with pytest.raises(
        ValueError,
        match=r"normativeReferences\[0\]: standardCode is not supported by quotedText",
    ):
        extract_standard_semantics(
            semantic_record_fixture(pages={7: "按GB/T 1234-2020检测"}),
            FakeLiteLLMClient(
                {
                    "normativeReferences": [
                        {
                            "standardCode": "GB/T 123",
                            "pageNo": 7,
                            "quotedText": "按GB/T 1234-2020检测",
                        }
                    ]
                }
            ),
        )


@pytest.mark.parametrize(
    ("quoted_code", "expected"),
    [
        ("GB 50236-2011", "GB 50236-2011"),
        ("GB/T 123-2020", "GB/T 123-2020"),
        ("NB/T 47013.3-2015", "NB/T 47013.3-2015"),
        ("JB/T 3223-2017", "JB/T 3223-2017"),
        ("SY/T 4113.11-2023", "SY/T 4113.11-2023"),
        ("TSG D7006-2020", "TSG D7006-2020"),
        ("DL/T 123.4-2020", "DL/T 123.4-2020"),
        ("HG／T 20570—2019", "HG/T 20570-2019"),
        ("ISO 9001:2015", "ISO 9001:2015"),
        ("ISO/IEC 17025:2017", "ISO/IEC 17025:2017"),
        ("IEC 60079-1:2014", "IEC 60079-1:2014"),
        ("ASTM A106/A106M-19", "ASTM A106/A106M-19"),
        ("ASTM E1066-95R06", "ASTM E1066-95R06"),
        ("ASTM E-317", "ASTM E-317"),
    ],
)
def test_broad_standard_families_validate_with_exact_boundaries(
    quoted_code,
    expected,
):
    record = semantic_record_fixture(pages={7: f"按{quoted_code}执行"})
    record["identity"] = {"standardCode": {"value": "GB/T 5000-2020"}}

    extracted = extract_standard_semantics(
        record,
        FakeLiteLLMClient(
            {
                "normativeReferences": [
                    {
                        "standardCode": quoted_code,
                        "pageNo": 7,
                        "quotedText": f"按{quoted_code}执行",
                    }
                ]
            }
        ),
    )

    assert extracted["normativeReferences"][0]["targetStandardCode"] == expected


def test_malformed_reference_item_is_rejected_without_dropping_valid_relations_or_fields():
    record = semantic_record_fixture(
        pages={7: ("适用于低碳钢材料。按DL/T 123.4-2020执行。来源误写XYZ/T 12-2020。")}
    )
    record["identity"] = {"standardCode": {"value": "GB/T 5000-2020"}}

    extracted = extract_standard_semantics(
        record,
        FakeLiteLLMClient(
            {
                "scope": {
                    "value": "适用于低碳钢材料。",
                    "pageNo": 7,
                    "quotedText": "适用于低碳钢材料",
                },
                "normativeReferences": [
                    {
                        "standardCode": "DL/T 123.4-2020",
                        "pageNo": 7,
                        "quotedText": "按DL/T 123.4-2020执行",
                    },
                    {
                        "standardCode": "XYZ/T 12-2020",
                        "pageNo": 7,
                        "quotedText": "来源误写XYZ/T 12-2020",
                    },
                ],
            }
        ),
    )

    assert extracted["scope"]["value"] == "适用于低碳钢材料。"
    assert [item["targetStandardCode"] for item in extracted["normativeReferences"]] == [
        "DL/T 123.4-2020"
    ]


def test_astm_revision_does_not_ground_unrevised_designation():
    with pytest.raises(
        ValueError,
        match=r"normativeReferences\[0\]: standardCode is not supported by quotedText",
    ):
        record = semantic_record_fixture(pages={7: "按ASTM E1066-95R06执行"})
        record["identity"] = {"standardCode": {"value": "GB/T 5000-2020"}}
        extract_standard_semantics(
            record,
            FakeLiteLLMClient(
                {
                    "normativeReferences": [
                        {
                            "standardCode": "ASTM E1066",
                            "pageNo": 7,
                            "quotedText": "按ASTM E1066-95R06执行",
                        }
                    ]
                }
            ),
        )


def test_replacement_identity_preserves_astm_revision_and_combined_iso_iec_family():
    source = "DL/T 1000-2020"
    astm_revision = structured_identity(
        "replacement",
        {
            "sourceStandardCode": source,
            "purpose": "replaces",
            "targetStandardCode": "ASTM E1066-95R06",
        },
    )
    astm_base = structured_identity(
        "replacement",
        {
            "sourceStandardCode": source,
            "purpose": "replaces",
            "targetStandardCode": "ASTM E1066",
        },
    )
    astm_typographic = structured_identity(
        "replacement",
        {
            "sourceStandardCode": "DL／T 1000—2020",
            "purpose": "replaces",
            "targetStandardCode": "ASTM E1066—95R06",
        },
    )
    combined = structured_identity(
        "replacement",
        {
            "sourceStandardCode": source,
            "purpose": "replaces",
            "targetStandardCode": "ISO/IEC 17025:2017",
        },
    )
    iec_only = structured_identity(
        "replacement",
        {
            "sourceStandardCode": source,
            "purpose": "replaces",
            "targetStandardCode": "IEC 17025:2017",
        },
    )

    assert astm_revision != astm_base
    assert astm_revision == astm_typographic
    assert combined != iec_only


def test_model_standard_name_requires_grounded_evidence():
    with pytest.raises(
        ValueError,
        match="standardNameZh: pageNo and quotedText are required",
    ):
        extract_standard_semantics(
            semantic_record_fixture(pages={1: "承压设备无损检测"}),
            FakeLiteLLMClient({"standardNameZh": "承压设备无损检测"}),
        )


@pytest.mark.parametrize(
    ("item", "message"),
    [
        (
            {
                "standardCode": "NB/T 47013.3",
                "pageNo": "7",
                "quotedText": "按NB/T 47013.3检测",
            },
            "pageNo must be a positive integer",
        ),
        (
            {
                "standardCode": "NB/T 47013.3",
                "pageNo": 7,
                "quotedText": 47013,
            },
            "quotedText must be a non-empty string",
        ),
        (
            {
                "standardCode": "NB/T 47013.3",
                "clauseNo": 3,
                "pageNo": 7,
                "quotedText": "按NB/T 47013.3检测",
            },
            "clauseNo must be a string",
        ),
    ],
)
def test_model_relation_evidence_uses_strict_json_types(item, message):
    with pytest.raises(ValueError, match=message):
        extract_standard_semantics(
            semantic_record_fixture(pages={7: "按NB/T 47013.3检测"}),
            FakeLiteLLMClient({"normativeReferences": [item]}),
        )


def test_model_code_value_must_be_supported_by_its_grounded_quote():
    client = FakeLiteLLMClient(
        {
            "standardCode": {
                "value": "NB/T 47013.10-2015",
                "pageNo": 1,
                "quotedText": "本标准代替NB/T 47013.10-2010",
            }
        }
    )

    with pytest.raises(ValueError, match="standardCode is not supported by quotedText"):
        extract_standard_semantics(
            semantic_record_fixture(pages={1: "本标准代替NB/T 47013.10-2010。"}),
            client,
        )


@pytest.mark.parametrize(
    ("key", "value", "quoted_text"),
    [
        ("publicationDate", "2014-01-01", "发布日期：2015-04-02"),
        ("effectiveDate", "2014-01-01", "实施日期：2015-09-01"),
        ("issuingAuthority", "错误机构", "发布机构：国家能源局"),
    ],
)
def test_exact_model_metadata_value_must_be_supported_by_grounded_quote(key, value, quoted_text):
    with pytest.raises(ValueError, match=f"{key} is not supported by quotedText"):
        extract_standard_semantics(
            semantic_record_fixture(pages={1: quoted_text}),
            FakeLiteLLMClient(
                {
                    key: {
                        "value": value,
                        "pageNo": 1,
                        "quotedText": quoted_text,
                    }
                }
            ),
        )


def test_optional_model_evidence_is_validated_when_present():
    client = FakeLiteLLMClient(
        {
            "standardNameZh": {
                "value": "承压设备无损检测",
                "pageNo": 1,
                "quotedText": "并不存在的标准名称",
            }
        }
    )

    with pytest.raises(ValueError, match="not grounded on page 1"):
        extract_standard_semantics(
            semantic_record_fixture(pages={1: "真实封面正文"}),
            client,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("```json\n{}\n```", "strict JSON object"),
        ({"inventedField": "value"}, "unsupported semantic field"),
        ({"publicationDate": "2015-04-02"}, "pageNo and quotedText are required"),
    ],
)
def test_model_payload_rejects_non_strict_or_unsupported_values(payload, message):
    with pytest.raises(ValueError, match=message):
        extract_standard_semantics(
            semantic_record_fixture(pages={1: "发布日期：2015-04-02"}),
            FakeLiteLLMClient(payload),
        )


def test_deterministic_value_wins_a_conflicting_grounded_model_value():
    record = semantic_record_fixture(
        pages={
            1: "发布日期：2015-04-02。历史记录曾写作2014-01-01。",
        }
    )
    client = FakeLiteLLMClient(
        {
            "publicationDate": {
                "value": "2014-01-01",
                "pageNo": 1,
                "quotedText": "历史记录曾写作2014-01-01",
            }
        }
    )

    extracted = extract_standard_semantics(record, client)

    assert extracted["publicationDate"]["value"] == "2015-04-02"
    assert extracted["publicationDate"]["extractionMethod"] == "deterministic"


def test_replacement_relations_union_deterministic_and_distinct_model_relations():
    record = semantic_record_fixture(
        pages={
            1: ("NB/T 47013.10-2015。本标准代替NB/T 47013.10-2010。"),
            2: ("NB/T 47013.10-2025替代本标准。本标准修改GB/T 999-2022，并被GB/T 888-2024修改。"),
        },
        page_contexts={1: {"blockType": "document_title"}},
    )
    payload = {
        "replacementRelations": [
            {
                "relation": "replaces",
                "standardCode": "NB/T 47013.10-2010",
                "pageNo": 1,
                "quotedText": "本标准代替NB/T 47013.10-2010",
            },
            {
                "relation": "replacedBy",
                "standardCode": "NB/T 47013.10-2025",
                "pageNo": 2,
                "quotedText": "NB/T 47013.10-2025替代本标准",
            },
            {
                "relation": "amends",
                "standardCode": "GB/T 999-2022",
                "pageNo": 2,
                "quotedText": "本标准修改GB/T 999-2022",
            },
            {
                "relation": "amendedBy",
                "standardCode": "GB/T 888-2024",
                "pageNo": 2,
                "quotedText": "被GB/T 888-2024修改",
            },
        ]
    }

    extracted = extract_standard_semantics(record, FakeLiteLLMClient(payload))

    assert {
        (item["purpose"], item["targetStandardCode"]) for item in extracted["replacementRelations"]
    } == {
        ("replaces", "NB/T 47013.10-2010"),
        ("replacedBy", "NB/T 47013.10-2025"),
        ("amends", "GB/T 999-2022"),
        ("amendedBy", "GB/T 888-2024"),
    }
    replaces = next(
        item for item in extracted["replacementRelations"] if item["purpose"] == "replaces"
    )
    assert replaces["extractionMethod"] == "deterministic"


def test_replacement_identity_separates_sources_for_the_same_relation_and_target():
    first = structured_identity(
        "replacement",
        {
            "sourceStandardCode": "GB/T 1000-2020",
            "purpose": "replaces",
            "targetStandardCode": "HG/T 20570-2019",
        },
    )
    second = structured_identity(
        "replacement",
        {
            "sourceStandardCode": "GB/T 2000-2020",
            "purpose": "replaces",
            "targetStandardCode": "HG/T 20570-2019",
        },
    )

    assert first != second


def test_replacement_identity_deduplicates_typographic_variants_within_same_source():
    deterministic = structured_identity(
        "replacement",
        {
            "sourceStandardCode": "GB／T 1000—2020",
            "purpose": "replaces",
            "targetStandardCode": "HG／T 20570—2019",
        },
    )
    model = structured_identity(
        "replacement",
        {
            "sourceStandardCode": "GBT 1000-2020",
            "purpose": "replaces",
            "targetStandardCode": "HGT 20570-2019",
        },
    )

    assert deterministic == model


def test_relations_use_standard_code_selected_in_same_extraction_and_keep_name():
    record = semantic_record_fixture(
        pages={
            1: "NB/T 47013.10-2015 承压设备无损检测。",
            7: "按NB/T 47013.3-2015《超声检测》检测。",
        },
        page_contexts={1: {"blockType": "document_title"}},
    )
    extracted = extract_standard_semantics(
        record,
        FakeLiteLLMClient(
            {
                "normativeReferences": [
                    {
                        "standardCode": "NB/T 47013.3-2015",
                        "standardName": "超声检测",
                        "pageNo": 7,
                        "quotedText": "按NB/T 47013.3-2015《超声检测》检测",
                    }
                ]
            }
        ),
    )

    assert extracted["normativeReferences"][0]["sourceStandardCode"] == ("NB/T 47013.10-2015")
    assert extracted["normativeReferences"][0]["targetStandardName"] == "超声检测"

    merged = merge_canonical_semantic_candidates(
        record,
        extracted,
        extracted_at="2026-08-29T14:00:00+00:00",
    )

    assert merged["normativeReferences"][0]["sourceStandardCode"] == ("NB/T 47013.10-2015")
    assert merged["normativeReferences"][0]["targetStandardName"] == "超声检测"


def test_relation_is_rejected_when_source_standard_code_remains_missing():
    with pytest.raises(ValueError, match="relations require source standardCode"):
        extract_standard_semantics(
            semantic_record_fixture(pages={7: "按NB/T 47013.3-2015检测"}),
            FakeLiteLLMClient(
                {
                    "normativeReferences": [
                        {
                            "standardCode": "NB/T 47013.3-2015",
                            "pageNo": 7,
                            "quotedText": "按NB/T 47013.3-2015检测",
                        }
                    ]
                }
            ),
        )


def test_page_digest_ignores_non_mineru_and_legacy_only_blocks():
    record = semantic_record_fixture(pages={1: "当前 MinerU 正文"})
    record["blocks"].extend(
        [
            {
                "id": "B-VISUAL",
                "pageNo": 1,
                "text": "视觉抽取正文",
                "authority": "current",
                "sources": [{"sourceType": "visual_extraction", "sourceId": "VISUAL-1"}],
            },
            {
                "id": "B-LEGACY",
                "pageNo": 2,
                "text": "旧 OCR 正文",
                "authority": "legacy_only",
                "sources": [{"sourceType": "legacy_ocr", "sourceId": "OLD-1"}],
            },
        ]
    )

    assert canonical_page_digest(record) == {1: "当前 MinerU 正文"}


def test_semantic_candidate_has_higher_priority_than_raw_new_mineru_field():
    selected = select_canonical_field(
        "publicationDate",
        [
            {
                "value": "2014-01-01",
                "sourceType": "new_mineru",
                "sourceId": "PARSE-NEW",
            },
            {
                "value": "2015-04-02",
                "sourceType": "new_mineru_semantic",
                "sourceId": "PARSE-NEW",
            },
        ],
    )

    assert selected is not None
    assert selected["value"] == "2015-04-02"
    assert selected["selectedSourceId"] == "PARSE-NEW"


def test_semantic_candidates_merge_through_canonical_selectors_and_preserve_generation():
    record = semantic_record_fixture(
        pages={
            1: "发布日期：2015-04-02。本标准代替NB/T 47013.10-2010。",
            7: "适用于低碳钢材料，按NB/T 47013.3检测。",
        }
    )
    record["identity"] = {
        "standardCode": {
            "id": "SKI-FIELD-CODE",
            "key": "standardCode",
            "value": "NB/T 47013.10-2015",
            "authority": "current",
            "selectedSourceId": "PARSE-NEW",
            "sources": [
                {
                    "key": "standardCode",
                    "value": "NB/T 47013.10-2015",
                    "sourceType": "new_mineru",
                    "sourceId": "PARSE-NEW",
                    "documentVersionId": "KDV-TEST-V1",
                }
            ],
        }
    }
    record["version"] = {
        "publicationDate": {
            "id": "SKI-FIELD-DATE",
            "key": "publicationDate",
            "value": "2014-01-01",
            "authority": "current",
            "selectedSourceId": "PARSE-NEW",
            "sources": [
                {
                    "key": "publicationDate",
                    "value": "2014-01-01",
                    "sourceType": "new_mineru",
                    "sourceId": "PARSE-NEW",
                    "documentVersionId": "KDV-TEST-V1",
                }
            ],
        }
    }
    record["normativeReferences"] = [
        {
            "id": "SKI-REFERENCE-OLD",
            "sourceStandardCode": "NB/T 47013.10-2015",
            "sourceClauseNo": "",
            "targetStandardCode": "NB/T 47013.3",
            "targetClauseNo": "",
            "text": "NB/T 47013.3",
            "pageNo": 7,
            "authority": "current",
            "selectedSourceId": "REF-OLD",
            "sources": [
                {
                    "sourceType": "standard_reference",
                    "sourceId": "REF-OLD",
                    "documentVersionId": "KDV-TEST-V1",
                    "pageNo": 7,
                    "quotedText": "NB/T 47013.3",
                }
            ],
        }
    ]
    semantic = extract_standard_semantics(
        record,
        FakeLiteLLMClient(
            {
                "scope": {
                    "value": "适用于低碳钢材料。",
                    "pageNo": 7,
                    "quotedText": "适用于低碳钢材料",
                },
                "normativeReferences": [
                    {
                        "standardCode": "NB/T 47013.3",
                        "clauseNo": "",
                        "pageNo": 7,
                        "quotedText": "按NB/T 47013.3检测",
                    }
                ],
                "replacementRelations": [],
            }
        ),
    )

    enriched = merge_canonical_semantic_candidates(
        record,
        semantic,
        extracted_at="2026-08-29T13:00:00+00:00",
    )

    assert enriched["generatedAt"] == "2026-08-29T12:00:00+00:00"
    assert enriched["version"]["publicationDate"]["value"] == "2015-04-02"
    assert {item["sourceType"] for item in enriched["version"]["publicationDate"]["sources"]} == {
        "new_mineru",
        "new_mineru_semantic",
    }
    assert enriched["metadata"]["scope"]["value"] == "适用于低碳钢材料。"
    assert len(enriched["normativeReferences"]) == 1
    assert {item["sourceType"] for item in enriched["normativeReferences"][0]["sources"]} == {
        "standard_reference",
        "new_mineru_semantic",
    }
    assert enriched["replacementRelations"][0]["targetStandardCode"] == ("NB/T 47013.10-2010")
    assert enriched["semanticExtractionVersion"] == PROMPT_VERSION
    assert enriched["semanticExtractedAt"] == "2026-08-29T13:00:00+00:00"
    assert enriched["semanticModelRoute"] == "review-chat"
    assert enriched["semanticPromptHash"].startswith("sha256:")
    assert enriched["semanticContentHash"].startswith("sha256:")
    semantic_provenance = [
        item for item in enriched["provenance"] if item["sourceType"] == "new_mineru_semantic"
    ]
    assert len(semantic_provenance) == 1
    assert "pages" not in semantic_provenance[0]
    assert "messages" not in semantic_provenance[0]


def _complete_field(
    key: str,
    value: str,
    *,
    source_type: str = "new_mineru",
    source_id: str = "PARSE-NEW",
) -> dict[str, Any]:
    return {
        "id": f"SKI-FIELD-{key.upper()}",
        "key": key,
        "value": value,
        "authority": "current",
        "selectedSourceId": source_id,
        "sources": [
            {
                "key": key,
                "value": value,
                "sourceType": source_type,
                "sourceId": source_id,
                "documentVersionId": "KDV-TEST-V1",
                "quotedText": value,
            }
        ],
    }


def _database_record(*, file_id: str, context_type: str = "standard_reference"):
    record = semantic_record_fixture(
        pages={
            1: ("NB/T 47013.10-2015 发布日期：2015-04-02。本标准代替NB/T 47013.10-2010。"),
            7: "适用于低碳钢材料，按NB/T 47013.3检测。",
        }
    )
    record.update(
        {
            "id": f"SKR-{file_id}",
            "knowledgeFileId": file_id,
            "contextType": context_type,
            "sourceFingerprint": f"sha256:{file_id.lower()}",
            "identity": {
                "standardCode": _complete_field("standardCode", "NB/T 47013.10-2015"),
                "standardNameZh": _complete_field("standardNameZh", "承压设备无损检测"),
            },
            "version": {
                "status": _complete_field(
                    "status",
                    "current",
                    source_type="standard_catalog",
                    source_id="KDV-TEST-V1",
                )
            },
            "metadata": {},
            "provenance": [
                {
                    "sourceType": "new_mineru",
                    "sourceId": "PARSE-NEW",
                    "documentVersionId": "KDV-TEST-V1",
                    "capabilities": ["fullText", "clause"],
                }
            ],
            "completeness": {
                "identity": {"status": "complete", "missing": []},
                "version": {"status": "complete", "missing": []},
                "metadata": {"status": "partial", "missing": ["scope"]},
                "normativeReferences": {"status": "missing", "count": 0},
                "replacementRelations": {"status": "not_applicable", "count": 0},
                "overall": "partial",
                "missingCategories": ["metadata", "normativeReferences"],
            },
        }
    )
    return record


def _seed_semantic_database(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=False) as connection:
        connection.execute(
            """
            CREATE TABLE aicheck_state (
                tenant_id text NOT NULL,
                collection text NOT NULL,
                object_id text NOT NULL,
                payload jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (tenant_id, collection, object_id)
            )
            """
        )
        rows = [
            (
                "TENANT-DEFAULT",
                "standard_knowledge_records",
                "KF-KB-TEST",
                _database_record(file_id="KF-KB-TEST"),
            ),
            (
                "TENANT-DEFAULT",
                "standard_knowledge_records",
                "KF-KB-CONTEXT",
                _database_record(file_id="KF-KB-CONTEXT", context_type="context_only"),
            ),
            (
                "TENANT-OTHER",
                "standard_knowledge_records",
                "KF-KB-OTHER",
                _database_record(file_id="KF-KB-OTHER"),
            ),
            (
                "TENANT-DEFAULT",
                "knowledge_files",
                "KF-KB-TEST",
                {"id": "KF-KB-TEST", "immutable": True},
            ),
        ]
        for tenant_id, collection, object_id, payload in rows:
            connection.execute(
                """
                INSERT INTO aicheck_state
                    (tenant_id, collection, object_id, payload, updated_at)
                VALUES (%s, %s, %s, %s, now())
                """,
                (tenant_id, collection, object_id, Jsonb(payload)),
            )
        connection.commit()


def _read_payload(
    database_url: str, collection: str, object_id: str, *, tenant_id="TENANT-DEFAULT"
) -> dict[str, Any]:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id=%s AND collection=%s AND object_id=%s
            """,
            (tenant_id, collection, object_id),
        ).fetchone()
    assert row is not None
    return dict(row[0])


def _grounded_model_payload() -> dict[str, Any]:
    return {
        "scope": {
            "value": "适用于低碳钢材料。",
            "pageNo": 7,
            "quotedText": "适用于低碳钢材料",
        },
        "normativeReferences": [
            {
                "standardCode": "NB/T 47013.3",
                "clauseNo": "",
                "pageNo": 7,
                "quotedText": "按NB/T 47013.3检测",
            }
        ],
    }


def test_enrichment_updates_only_configured_tenant_canonical_and_skips_unchanged_hash(
    isolated_postgres_url,
):
    _seed_semantic_database(isolated_postgres_url)
    source_before = _read_payload(isolated_postgres_url, "knowledge_files", "KF-KB-TEST")
    first_client = FakeLiteLLMClient(_grounded_model_payload())

    first = enrich_script.enrich(
        isolated_postgres_url,
        apply=True,
        only_missing=False,
        client=first_client,
    )

    assert first["selected"] == 2
    assert first["processed"] == 1
    assert first["contextOnlySkipped"] == 1
    assert first["updated"] == 1
    assert first["failed"] == 0
    assert first["modelCalls"] == 1
    enriched = _read_payload(isolated_postgres_url, "standard_knowledge_records", "KF-KB-TEST")
    assert enriched["generatedAt"] == "2026-08-29T12:00:00+00:00"
    assert enriched["metadata"]["scope"]["value"] == "适用于低碳钢材料。"
    assert enriched["version"]["replaces"]["value"] == "NB/T 47013.10-2010"
    assert enriched["replacementRelations"][0]["targetStandardCode"] == ("NB/T 47013.10-2010")
    assert enriched["semanticExtractionVersion"] == PROMPT_VERSION
    assert _read_payload(isolated_postgres_url, "knowledge_files", "KF-KB-TEST") == source_before
    assert "semanticExtractionVersion" not in _read_payload(
        isolated_postgres_url,
        "standard_knowledge_records",
        "KF-KB-OTHER",
        tenant_id="TENANT-OTHER",
    )

    second_client = FakeLiteLLMClient(_grounded_model_payload())
    second = enrich_script.enrich(
        isolated_postgres_url,
        apply=True,
        only_missing=False,
        client=second_client,
    )

    assert second["unchanged"] == 1
    assert second["modelCalls"] == 0
    assert second_client.calls == []


def test_semantic_refresh_selects_newest_candidate_before_hash_skip(
    isolated_postgres_url,
):
    _seed_semantic_database(isolated_postgres_url)
    record = _read_payload(isolated_postgres_url, "standard_knowledge_records", "KF-KB-TEST")
    old_scope = _complete_field(
        "scope",
        "低碳钢",
        source_type="new_mineru_semantic",
    )
    old_scope["sources"][0].update(
        {
            "pageNo": 7,
            "quotedText": "低碳钢",
            "createdAt": "2026-08-28T12:00:00+00:00",
            "extractedAt": "2026-08-28T12:00:00+00:00",
        }
    )
    record["metadata"]["scope"] = old_scope
    hashes = semantic_extraction_hashes(
        record, requested_fields=set(enrich_script.semantic_field_names())
    )
    record.update(
        {
            "semanticExtractionVersion": PROMPT_VERSION,
            "semanticModelRoute": "review-chat",
            "semanticPromptHash": hashes["promptHash"],
            "semanticContentHash": hashes["contentHash"],
        }
    )
    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE aicheck_state SET payload=%s, updated_at=now()
            WHERE tenant_id=%s
              AND collection='standard_knowledge_records'
              AND object_id=%s
            """,
            (Jsonb(record), "TENANT-DEFAULT", "KF-KB-TEST"),
        )

    first_client = FakeLiteLLMClient(_grounded_model_payload())
    first = enrich_script.enrich(
        isolated_postgres_url,
        apply=True,
        only_missing=False,
        file_id="KF-KB-TEST",
        client=first_client,
    )

    assert first["updated"] == 1
    assert first["unchanged"] == 0
    assert len(first_client.calls) == 1
    refreshed = _read_payload(isolated_postgres_url, "standard_knowledge_records", "KF-KB-TEST")
    assert refreshed["metadata"]["scope"]["value"] == "适用于低碳钢材料。"
    scope_sources = refreshed["metadata"]["scope"]["sources"]
    assert scope_sources[0]["createdAt"] > scope_sources[1]["createdAt"]
    assert refreshed["semanticSelectedValuesHash"].startswith("sha256:")

    second_client = FakeLiteLLMClient(_grounded_model_payload())
    second = enrich_script.enrich(
        isolated_postgres_url,
        apply=True,
        only_missing=False,
        file_id="KF-KB-TEST",
        client=second_client,
    )

    assert second["unchanged"] == 1
    assert second["modelCalls"] == 0
    assert second_client.calls == []


def test_only_missing_restricts_prompt_to_partial_or_missing_categories(
    isolated_postgres_url,
):
    _seed_semantic_database(isolated_postgres_url)
    client = FakeLiteLLMClient(_grounded_model_payload())

    report = enrich_script.enrich(
        isolated_postgres_url,
        apply=False,
        only_missing=True,
        file_id="KF-KB-TEST",
        client=client,
    )

    assert report["planned"] == 1
    assert report["modelCalls"] == 1
    request = json.loads(client.calls[0]["messages"][1]["content"])
    assert "scope" in request["requestedFields"]
    assert "normativeReferences" in request["requestedFields"]
    assert "standardCode" not in request["requestedFields"]
    assert "publicationDate" not in request["requestedFields"]
    assert "replacementRelations" not in request["requestedFields"]
    assert "semanticExtractionVersion" not in _read_payload(
        isolated_postgres_url, "standard_knowledge_records", "KF-KB-TEST"
    )


def test_row_fingerprint_change_during_model_call_rejects_stale_update(
    isolated_postgres_url,
):
    _seed_semantic_database(isolated_postgres_url)

    class FingerprintChangingClient(FakeLiteLLMClient):
        def chat_sync(self, messages, model="review-chat", **kwargs):
            current = _read_payload(
                isolated_postgres_url,
                "standard_knowledge_records",
                "KF-KB-TEST",
            )
            current["sourceFingerprint"] = "sha256:changed-concurrently"
            with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
                connection.execute(
                    """
                    UPDATE aicheck_state SET payload=%s, updated_at=now()
                    WHERE tenant_id=%s
                      AND collection='standard_knowledge_records'
                      AND object_id=%s
                    """,
                    (Jsonb(current), "TENANT-DEFAULT", "KF-KB-TEST"),
                )
            return super().chat_sync(messages, model=model, **kwargs)

    report = enrich_script.enrich(
        isolated_postgres_url,
        apply=True,
        only_missing=False,
        file_id="KF-KB-TEST",
        client=FingerprintChangingClient(_grounded_model_payload()),
    )

    assert report["stale"] == 1
    assert report["updated"] == 0
    stored = _read_payload(isolated_postgres_url, "standard_knowledge_records", "KF-KB-TEST")
    assert stored["sourceFingerprint"] == "sha256:changed-concurrently"
    assert "semanticExtractionVersion" not in stored


def test_one_failed_model_response_does_not_roll_back_enriched_sibling(
    isolated_postgres_url,
):
    _seed_semantic_database(isolated_postgres_url)
    second = _database_record(file_id="KF-KB-CONTEXT")
    with psycopg.connect(isolated_postgres_url, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE aicheck_state SET payload=%s, updated_at=now()
            WHERE tenant_id=%s
              AND collection='standard_knowledge_records'
              AND object_id=%s
            """,
            (Jsonb(second), "TENANT-DEFAULT", "KF-KB-CONTEXT"),
        )

    class SequenceClient(FakeLiteLLMClient):
        def __init__(self):
            super().__init__(_grounded_model_payload())
            self.responses = [_grounded_model_payload(), "not-json"]

        def chat_sync(self, messages, model="review-chat", **kwargs):
            self.content = self.responses.pop(0)
            return super().chat_sync(messages, model=model, **kwargs)

    report = enrich_script.enrich(
        isolated_postgres_url,
        apply=True,
        only_missing=False,
        client=SequenceClient(),
    )

    assert report["processed"] == 2
    assert report["updated"] == 1
    assert report["failed"] == 1
    stored = [
        _read_payload(
            isolated_postgres_url,
            "standard_knowledge_records",
            file_id,
        )
        for file_id in ("KF-KB-CONTEXT", "KF-KB-TEST")
    ]
    assert sum("semanticExtractionVersion" in item for item in stored) == 1


def test_model_failure_report_never_contains_exception_message_or_document_text(
    isolated_postgres_url,
):
    _seed_semantic_database(isolated_postgres_url)

    class SecretFailureClient(FakeLiteLLMClient):
        def chat_sync(self, messages, model="review-chat", **kwargs):
            raise RuntimeError("SECRET=sk-live-token PAGE TEXT=适用于低碳钢材料 prompt body")

    report = enrich_script.enrich(
        isolated_postgres_url,
        apply=True,
        file_id="KF-KB-TEST",
        client=SecretFailureClient({}),
    )
    rendered = json.dumps(report, ensure_ascii=False)

    assert report["failed"] == 1
    failed = report["records"][0]
    assert failed == {
        "knowledgeFileId": "KF-KB-TEST",
        "action": "failed",
        "errorCode": "SEMANTIC_ENRICHMENT_FAILED",
        "errorType": "RuntimeError",
    }
    assert "sk-live-token" not in rendered
    assert "适用于低碳钢材料" not in rendered
    assert "prompt body" not in rendered


def test_explicit_missing_file_id_emits_json_and_returns_nonzero(
    isolated_postgres_url,
    tmp_path,
    capsys,
    monkeypatch,
):
    _seed_semantic_database(isolated_postgres_url)
    monkeypatch.setenv("AICHECK_DATABASE_URL", "postgresql:///configured-production")
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    output_path = tmp_path / "missing-target.json"

    exit_code = enrich_script.main(
        [
            "--database-url",
            isolated_postgres_url,
            "--apply",
            "--file-id",
            "KF-KB-NOT-FOUND",
            "--output",
            str(output_path),
        ]
    )
    stdout_report = json.loads(capsys.readouterr().out)
    file_report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert stdout_report == file_report
    assert stdout_report["selected"] == 0
    assert stdout_report["missing"] == 1
    assert stdout_report["records"] == [
        {
            "knowledgeFileId": "KF-KB-NOT-FOUND",
            "action": "missing",
            "errorCode": "CANONICAL_TARGET_NOT_FOUND",
        }
    ]


def test_verifier_resolves_semantic_candidates_to_their_mineru_parse_source():
    registry = verify_script._source_registry(
        [
            (
                "knowledge_files",
                "KF-KB-TEST",
                {
                    "id": "KF-KB-TEST",
                    "sourceId": "KS-STANDARD-RULES",
                    "documentVersionId": "KDV-TEST-V1",
                },
            ),
            (
                "ocr_parse_results",
                "PARSE-NEW",
                {
                    "id": "PARSE-NEW",
                    "parseResultId": "PARSE-NEW",
                    "documentVersionId": "KDV-TEST-V1",
                    "metadata": {"sidecarImported": True},
                },
            ),
        ]
    )

    assert (
        registry.resolution_issue(
            "KF-KB-TEST",
            "KDV-TEST-V1",
            "new_mineru_semantic",
            "PARSE-NEW",
        )
        is None
    )
