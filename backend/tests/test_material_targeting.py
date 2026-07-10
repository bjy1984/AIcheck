from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID
from libs.integrations import task_dispatcher


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
    result = {
        "status": "success",
        "fileName": document["fileName"],
        "documentType": document_type,
        "fragments": [{"pageNo": 1, "text": text, "confidence": 0.92}],
        "fields": fields,
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
    result = {
        "status": "success",
        "fileName": document["fileName"],
        "documentType": "design_license",
        "fragments": [
            {
                "pageNo": 1,
                "text": "设计许可证机构名称 华东设计院 许可范围 压力管道设计 许可级别 GA 有效期 2028-12-31 印章清晰",
                "confidence": 0.96,
            }
        ],
        "fields": [
            {"fieldName": "设计许可证机构名称", "fieldValue": "华东设计院", "pageNo": 1, "confidence": 0.96},
            {"fieldName": "许可范围", "fieldValue": "压力管道设计", "pageNo": 1, "confidence": 0.95},
            {"fieldName": "许可级别", "fieldValue": "GA", "pageNo": 1, "confidence": 0.94},
            {"fieldName": "有效期", "fieldValue": "2028-12-31", "pageNo": 1, "confidence": 0.95},
            {"fieldName": "印章", "fieldValue": "清晰", "pageNo": 1, "confidence": 0.92},
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

    readiness = assert_ok(client.get(f"/api/projects/{PROJECT_ID}/nodes/1/evidence-readiness"))
    assert readiness["hasReviewPoints"] is True
    assert any(link["documentVersionId"] == version["id"] for link in readiness["nodeEvidenceLinks"])
    assert any(
        binding["documentVersionId"] == version["id"] and int(binding["nodeId"]) == 1
        for binding in repo.state["bindings"]
    )


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
    assert readiness["readyForGapPrecheck"] is False
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
