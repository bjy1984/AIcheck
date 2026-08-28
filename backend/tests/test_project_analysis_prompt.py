from __future__ import annotations

import json

import pytest


def _state() -> dict:
    return {
        "projects": [
            {
                "id": "P-1",
                "name": "单体分析测试工程",
                "businessPackId": "engineering_inspection_v1",
            }
        ],
        "tree_nodes": [
            {
                "projectId": "P-1",
                "nodeId": 1,
                "name": "设计单位许可资质",
                "criteria": "规则一原文",
                "checkMethod": "方法一原文",
            },
            {
                "projectId": "P-1",
                "nodeId": 2,
                "name": "施工单位许可资质",
                "criteria": "规则二原文",
                "checkMethod": "方法二原文",
            },
            {
                "projectId": "P-1",
                "nodeId": 3,
                "name": "无资料节点",
                "criteria": "规则三原文",
                "checkMethod": "方法三原文",
            },
        ],
        "requirements": [
            {
                "projectId": "P-1",
                "nodeId": 1,
                "materialTypeCode": "design_license",
                "materialTypeName": "设计许可证",
                "requiredType": "必传",
                "evidenceItems": ["机构名称", "许可范围"],
            }
        ],
        "documents": [
            {
                "id": "DOC-SHARED",
                "projectId": "P-1",
                "fileName": "共享许可证.pdf",
                "currentVersionId": "DV-SHARED-V2",
            },
            {
                "id": "DOC-SECOND",
                "projectId": "P-1",
                "fileName": "施工方案.pdf",
                "currentVersionId": "DV-SECOND-V1",
            },
            {
                "id": "DOC-REJECTED",
                "projectId": "P-1",
                "fileName": "已驳回.pdf",
                "currentVersionId": "DV-REJECTED-V1",
            },
        ],
        "versions": [
            {"id": "DV-SHARED-V1", "documentId": "DOC-SHARED", "contentHash": "sha256:old"},
            {"id": "DV-SHARED-V2", "documentId": "DOC-SHARED", "contentHash": "sha256:new"},
            {"id": "DV-SECOND-V1", "documentId": "DOC-SECOND", "contentHash": "sha256:second"},
            {
                "id": "DV-REJECTED-V1",
                "documentId": "DOC-REJECTED",
                "contentHash": "sha256:rejected",
            },
        ],
        "document_versions": [
            {"id": "DV-SHARED-V1", "documentId": "DOC-SHARED", "contentHash": "sha256:old"},
            {"id": "DV-SHARED-V2", "documentId": "DOC-SHARED", "contentHash": "sha256:new"},
            {"id": "DV-SECOND-V1", "documentId": "DOC-SECOND", "contentHash": "sha256:second"},
            {
                "id": "DV-REJECTED-V1",
                "documentId": "DOC-REJECTED",
                "contentHash": "sha256:rejected",
            },
        ],
        "node_evidence_links": [
            {
                "id": "NEL-1",
                "projectId": "P-1",
                "nodeId": 1,
                "documentId": "DOC-SHARED",
                "documentVersionId": "DV-SHARED-V2",
                "manualStatus": "confirmed",
                "revision": 1,
            },
            {
                "id": "NEL-2",
                "projectId": "P-1",
                "nodeId": 2,
                "documentId": "DOC-SHARED",
                "documentVersionId": "DV-SHARED-V2",
                "manualStatus": "confirmed",
                "revision": 2,
            },
            {
                "id": "NEL-3",
                "projectId": "P-1",
                "nodeId": 2,
                "documentId": "DOC-SECOND",
                "documentVersionId": "DV-SECOND-V1",
                "manualStatus": "confirmed",
                "revision": 1,
            },
            {
                "id": "NEL-OLD",
                "projectId": "P-1",
                "nodeId": 1,
                "documentId": "DOC-SHARED",
                "documentVersionId": "DV-SHARED-V1",
                "manualStatus": "confirmed",
                "revision": 1,
            },
            {
                "id": "NEL-REJECTED",
                "projectId": "P-1",
                "nodeId": 1,
                "documentId": "DOC-REJECTED",
                "documentVersionId": "DV-REJECTED-V1",
                "manualStatus": "rejected",
                "revision": 1,
            },
        ],
        "ocr_parse_results": [
            {
                "id": "OCR-SHARED-V1",
                "documentVersionId": "DV-SHARED-V1",
                "artifactHash": "sha256:ocr-old",
                "status": "success",
                "fragments": [{"pageNo": 1, "text": "旧版本不得进入"}],
            },
            {
                "id": "OCR-SHARED-V2",
                "documentVersionId": "DV-SHARED-V2",
                "artifactHash": "sha256:ocr-new",
                "status": "success",
                "fragments": [
                    {
                        "pageNo": 1,
                        "text": "<table><tr><td>许可证编号</td><td>TS-001</td></tr></table>",
                    }
                ],
            },
            {
                "id": "OCR-SECOND-V1",
                "documentVersionId": "DV-SECOND-V1",
                "artifactHash": "sha256:ocr-second",
                "status": "success",
                "fragments": [{"pageNo": 1, "text": "施工方案完整正文"}],
            },
            {
                "id": "OCR-REJECTED-V1",
                "documentVersionId": "DV-REJECTED-V1",
                "artifactHash": "sha256:ocr-rejected",
                "status": "success",
                "fragments": [{"pageNo": 1, "text": "驳回资料不得进入"}],
            },
        ],
    }


def _route(**overrides) -> dict:
    return {
        "id": "MODELROUTE-project-review-large-v1",
        "modelAlias": "project-review-large",
        "version": "1.0.0",
        "status": "production",
        "maxContextTokens": 131072,
        "reservedOutputTokens": 24000,
        **overrides,
    }


def test_project_prompt_deduplicates_shared_ocr_and_resolves_every_file_ref() -> None:
    from libs.project_analysis.prompt import (
        build_project_analysis_request,
        build_project_analysis_snapshot,
    )

    state = _state()
    snapshot = build_project_analysis_snapshot(
        state,
        "P-1",
        business_pack_id="engineering_inspection_v1",
        prompt_version="project-monolithic-analysis@1.0.0",
        model_route=_route(),
    )
    request = build_project_analysis_request(state, snapshot)
    payload = json.loads(request["messages"][1]["content"])
    project = payload["project"]

    assert snapshot["nodeIds"] == [1, 2]
    assert snapshot["documentVersionIds"] == ["DV-SECOND-V1", "DV-SHARED-V2"]
    assert [node["nodeId"] for node in project["nodes"]] == [1, 2]
    assert set(project["fileCorpus"]) == {"DOC-SHARED", "DOC-SECOND"}
    assert request["messages"][1]["content"].count('"fullOcrText"') == 2
    assert "许可证编号 | TS-001" in project["fileCorpus"]["DOC-SHARED"]["fullOcrText"]
    assert "<table" not in project["fileCorpus"]["DOC-SHARED"]["fullOcrText"]
    assert "旧版本不得进入" not in request["messages"][1]["content"]
    assert "驳回资料不得进入" not in request["messages"][1]["content"]
    assert all(
        file_ref["fileId"] in project["fileCorpus"]
        for node in project["nodes"]
        for file_ref in node["fileRefs"]
    )
    assert "linkedFiles" not in request["messages"][0]["content"]
    assert "linkedFiles" not in request["messages"][1]["content"]
    assert snapshot["snapshotHash"].startswith("sha256:")


def test_project_prompt_only_requests_fields_the_model_must_own() -> None:
    from libs.project_analysis.prompt import (
        build_project_analysis_request,
        build_project_analysis_snapshot,
    )

    state = _state()
    snapshot = build_project_analysis_snapshot(
        state,
        "P-1",
        business_pack_id="engineering_inspection_v1",
        prompt_version="project-monolithic-analysis@1.0.0",
        model_route=_route(),
    )
    request = build_project_analysis_request(state, snapshot)
    schema = json.loads(request["messages"][1]["content"])["outputSchema"]

    assert set(schema) == {"nodeReviews"}
    node_schema = schema["nodeReviews"][0]
    assert set(node_schema) == {"nodeId", "reviewResult", "findings"}
    assert set(node_schema["findings"][0]) == {
        "findingType",
        "severity",
        "title",
        "description",
        "evidenceRefs",
    }
    assert set(node_schema["findings"][0]["evidenceRefs"][0]) == {
        "fileId",
        "pageNo",
        "quotedText",
    }


def test_project_prompt_excludes_file_names_and_version_metadata_from_model_context() -> None:
    from libs.project_analysis.prompt import (
        build_project_analysis_request,
        build_project_analysis_snapshot,
    )

    state = _state()
    snapshot = build_project_analysis_snapshot(
        state,
        "P-1",
        business_pack_id="engineering_inspection_v1",
        prompt_version="project-monolithic-analysis@1.0.0",
        model_route=_route(),
    )
    request = build_project_analysis_request(state, snapshot)
    content = request["messages"][1]["content"]
    project = json.loads(content)["project"]

    assert all(
        set(file_ref) == {"fileId"}
        for node in project["nodes"]
        for file_ref in node["fileRefs"]
    )
    assert all(
        "fileName" not in source and "documentVersionId" not in source
        for source in project["fileCorpus"].values()
    )
    assert "共享许可证.pdf" not in content
    assert "施工方案.pdf" not in content


def test_project_analysis_preview_blocks_context_overflow_without_model_call() -> None:
    from libs.project_analysis.prompt import (
        ProjectAnalysisContextLimitError,
        prepare_project_analysis_request,
        project_analysis_preview,
    )

    state = _state()
    route = _route(maxContextTokens=100, reservedOutputTokens=20)
    preview = project_analysis_preview(state, "P-1", model_route=route)
    called = False

    def model_call(_request: dict) -> None:
        nonlocal called
        called = True

    assert preview["contextLimitExceeded"] is True
    assert preview["availableInputTokens"] == 80
    assert preview["estimatedInputTokens"] > 80
    with pytest.raises(ProjectAnalysisContextLimitError) as error:
        prepare_project_analysis_request(
            state,
            "P-1",
            model_route=route,
            model_call=model_call,
        )
    assert error.value.estimated_tokens == preview["estimatedInputTokens"]
    assert called is False


def test_large_project_model_route_is_explicit_and_has_no_small_model_fallback() -> None:
    from libs.db.seed import MODEL_ROUTE_VERSIONS
    from libs.qwen_runtime import MODEL_ROLE_ALIASES

    route = next(
        row for row in MODEL_ROUTE_VERSIONS if row.get("modelAlias") == "project-review-large"
    )

    assert MODEL_ROLE_ALIASES["project-review-large"] == "projectReview"
    assert route["status"] == "production"
    assert route["maxContextTokens"] >= 131072
    assert route["reservedOutputTokens"] >= 24000
    assert route["fallbackAliases"] == []


def test_snapshot_accepts_legacy_active_bindings_when_evidence_links_are_absent() -> None:
    from libs.project_analysis.prompt import build_project_analysis_snapshot

    state = _state()
    state["node_evidence_links"] = []
    state["bindings"] = [
        {
            "id": "BIND-LEGACY",
            "projectId": "P-1",
            "nodeId": 1,
            "documentId": "DOC-SHARED",
            "documentVersionId": "DV-SHARED-V2",
            "bindingStatus": "已提交",
        }
    ]

    snapshot = build_project_analysis_snapshot(
        state,
        "P-1",
        model_route=_route(),
    )

    assert snapshot["nodeIds"] == [1]
    assert snapshot["documentVersionIds"] == ["DV-SHARED-V2"]


def test_snapshot_hash_changes_when_ocr_content_changes_for_same_document_version() -> None:
    from libs.project_analysis.prompt import build_project_analysis_snapshot

    state = _state()
    first = build_project_analysis_snapshot(state, "P-1", model_route=_route())
    shared = next(
        row for row in state["ocr_parse_results"] if row["documentVersionId"] == "DV-SHARED-V2"
    )
    shared["fragments"][0]["text"] = "同一版本后来出现的不同 OCR 正文"
    shared["artifactHash"] = "sha256:ocr-newer"

    second = build_project_analysis_snapshot(state, "P-1", model_route=_route())

    assert first["snapshotHash"] != second["snapshotHash"]
    assert first["documentOcrHashes"] != second["documentOcrHashes"]


def test_snapshot_falls_back_to_business_pack_rule_text() -> None:
    from libs.project_analysis.prompt import build_project_analysis_snapshot

    state = _state()
    state["tree_nodes"][0]["criteria"] = ""
    state["tree_nodes"][0]["checkMethod"] = ""

    snapshot = build_project_analysis_snapshot(state, "P-1", model_route=_route())
    node = next(row for row in snapshot["nodes"] if row["nodeId"] == 1)

    assert node["criteria"]
    assert node["checkMethod"]
