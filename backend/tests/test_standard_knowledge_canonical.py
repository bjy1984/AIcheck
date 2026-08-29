import json

import pytest

from libs.db.repository import STATE_COLLECTIONS, repo
from libs.standard_knowledge_canonical import (
    build_standard_knowledge_record,
    collect_standard_sources,
    normalized_content_hash,
    select_canonical_field,
)


def canonical_source_fixture(*, without_references: bool = False) -> dict[str, object]:
    file = {
        "id": "KF-KB-TEST",
        "sourceId": "KS-STANDARD-RULES",
        "sourceType": "standard",
        "documentId": "KDOC-TEST",
        "documentVersionId": "KDV-TEST-V1",
        "fileName": "NB_T 47013.10-2015.pdf",
        "sourceRelativePath": "rules/standards/NB_T 47013.10-2015.pdf",
        "tenantId": "TENANT-DEFAULT",
    }
    state = {
        "knowledge_sources": [{"id": "KS-STANDARD-RULES", "version": "inspection_kb@test"}],
        "knowledge_files": [file],
        "documents": [
            {"id": "KDOC-TEST", "currentVersionId": "KDV-TEST-V1", "tenantId": "TENANT-DEFAULT"}
        ],
        "versions": [
            {
                "id": "KDV-TEST-V1",
                "documentId": "KDOC-TEST",
                "isCurrent": True,
                "tenantId": "TENANT-DEFAULT",
            }
        ],
        "ocr_parse_results": [
            {
                "id": "PARSE-NEW",
                "parseResultId": "PARSE-NEW",
                "documentVersionId": "KDV-TEST-V1",
                "createdAt": "2026-08-29 12:00:00",
                "metadata": {"sidecarImported": True},
                "fields": [{"fieldName": "发布日期", "fieldValue": "2015-04-02", "pageNo": 1}],
                "layoutBlocks": [
                    {"blockId": "B-NEW", "blockType": "text", "text": "1.1 范围正文", "pageNo": 7}
                ],
                "tables": [],
                "seals": [],
                "pages": [{"pageNo": 1}, {"pageNo": 7}],
            },
            {
                "id": "PARSE-OLD",
                "parseResultId": "PARSE-OLD",
                "documentVersionId": "KDV-TEST-V1",
                "createdAt": "2026-07-01 12:00:00",
                "metadata": {},
                "fields": [
                    {"fieldName": "发布日期", "fieldValue": "2014-01-01", "pageNo": 1},
                    {"fieldName": "备案号", "fieldValue": "61188-2018", "pageNo": 1},
                ],
                "layoutBlocks": [],
                "tables": [],
                "seals": [],
                "pages": [],
            },
        ],
        "extracted_fields": [
            {
                "id": "FIELD-OLD",
                "documentVersionId": "KDV-TEST-V1",
                "fieldName": "OCR文本",
                "fieldValue": "旧正文",
            }
        ],
        "evidence_links": [
            {
                "id": "EV-OLD",
                "documentVersionId": "KDV-TEST-V1",
                "fieldName": "OCR文本",
                "quotedText": "旧正文",
                "pageNo": 7,
            }
        ],
        "knowledge_chunks": [
            {"id": "CHK-TEST", "fileId": "KF-KB-TEST", "text": "1.1 范围正文", "pageNo": 7}
        ],
        "knowledge_clauses": [
            {
                "id": "KC-TEST",
                "fileId": "KF-KB-TEST",
                "clauseNo": "1.1",
                "text": "1.1 范围正文",
                "pageNo": 7,
            }
        ],
        "knowledge_page_index_nodes": [
            {
                "id": "PIN-TEST",
                "sourceRelativePath": file["sourceRelativePath"],
                "title": "1 范围",
                "startPage": 7,
                "endPage": 7,
            }
        ],
        "standard_document_versions": [
            {
                "id": "SDV-TEST",
                "knowledgeFileId": "KF-KB-TEST",
                "standardRef": "STD-TEST",
                "code": "NB/T 47013.10-2015",
                "name": "衍射时差法超声检测",
            }
        ],
        "standard_clause_references": []
        if without_references
        else [
            {
                "id": "SCR-TEST",
                "knowledgeFileId": "KF-KB-TEST",
                "standardRef": "STD-TEST",
                "clauseNo": "1.1",
                "sourcePage": 7,
            }
        ],
        "standard_clause_locators": []
        if without_references
        else [
            {
                "id": "SCL-TEST",
                "knowledgeFileId": "KF-KB-TEST",
                "standardRef": "STD-TEST",
                "clauseNo": "1.1",
                "sourcePage": 7,
                "bbox": [10, 20, 300, 80],
            }
        ],
        "rule_versions": [
            {
                "id": "RULE-1",
                "nodeIds": [40],
                "referencedStandards": [
                    {"knowledgeFileId": "KF-KB-TEST", "standardRef": "STD-TEST", "clauseNo": "1.1"}
                ],
            }
        ],
        "business_packs": [
            {
                "id": "engineering_inspection_v1",
                "standardCatalog": [
                    {"id": "STD-TEST", "code": "NB/T 47013.10-2015", "name": "衍射时差法超声检测"}
                ],
            }
        ],
    }
    return state


def test_new_mineru_value_wins_and_old_only_value_survives():
    selected = select_canonical_field(
        "publicationDate",
        [
            {"value": "2014-01-01", "sourceType": "legacy_ocr", "sourceId": "OLD"},
            {"value": "2015-04-02", "sourceType": "new_mineru", "sourceId": "NEW"},
        ],
    )
    assert selected["value"] == "2015-04-02"
    assert selected["authority"] == "current"
    assert selected["selectedSourceId"] == "NEW"
    assert {item["sourceId"] for item in selected["sources"]} == {"OLD", "NEW"}

    legacy_only = select_canonical_field(
        "filingNumber",
        [{"value": "61188-2018", "sourceType": "legacy_ocr", "sourceId": "OLD"}],
    )
    assert legacy_only["value"] == "61188-2018"
    assert legacy_only["authority"] == "legacy_only"


def test_canonical_collection_is_persisted_state():
    assert STATE_COLLECTIONS["standard_knowledge_records"] == "standard_knowledge_records"
    assert "standard_knowledge_records" in repo.state


def test_collect_standard_sources_maps_every_supported_source(tmp_path):
    state = canonical_source_fixture()
    visual_dir = tmp_path / "backend/data/visual_extractions"
    visual_dir.mkdir(parents=True)
    (visual_dir / "KF-KB-TEST.json").write_text(
        json.dumps(
            {
                "fileId": "KF-KB-TEST",
                "sourceMethod": "codex_visual_manual_extraction",
                "pages": [{"pageNo": 1, "title": "封面", "extractedText": "发布日期为 2015-04-02"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sidecar_dir = tmp_path / "backend/data/rules_ocr_sidecars"
    sidecar_dir.mkdir(parents=True)
    (sidecar_dir / "KF-KB-TEST.json").write_text(
        json.dumps({"fileId": "KF-KB-TEST"}), encoding="utf-8"
    )

    sources = collect_standard_sources(state, "KF-KB-TEST", tmp_path)

    assert sources["file"]["id"] == "KF-KB-TEST"
    assert sources["document"]["id"] == "KDOC-TEST"
    assert sources["version"]["id"] == "KDV-TEST-V1"
    assert sources["newParse"]["parseResultId"] == "PARSE-NEW"
    assert [item["parseResultId"] for item in sources["legacyParses"]] == ["PARSE-OLD"]
    assert len(sources["legacyFields"]) == 1
    assert len(sources["legacyEvidence"]) == 1
    assert sources["visualExtraction"]["pages"][0]["title"] == "封面"
    assert sources["legacyRuleSidecar"]["fileId"] == "KF-KB-TEST"
    assert len(sources["chunks"]) == 1
    assert len(sources["clauses"]) == 1
    assert len(sources["pageIndexNodes"]) == 1
    assert sources["standardVersions"][0]["standardRef"] == "STD-TEST"
    assert sources["clauseReferences"][0]["clauseNo"] == "1.1"
    assert sources["clauseLocators"][0]["clauseNo"] == "1.1"
    assert sources["catalogItems"] == []
    assert sources["ruleReferences"] == [
        {
            "knowledgeFileId": "KF-KB-TEST",
            "standardRef": "STD-TEST",
            "clauseNo": "1.1",
            "ruleId": "RULE-1",
            "nodeIds": [40],
        }
    ]


def test_source_collection_does_not_mutate_input_state(tmp_path):
    state = canonical_source_fixture()
    before = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    collect_standard_sources(state, "KF-KB-TEST", tmp_path)

    after = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert after == before


def test_collect_standard_sources_rejects_cross_document_version(tmp_path):
    state = canonical_source_fixture()
    state["versions"][0]["documentId"] = "KDOC-OTHER"

    with pytest.raises(
        ValueError, match="standard document/version relationship invalid: KF-KB-TEST"
    ):
        collect_standard_sources(state, "KF-KB-TEST", tmp_path)


def test_build_record_uses_new_values_and_keeps_old_only_information(tmp_path):
    record = build_standard_knowledge_record(canonical_source_fixture(), "KF-KB-TEST", tmp_path)

    assert record["kbVersion"] == "inspection_kb@test"
    assert record["canonicalVersion"] == "standard-knowledge-canonical@1"
    assert record["identity"]["standardCode"]["value"] == "NB/T 47013.10-2015"
    assert record["version"]["publicationDate"]["value"] == "2015-04-02"
    assert record["version"]["publicationDate"]["selectedSourceId"] == "PARSE-NEW"
    assert record["identity"]["filingNumber"]["value"] == "61188-2018"
    assert record["identity"]["filingNumber"]["authority"] == "legacy_only"


def test_kb_version_change_invalidates_source_fingerprint(tmp_path):
    state = canonical_source_fixture()
    first = build_standard_knowledge_record(state, "KF-KB-TEST", tmp_path)
    state["knowledge_sources"][0]["version"] = "inspection_kb@next"

    second = build_standard_knowledge_record(state, "KF-KB-TEST", tmp_path)

    assert second["kbVersion"] == "inspection_kb@next"
    assert second["sourceFingerprint"] != first["sourceFingerprint"]


def test_structure_is_deduplicated_but_all_sources_are_retained(tmp_path):
    visual_dir = tmp_path / "backend/data/visual_extractions"
    visual_dir.mkdir(parents=True)
    (visual_dir / "KF-KB-TEST.json").write_text(
        json.dumps(
            {
                "fileId": "KF-KB-TEST",
                "pages": [{"pageNo": 7, "text": "1.1 范围正文", "bbox": [10, 20, 300, 80]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    record = build_standard_knowledge_record(canonical_source_fixture(), "KF-KB-TEST", tmp_path)

    matching = [item for item in record["clauses"] if item["clauseNo"] == "1.1"]
    assert len(matching) == 1
    assert {source["sourceType"] for source in matching[0]["sources"]} == {
        "new_mineru",
        "knowledge_clause",
        "visual_extraction",
    }


def test_completeness_names_specific_missing_categories(tmp_path):
    record = build_standard_knowledge_record(
        canonical_source_fixture(without_references=True), "KF-KB-TEST", tmp_path
    )

    assert record["completeness"]["normativeReferences"]["status"] == "missing"
    assert record["completeness"]["overall"] == "partial"
    assert "normativeReferences" in record["completeness"]["missingCategories"]


def test_business_rule_context_is_context_only_with_standard_structure_not_applicable(tmp_path):
    state = canonical_source_fixture()
    state["knowledge_files"][0]["contextType"] = "business_rule_context"
    state["knowledge_files"][0]["fileName"] = "业务规则.md"

    record = build_standard_knowledge_record(state, "KF-KB-TEST", tmp_path)

    assert record["contextType"] == "context_only"
    for category in (
        "sections",
        "clauses",
        "tables",
        "equations",
        "images",
        "seals",
        "normativeReferences",
        "replacementRelations",
        "evidenceLocation",
    ):
        assert record["completeness"][category]["status"] == "not_applicable"
        assert category not in record["completeness"]["missingCategories"]


def test_clause_uses_valid_supporting_locator_and_preserves_every_locator(tmp_path):
    state = canonical_source_fixture()
    state["standard_clause_locators"] = [
        {
            "id": "SCL-INVALID",
            "knowledgeFileId": "KF-KB-TEST",
            "clauseNo": "1.1",
            "sourcePage": 7,
            "bbox": [10, 20, 10, 80],
        },
        {
            "id": "SCL-VALID",
            "knowledgeFileId": "KF-KB-TEST",
            "clauseNo": "1.1",
            "sourcePage": 7,
            "bbox": [10, 20, 300, 80],
        },
    ]

    record = build_standard_knowledge_record(state, "KF-KB-TEST", tmp_path)

    clause = next(item for item in record["clauses"] if item["clauseNo"] == "1.1")
    assert clause["pageNo"] == 7
    assert clause["bbox"] == [10.0, 20.0, 300.0, 80.0]
    assert {
        item["sourceId"] for item in record["provenance"] if item["sourceType"] == "clause_locator"
    } == {"SCL-INVALID", "SCL-VALID"}
    assert record["completeness"]["evidenceLocation"]["located"] > 0


def test_clause_location_never_combines_selected_page_with_supporting_bbox(tmp_path):
    state = canonical_source_fixture()
    state["standard_clause_locators"] = [
        {
            "id": "SCL-PAGE-8",
            "knowledgeFileId": "KF-KB-TEST",
            "clauseNo": "1.1",
            "sourcePage": 8,
            "bbox": [10, 20, 300, 80],
        }
    ]

    record = build_standard_knowledge_record(state, "KF-KB-TEST", tmp_path)

    clause = next(item for item in record["clauses"] if item["clauseNo"] == "1.1")
    assert clause["pageNo"] == 8
    assert clause["bbox"] == [10.0, 20.0, 300.0, 80.0]
    assert clause["locatorIds"] == ["SCL-PAGE-8"]


def test_page_only_locator_survives_and_counts_as_located(tmp_path):
    state = canonical_source_fixture()
    state["standard_clause_locators"] = [
        {
            "id": "SCL-PAGE-ONLY",
            "knowledgeFileId": "KF-KB-TEST",
            "clauseNo": "1.1",
            "sourcePage": 8,
            "bbox": None,
        }
    ]

    record = build_standard_knowledge_record(state, "KF-KB-TEST", tmp_path)

    clause = next(item for item in record["clauses"] if item["clauseNo"] == "1.1")
    assert clause["pageNo"] == 8
    assert clause["bbox"] is None
    assert clause["locatorIds"] == ["SCL-PAGE-ONLY"]
    assert record["completeness"]["evidenceLocation"] == {
        "status": "complete",
        "located": 1,
        "total": 1,
    }


def test_content_hash_normalizes_whitespace_before_json_encoding():
    assert normalized_content_hash({"text": "alpha\nbeta"}) == normalized_content_hash(
        {"text": "alpha beta"}
    )


def test_field_evidence_hashes_include_value_and_quoted_text(tmp_path):
    record = build_standard_knowledge_record(canonical_source_fixture(), "KF-KB-TEST", tmp_path)
    old_field_evidence = [
        item
        for item in record["evidence"]
        if item["sourceId"] == "PARSE-OLD" and item["pageNo"] == 1
    ]

    assert {item["quotedText"] for item in old_field_evidence} == {
        "2014-01-01",
        "61188-2018",
    }
    assert len({item["contentHash"] for item in old_field_evidence}) == 2
