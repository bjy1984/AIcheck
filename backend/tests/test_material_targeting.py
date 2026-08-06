from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID
from libs.integrations import task_dispatcher
from libs.material_targeting import PARTIAL_STATUS, build_node_evidence_readiness


client = TestClient(app)


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def assert_ok(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    return payload["data"]


def apply_ocr(document: dict, version: dict, *, document_type: str, text: str, fields: list[dict]) -> None:
    located_fields = [
        {
            **field,
            "bbox": field.get("bbox") or [20.0, 20.0 + index * 30, 520.0, 45.0 + index * 30],
        }
        for index, field in enumerate(fields)
    ]
    result = {
        "status": "success",
        "fileName": document["fileName"],
        "documentType": document_type,
        "fragments": [
            {
                "pageNo": 1,
                "text": text,
                "bbox": [10.0, 10.0, 560.0, 260.0],
                "confidence": 0.92,
            }
        ],
        "fields": located_fields,
    }
    job = repo.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        document_type=document_type,
    )
    repo.finish_ocr_job_record(job, result)
    repo.apply_ocr_result(document["id"], version["id"], result)


def test_admin_material_review_points_crud() -> None:
    overview = assert_ok(client.get("/api/admin/config-overview"))
    initial_count = len(overview["materialReviewPoints"])
    assert initial_count > 100

    payload = {
        "target": "material-review-point",
        "reason": "测试新增业务资料审查点。",
        "values": {
            "businessPackId": "engineering_inspection_v1",
            "nodeId": 1,
            "nodeName": "设计单位许可资质",
            "ruleId": "R01",
            "businessModule": "受检单位资质",
            "reviewClass": "C",
            "reviewContent": "测试审查点",
            "materialCategory": "资质证照",
            "materialTypeCode": "design_license",
            "materialTypeName": "设计单位许可证",
            "fileContent": "设计单位许可证",
            "evidenceItemText": "机构名称、许可范围、有效期",
            "evidenceItems": ["机构名称", "许可范围", "有效期"],
            "responsibleParty": "contractor",
            "responsiblePartyLabel": "施工",
            "requiredType": "必传",
            "mappingRelation": "直接资料类型匹配",
            "minConfidence": 0.65,
            "enabled": True,
        },
    }
    created = assert_ok(client.post("/api/admin/config-items/material-review-point", json=payload))
    assert len(created["overview"]["materialReviewPoints"]) == initial_count + 1
    created_point = created["overview"]["materialReviewPoints"][0]

    updated = assert_ok(
        client.put(
            f"/api/admin/config-items/material-review-point/{created_point['id']}",
            json={
                "target": "material-review-point",
                "id": created_point["id"],
                "reason": "测试编辑业务资料审查点。",
                "values": {"reviewContent": "测试审查点-已更新"},
            },
        )
    )
    assert updated["overview"]["materialReviewPoints"][0]["reviewContent"] == "测试审查点-已更新"

    deleted = assert_ok(client.delete(f"/api/admin/config-items/material-review-point/{created_point['id']}"))
    assert len(deleted["overview"]["materialReviewPoints"]) == initial_count


def test_ocr_targeting_creates_node_evidence_links_and_auto_binding() -> None:
    document, version = repo.create_document(
        PROJECT_ID,
        "设计单位许可证.pdf",
        "application/pdf",
        material_category="资质证照",
    )
    document["materialTypeCode"] = "design_license"
    result = {
        "status": "success",
        "fileName": document["fileName"],
        "documentType": "design_license",
        "fragments": [
            {
                "pageNo": 1,
                "bbox": [10.0, 10.0, 560.0, 180.0],
                "text": "设计许可证机构名称 华东设计院 许可范围 压力管道设计 许可级别 GA 有效期 2028-12-31 印章清晰",
                "confidence": 0.96,
            }
        ],
        "fields": [
            {"fieldName": "设计许可证机构名称", "fieldValue": "华东设计院", "pageNo": 1, "bbox": [10, 10, 180, 30], "confidence": 0.96},
            {"fieldName": "许可范围", "fieldValue": "压力管道设计", "pageNo": 1, "bbox": [10, 35, 220, 55], "confidence": 0.95},
            {"fieldName": "许可级别", "fieldValue": "GA", "pageNo": 1, "bbox": [10, 60, 120, 80], "confidence": 0.94},
            {"fieldName": "有效期", "fieldValue": "2028-12-31", "pageNo": 1, "bbox": [10, 85, 220, 105], "confidence": 0.95},
            {"fieldName": "印章", "fieldValue": "清晰", "pageNo": 1, "bbox": [10, 110, 120, 130], "confidence": 0.92},
        ],
    }
    job = repo.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        document_type="design_license",
    )
    repo.finish_ocr_job_record(job, result)
    repo.apply_ocr_result(document["id"], version["id"], result)

    targeting = assert_ok(
        client.post(f"/api/projects/{PROJECT_ID}/documents/{document['id']}/targeting/recompute")
    )["run"]
    assert targeting["createdLinkCount"] >= 1
    assert targeting["createdBindingCount"] >= 1
    license_link = next(
        item
        for item in targeting["createdLinks"]
        if item["materialTypeCode"] == "design_license"
    )
    assert license_link["formalEvidenceEligible"] is True
    assert license_link["quotedText"] not in {"设计单位许可证", "资质证照"}
    assert license_link["fieldName"] not in {"资料类型", "OCR分类依据", "页数"}
    assert license_link["evidenceFacts"]
    assert all(item["bbox"] for item in license_link["evidenceFacts"] if item["formalEvidenceEligible"])

    readiness = assert_ok(client.get(f"/api/projects/{PROJECT_ID}/nodes/1/evidence-readiness"))
    assert readiness["hasReviewPoints"] is True
    assert any(link["documentVersionId"] == version["id"] for link in readiness["nodeEvidenceLinks"])
    assert any(
        binding["documentVersionId"] == version["id"] and int(binding["nodeId"]) == 1
        for binding in repo.state["bindings"]
    )


def test_unlocatable_fact_is_separated_as_advisory_file() -> None:
    document, version = repo.create_document(
        PROJECT_ID,
        "设计单位许可证-无定位.pdf",
        "application/pdf",
        material_category="资质证照",
    )
    document["materialTypeCode"] = "design_license"
    apply_ocr(
        document,
        version,
        document_type="design_license",
        text="设计许可证机构名称 华东设计院 许可范围 压力管道设计 有效期至 2028年12月31日",
        fields=[
            {"fieldName": "设计许可证机构名称", "fieldValue": "华东设计院", "pageNo": 1, "confidence": 0.96},
            {"fieldName": "许可范围", "fieldValue": "压力管道设计", "pageNo": 1, "confidence": 0.95},
        ],
    )
    parse_result = next(
        item
        for item in repo.state["ocr_parse_results"]
        if item.get("documentVersionId") == version["id"]
    )
    for fragment in parse_result.get("fragments") or []:
        fragment["bbox"] = None
    for field in repo.state["extracted_fields"]:
        if field.get("documentVersionId") == version["id"]:
            field["bbox"] = None

    targeting = assert_ok(
        client.post(f"/api/projects/{PROJECT_ID}/documents/{document['id']}/targeting/recompute")
    )["run"]
    advisory = next(item for item in targeting["createdLinks"] if item["materialTypeCode"] == "design_license")

    assert advisory["formalEvidenceEligible"] is False
    assert advisory["evidenceTier"] == "advisory"
    readiness = assert_ok(client.get(f"/api/projects/{PROJECT_ID}/nodes/1/evidence-readiness"))
    assert advisory["id"] not in {item["id"] for item in readiness["nodeEvidenceLinks"]}
    assert advisory["id"] in {item["id"] for item in readiness["advisoryEvidenceLinks"]}


def test_design_document_cannot_prove_design_license_point() -> None:
    document, version = repo.create_document(
        PROJECT_ID,
        "管道特性表.png",
        "image/png",
        material_category="设计基础资料",
    )
    document["materialTypeCode"] = "design_document"
    apply_ocr(
        document,
        version,
        document_type="design_document",
        text=(
            "项目名称 广东LNG支线改造工程 单位名称 广东星燃石化设计院有限公司 "
            "资质证书编号 A244010070 有效期至 2024年6月21日 管道级别 GC2 设计压力 2.5MPa"
        ),
        fields=[
            {"fieldName": "单位名称", "fieldValue": "广东星燃石化设计院有限公司", "pageNo": 1, "confidence": 0.94},
            {"fieldName": "证书编号", "fieldValue": "A244010070", "pageNo": 1, "confidence": 0.95},
            {"fieldName": "有效期至", "fieldValue": "2024年6月21日", "pageNo": 1, "confidence": 0.93},
            {"fieldName": "管道级别", "fieldValue": "GC2", "pageNo": 1, "confidence": 0.93},
            {"fieldName": "设计压力", "fieldValue": "2.5MPa", "pageNo": 1, "confidence": 0.93},
        ],
    )

    targeting = assert_ok(
        client.post(f"/api/projects/{PROJECT_ID}/documents/{document['id']}/targeting/recompute")
    )["run"]

    assert not any(
        int(item["nodeId"]) == 1 and item["materialTypeCode"] == "design_license"
        for item in targeting["createdLinks"]
    )


def test_apply_ocr_result_promotes_usable_quality_blocked_result() -> None:
    document, version = repo.create_document(
        PROJECT_ID,
        "图纸目录.png",
        "image/png",
    )
    result = {
        "status": "success",
        "outcomeStatus": "partial",
        "quality": {
            "status": "needs_human_review",
            "reasons": ["REQUIRED_FIELD_MISSING", "FIELD_EVIDENCE_MISSING"],
        },
        "fragments": [{"pageNo": 1, "text": "DRAWING LIST", "confidence": 0.55}],
        "fields": [],
        "tables": [],
        "seals": [],
    }

    applied = repo.apply_ocr_result(document["id"], version["id"], result)

    assert applied["status"] == "success"
    assert applied["reviewOutcomeStatus"] == "partial"
    assert applied["qualityReasons"] == ["FIELD_EVIDENCE_MISSING", "REQUIRED_FIELD_MISSING"]
    assert document["currentOcrStatus"] == "已识别"
    assert version["ocrStatus"] == "已识别"
    assert version["sliceStatus"] == "待切片"
    assert version["vectorStatus"] == "待向量化"
    assert [item for item in repo.state["extracted_fields"] if item.get("documentVersionId") == version["id"]]


def test_apply_ocr_result_rejects_successful_but_empty_result() -> None:
    document, version = repo.create_document(
        PROJECT_ID,
        "空白文件.png",
        "image/png",
    )
    result = {
        "status": "success",
        "outcomeStatus": "completed",
        "quality": {"status": "auto_usable", "reasons": []},
        "fragments": [{"pageNo": 1, "text": "   "}],
        "fields": [{"fieldName": "文件名", "fieldValue": "不应作为入库成功依据"}],
        "tables": [{"rows": []}],
        "seals": [],
    }

    applied = repo.apply_ocr_result(document["id"], version["id"], result)

    assert applied["status"] == "failed"
    assert applied["ingestionStatus"] == "empty"
    assert document["currentOcrStatus"] == "识别失败"
    assert version["sliceStatus"] == "未切片"
    assert version["vectorStatus"] == "未向量化"
    assert not [item for item in repo.state["extracted_fields"] if item.get("documentVersionId") == version["id"]]


def test_node2_license_evidence_requires_manual_confirmation() -> None:
    document, version = repo.create_document(
        PROJECT_ID,
        "施工单位安装许可证.pdf",
        "application/pdf",
        material_category="资质证照",
    )
    document["materialTypeCode"] = "construction_license"
    apply_ocr(
        document,
        version,
        document_type="construction_license",
        text=(
            "中华人民共和国特种设备安装改造维修许可证 单位名称 贵州化工建设有限责任公司 "
            "许可证编号 TS3810436-2021 许可范围 工业管道 GC1级 有效期至 2021年4月27日"
        ),
        fields=[
            {"fieldName": "单位名称", "fieldValue": "贵州化工建设有限责任公司", "pageNo": 1, "confidence": 0.94},
            {"fieldName": "许可证编号", "fieldValue": "TS3810436-2021", "pageNo": 1, "confidence": 0.95},
            {"fieldName": "许可范围", "fieldValue": "工业管道 GC1级", "pageNo": 1, "confidence": 0.93},
            {"fieldName": "有效期至", "fieldValue": "2021年4月27日", "pageNo": 1, "confidence": 0.93},
        ],
    )

    targeting = assert_ok(
        client.post(f"/api/projects/{PROJECT_ID}/documents/{document['id']}/targeting/recompute")
    )["run"]
    node2_links = [link for link in targeting["createdLinks"] if int(link["nodeId"]) == 2]
    license_link = next(link for link in node2_links if link["materialTypeCode"] == "construction_license")

    assert license_link["supportStatus"] == "命中"
    assert license_link["manualStatus"] == "pending"

    readiness = assert_ok(client.get(f"/api/projects/{PROJECT_ID}/nodes/2/evidence-readiness"))
    license_row = next(row for row in readiness["requirements"] if row["materialTypeCode"] == "construction_license")
    assert license_row["evidenceReviewStatus"] == "待确认"
    assert license_row["fulfilled"] is False
    assert readiness["readyForAi"] is False

    confirmed = assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/nodes/2/evidence-links/{license_link['id']}/confirm",
            json={"comment": "原文与资料项一致。"},
        )
    )
    confirmed_row = next(
        row
        for row in confirmed["evidenceReadiness"]["requirements"]
        if row["materialTypeCode"] == "construction_license"
    )
    assert confirmed["evidenceLink"]["manualStatus"] == "confirmed"
    assert confirmed_row["evidenceReviewStatus"] == "已确认"
    assert confirmed_row["fulfilled"] is True
    assert confirmed["evidenceReadiness"]["unlocatableConfirmedCount"] == 0

    rejected = assert_ok(
        client.post(
            f"/api/projects/{PROJECT_ID}/nodes/2/evidence-links/{license_link['id']}/reject",
            json={"comment": "测试改为不采用。"},
        )
    )
    rejected_row = next(
        row
        for row in rejected["evidenceReadiness"]["requirements"]
        if row["materialTypeCode"] == "construction_license"
    )
    assert rejected["evidenceLink"]["manualStatus"] == "rejected"
    assert rejected_row["evidenceReviewStatus"] == "不采用"
    assert rejected_row["fulfilled"] is False


def test_node2_schedule_can_target_construction_plan_text() -> None:
    document, version = repo.create_document(
        PROJECT_ID,
        "施工方案.pdf",
        "application/pdf",
        material_category="施工组织设计",
    )
    document["materialTypeCode"] = "construction_organization_design"
    apply_ocr(
        document,
        version,
        document_type="construction_organization_design",
        text=(
            "恒基达鑫装车站新增两套卸车系统项目施工方案。工程内容为两条 20# 管线安装。"
            "工期目标：2021年3月15日进场，2021年3月26日竣工验收。"
        ),
        fields=[
            {"fieldName": "工程内容", "fieldValue": "两条 20# 管线安装", "pageNo": 1, "confidence": 0.9},
            {"fieldName": "施工计划工期", "fieldValue": "2021年3月15日 至 2021年3月26日", "pageNo": 1, "confidence": 0.9},
        ],
    )

    targeting = assert_ok(
        client.post(f"/api/projects/{PROJECT_ID}/documents/{document['id']}/targeting/recompute")
    )["run"]
    schedule_links = [
        link
        for link in targeting["createdLinks"]
        if int(link["nodeId"]) == 2 and link["materialTypeCode"] == "construction_schedule"
    ]

    assert schedule_links
    assert schedule_links[0]["manualStatus"] == "pending"


def test_ai_recheck_allows_pending_evidence_decisions(monkeypatch) -> None:
    document, version = repo.create_document(
        PROJECT_ID,
        "设计单位许可证.pdf",
        "application/pdf",
        material_category="资质证照",
    )
    point = next(
        item
        for item in repo.state["admin_config"]["materialReviewPoints"]
        if int(item.get("nodeId") or 0) == 1
    )
    repo.state["node_evidence_links"].append(
        {
            "id": "NEL-PARTIAL-READINESS",
            "projectId": PROJECT_ID,
            "nodeId": 1,
            "nodeName": point["nodeName"],
            "reviewPointId": point["id"],
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "fileName": document["fileName"],
            "supportStatus": "partial",
            "confidence": 0.7,
            "matchedEvidenceItems": ["机构名称"],
            "source": "material_targeting",
            "createdAt": "2026-07-07 00:00:00",
        }
    )

    readiness = assert_ok(client.get(f"/api/projects/{PROJECT_ID}/nodes/1/evidence-readiness"))
    assert readiness["nodeEvidenceLinks"]
    assert readiness["readyForAi"] is False
    assert readiness["readyForAiFormal"] is False
    assert readiness["readyForGapPrecheck"] is True
    assert readiness["availableReviewModes"] == ["gap_precheck"]
    assert readiness["recommendedAction"] == "run_gap_precheck"
    assert {item["code"] for item in readiness["blockingReasons"]} >= {"PENDING_EVIDENCE_DECISION", "MISSING_REQUIRED_EVIDENCE"}

    monkeypatch.setattr(
        task_dispatcher,
        "ai_recheck_dispatch_readiness",
        lambda: {"ready": True, "mode": "test", "statusReason": "test_dispatch"},
    )
    monkeypatch.setattr(
        task_dispatcher,
        "dispatch_ai_recheck",
        lambda project_id, node_id, run_id: {"mode": "test", "taskId": f"TEST-{run_id}"},
    )

    result = assert_ok(client.post(f"/api/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck"))

    latest_run = result["latestRun"]
    assert result["reviewMode"] == "gap_precheck"
    assert result["advisoryOnly"] is True
    assert latest_run["reviewMode"] == "gap_precheck"
    assert latest_run["evidenceReadiness"]["readyForAiFormal"] is False
    assert latest_run["evidenceReadiness"]["pendingCount"] >= 1
    assert version["id"] in latest_run["inputDocumentVersionIds"]
    assert result["dispatch"]["taskId"].startswith("TEST-")


def test_scan_import_expands_contractor_member_scope() -> None:
    from scripts.import_scan_test_scenario import CONTRACTOR_USER, ensure_role_member_scope

    member = ensure_role_member_scope(PROJECT_ID, "contractor", CONTRACTOR_USER, {1, 2, 4, 53})

    assert member["userId"] == "USER-CONTRACTOR-001"
    assert member["orgName"] == "粤海安装工程有限公司"
    assert {1, 2, 4, 16, 24, 25, 53}.issubset(set(member["nodeScope"]))


def test_domestic_manufacturing_license_does_not_auto_bind_overseas_node() -> None:
    document, version = repo.create_document(
        PROJECT_ID,
        "国内压力管道元件制造许可证.pdf",
        "application/pdf",
        material_category="制造单位许可资质",
    )
    document["materialTypeCode"] = "manufacturing_license"
    apply_ocr(
        document,
        version,
        document_type="manufacturing_license",
        text=(
            "中华人民共和国特种设备制造许可证 单位名称 河北广浩管件有限公司 "
            "许可证编号 TS2710504-2022 许可范围 压力管道管件 有效期至 2022年9月29日"
        ),
        fields=[
            {"fieldName": "单位名称", "fieldValue": "河北广浩管件有限公司", "pageNo": 1, "confidence": 0.96},
            {"fieldName": "许可证编号", "fieldValue": "TS2710504-2022", "pageNo": 1, "confidence": 0.96},
            {"fieldName": "许可范围", "fieldValue": "压力管道管件", "pageNo": 1, "confidence": 0.95},
        ],
    )

    targeting = assert_ok(
        client.post(f"/api/projects/{PROJECT_ID}/documents/{document['id']}/targeting/recompute")
    )["run"]

    assert any(int(link["nodeId"]) == 12 for link in targeting["createdLinks"])
    assert not any(int(link["nodeId"]) == 15 for link in targeting["createdLinks"])
    assert not any(
        int(binding.get("nodeId") or 0) == 15 and binding.get("documentVersionId") == version["id"]
        for binding in repo.state["bindings"]
    )


def test_readiness_counts_consolidated_binding_for_each_review_point() -> None:
    document, version = repo.create_document(
        PROJECT_ID,
        "设计图纸标题栏.png",
        "image/png",
        material_category="设计基础资料",
    )
    design_points = [
        point
        for point in repo.state["admin_config"]["materialReviewPoints"]
        if int(point.get("nodeId") or 0) == 1 and point.get("materialTypeCode") == "design_document"
    ]
    assert len(design_points) == 2
    review_point_ids = [str(point["id"]) for point in design_points]
    repo.state["bindings"].insert(
        0,
        {
            "id": "BIND-CONSOLIDATED-DESIGN",
            "projectId": PROJECT_ID,
            "nodeId": 1,
            "requirementId": review_point_ids[0],
            "reviewPointIds": review_point_ids,
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "fileName": document["fileName"],
            "bindingStatus": "已提交",
        },
    )

    readiness = build_node_evidence_readiness(repo, PROJECT_ID, 1)
    rows = {str(row["id"]): row for row in readiness["requirements"]}

    for point_id in review_point_ids:
        assert rows[point_id]["matchedBindingCount"] == 1
        assert rows[point_id]["matchedBindingIds"] == ["BIND-CONSOLIDATED-DESIGN"]
        assert rows[point_id]["matchedFileNames"] == ["设计图纸标题栏.png"]
        assert rows[point_id]["supportStatus"] == PARTIAL_STATUS
        assert rows[point_id]["evidenceReviewStatus"] == "已挂载待定位"
        assert rows[point_id]["fulfilled"] is False
