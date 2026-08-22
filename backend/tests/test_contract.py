from __future__ import annotations

import importlib.util
import inspect
import io
import json
import sys
import zipfile
from argparse import Namespace
from copy import deepcopy
from datetime import UTC
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.indexes import POSTGRES_INDEXES
from libs.db.postgres import bootstrap_local_roles_if_configured, run_transaction_probe
from libs.db.repository import (
    IDEMPOTENCY_COLLECTION,
    SINGLETON_COLLECTIONS,
    STATE_COLLECTIONS,
    repo,
)
from libs.integrations import task_dispatcher
from libs.knowledge_retrieval import (
    canonical_standard_text,
    retrieval_quality_bias,
    standard_alias_candidate_matches,
    standard_alias_match_score,
    standard_alias_matches,
)

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
    assert "operationId" in payload
    assert "serverTime" in payload
    return payload["data"]


def assert_error(response, reason: str):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] != 0
    assert payload["data"]["reason"] == reason
    assert "operationId" in payload
    assert "serverTime" in payload
    return payload


def test_project_document_endpoints_use_detached_latest_read_view(monkeypatch) -> None:
    project_id = "P-2026-GDLNG-002"
    from libs.db.repository import InMemoryRepository

    view = InMemoryRepository()
    for state_key in (
        "documents",
        "versions",
        "bindings",
        "knowledge_files",
        "ocr_parse_results",
        "ocr_pipeline_runs",
        "ocr_stage_runs",
        "extracted_fields",
    ):
        view.state[state_key] = []
    view.state["documents"].append(
        {
            "id": "DOC-LATEST-VIEW",
            "projectId": project_id,
            "currentVersionId": "VER-LATEST-VIEW",
            "fileName": "latest.pdf",
            "currentOcrStatus": "已识别",
        }
    )
    view.state["versions"].append(
        {
            "id": "VER-LATEST-VIEW",
            "documentId": "DOC-LATEST-VIEW",
            "isCurrent": True,
        }
    )
    view.state["knowledge_files"].append(
        {
            "id": "KF-LATEST-VIEW",
            "projectId": project_id,
            "documentId": "DOC-LATEST-VIEW",
            "documentVersionId": "VER-LATEST-VIEW",
            "sliceStatus": "切片中",
            "vectorStatus": "待向量化",
        }
    )
    view.state["bindings"].append(
        {
            "id": "BIND-LATEST-VIEW",
            "projectId": project_id,
            "nodeId": 24,
            "documentId": "DOC-LATEST-VIEW",
            "documentVersionId": "VER-LATEST-VIEW",
        }
    )
    monkeypatch.setattr(repo, "project_document_read_view", lambda _project_id: view)

    documents = assert_ok(client.get(f"/projects/{project_id}/documents"))
    package = assert_ok(client.get(f"/projects/{project_id}/nodes/24/package"))

    assert [item["id"] for item in documents["items"]] == ["DOC-LATEST-VIEW"]
    assert [item["id"] for item in package["projectFiles"]] == ["DOC-LATEST-VIEW"]
    assert package["projectFiles"][0]["sliceStatus"] == "切片中"
    assert package["bindings"][0]["id"] == "BIND-LATEST-VIEW"


def allow_test_ai_dispatch(monkeypatch) -> None:
    from libs.business_pack import load_business_pack

    pack = load_business_pack("engineering_inspection_v1")
    monkeypatch.setitem(pack["atomicCheckToolBindingSet"], "lifecycleStatus", "published")
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


def admin_project_create_payload(code: str, name: str) -> dict[str, object]:
    return {
        "businessPackId": "engineering_inspection_v1",
        "code": code,
        "name": name,
        "type": "工业压力管道",
        "region": "华东",
        "ownerOrgName": "华东管网建设公司",
        "contractorOrgName": "粤海安装工程有限公司",
        "ndtOrgName": "粤检无损检测",
        "inspectionOrgName": "省特检院一部",
        "memberUserIds": {
            "owner": "USER-OWNER-001",
            "contractor": "USER-CONTRACTOR-001",
            "ndt": "USER-NDT-001",
            "inspection": "USER-INSPECTION-001",
        },
    }
def seed_confirmed_node_24_evidence(project_id: str = "P-2026-HDCP-001") -> list[str]:
    from libs.material_targeting import review_points_for_project

    project = repo.require_project(project_id)
    points = [
        point
        for point in review_points_for_project(repo, project, node_id=24)
        if point.get("requiredType") != "可选"
    ]
    evidence_ids: list[str] = []
    for index, point in enumerate(points, start=1):
        link_id = f"NEL-TEST-24-{index}"
        existing = repo.find_one("node_evidence_links", link_id)
        if existing:
            evidence_ids.append(link_id)
            continue
        is_certificate = point.get("materialTypeCode") == "welder_certificate"
        document_id = "DOC-20260625-001" if is_certificate else "DOC-20260625-002"
        version_id = "DV-20260625-001-V2" if is_certificate else "DV-20260625-002-V1"
        repo.state["node_evidence_links"].append(
            {
                "id": link_id,
                "projectId": project_id,
                "nodeId": 24,
                "nodeName": point.get("nodeName"),
                "reviewPointId": point.get("id"),
                "reviewContent": point.get("reviewContent"),
                "materialTypeCode": point.get("materialTypeCode"),
                "materialTypeName": point.get("materialTypeName"),
                "requiredType": point.get("requiredType"),
                "documentId": document_id,
                "documentVersionId": version_id,
                "fileName": "焊工资格证-王建国.pdf" if is_certificate else "焊工名册.xlsx",
                "pageNo": 1,
                "bbox": [10, 20, 180, 42],
                "fieldName": "证书编号" if is_certificate else "焊工姓名",
                "fieldId": "FIELD-24-001" if is_certificate else None,
                "quotedText": "TS6J-2024-03158" if is_certificate else "王建国 焊工名册",
                "matchedEvidenceItems": ["TS6J-2024-03158"] if is_certificate else ["王建国"],
                "supportStatus": "supported",
                "confidence": 0.96,
                "manualStatus": "confirmed",
                "manualStatusLabel": "已确认",
                "confirmedByName": "张工",
                "confirmedAt": "2026-07-08 00:00:00",
                "source": "test_confirmed_evidence",
                "createdAt": "2026-07-08 00:00:00",
            }
        )
        evidence_ids.append(link_id)
    return evidence_ids


def seed_reviewed_node_24(project_id: str = "P-2026-HDCP-001") -> list[str]:
    evidence_ids = seed_confirmed_node_24_evidence(project_id)
    repo.state["review_opinions"].insert(
        0,
        {
            "id": "OPN-TEST-24",
            "projectId": project_id,
            "nodeId": 24,
            "result": "满足要求",
            "opinion": "测试审查意见：已基于 confirmed 证据核验。",
            "riskLevel": "低",
            "closeStatus": "未关闭",
            "evidenceLinkIds": evidence_ids,
            "reviewerName": "张工",
            "createdAt": "2026-07-08 00:00:00",
        },
    )
    repo.set_node_status(project_id, 24, "已通过")
    return evidence_ids


def seed_report_scope(
    report_id: str = "RPT-20260625-001",
    project_id: str = "P-2026-HDCP-001",
    *,
    status: str = "复核中",
) -> list[str]:
    evidence_ids = seed_reviewed_node_24(project_id)
    report = repo.find_one("reports", report_id)
    assert report is not None
    rows = [item for item in repo.state["node_evidence_links"] if item.get("id") in set(evidence_ids)]
    report["status"] = status
    report["evidenceScope"] = {
        "schemaVersion": "report-evidence-scope-v1",
        "source": "test_confirmed_node_evidence",
        "nodeIds": [24],
        "evidenceLinkIds": evidence_ids,
        "evidenceLinks": rows,
    }
    report["evidenceValidation"] = {"schemaVersion": "report-evidence-validation-v1", "passed": True, "evidenceCount": len(rows)}
    report["sections"] = [
        {
            "key": "summary",
            "title": "检验结论",
            "content": "测试报告章节。",
            "evidenceLinkIds": evidence_ids[:1],
        }
    ]
    return evidence_ids


def mark_ndt_report_ready(report_id: str = "NDT-RPT-001") -> None:
    report = repo.find_one("ndt_reports", report_id)
    assert report is not None
    document = repo.find_one("documents", report["fileId"])
    assert document is not None
    document["currentOcrStatus"] = "已识别"
    version_id = document["currentVersionId"]
    report["detectionRatio"] = report.get("detectionRatio") or "10%"
    report["conclusion"] = report.get("conclusion") or "RT II 级合格。"
    existing = {item["id"] for item in repo.state["extracted_fields"]}
    for suffix, name, value, bbox in [
        ("REPORTNO", "报告编号", report["reportNo"], [10, 10, 180, 42]),
        ("RATIO", "检测比例", report["detectionRatio"], [190, 10, 280, 42]),
        ("LEVEL", "合格级别", "II 级", [290, 10, 360, 42]),
    ]:
        field_id = f"FIELD-{report_id}-{suffix}"
        if field_id not in existing:
            repo.state["extracted_fields"].append(
                {
                    "id": field_id,
                    "documentVersionId": version_id,
                    "fieldName": name,
                    "fieldValue": value,
                    "pageNo": 1,
                    "bbox": bbox,
                    "confidence": 0.95,
                    "reviewStatus": "已确认",
                }
            )


def test_response_envelope_and_api_prefix_compatibility() -> None:
    data = assert_ok(client.get("/workbench/projects?role=inspection"))
    prefixed = assert_ok(client.get("/api/workbench/projects?role=inspection"))
    contractor = assert_ok(client.get("/api/workbench/projects?role=contractor"))

    assert data[0]["id"] == "P-2026-HDCP-001"
    assert prefixed[0]["currentNodeId"] == 24
    assert prefixed[0]["riskLevel"] == "高"
    assert contractor[0]["id"] == "P-2026-GDLNG-002"
    assert contractor[0]["status"] != "已归档"


def test_business_role_project_visibility_matches_member_authorization() -> None:
    role_users = {
        "inspection": "USER-INSPECTION-001",
        "contractor": "USER-CONTRACTOR-001",
        "ndt": "USER-NDT-001",
        "owner": "USER-OWNER-001",
    }

    for role, user_id in role_users.items():
        projects = assert_ok(
            client.get(
                f"/api/workbench/projects?role={role}",
                headers={"X-Role": role, "X-User-Id": user_id},
            )
        )
        project_ids = {project["id"] for project in projects}
        authorized_members = [
            member
            for member in repo.state["project_members"]
            if member.get("userId") == user_id
            and member.get("role") == role
            and member.get("status") == "启用"
        ]
        authorized_project_ids = {member["projectId"] for member in authorized_members}
        node_scopes = {
            member["projectId"]: {int(node_id) for node_id in member.get("nodeScope") or []}
            for member in authorized_members
        }

        assert project_ids == authorized_project_ids
        for project in projects:
            assert int(project["currentNodeId"]) in node_scopes[project["id"]]
        if role == "inspection":
            assert project_ids == {project["id"] for project in repo.state["projects"]}
            for project in repo.state["projects"]:
                member = next(
                    item
                    for item in authorized_members
                    if item["projectId"] == project["id"]
                )
                project_node_ids = {
                    int(node["nodeId"])
                    for node in repo.state["tree_nodes"]
                    if node["projectId"] == project["id"]
                }
                assert project_node_ids.issubset({int(node_id) for node_id in member["nodeScope"]})

    assert "P-2026-GDLNG-002" in {
        project["id"]
        for project in assert_ok(
            client.get(
                "/api/workbench/projects?role=contractor",
                headers={"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"},
            )
        )
    }


def test_seed_compatibility_backfills_inspection_authorization_for_existing_projects() -> None:
    loaded = deepcopy(repo.state)
    loaded["project_members"] = [
        member
        for member in loaded["project_members"]
        if member.get("userId") != "USER-INSPECTION-001"
    ]

    changed = repo.apply_seed_compatibility_defaults(loaded)
    project_ids = {project["id"] for project in loaded["projects"]}
    inspection_project_ids = {
        member["projectId"]
        for member in loaded["project_members"]
        if member.get("userId") == "USER-INSPECTION-001"
        and member.get("role") == "inspection"
        and member.get("status") == "启用"
    }

    assert changed is True
    assert inspection_project_ids == project_ids


def test_seed_compatibility_authorizes_default_test_users_for_both_demo_projects() -> None:
    loaded = deepcopy(repo.state)
    test_user_ids = {
        "USER-INSPECTION-001",
        "USER-CONTRACTOR-001",
        "USER-NDT-001",
        "USER-OWNER-001",
    }
    test_project_ids = {"P-2026-HDCP-001", "P-2026-GDLNG-002"}
    loaded["project_members"] = [
        member
        for member in loaded["project_members"]
        if not (
            member.get("userId") in test_user_ids
            and member.get("projectId") in test_project_ids
        )
    ]

    changed = repo.apply_seed_compatibility_defaults(loaded)

    assert changed is True
    projects_by_id = {
        str(project.get("id")): project
        for project in loaded.get("projects", [])
        if str(project.get("id") or "") in test_project_ids
    }
    expected_org_by_role = {
        "inspection": lambda project: project.get("inspectionOrgName") or "省特检院一部",
        "contractor": lambda project: project.get("contractorOrgName") or "粤海安装工程有限公司",
        "ndt": lambda project: project.get("ndtOrgName") or "粤检无损检测",
        "owner": lambda project: project.get("ownerOrgName") or "华东管网建设公司",
    }
    for user_id in test_user_ids:
        memberships = [
            member
            for member in loaded["project_members"]
            if member.get("userId") == user_id
            and member.get("projectId") in test_project_ids
            and member.get("status") == "启用"
        ]
        assert {member["projectId"] for member in memberships} == test_project_ids
        assert all(member.get("nodeScope") for member in memberships)
        for member in memberships:
            project = projects_by_id[str(member["projectId"])]
            role = str(member.get("role") or "")
            assert member.get("orgName") == expected_org_by_role[role](project)


def test_healthz_reports_runtime_flags(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "false")
    repo.postgres_enabled = True

    health = assert_ok(client.get("/api/healthz"))

    assert health["service"] == "api-service"
    assert health["authRequired"] is True
    assert health["demoUsersEnabled"] is False
    assert health["postgresTransactions"] is True
    assert "objectStorageEnabled" in health


def test_readyz_is_public_minimal_and_fail_closed(monkeypatch) -> None:
    from apps.api import main as api_main

    async def ready_health():
        return {
            "databaseConnected": True,
            "securityReady": True,
            "runtimeReady": True,
            "workflowReady": True,
        }

    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setattr(api_main, "health_payload", ready_health)
    monkeypatch.setattr(api_main, "database_schema_readiness", lambda: {"schema": True, "auditAnchor": True})

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "ready": True,
        "authRequired": True,
        "checks": {
            "database": True,
            "security": True,
            "runtime": True,
            "workflow": True,
            "schema": True,
            "auditAnchor": True,
        },
    }

    monkeypatch.setattr(api_main, "database_schema_readiness", lambda: {"schema": False, "auditAnchor": True})
    blocked = client.get("/api/readyz")
    assert blocked.status_code == 503
    assert blocked.json()["ready"] is False


def test_local_role_bootstrap_creates_login_accounts_without_postgres(monkeypatch) -> None:
    passwords = {
        "admin": "Local!2026-SystemZ",
        "inspection": "Local!2026-InspectZ",
        "contractor": "Local!2026-BuildZ",
        "ndt": "Local!2026-TestZ",
        "owner": "Local!2026-ViewZ",
    }
    existing_member = {
        "id": "PM-GDLNG-CONTRACTOR",
        "projectId": "P-2026-GDLNG-002",
        "userId": "USER-CONTRACTOR-001",
        "role": "contractor",
        "nodeScope": [1, 2, 16, 40],
        "actions": ["document:upload"],
        "expiresAt": None,
        "enabled": True,
    }
    repo.state["project_members"].append(existing_member)
    monkeypatch.setenv("AICHECK_BOOTSTRAP_LOCAL_ROLES", "true")
    for role, password in passwords.items():
        monkeypatch.setenv(f"AICHECK_BOOTSTRAP_PASSWORD_{role.upper()}", password)

    bootstrap_local_roles_if_configured()

    assert {user["username"] for user in repo.state["users"]} >= set(passwords)
    assert {member["role"] for member in repo.state["project_members"]} >= set(passwords)
    assert any(
        member["id"] == existing_member["id"] and member["nodeScope"] == existing_member["nodeScope"]
        for member in repo.state["project_members"]
    )
    for role, password in passwords.items():
        result = assert_ok(client.post("/api/auth/login", json={"username": role, "password": password}))
        assert result["user"]["role"] == role
        assert result["user"]["defaultPath"]


def test_postgres_transaction_probe_endpoint_is_admin_only_when_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    contractor = assert_ok(client.post("/api/auth/login", json={"username": "contractor", "password": "contractor"}))
    admin = assert_ok(client.post("/api/auth/login", json={"username": "admin", "password": "admin"}))

    assert_error(
        client.get(
            "/api/system/postgres-transaction-probe",
            headers={"Authorization": f"Bearer {contractor['token']}"},
        ),
        "FORBIDDEN",
    )
    result = assert_ok(
        client.get(
            "/api/system/postgres-transaction-probe",
            headers={"Authorization": f"Bearer {admin['token']}"},
        )
    )

    assert result["postgresEnabled"] is False
    assert result["transactionProbe"] == "skipped"


def test_postgres_transaction_probe_does_not_bool_check_database(monkeypatch) -> None:
    class BoolRaisingDsn(str):
        def __bool__(self) -> bool:
            raise NotImplementedError("DSN objects do not implement truth value testing")

    async def fake_probe(dsn):
        assert isinstance(dsn, BoolRaisingDsn)
        return {"postgresEnabled": True, "transactionsConfigured": True, "transactionProbe": "pass"}

    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setattr(app.state, "postgres", BoolRaisingDsn("postgresql://example"), raising=False)
    monkeypatch.setattr("apps.api.main.run_transaction_probe", fake_probe)
    admin = assert_ok(client.post("/api/auth/login", json={"username": "admin", "password": "admin"}))

    result = assert_ok(
        client.get(
            "/api/system/postgres-transaction-probe",
            headers={"Authorization": f"Bearer {admin['token']}"},
        )
    )

    assert result["transactionProbe"] == "pass"


def test_ocr_healthz_reports_pipeline_flags(monkeypatch) -> None:
    from apps.ocr_service.main import app as ocr_app

    monkeypatch.setenv("AICHECK_OCR_ALLOW_PLACEHOLDER", "false")
    ocr_client = TestClient(ocr_app)
    health = assert_ok(ocr_client.get("/healthz"))

    assert health["service"] == "ocr-service"
    assert "pipelineAvailable" in health
    assert "pipelineBackend" in health
    assert health["placeholderAllowed"] is False


def test_ocr_runtime_doctor_reports_dependency_contract(monkeypatch) -> None:
    from apps.ocr_service.main import app as ocr_app

    monkeypatch.delenv("AICHECK_OCR_SUBPROCESS_PYTHON", raising=False)
    ocr_client = TestClient(ocr_app)
    report = assert_ok(ocr_client.get("/internal/ocr/doctor"))

    assert report["schemaVersion"] == "aicheck-ocr-runtime-doctor-v1"
    assert {"pass", "warn", "fail", "total"} <= set(report["summary"])
    names = {item["name"] for item in report["checks"]}
    assert "package.cv2" in names
    assert "subprocess.python" in names
    assert "preprocess.variants" in names
    assert "policy.placeholder-disabled" in names


def test_ocr_runtime_doctor_recommends_discovered_local_ocr_env(monkeypatch, tmp_path) -> None:
    from apps.ocr_service import runtime_doctor

    root = tmp_path / "agentdesign"
    python_bin = root / ".venv-ocr311" / "bin" / "python"
    python_bin.parent.mkdir(parents=True)
    python_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    model_base = root / ".paddlex-cache" / "official_models"
    for model_name in [
        "PP-OCRv6_medium_det",
        "PP-OCRv6_medium_rec",
        "PP-OCRv4_server_seal_det",
        "PP-OCRv4_server_rec",
        "PP-DocLayout-L",
        "PP-DocLayoutV3",
        "PaddleOCR-VL-1.6",
    ]:
        (model_base / model_name).mkdir(parents=True)
    docling_dir = root / "docling"
    docling_dir.mkdir()
    (docling_dir / "model.bin").write_text("local-docling-artifact", encoding="utf-8")

    monkeypatch.setenv("AICHECK_AGENTDESIGN_HOST_PATH", str(root))
    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", str(python_bin))
    monkeypatch.delenv("AICHECK_PADDLEX_MODEL_CACHE", raising=False)
    monkeypatch.setattr(
        runtime_doctor,
        "check_subprocess_packages",
        lambda _python_bin, packages: {name: True for name in packages},
    )

    report = runtime_doctor.build_runtime_doctor(
        engine_status=[],
        model_manifest={"modelDirs": {}},
        offline_only=True,
        network_disabled=True,
        placeholder_allowed=False,
    )

    assert report["recommendedEnv"]["AICHECK_OCR_SUBPROCESS_PYTHON"] == str(python_bin)
    assert report["recommendedEnv"]["AICHECK_PADDLEOCR_DET_MODEL_DIR"] == str(model_base / "PP-OCRv6_medium_det")
    assert report["recommendedEnv"]["AICHECK_SEAL_DET_MODEL_DIR"] == str(model_base / "PP-OCRv4_server_seal_det")
    assert report["recommendedEnv"]["AICHECK_PPSTRUCTURE_LAYOUT_MODEL_DIR"] == str(model_base / "PP-DocLayout-L")
    assert report["recommendedEnv"]["AICHECK_PADDLEOCR_VL_REC_MODEL_DIR"] == str(model_base / "PaddleOCR-VL-1.6")
    assert report["recommendedEnv"]["DOCLING_ARTIFACTS_PATH"] == str(docling_dir)
    assert report["discovered"]["doclingArtifacts"][0]["fileCount"] == 1
    assert report["discovered"]["subprocessPythonCandidates"][0]["usable"] is True
    checks_by_name = {item["name"]: item for item in report["checks"]}
    assert checks_by_name["subprocess.python"]["status"] == "pass"
    assert checks_by_name["package.paddleocr"]["status"] in {"pass", "warn"}
    assert checks_by_name["package.paddleocr"]["data"]["subprocessCovered"] is True
    assert checks_by_name["preprocess.variants"]["status"] == "pass"


def test_piping_raw_cells_mapping_extracts_business_columns() -> None:
    from apps.ocr_service.service import map_piping_row

    mapped = map_piping_row(
        {
            "pipeNo": "PL8302",
            "rawCells": [
                "2",
                "PL8302",
                "DN100",
                "MIB",
                "1",
                "Φ108x4",
                "化工品",
                "(丙醇",
                "液体",
                "易燃易爆",
                "装车鹤管",
                "F8301A",
                "V8301",
                "Y-02",
                "常温",
                "0.01",
                "50",
                "0.1",
                "水",
                "0.150",
                "空气",
                "0.1",
                "RT",
                "10%",
                "III",
                "AB",
            ],
        }
    )

    assert mapped["pipeNo"] == "PL8302"
    assert mapped["nominalDiameter"] == "DN100"
    assert mapped["outerDiameterThickness"] == "Φ108x4"
    assert mapped["mediumName"] == "化工品(丙醇"
    assert mapped["pAndId"] == "Y-02"
    assert mapped["designPressure"] == "0.1"
    assert mapped["weldDetectionMethod"] == "RT"
    assert mapped["weldDetectionScale"] == "10%"
    assert mapped["eligibleLevel"] == "III"
    assert mapped["ranking"] == "AB"


def test_piping_continuation_row_inherits_pipe_no_and_normalizes_values() -> None:
    from apps.ocr_service.service import map_piping_row

    mapped = map_piping_row(
        {
            "pipeNo": "PL8303",
            "isContinuation": True,
            "sourceRowIndex": 7,
            "rawCells": [
                "4",
                "DN80",
                "MIB",
                "GC2",
                "089x4",
                "化工品",
                "(丙醇",
                "液体",
                "易燃易爆",
                "P8301A",
                "四区交换站",
                "Y-02",
                "常温",
                "常温",
                "0.5",
                "0.5",
                "50",
                "50",
                "0.55",
                "水",
                "0.825",
                "空气",
                "0.55",
                "RT",
                "10%",
                "III",
                "AB",
            ],
        }
    )

    assert mapped["pipeNo"] == "PL8303"
    assert mapped["isContinuation"] == "true"
    assert mapped["sourceRowIndex"] == "7"
    assert mapped["nominalDiameter"] == "DN80"
    assert mapped["outerDiameterThickness"] == "Φ89x4"
    assert mapped["operatingPressure"] == "0.5"
    assert mapped["designTemperature"] == "50"
    assert mapped["designPressure"] == "0.55"


def test_piping_visual_seal_priority_prefers_bottom_right_red_candidate() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = {
        "status": "success",
        "fields": [],
        "tables": [],
        "seals": [
            {
                "sealId": "blue_title_block",
                "sealName": "视觉蓝章候选",
                "visualColor": "blue",
                "bbox": [2800, 500, 3400, 800],
                "pageWidth": 4000,
                "pageHeight": 3000,
                "visualConfidence": 0.95,
                "ocrConfidence": 0.0,
                "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
            },
            {
                "sealId": "red_license",
                "sealName": "视觉印章候选",
                "visualColor": "red",
                "bbox": [2600, 2100, 3400, 2750],
                "pageWidth": 4000,
                "pageHeight": 3000,
                "visualConfidence": 0.7,
                "ocrConfidence": 0.0,
                "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
            },
        ],
    }

    fused = fuse_parse_result(result, profile=profile_for("piping_characteristic_list_v1"))

    assert fused["seals"][0]["sealId"] == "red_license"
    assert fused["seals"][0]["visualRankScore"] > fused["seals"][1]["visualRankScore"]
    assert fused["quality"]["status"] == "needs_human_review"
    assert "SEAL_TEXT_LOW_CONFIDENCE" in fused["quality"]["reasons"]


def test_visual_seal_candidates_do_not_create_business_fields() -> None:
    from apps.ocr_service.service import fields_from_seals

    fields = fields_from_seals(
        [
            {
                "sealId": "red_candidate",
                "pageNo": 1,
                "bbox": [1, 2, 3, 4],
                "fields": [{"fieldName": "印章颜色", "fieldValue": "red", "confidence": 0.8}],
                "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
            }
        ]
    )

    assert fields == []


def test_visual_seal_candidate_enriched_from_ocr_fragments_requires_crop_ocr_for_required_seal() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    required_fields = [
        "company_name",
        "project_name",
        "document_title",
        "drawing_no",
        "design_phase",
        "pipe_no",
    ]
    fused = fuse_parse_result(
        {
            "status": "success",
            "fragments": [
                {
                    "text": "压力管道",
                    "confidence": 0.99,
                    "bbox": [4378, 2466, 4730, 2569],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
                {
                    "text": "杨道红",
                    "confidence": 0.99,
                    "bbox": [4428, 2540, 4685, 2626],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
                {
                    "text": "TS1810648-2021",
                    "confidence": 0.99,
                    "bbox": [4362, 2605, 4758, 2688],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
                {
                    "text": "2017年8月31日",
                    "confidence": 0.99,
                    "bbox": [4361, 2660, 4768, 2753],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
            ],
            "fields": [
                {
                    "fieldCode": code,
                    "fieldName": code,
                    "fieldValue": {
                        "company_name": "广东星燃石化设计院有限公司",
                        "project_name": "项目",
                        "document_title": "管道特性表",
                        "drawing_no": "QX201903S-13-Y-07",
                        "design_phase": "施工图",
                        "pipe_no": "PL8301",
                    }[code],
                    "confidence": 0.9,
                    "bbox": [1, 1, 2, 2],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                }
                for code in required_fields
            ],
            "tables": [
                {
                    "tableId": "grid",
                    "businessSchema": "piping_characteristic_table_v1",
                    "sourceEngine": "opencv_grid_text_aligned",
                    "bbox": [1, 1, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                    "structureConfidence": 0.9,
                    "normalizedRows": [{"pipeNo": "PL8301"}],
                }
            ],
            "seals": [
                {
                    "sealId": "visual_red",
                    "sealName": "视觉印章候选",
                    "visualColor": "red",
                    "bbox": [4141, 2364, 4981, 2879],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                    "pageWidth": 5712,
                    "pageHeight": 3213,
                    "visualConfidence": 0.95,
                    "ocrConfidence": 0.0,
                    "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
                }
            ],
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    seal = fused["seals"][0]
    assert seal["sourceEngine"] == "fragment_seal_text_fusion"
    assert seal["sealType"] == "design_license_seal"
    assert "TS1810648-2021" in seal["sealName"]
    assert "fragment_seal_text" in seal["qualityFlags"]
    assert "visual_candidate_only" in seal["qualityFlags"]
    assert seal["candidateOnly"] is True
    assert seal["canSatisfyRequiredSeal"] is False
    assert "SEAL_TEXT_LOW_CONFIDENCE" in fused["quality"]["reasons"]
    assert fused["quality"]["matchedSealTypes"] == []
    assert "design_license_seal" in fused["quality"]["missingExpectedSealTypes"]
    assert fused["quality"]["sealCompleteness"] == 0.0
    assert fused["quality"]["status"] == "needs_human_review"


def test_visual_red_design_license_seal_text_fields_are_structured() -> None:
    from apps.ocr_service.seal_text import extract_structured_seal_fields_from_lines

    fields = extract_structured_seal_fields_from_lines(
        [
            ("压力管道", 0.91),
            ("杨道红", 0.86),
            ("TS1810648-2021", 0.93),
            ("2017年8月31日", 0.9),
            ("广东星燃石化设计院有限公司", 0.58),
        ],
        [191, 758, 593, 1005],
    )
    values = {field["fieldName"]: field["fieldValue"] for field in fields}

    assert values["印章名称"] == "特种设备设计许可印章"
    assert values["许可项目"] == "压力管道"
    assert values["许可人员"] == "杨道红"
    assert values["许可证编号"] == "TS1810648-2021"
    assert values["日期"] == "2017年8月31日"
    assert values["单位名称"] == "广东星燃石化设计院有限公司"
    assert "杨道红" in values["识别文字"]


def test_visual_red_seal_unit_name_reconciles_with_document_organization_fragment() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    fused = fuse_parse_result(
        {
            "status": "success",
            "fragments": [
                {
                    "text": "广东星燃石化设计院有限公司",
                    "confidence": 0.96,
                    "bbox": [250, 36, 610, 82],
                    "pageNo": 1,
                }
            ],
            "fields": [],
            "tables": [],
            "seals": [
                {
                    "sealId": "red_candidate",
                    "sealName": "特种设备设计许可印章",
                    "sealType": "visual_red_seal_candidate",
                    "visualColor": "red",
                    "ocrConfidence": 0.91,
                    "bbox": [201, 796, 624, 1057],
                    "fields": [
                        {"fieldName": "单位名称", "fieldValue": "广东星燃石化设中股有限公司", "confidence": 0.74},
                        {"fieldName": "单位名称", "fieldValue": "广东星衡石化设计股有限公司", "confidence": 0.73},
                        {"fieldName": "许可证编号", "fieldValue": "TS1810648-2021", "confidence": 0.92},
                    ],
                    "qualityFlags": ["visual_candidate_only", "seal_text_from_crop_ocr"],
                }
            ],
        },
        profile={"profileId": "seal-test", "sealRules": {"required": False}},
    )

    unit_fields = [
        field
        for field in fused["seals"][0]["fields"]
        if field.get("fieldName") == "单位名称"
    ]
    assert len(unit_fields) == 1
    assert unit_fields[0]["fieldValue"] == "广东星燃石化设计院有限公司"
    assert unit_fields[0]["originalFieldValue"] == "广东星燃石化设中股有限公司"


def test_fragment_text_can_create_drawing_approval_seal_without_visual_candidate() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    fused = fuse_parse_result(
        {
            "status": "success",
            "fragments": [
                {"text": "广东省建设工程勘察设计出图专用章", "confidence": 0.94, "bbox": [4382, 1927, 5230, 1989]},
                {"text": "单位名称：广东星燃石化设计院有限公司", "confidence": 0.94, "bbox": [4388, 2001, 5257, 2059]},
                {"text": "项目范围：压力管道设计", "confidence": 0.9, "bbox": [4388, 2070, 5257, 2130]},
            ],
            "fields": [],
            "tables": [],
            "seals": [],
        },
        profile={
            "profileId": "drawing_seal_profile",
            "sealRules": {"required": True, "expectedSealTypes": ["drawing_approval_seal"]},
        },
    )

    assert fused["seals"]
    assert fused["seals"][0]["sealType"] == "drawing_approval_seal"
    assert fused["seals"][0]["sourceEngine"] == "fragment_seal_text_detector"
    assert "text_only_seal_candidate" in fused["seals"][0]["qualityFlags"]
    assert fused["quality"]["matchedSealTypes"] == ["drawing_approval_seal"]
    assert fused["quality"]["missingExpectedSealTypes"] == []


def test_agentdesign_seal_payload_normalizes_to_readable_formal_seal() -> None:
    from apps.ocr_service.engines import normalize_agentdesign_seal_result
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    seals = normalize_agentdesign_seal_result(
        {
            "seals": [
                {
                    "seal_result_id": "seal_result_1",
                    "page_index": 1,
                    "polygon": [[4041, 2264], [5081, 2264], [5081, 2979], [4041, 2979]],
                    "decision": "REVIEW",
                    "fields": {
                        "organization_name": {
                            "value": "广东星燃石化设计院有限公司",
                            "calibrated_confidence": 0.92,
                        },
                        "seal_type": {
                            "value": "特种设备设计许可印章",
                            "calibrated_confidence": 0.86,
                        },
                        "valid_until": {
                            "value": "2024年6月21日",
                            "calibrated_confidence": 0.93,
                        },
                    },
                    "audit_trace": {"candidate": {"candidate_type": "red_round_seal"}},
                }
            ]
        }
    )

    fused = fuse_parse_result(
        {
            "status": "success",
            "fields": [],
            "tables": [],
            "seals": seals,
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    assert fused["seals"][0]["sealType"] == "special_equipment_design_permit_seal"
    assert "广东星燃石化设计院有限公司" in fused["seals"][0]["sealName"]
    assert fused["seals"][0]["ocrConfidence"] >= 0.86
    assert fused["quality"]["matchedSealTypes"] == ["design_license_seal"]
    assert fused["quality"]["missingExpectedSealTypes"] == []
    assert "SEAL_TEXT_LOW_CONFIDENCE" not in fused["quality"]["reasons"]


def test_ocr_fusion_wrong_formal_seal_type_requires_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [{"fieldCode": "report_no", "fieldValue": "RT-1", "confidence": 0.9, "bbox": [0, 0, 10, 10]}],
            "tables": [],
            "seals": [
                {
                    "sealId": "company",
                    "sealName": "某某有限公司公章",
                    "sealType": "company_official_seal",
                    "ocrConfidence": 0.9,
                    "bbox": [0, 0, 10, 10],
                }
            ],
        },
        profile={
            "profileId": "seal_type_profile_v1",
            "documentType": "ndt_report",
            "requiredFields": ["report_no"],
            "requiredTables": [],
            "sealRules": {"required": True, "expectedSealTypes": ["inspection_testing_seal"]},
            "qualityRules": {"minFieldConfidence": 0.75, "criticalConflictFields": []},
        },
    )

    assert result["quality"]["status"] == "needs_human_review"
    assert "EXPECTED_SEAL_TYPE_MISSING" in result["quality"]["reasons"]
    assert result["quality"]["matchedSealTypes"] == []
    assert result["quality"]["missingExpectedSealTypes"] == ["inspection_testing_seal"]
    assert result["quality"]["sealCompleteness"] == 0.0


def test_formal_agentdesign_seal_beats_overlapping_visual_candidate() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    fused = fuse_parse_result(
        {
            "status": "success",
            "fields": [],
            "tables": [],
            "seals": [
                {
                    "sealId": "visual_red",
                    "sealName": "视觉印章候选",
                    "visualColor": "red",
                    "bbox": [4040, 2260, 5080, 2980],
                    "pageWidth": 5712,
                    "pageHeight": 3213,
                    "visualConfidence": 0.95,
                    "ocrConfidence": 0.0,
                    "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
                },
                {
                    "sealId": "formal_red",
                    "sealName": "石化设计院有限公司 特种设备设计许可印章",
                    "sealType": "special_equipment_design_permit_seal",
                    "bbox": [4041, 2264, 5081, 2979],
                    "ocrConfidence": 0.86,
                    "qualityFlags": ["agentdesign_seal_ocr", "review_required"],
                    "fields": [
                        {
                            "fieldCode": "seal_type",
                            "fieldName": "seal_type",
                            "fieldValue": "特种设备设计许可印章",
                            "confidence": 0.86,
                        }
                    ],
                },
            ],
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    assert len(fused["seals"]) == 1
    assert fused["seals"][0]["sealId"] == "formal_red"


def test_piping_grid_aligned_table_is_not_flagged_as_heuristic() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.service import align_piping_text_table_with_grid
    from libs.ocr.profiles import profile_for

    text_table = {
        "tableId": "piping_characteristic_table_1",
        "sourceEngine": "heuristic_table_from_ocr_fragments",
        "bbox": [800, 600, 5100, 3000],
        "rows": 10,
        "columns": 30,
        "structureConfidence": 0.78,
        "qualityFlags": ["heuristic_table_fallback"],
        "normalizedRows": [
            {
                "pipeNo": "PL8301",
                "rawCells": ["1", "PL8301", "DN100", "MIB", "Φ108x4", "化工品", "液体", "Y-02", "常温", "0.01", "50", "0.1", "RT", "10%"],
            }
        ],
        "businessRows": [
            {
                "pipeNo": "PL8301",
                "nominalDiameter": "DN100",
                "designPressure": "0.1",
                "weldDetectionMethod": "RT",
            }
        ],
    }
    grid_table = {
        "tableId": "opencv_grid_table_1",
        "sourceEngine": "opencv_table_grid_subprocess",
        "bbox": [790, 590, 5120, 3020],
        "rows": 32,
        "columns": 44,
        "gridCellCount": 1408,
        "gridLineXs": [790, 900, 1020],
        "gridLineYs": [590, 650, 710],
        "structureConfidence": 0.91,
    }

    aligned = align_piping_text_table_with_grid(text_table, grid_table)
    fused = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "company_name", "fieldValue": "A", "confidence": 0.9, "bbox": [1, 1, 2, 2]},
                {"fieldCode": "project_name", "fieldValue": "B", "confidence": 0.9, "bbox": [1, 1, 2, 2]},
                {"fieldCode": "document_title", "fieldValue": "管道特性表", "confidence": 0.9, "bbox": [1, 1, 2, 2]},
                {"fieldCode": "drawing_no", "fieldValue": "QX201903S-13-Y-07", "confidence": 0.9, "bbox": [1, 1, 2, 2]},
                {"fieldCode": "design_phase", "fieldValue": "施工图", "confidence": 0.9, "bbox": [1, 1, 2, 2]},
                {"fieldCode": "pipe_no", "fieldValue": "PL8301", "confidence": 0.9, "bbox": [1, 1, 2, 2]},
            ],
            "tables": [aligned],
            "seals": [
                {
                    "sealId": "formal",
                    "sealName": "广东星燃石化设计院有限公司 特种设备设计许可印章",
                    "sealType": "special_equipment_design_permit_seal",
                    "bbox": [1, 1, 2, 2],
                    "ocrConfidence": 0.9,
                    "qualityFlags": ["agentdesign_seal_ocr", "review_required"],
                }
            ],
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    assert aligned["sourceEngine"] == "opencv_grid_text_aligned"
    assert "heuristic_table_fallback" not in aligned["qualityFlags"]
    assert "TABLE_HEURISTIC_REVIEW_REQUIRED" not in fused["quality"]["reasons"]


def test_ocr_parse_rejects_missing_storage_key() -> None:
    from apps.ocr_service.main import app as ocr_app

    ocr_client = TestClient(ocr_app)
    payload = ocr_client.post("/internal/ocr/parse", json={}).json()

    assert payload["code"] != 0
    assert payload["data"]["reason"] == "VALIDATION_ERROR"
    assert "operationId" in payload
    assert "serverTime" in payload


def test_ocr_document_parse_job_lifecycle(monkeypatch) -> None:
    from apps.ocr_service.main import app as ocr_app
    from apps.ocr_service.main import ocr_service as app_ocr_service

    def fake_parse_document(storage_key: str, **kwargs):
        return {
            "parseResultId": "PARSE-TEST",
            "storageKey": storage_key,
            "fileName": kwargs.get("file_name"),
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "job ok", "confidence": 1.0}],
            "fields": [],
            "diagnostics": [],
            "engineRuns": [{"engine": "test", "status": "success"}],
        }

    monkeypatch.setattr(app_ocr_service, "parse_document", fake_parse_document)
    ocr_client = TestClient(ocr_app)

    created = assert_ok(
        ocr_client.post(
            "/internal/document-parse/jobs",
            json={
                "storageKey": "minio://documents/job.pdf",
                "fileName": "job.pdf",
                "profileId": "quality_certificate_v1",
            },
        )
    )
    job = assert_ok(ocr_client.get(f"/internal/document-parse/jobs/{created['jobId']}"))

    assert job["status"] == "success"
    assert job["parseResultId"] == "PARSE-TEST"
    result = assert_ok(ocr_client.get("/internal/document-parse/results/PARSE-TEST"))
    assert result["fragments"][0]["text"] == "job ok"
    retry = assert_ok(ocr_client.post(f"/internal/document-parse/jobs/{created['jobId']}/retry"))
    assert retry["retryOfJobId"] == created["jobId"]


def test_ocr_normalize_preserves_zero_values() -> None:
    from apps.ocr_service.service import normalize_ocr_result

    result = normalize_ocr_result(
        {
            "text": "zero",
            "fields": [
                {
                    "fieldName": "zero_field",
                    "fieldValue": 0,
                    "page_index": 0,
                    "bbox": [0, 0, 1, 1],
                    "confidence": 0,
                }
            ],
        },
        "minio://documents/zero.pdf",
        "zero.pdf",
    )

    assert result["fields"][0]["fieldValue"] == "0"
    assert result["fields"][0]["confidence"] == 0


def test_ocr_normalize_does_not_invent_missing_confidence() -> None:
    from apps.ocr_service.service import normalize_ocr_result

    result = normalize_ocr_result(
        {
            "text": "plain fallback text",
            "fields": [{"fieldName": "missing_conf_field", "fieldValue": "A", "bbox": [0, 0, 1, 1]}],
            "seals": [{"sealName": "未知置信印章", "bbox": [1, 2, 3, 4], "fields": [{"fieldName": "seal_text", "fieldValue": "未知置信印章"}]}],
        },
        "minio://documents/missing-confidence.pdf",
        "missing-confidence.pdf",
    )

    assert result["fragments"][0]["confidence"] == 0
    assert result["fields"][0]["confidence"] == 0
    assert result["fields"][1]["confidence"] == 0
    assert result["seals"][0]["visualConfidence"] == 0
    assert result["seals"][0]["ocrConfidence"] == 0


def test_ocr_normalize_does_not_treat_seal_summary_as_text() -> None:
    from apps.ocr_service.service import has_parse_content, normalize_ocr_result

    result = normalize_ocr_result(
        {
            "ok": True,
            "document_summary": {"page_count": 1, "candidate_count": 0},
            "candidate_summary": {"total": 0, "candidates": []},
            "diagnostics": [{"code": "NO_SEAL_CANDIDATE", "message": "no seal candidate selected for OCR"}],
        },
        "minio://documents/seal-summary-only.png",
        "seal-summary-only.png",
    )

    assert result["status"] == "success"
    assert result["fragments"] == []
    assert result["fields"] == []
    assert result["seals"] == []
    assert has_parse_content(result) is False


def test_piping_profile_infers_table_and_fields_from_fragments() -> None:
    from apps.ocr_service.service import enrich_parse_result
    from libs.ocr.profiles import profile_for

    fragments = [
        {"pageNo": 1, "text": "广东星燃石化设计院有限公司", "bbox": [100, 20, 450, 60], "confidence": 0.94},
        {"pageNo": 1, "text": "管道特性表", "bbox": [600, 60, 760, 100], "confidence": 0.96},
        {"pageNo": 1, "text": "PIPING CHARACTERISTIC LIST", "bbox": [590, 105, 850, 130], "confidence": 0.92},
        {"pageNo": 1, "text": "项目名称 珠海恒基达鑫国际化工仓储股份有限公司二期装车站新增项目", "bbox": [80, 140, 700, 175], "confidence": 0.9},
        {"pageNo": 1, "text": "图纸编号 QX201903S-13-Y-0", "bbox": [880, 140, 1120, 175], "confidence": 0.9},
        {"pageNo": 1, "text": "设计阶段 施工图", "bbox": [880, 178, 1050, 210], "confidence": 0.9},
        {"pageNo": 1, "text": "序号", "bbox": [50, 260, 90, 280], "confidence": 0.9},
        {"pageNo": 1, "text": "管道代号", "bbox": [110, 260, 180, 280], "confidence": 0.9},
        {"pageNo": 1, "text": "公称直径", "bbox": [200, 260, 280, 280], "confidence": 0.9},
        {"pageNo": 1, "text": "介质", "bbox": [300, 260, 360, 280], "confidence": 0.9},
        {"pageNo": 1, "text": "起点", "bbox": [390, 260, 450, 280], "confidence": 0.9},
        {"pageNo": 1, "text": "1", "bbox": [55, 300, 75, 320], "confidence": 0.9},
        {"pageNo": 1, "text": "PL8301", "bbox": [110, 300, 175, 320], "confidence": 0.91},
        {"pageNo": 1, "text": "DN100", "bbox": [200, 300, 260, 320], "confidence": 0.91},
        {"pageNo": 1, "text": "液体", "bbox": [300, 300, 345, 320], "confidence": 0.91},
        {"pageNo": 1, "text": "E8301A", "bbox": [390, 300, 455, 320], "confidence": 0.91},
        {"pageNo": 1, "text": "2", "bbox": [55, 340, 75, 360], "confidence": 0.9},
        {"pageNo": 1, "text": "VT8301", "bbox": [110, 340, 175, 360], "confidence": 0.91},
        {"pageNo": 1, "text": "DN50", "bbox": [200, 340, 250, 360], "confidence": 0.91},
        {"pageNo": 1, "text": "气相", "bbox": [300, 340, 345, 360], "confidence": 0.91},
        {"pageNo": 1, "text": "放空", "bbox": [390, 340, 435, 360], "confidence": 0.91},
    ]

    result = enrich_parse_result(
        {
            "status": "success",
            "storageKey": "/tmp/piping.png",
            "fileName": "piping.png",
            "fragments": fragments,
            "fields": [],
            "tables": [],
            "seals": [
                {
                    "sealId": "fragment_seal",
                    "sealName": "压力管道 杨道红 TS1810648-2021",
                    "sealType": "design_license_seal",
                    "sourceEngine": "fragment_seal_text_fusion",
                    "ocrConfidence": 0.88,
                    "qualityFlags": ["fragment_seal_text"],
                },
                {
                    "sealId": "visual_candidate",
                    "sealName": "视觉印章候选",
                    "sealType": "visual_red_seal_candidate",
                    "visualConfidence": 0.92,
                    "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
                },
                {
                    "sealId": "missing_evidence",
                    "sealName": "测试单位章",
                    "ocrConfidence": 0.72,
                    "qualityFlags": ["seal_evidence_missing"],
                },
            ],
            "diagnostics": [],
        },
        profile=profile_for("piping_characteristic_list_v1"),
        document_version_id="docv_test",
        business_pack_id="engineering_inspection_v1",
        model_manifest={},
    )

    field_codes = {field["fieldCode"] for field in result["fields"]}
    assert result["tables"][0]["tableId"] == "page_1_piping_characteristic_table_1"
    assert result["tables"][0]["normalizedRows"][0]["pipeNo"] == "PL8301"
    assert "HEURISTIC_TABLE_INFERRED" in {item["code"] for item in result["diagnostics"] if isinstance(item, dict)}
    assert {"company_name", "project_name", "document_title", "drawing_no", "design_phase", "pipe_no"} <= field_codes


def test_piping_profile_maps_formal_table_rows_to_business_fields() -> None:
    from apps.ocr_service.service import enrich_parse_result
    from libs.ocr.profiles import profile_for

    result = enrich_parse_result(
        {
            "status": "success",
            "storageKey": "/tmp/piping-formal.png",
            "fileName": "piping-formal.png",
            "fragments": [
                {"pageNo": 1, "text": "管道特性表", "bbox": [0, 0, 100, 20], "confidence": 0.95},
                {"pageNo": 1, "text": "图纸编号 QX201903S-13-Y-07", "bbox": [0, 30, 200, 50], "confidence": 0.9},
                {"pageNo": 1, "text": "设计阶段 施工图", "bbox": [0, 60, 200, 80], "confidence": 0.9},
            ],
            "fields": [
                {"fieldCode": "company_name", "fieldName": "公司名称", "fieldValue": "广东星燃石化设计院有限公司", "confidence": 0.9},
                {"fieldCode": "project_name", "fieldName": "项目名称", "fieldValue": "项目", "confidence": 0.9},
            ],
            "tables": [
                {
                    "tableId": "table_1",
                    "pageNo": 1,
                    "bbox": [0, 100, 400, 240],
                    "rows": 3,
                    "columns": 5,
                    "cells": [],
                    "normalizedRows": [
                        {"管道代号": "PL8301", "公称直径": "DN100", "介质名称": "化工品", "设计压力": "0.1", "检测方法": "RT"},
                        {"管道代号": "VT8301", "公称直径": "DN50", "介质名称": "气相", "设计压力": "0.55", "检测方法": "RT"},
                    ],
                    "sourceEngine": "pp_structure_v3",
                    "structureConfidence": 0.91,
                }
            ],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile_for("piping_characteristic_list_v1"),
        document_version_id="docv_test",
        business_pack_id="engineering_inspection_v1",
        model_manifest={},
    )

    table = result["tables"][0]
    fields = {field["fieldCode"]: field["fieldValue"] for field in result["fields"]}

    assert table["businessSchema"] == "piping_characteristic_table_v1"
    assert table["businessRows"][0]["pipeNo"] == "PL8301"
    assert table["businessRows"][0]["nominalDiameter"] == "DN100"
    assert table["businessRows"][0]["mediumName"] == "化工品"
    assert table["businessRows"][0]["designPressure"] == "0.1"
    assert table["businessRows"][0]["weldDetectionMethod"] == "RT"
    assert table["normalizedRows"][1]["pipeNo"] == "VT8301"
    assert fields["pipe_no"] == "PL8301,VT8301"


def test_quality_certificate_profile_extracts_business_fields_and_table_schemas() -> None:
    from apps.ocr_service.service import enrich_parse_result
    from libs.ocr.profiles import profile_for

    fragments = [
        {"pageNo": 1, "text": "河北广浩管件有限公司", "bbox": [10, 10, 180, 30], "confidence": 0.95},
        {"pageNo": 1, "text": "产品出厂检验合格证", "bbox": [10, 40, 180, 65], "confidence": 0.96},
        {"pageNo": 1, "text": "2021年3月18日", "bbox": [300, 40, 420, 65], "confidence": 0.92},
        {"pageNo": 1, "text": "材质", "bbox": [10, 80, 60, 100], "confidence": 0.9},
        {"pageNo": 1, "text": "20#", "bbox": [70, 80, 110, 100], "confidence": 0.9},
        {"pageNo": 1, "text": "WN100(B)-16 RF S=5", "bbox": [120, 80, 260, 100], "confidence": 0.9},
        {"pageNo": 1, "text": "HG/T20592-2009", "bbox": [270, 80, 390, 100], "confidence": 0.9},
        {"pageNo": 1, "text": "检验合格", "bbox": [10, 220, 100, 245], "confidence": 0.91},
    ]
    table = {
        "tableId": "docling_table_10",
        "sourceEngine": "docling_local",
        "rows": 7,
        "columns": 7,
        "bbox": [10, 110, 400, 260],
        "structureConfidence": 0.88,
        "cells": [
            {"text": "材质 20#", "bbox": [10, 110, 80, 130], "isHeader": True},
            {"text": "化学成分%", "bbox": [10, 140, 80, 160], "isHeader": True},
            {"text": "碳C", "bbox": [90, 140, 120, 160], "isHeader": True},
            {"text": "锰Mn", "bbox": [130, 140, 160, 160], "isHeader": True},
            {"text": "硅Si", "bbox": [170, 140, 200, 160], "isHeader": True},
            {"text": "屈服点", "bbox": [10, 180, 80, 200], "isHeader": True},
            {"text": "抗拉强度", "bbox": [90, 180, 160, 200], "isHeader": True},
            {"text": "延伸率", "bbox": [170, 180, 220, 200], "isHeader": True},
        ],
    }

    result = enrich_parse_result(
        {
            "status": "success",
            "storageKey": "/tmp/quality.png",
            "fileName": "quality.png",
            "fragments": fragments,
            "fields": [],
            "tables": [table],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile_for("quality_certificate_v1"),
        document_version_id="docv_quality",
        business_pack_id="engineering_inspection_v1",
        model_manifest={},
    )

    fields = {field["fieldCode"]: field["fieldValue"] for field in result["fields"]}
    assert fields["manufacturer"] == "河北广浩管件有限公司"
    assert fields["material_grade"] == "20#"
    assert fields["specification"] == "WN100(B)-16 RF S=5"
    assert fields["standard_no"] == "HG/T20592-2009"
    assert fields["inspection_conclusion"] == "检验合格"
    assert fields["issue_date"] == "2021年3月18日"
    assert set(result["tables"][0]["businessSchemas"]) == {
        "material_chemical_composition_table",
        "mechanical_property_table",
    }
    assert result["quality"]["missingTables"] == []


def test_quality_certificate_profile_does_not_extract_fields_from_design_spec_text() -> None:
    from apps.ocr_service.service import enrich_parse_result
    from libs.ocr.profiles import profile_for

    result = enrich_parse_result(
        {
            "status": "success",
            "storageKey": "/tmp/design-spec.png",
            "fileName": "design-spec.png",
            "fragments": [
                {"pageNo": 1, "text": "广东星燃石化设计院有限公司", "bbox": [1, 1, 100, 20], "confidence": 0.9},
                {"pageNo": 1, "text": "工艺设计说明书", "bbox": [1, 30, 100, 50], "confidence": 0.9},
                {"pageNo": 1, "text": "质量验收标准进行", "bbox": [1, 60, 100, 80], "confidence": 0.9},
            ],
            "fields": [],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile_for("quality_certificate_v1"),
        document_version_id="docv_design",
        business_pack_id="engineering_inspection_v1",
        model_manifest={},
    )

    assert not any(field["fieldCode"] == "manufacturer" for field in result["fields"])
    assert "REQUIRED_FIELD_MISSING" in result["quality"]["reasons"]


def test_welding_record_profile_extracts_process_assessment_identifiers() -> None:
    from apps.ocr_service.service import enrich_parse_result
    from libs.ocr.profiles import profile_for

    result = enrich_parse_result(
        {
            "status": "success",
            "storageKey": "/tmp/welding.png",
            "fileName": "welding.png",
            "fragments": [
                {"pageNo": 1, "text": "承压设备焊接工艺评定报告", "bbox": [10, 10, 220, 35], "confidence": 0.94},
                {"pageNo": 1, "text": "编号：", "bbox": [10, 50, 60, 70], "confidence": 0.92},
                {"pageNo": 1, "text": "HP2013-10", "bbox": [70, 50, 150, 70], "confidence": 0.93},
                {"pageNo": 1, "text": "单位：贵州化工建设公司", "bbox": [10, 80, 220, 100], "confidence": 0.91},
                {"pageNo": 1, "text": "日期：2013年11月2日", "bbox": [10, 110, 190, 130], "confidence": 0.91},
            ],
            "fields": [],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile_for("welding_record_v1"),
        document_version_id="docv_welding",
        business_pack_id="engineering_inspection_v1",
        model_manifest={},
    )

    fields = {field["fieldCode"]: field["fieldValue"] for field in result["fields"]}
    assert fields["record_no"] == "HP2013-10"
    assert fields["welding_date"] == "2013年11月2日"
    assert "weld_no" in result["quality"]["missingFields"]
    assert "welding_record_table" in result["quality"]["missingTables"]


def test_welding_record_profile_does_not_extract_from_unrelated_design_text() -> None:
    from apps.ocr_service.service import enrich_parse_result
    from libs.ocr.profiles import profile_for

    result = enrich_parse_result(
        {
            "status": "success",
            "storageKey": "/tmp/design.png",
            "fileName": "design.png",
            "fragments": [
                {"pageNo": 1, "text": "广东星燃石化设计院有限公司", "bbox": [1, 1, 100, 20], "confidence": 0.9},
                {"pageNo": 1, "text": "编号：QX201903S", "bbox": [1, 30, 100, 50], "confidence": 0.9},
                {"pageNo": 1, "text": "日期：2021年3月1日", "bbox": [1, 60, 100, 80], "confidence": 0.9},
            ],
            "fields": [],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile_for("welding_record_v1"),
        document_version_id="docv_design",
        business_pack_id="engineering_inspection_v1",
        model_manifest={},
    )

    assert result["fields"] == []
    assert "REQUIRED_FIELD_MISSING" in result["quality"]["reasons"]


def test_visual_seal_subprocess_normalizes_candidates(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.engines import VisualSealCandidateSubprocessEngine

    class Completed:
        returncode = 0
        stderr = ""
        stdout = json.dumps(
            {
                "ok": True,
                "seals": [
                    {
                        "sealId": "red_candidate_1",
                        "pageNo": 1,
                        "sealType": "visual_red_seal_candidate",
                        "sealName": "视觉印章候选",
                        "bbox": [10, 20, 110, 120],
                        "visualConfidence": 0.82,
                        "ocrConfidence": 0,
                        "fields": [{"fieldName": "印章颜色", "fieldValue": "red"}],
                        "qualityFlags": ["visual_candidate_only"],
                    }
                ],
            },
            ensure_ascii=False,
        )

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    sample = tmp_path / "seal.png"
    sample.write_bytes(b"png")
    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", sys.executable)
    monkeypatch.setattr("apps.ocr_service.engines.run_ocr_subprocess", fake_run)

    result = VisualSealCandidateSubprocessEngine().parse(sample)

    assert result["ok"] is True
    assert result["seals"][0]["sealType"] == "visual_red_seal_candidate"
    assert calls[0][1]["env"]["HF_HUB_OFFLINE"] == "1"


def test_paddle_ocr_subprocess_can_reuse_persistent_worker(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.engines import PaddleOcrSubprocessEngine

    class FakeStdin:
        def __init__(self):
            self.writes = []

        def write(self, value):
            self.writes.append(value)

        def flush(self):
            return None

    class FakeStdout:
        def __init__(self):
            self.lines = [
                'AICHECK_OCR_RESULT {"ok": true, "fragments": [{"text": "A"}], "text": "A"}\n',
                'AICHECK_OCR_RESULT {"ok": true, "fragments": [{"text": "B"}], "text": "B"}\n',
            ]

        def fileno(self):
            return 0

        def readline(self):
            return self.lines.pop(0)

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    popen_calls = []
    process = FakeProcess()

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return process

    def fake_select(readable, _writeable, _errors, _timeout):
        return readable, [], []

    source = tmp_path / "sample.png"
    det_dir = tmp_path / "det"
    rec_dir = tmp_path / "rec"
    source.write_bytes(b"image")
    det_dir.mkdir()
    rec_dir.mkdir()
    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", sys.executable)
    monkeypatch.setenv("AICHECK_PADDLEOCR_DET_MODEL_DIR", str(det_dir))
    monkeypatch.setenv("AICHECK_PADDLEOCR_REC_MODEL_DIR", str(rec_dir))
    monkeypatch.setenv("AICHECK_OCR_ENABLE_PERSISTENT_SUBPROCESS", "true")
    monkeypatch.setattr("apps.ocr_service.engines.subprocess.Popen", fake_popen)
    monkeypatch.setattr("apps.ocr_service.engines.select.select", fake_select)

    engine = PaddleOcrSubprocessEngine()
    first = engine.parse(source)
    second = engine.parse(source)

    assert first["workerMode"] == "persistent"
    assert second["workerMode"] == "persistent"
    assert first["text"] == "A"
    assert second["text"] == "B"
    assert len(popen_calls) == 1
    assert len(process.stdin.writes) == 2


def test_pp_structure_requires_explicit_local_model_dirs(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.engines import PpStructureEngine

    monkeypatch.setenv("AICHECK_PADDLEX_MODEL_CACHE", str(tmp_path))
    for key in [
        "AICHECK_PPSTRUCTURE_LAYOUT_MODEL_DIR",
        "AICHECK_PPSTRUCTURE_WIRED_TABLE_STRUCTURE_MODEL_DIR",
        "AICHECK_PPSTRUCTURE_WIRED_TABLE_CELLS_MODEL_DIR",
        "AICHECK_PPSTRUCTURE_WIRELESS_TABLE_STRUCTURE_MODEL_DIR",
        "AICHECK_PPSTRUCTURE_WIRELESS_TABLE_CELLS_MODEL_DIR",
        "AICHECK_PADDLEOCR_DET_MODEL_DIR",
        "AICHECK_PADDLEOCR_REC_MODEL_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)

    status = PpStructureEngine().status()

    assert status["available"] is False
    assert "layout" in status["missingModelDirs"]
    assert "wired_table_structure" in status["missingModelDirs"]


def test_pp_structure_html_table_normalizes_cells_and_rows() -> None:
    from apps.ocr_service.engines import normalize_structure_result

    tables, blocks = normalize_structure_result(
        [
            {
                "type": "table",
                "bbox": [10, 20, 300, 180],
                "confidence": 0.91,
                "res": {
                    "html": """
                    <table>
                      <tr><th>管道代号</th><th>公称直径</th><th>介质</th></tr>
                      <tr><td>PL8301</td><td>DN100</td><td>液体</td></tr>
                      <tr><td>VT8301</td><td>DN50</td><td>气相</td></tr>
                    </table>
                    """
                },
            }
        ],
        "pp_structure_v3",
    )

    assert blocks[0]["blockType"] == "table"
    assert tables[0]["sourceEngine"] == "pp_structure_v3"
    assert tables[0]["rows"] == 3
    assert tables[0]["columns"] == 3
    assert len(tables[0]["cells"]) == 9
    assert tables[0]["cells"][0]["isHeader"] is True
    assert tables[0]["normalizedRows"][0]["管道代号"] == "PL8301"
    assert tables[0]["normalizedRows"][1]["介质"] == "气相"


def test_pp_structure_html_table_handles_rowspan_and_colspan() -> None:
    from apps.ocr_service.engines import html_table_to_structure

    structure = html_table_to_structure(
        """
        <table>
          <tr><th rowspan="2">管道代号</th><th colspan="2">强度试验</th></tr>
          <tr><th>介质</th><th>压力</th></tr>
          <tr><td>PL8301</td><td>水</td><td>0.15</td></tr>
        </table>
        """
    )

    assert structure["rows"] == 3
    assert structure["columns"] == 3
    assert structure["cells"][0]["rowspan"] == 2
    assert structure["cells"][1]["colspan"] == 2
    assert structure["normalizedRows"][0]["管道代号"] == "PL8301"
    assert structure["normalizedRows"][0]["介质"] == "水"
    assert structure["normalizedRows"][0]["压力"] == "0.15"


def test_ocr_engine_normalizers_preserve_zero_confidence() -> None:
    from apps.ocr_service.engines import (
        normalize_paddle_fragments,
        normalize_seal_result,
        normalize_structure_result,
    )

    fragments = normalize_paddle_fragments(
        {"rec_texts": ["低置信文字"], "rec_scores": [0], "dt_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]]},
        page_no=1,
        source_engine="paddle_ocr_subprocess",
    )
    tables, blocks = normalize_structure_result(
        [{"type": "table", "score": 0, "bbox": [0, 0, 10, 10], "html": "<table><tr><td>A</td></tr></table>"}],
        "pp_structure_v3",
    )
    seals = normalize_seal_result([{"sealName": "低置信印章", "bbox": [1, 2, 3, 4], "score": 0}])

    assert fragments[0]["confidence"] == 0
    assert blocks[0]["confidence"] == 0
    assert tables[0]["structureConfidence"] == 0
    assert seals[0]["visualConfidence"] == 0
    assert seals[0]["ocrConfidence"] == 0


def test_ocr_engine_normalizers_do_not_invent_missing_confidence() -> None:
    from apps.ocr_service.engines import (
        normalize_paddle_fragments,
        normalize_seal_result,
        normalize_structure_result,
    )

    fragments = normalize_paddle_fragments({"rec_texts": ["未知置信文字"], "dt_polys": []}, page_no=1, source_engine="paddle")
    tables, blocks = normalize_structure_result(
        [{"type": "table", "bbox": [0, 0, 10, 10], "html": "<table><tr><td>A</td></tr></table>"}],
        "pp_structure_v3",
    )
    seals = normalize_seal_result([{"sealName": "未知置信印章", "bbox": [1, 2, 3, 4]}])

    assert fragments[0]["confidence"] == 0
    assert blocks[0]["confidence"] == 0
    assert tables[0]["structureConfidence"] == 0
    assert seals[0]["visualConfidence"] == 0
    assert seals[0]["ocrConfidence"] == 0


def test_ocr_routing_uses_enhanced_text_variant_for_low_quality_page() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {"variantId": "page_1_original", "path": "/tmp/original.png", "purpose": "general"},
        {"variantId": "page_1_gray_clahe", "path": "/tmp/gray.png", "purpose": "text"},
    ]

    routed = route_engine_variants(
        "paddle_ocr_subprocess",
        variants,
        profile={"preprocessPolicy": {}},
        page_quality=[{"pageNo": 1, "quality": {"isLowQuality": True}}],
        options={},
    )

    assert routed[0]["variantId"] == "page_1_gray_clahe"
    assert [item["variantId"] for item in routed] == ["page_1_gray_clahe", "page_1_original"]


def test_ocr_routing_runs_structure_original_and_best_enhanced_variant() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {"variantId": "page_1_original", "path": "/tmp/original.png", "purpose": "general"},
        {"variantId": "page_1_table_line_enhanced", "path": "/tmp/table.png", "purpose": "table"},
        {"variantId": "page_1_deskew", "path": "/tmp/deskew.png", "purpose": "text"},
        {"variantId": "page_1_gray_clahe", "path": "/tmp/gray.png", "purpose": "text"},
    ]

    routed = route_engine_variants(
        "pp_structure_v3",
        variants,
        profile={"preprocessPolicy": {}},
        page_quality=[{"pageNo": 1, "quality": {"isLowQuality": True, "skewAngle": 1.4}}],
        options={},
    )

    assert [item["variantId"] for item in routed] == ["page_1_deskew"]


def test_ocr_routing_keeps_opencv_grid_on_table_variant_only() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {"variantId": "page_1_original", "path": "/tmp/original.png", "purpose": "general"},
        {"variantId": "page_1_table_line_enhanced", "path": "/tmp/table.png", "purpose": "table"},
        {"variantId": "page_1_gray_clahe", "path": "/tmp/gray.png", "purpose": "text"},
    ]

    routed = route_engine_variants(
        "opencv_table_grid_subprocess",
        variants,
        profile={"preprocessPolicy": {}},
        page_quality=[{"pageNo": 1, "quality": {"hasTableCandidate": True}}],
        options={},
    )

    assert [item["variantId"] for item in routed] == ["page_1_table_line_enhanced"]


def test_ocr_routing_runs_formal_seal_ocr_on_original_and_mask_candidate() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {"variantId": "page_1_original", "pageNo": 1, "path": "/tmp/p1.png", "purpose": "general"},
        {"variantId": "page_1_seal_color_mask", "pageNo": 1, "path": "/tmp/p1-seal.png", "purpose": "seal"},
        {"variantId": "page_2_original", "pageNo": 2, "path": "/tmp/p2.png", "purpose": "general"},
    ]

    routed = route_engine_variants(
        "paddlex_seal_recognition",
        variants,
        profile={"sealRules": {"required": True}, "preprocessPolicy": {"seal": {"maxPages": 4}}},
        page_quality=[
            {"pageNo": 1, "quality": {"hasSealCandidate": True}},
            {"pageNo": 2, "quality": {"hasSealCandidate": False}},
        ],
        options={},
    )

    assert [item["variantId"] for item in routed] == [
        "page_1_seal_color_mask",
        "page_2_original",
    ]


def test_ocr_routing_required_formal_seal_ocr_falls_back_to_edge_pages() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {"variantId": "page_1_original", "pageNo": 1, "path": "/tmp/p1.png", "purpose": "general"},
        {"variantId": "page_2_original", "pageNo": 2, "path": "/tmp/p2.png", "purpose": "general"},
        {"variantId": "page_3_original", "pageNo": 3, "path": "/tmp/p3.png", "purpose": "general"},
    ]

    routed = route_engine_variants(
        "paddlex_seal_recognition",
        variants,
        profile={"sealRules": {"required": True}, "preprocessPolicy": {"seal": {"maxPages": 2}}},
        page_quality=[
            {"pageNo": 1, "quality": {"hasSealCandidate": False}},
            {"pageNo": 2, "quality": {"hasSealCandidate": False}},
            {"pageNo": 3, "quality": {"hasSealCandidate": False}},
        ],
        options={},
    )

    assert [item["variantId"] for item in routed] == ["page_1_original", "page_3_original"]


def test_ocr_routing_can_infer_page_number_from_variant_id() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {"variantId": "page_1_original", "path": "/tmp/p1.png", "purpose": "general"},
        {"variantId": "page_2_original", "path": "/tmp/p2.png", "purpose": "general"},
        {"variantId": "page_3_original", "path": "/tmp/p3.png", "purpose": "general"},
    ]

    routed = route_engine_variants(
        "agentdesign_seal_ocr_subprocess",
        variants,
        profile={"sealRules": {"required": True}, "preprocessPolicy": {"seal": {"maxPages": 2}}},
        page_quality=[
            {"pageNo": 1, "quality": {"hasSealCandidate": False}},
            {"pageNo": 2, "quality": {"hasSealCandidate": False}},
            {"pageNo": 3, "quality": {"hasSealCandidate": False}},
        ],
        options={},
    )

    assert [item["variantId"] for item in routed] == ["page_1_original", "page_3_original"]


def test_ocr_routing_visual_seal_detector_does_not_fallback_to_edge_pages() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {"variantId": "page_1_original", "pageNo": 1, "path": "/tmp/p1.png", "purpose": "general"},
        {"variantId": "page_2_original", "pageNo": 2, "path": "/tmp/p2.png", "purpose": "general"},
    ]

    routed = route_engine_variants(
        "visual_seal_candidate_subprocess",
        variants,
        profile={"sealRules": {"required": True}, "preprocessPolicy": {"seal": {"maxPages": 2}}},
        page_quality=[
            {"pageNo": 1, "quality": {"hasSealCandidate": False}},
            {"pageNo": 2, "quality": {"hasSealCandidate": False}},
        ],
        options={},
    )

    assert routed == []


def test_ocr_quick_mode_runs_visual_seal_only_on_first_page() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {"variantId": "page_1_original", "pageNo": 1, "path": "/tmp/p1.png", "purpose": "general"},
        {"variantId": "page_2_original", "pageNo": 2, "path": "/tmp/p2.png", "purpose": "general"},
    ]
    profile = {
        "sealRules": {"required": True},
        "preprocessPolicy": {"seal": {"enableColorCandidate": True, "enablePaddlexSeal": True}},
    }
    page_quality = [
        {"pageNo": 1, "quality": {"hasSealCandidate": False}},
        {"pageNo": 2, "quality": {"hasSealCandidate": False}},
    ]

    assert (
        route_engine_variants(
            "paddlex_seal_recognition",
            variants,
            profile=profile,
            page_quality=page_quality,
            options={"quickMode": True, "enableSeals": True},
        )
        == []
    )
    assert (
        route_engine_variants(
            "agentdesign_seal_ocr_subprocess",
            variants,
            profile=profile,
            page_quality=page_quality,
            options={"quickMode": True, "enableSeals": True},
        )
        == []
    )

    visual = route_engine_variants(
        "visual_seal_candidate_subprocess",
        variants,
        profile=profile,
        page_quality=page_quality,
        options={"quickMode": True, "enableSeals": True},
    )
    assert [item["variantId"] for item in visual] == ["page_1_original"]

    assert (
        route_engine_variants(
            "visual_seal_candidate_subprocess",
            variants,
            profile=profile,
            page_quality=page_quality,
            options={"quickMode": True, "enableSeals": False},
        )
        == []
    )


def test_ocr_parse_document_merges_agentdesign_candidate_with_local_engines(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService

    class FakeEngine:
        name = "paddle_ocr_subprocess"
        version = "test"

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, source_path, *, file_name=None, profile=None, variant=None):
            return {
                "ok": True,
                "fragments": [{"pageNo": 1, "text": "local candidate", "bbox": [1, 1, 10, 10], "confidence": 0.91}],
                "diagnostics": [],
            }

    source = tmp_path / "sample.png"
    source.write_bytes(b"sample-image")
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))
    service = OcrService()
    service.pipeline = lambda path: {
        "ok": True,
        "fragments": [{"pageNo": 1, "text": "agentdesign candidate", "bbox": [0, 0, 8, 8], "confidence": 0.88}],
    }
    service.engines = [FakeEngine()]
    monkeypatch.setattr(service, "model_manifest", lambda: {"modelDirs": {"test": {"hash": "sha256:model"}}})

    result = service.parse_document(str(source), file_name="sample.png", profile_id="generic_document_v1", options={"disableResultCache": True})

    texts = {item["text"] for item in result["fragments"]}
    assert {"agentdesign candidate", "local candidate"}.issubset(texts)
    engines = {item["engine"] for item in result["engineRuns"]}
    assert {"agentdesign_pipeline", "paddle_ocr_subprocess"}.issubset(engines)


def test_ocr_preprocess_uses_page_scoped_original_variants(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.preprocess import generate_image_variants
    from libs.ocr.profiles import profile_for

    source = tmp_path / "two-pages.pdf"
    source.write_bytes(b"%PDF-1.4")
    page_one = tmp_path / "page-1.png"
    page_two = tmp_path / "page-2.png"
    page_one.write_bytes(b"page-one")
    page_two.write_bytes(b"page-two")
    monkeypatch.setattr(
        "apps.ocr_service.preprocess.render_document_pages",
        lambda source_path, profile=None: [
            {"pageNo": 1, "path": str(page_one), "documentPath": str(source), "sourceType": "pdf", "renderDpi": 300},
            {"pageNo": 2, "path": str(page_two), "documentPath": str(source), "sourceType": "pdf", "renderDpi": 300},
        ],
    )
    profile = profile_for("generic_document_v1")

    page_quality = [
        {"pageNo": 1, "quality": {"hasTableCandidate": False, "hasSealCandidate": False, "isLowQuality": False}},
        {"pageNo": 2, "quality": {"hasTableCandidate": False, "hasSealCandidate": False, "isLowQuality": False}},
    ]
    variants = generate_image_variants(source, profile=profile, page_quality=page_quality, options={"variants": ["original"]})

    assert {item["variantId"] for item in variants if item["source"] == "original"} == {"page_1_original", "page_2_original"}


def test_ocr_preprocess_variant_cache_round_trips(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.preprocess import (
        load_cached_variants,
        save_cached_variants,
        variant_cache_dir,
    )

    source = tmp_path / "source.png"
    source.write_bytes(b"source-image")
    monkeypatch.setenv("AICHECK_OCR_PREPROCESS_CACHE_DIR", str(tmp_path / "cache"))
    profile = {"profileId": "piping_characteristic_list_v1", "preprocessPolicy": {"variants": ["original", "gray_clahe"]}}
    cache_dir = variant_cache_dir(source, profile, ["original", "gray_clahe"], options={})
    assert cache_dir is not None
    variant_file = cache_dir / "source-gray_clahe.png"
    variant_file.parent.mkdir(parents=True, exist_ok=True)
    variant_file.write_bytes(b"variant")

    save_cached_variants(
        cache_dir,
        [
            {
                "variantId": "page_1_gray_clahe",
                "pageNo": 1,
                "path": str(variant_file),
                "preprocessChain": ["grayscale", "clahe"],
                "imageHash": "sha256:variant",
                "purpose": "text",
                "source": "generated",
            }
        ],
    )

    cached = load_cached_variants(cache_dir)

    assert cached is not None
    assert cached[0]["variantId"] == "page_1_gray_clahe"
    assert cached[0]["cacheHit"] is True
    assert variant_cache_dir(source, profile, ["original"], options={"disableVariantCache": True}) is None


def test_ocr_preprocess_keeps_table_and_seal_variants_in_priority_cap() -> None:
    from apps.ocr_service.preprocess import requested_variant_names
    from libs.ocr.profiles import profile_for

    requested = requested_variant_names(
        profile_for("piping_characteristic_list_v1"),
        [{"pageNo": 1, "quality": {"hasTableCandidate": True, "hasSealCandidate": True, "isLowQuality": False}}],
    )

    assert requested[:3] == ["original", "table_line_enhanced", "seal_color_mask"]
    assert len(requested) <= 4


def test_ocr_service_result_cache_skips_repeated_engine_run(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService
    from libs.ocr.profiles import profile_for

    class FakeEngine:
        name = "paddle_ocr_subprocess"
        version = "test"

        def __init__(self):
            self.calls = 0

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, source_path, *, file_name=None, profile=None, variant=None):
            self.calls += 1
            return {
                "ok": True,
                "fragments": [
                    {
                        "pageNo": 1,
                        "text": "管道特性表 PL8301 PL8302",
                        "bbox": [[0, 0], [200, 0], [200, 20], [0, 20]],
                        "confidence": 0.94,
                    }
                ],
                "diagnostics": [],
            }

    source = tmp_path / "sample.png"
    source.write_bytes(b"sample-image")
    monkeypatch.setenv("AICHECK_OCR_RESULT_CACHE_DIR", str(tmp_path / "result-cache"))
    monkeypatch.setenv("AICHECK_OCR_ENGINE_RESULT_CACHE_DIR", str(tmp_path / "engine-cache"))
    monkeypatch.setattr(
        "apps.ocr_service.service.probe_page_quality",
        lambda source_path, profile=None: [{"pageNo": 1, "quality": {"hasTableCandidate": False, "hasSealCandidate": False}}],
    )
    monkeypatch.setattr(
        "apps.ocr_service.service.generate_image_variants",
        lambda source_path, profile, page_quality, options=None: [
            {
                "variantId": "page_1_original",
                "pageNo": 1,
                "path": str(source_path),
                "preprocessChain": ["original"],
                "imageHash": "sha256:test",
                "purpose": "general",
                "source": "original",
            }
        ],
    )
    engine = FakeEngine()
    service = OcrService()
    service.pipeline = None
    service.engines = [engine]
    monkeypatch.setattr(service, "model_manifest", lambda: {"modelDirs": {"test": {"hash": "sha256:model"}}})
    profile = profile_for("piping_characteristic_list_v1")

    first = service.parse_with_local_engines(
        source,
        storage_key=str(source),
        file_name="sample.png",
        profile=profile,
        document_version_id="docv_1",
        business_pack_id="engineering_inspection_v1",
        options={"disableRemediation": True},
    )
    second = service.parse_with_local_engines(
        source,
        storage_key=str(source),
        file_name="sample.png",
        profile=profile,
        document_version_id="docv_2",
        business_pack_id="engineering_inspection_v1",
        options={"disableRemediation": True},
    )

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert engine.calls == 1
    assert first.get("resultCacheHit") is None
    assert second["resultCacheHit"] is True
    assert second["documentVersionId"] == "docv_2"
    assert second["parseResultId"] != first["parseResultId"]
    assert "OCR_RESULT_CACHE_HIT" in {item["code"] for item in second["diagnostics"] if isinstance(item, dict)}


def test_ocr_sample_probe_cache_control_options_are_mapped() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_sample_probe.py"
    spec = importlib.util.spec_from_file_location("ocr_sample_probe_contract", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    options = module.build_parse_options(
        Namespace(
            disable_result_cache=True,
            disable_engine_cache=True,
            disable_variant_cache=True,
            run_all_variants=True,
        )
    )

    assert options == {
        "disableEngineResultCache": True,
        "disableResultCache": True,
        "disableVariantCache": True,
        "runAllVariants": True,
    }


def test_ocr_sample_probe_auto_discover_runtime_sets_missing_env(monkeypatch) -> None:
    from apps.ocr_service import runtime_doctor

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_sample_probe.py"
    spec = importlib.util.spec_from_file_location("ocr_sample_probe_auto_runtime", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("AICHECK_OCR_SUBPROCESS_PYTHON", raising=False)
    monkeypatch.setenv("AICHECK_PADDLEOCR_DET_MODEL_DIR", "/already-set-det")
    monkeypatch.setattr(runtime_doctor, "discover_runtime_candidates", lambda: {"source": "test"})
    monkeypatch.setattr(
        runtime_doctor,
        "recommended_env",
        lambda discovered: {
            "AICHECK_OCR_SUBPROCESS_PYTHON": "/tmp/ocr-python",
            "AICHECK_PADDLEOCR_DET_MODEL_DIR": "/tmp/recommended-det",
        },
    )

    applied = module.apply_auto_discovered_runtime(Namespace(auto_discover_runtime=True))

    assert applied == {"AICHECK_OCR_SUBPROCESS_PYTHON": "/tmp/ocr-python"}
    assert module.os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON") == "/tmp/ocr-python"
    assert module.os.getenv("AICHECK_PADDLEOCR_DET_MODEL_DIR") == "/already-set-det"
    assert module.apply_auto_discovered_runtime(Namespace(auto_discover_runtime=False)) == {}


def test_ocr_sample_probe_can_write_compact_summary_output(monkeypatch, tmp_path) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_sample_probe.py"
    spec = importlib.util.spec_from_file_location("ocr_sample_probe_summary_output", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class FakeOcrService:
        def parse_document(self, source_path, *, file_name=None, profile_id=None, document_type=None, options=None):
            return {
                "status": "success",
                "parseResultId": "parse_test",
                "profileId": profile_id,
                "documentType": document_type,
                "quality": {
                    "status": "auto_usable",
                    "reasons": [],
                    "evidenceCompleteness": 1,
                    "lowConfidenceFields": [],
                    "missingEvidence": [],
                },
                "fragments": [{"text": "管道特性表"}],
                "fields": [],
                "tables": [],
                "seals": [],
                "diagnostics": [],
                "engineRuns": [],
            }

    source = tmp_path / "sample.png"
    source.write_bytes(b"image")
    full_output = tmp_path / "full.json"
    summary_output = tmp_path / "summary.json"
    monkeypatch.setattr(module, "ocr_service", FakeOcrService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ocr_sample_probe.py",
            str(source),
            "--output",
            str(full_output),
            "--summary-output",
            str(summary_output),
        ],
    )

    assert module.main() == 0
    assert json.loads(full_output.read_text(encoding="utf-8"))["fragments"][0]["text"] == "管道特性表"
    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["parseResultId"] == "parse_test"
    assert summary["fragments"] == 1
    assert "fields" not in summary or isinstance(summary["fields"], int)


def test_ocr_sample_probe_summary_output_includes_gate_failures(monkeypatch, tmp_path) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_sample_probe.py"
    spec = importlib.util.spec_from_file_location("ocr_sample_probe_gate_failures", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class FakeOcrService:
        def parse_document(self, source_path, *, file_name=None, profile_id=None, document_type=None, options=None):
            return {
                "status": "success",
                "parseResultId": "parse_gate",
                "profileId": profile_id,
                "documentType": document_type,
                "quality": {
                    "status": "needs_human_review",
                    "reasons": ["FIELD_EVIDENCE_MISSING"],
                    "evidenceCompleteness": 0.5,
                    "lowConfidenceFields": [{"fieldCode": "report_no"}],
                    "missingEvidence": [{"targetType": "field", "targetId": "report_no"}],
                },
                "fragments": [{"text": "管道特性表"}],
                "fields": [],
                "tables": [],
                "seals": [],
                "diagnostics": [],
                "engineRuns": [],
            }

    source = tmp_path / "sample.png"
    source.write_bytes(b"image")
    summary_output = tmp_path / "summary.json"
    monkeypatch.setattr(module, "ocr_service", FakeOcrService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ocr_sample_probe.py",
            str(source),
            "--require-quality-status",
            "auto_usable",
            "--min-evidence-completeness",
            "1",
            "--max-low-confidence-fields",
            "0",
            "--max-missing-evidence",
            "0",
            "--summary-output",
            str(summary_output),
        ],
    )

    assert module.main() == 1
    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["gatePassed"] is False
    assert summary["gateFailureCounts"] == {
        "EVIDENCE_COMPLETENESS_BELOW_MIN": 1,
        "LOW_CONFIDENCE_FIELDS_ABOVE_MAX": 1,
        "MISSING_EVIDENCE_ABOVE_MAX": 1,
        "QUALITY_STATUS_MISMATCH": 1,
    }
    assert {item["metric"] for item in summary["gateFailures"]} == {
        "qualityStatus",
        "evidenceCompleteness",
        "lowConfidenceFields",
        "missingEvidence",
    }


def test_ocr_sample_probe_summary_exposes_performance_metrics() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_sample_probe.py"
    spec = importlib.util.spec_from_file_location("ocr_sample_probe_metrics", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    summary = module.build_summary(
        {
            "status": "success",
            "quality": {
                "status": "auto_usable",
                "reasons": [],
                "evidenceCompleteness": 0.75,
                "missingFields": ["drawing_no", "design_phase"],
                "missingTables": ["piping_characteristic_table"],
                "matchedSealTypes": ["design_license_seal"],
                "missingExpectedSealTypes": ["inspection_testing_seal"],
                "lowConfidenceFields": [{"fieldCode": "report_no"}],
                "missingEvidence": [
                    {"targetType": "field", "targetId": "report_no"},
                    {"targetType": "seal", "targetId": "seal_001"},
                ],
            },
            "imageVariants": [],
            "preprocessStatus": {},
            "fragments": [],
            "fields": [
                {
                    "fieldCode": "project_name",
                    "fieldValue": "珠海恒基达鑫项目",
                    "confidence": 0.91,
                    "sourceEngine": "paddle_ocr_subprocess",
                    "qualityFlags": [],
                },
                {
                    "fieldCode": "document_title",
                    "fieldValue": "管道特性表",
                    "confidence": 0.95,
                    "sourceEngine": "profile_rule",
                },
                {
                    "fieldCode": "report_no",
                    "fieldValue": "RT-2026-001",
                    "confidence": 0.88,
                    "qualityFlags": ["field_value_conflict"],
                },
            ],
            "tables": [
                {
                    "tableId": "formal_grid",
                    "sourceEngine": "opencv_grid_text_aligned",
                    "structureConfidence": 0.91,
                    "qualityFlags": ["opencv_grid_structure", "ocr_text_aligned"],
                    "businessRows": [{"pipeNo": "PL8301"}, {"pipeNo": "VT8301"}],
                    "normalizedRows": [{"pipeNo": "PL8301"}, {"pipeNo": "VT8301"}],
                    "cells": [{"text": "pipeNo"}, {"text": "PL8301"}, {"text": "VT8301"}],
                },
                {
                    "tableId": "heuristic_table",
                    "sourceEngine": "heuristic_table_from_ocr_fragments",
                    "structureConfidence": 0.62,
                    "qualityFlags": ["heuristic_table_fallback"],
                    "businessRows": [{"pipeNo": "PL8302"}],
                    "normalizedRows": [{"pipeNo": "PL8302"}],
                },
            ],
            "seals": [
                {
                    "sealId": "fragment_seal",
                    "sealName": "压力管道 杨道红 TS1810648-2021",
                    "sealType": "design_license_seal",
                    "sourceEngine": "fragment_seal_text_fusion",
                    "ocrConfidence": 0.88,
                    "qualityFlags": ["fragment_seal_text"],
                },
                {
                    "sealId": "visual_candidate",
                    "sealName": "视觉印章候选",
                    "sealType": "visual_red_seal_candidate",
                    "visualConfidence": 0.92,
                    "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
                },
                {
                    "sealId": "missing_evidence",
                    "sealName": "测试单位章",
                    "ocrConfidence": 0.72,
                    "qualityFlags": ["seal_evidence_missing"],
                },
            ],
            "diagnostics": [],
            "engineRuns": [
                {"engine": "paddle_ocr_subprocess", "status": "success", "available": True, "durationMs": 10, "engineCacheHit": True},
                {"engine": "opencv_table_grid_subprocess", "status": "success", "available": True, "durationMs": 20, "engineCacheHit": False},
                {"engine": "agentdesign_seal_ocr_subprocess", "status": "failed", "available": True, "durationMs": 140000},
                {"engine": "pp_structure_v3", "status": "unavailable", "available": False, "durationMs": 0},
            ],
        },
        source="sample.png",
    )

    assert summary["engineRunCount"] == 4
    assert summary["eligibleEngineRunCount"] == 2
    assert summary["engineCacheHits"] == 1
    assert summary["engineCacheHitRate"] == 0.5
    assert summary["totalEngineDurationMs"] == 140030
    assert summary["engineStatusCounts"]["agentdesign_seal_ocr_subprocess:failed"] == 1
    assert summary["failedEngineRuns"][0]["engine"] == "agentdesign_seal_ocr_subprocess"
    assert summary["slowestEngineRuns"][0]["durationMs"] == 140000
    assert summary["evidenceCompleteness"] == 0.75
    assert summary["lowConfidenceFields"] == 1
    assert summary["missingEvidence"] == 2
    assert summary["missingEvidenceByType"] == {"field": 1, "seal": 1}
    assert summary["fields"] == 3
    assert summary["fieldCodes"] == ["document_title", "project_name", "report_no"]
    assert summary["fieldConflictCount"] == 1
    assert summary["fieldCodeCounts"] == {
        "document_title": 1,
        "project_name": 1,
        "report_no": 1,
    }
    assert summary["fieldSourceCounts"] == {
        "paddle_ocr_subprocess": 1,
        "profile_rule": 1,
        "unknown": 1,
    }
    assert summary["fieldQualityFlagCounts"] == {"field_value_conflict": 1}
    assert summary["missingRequiredFields"] == ["design_phase", "drawing_no"]
    assert summary["missingRequiredFieldCount"] == 2
    assert summary["missingRequiredFieldCounts"] == {"design_phase": 1, "drawing_no": 1}
    assert summary["tables"] == 2
    assert summary["missingRequiredTables"] == ["piping_characteristic_table"]
    assert summary["missingRequiredTableCount"] == 1
    assert summary["missingRequiredTableCounts"] == {"piping_characteristic_table": 1}
    assert summary["formalTables"] == 1
    assert summary["heuristicTables"] == 1
    assert summary["tableReviewRequired"] == 1
    assert summary["businessRows"] == 3
    assert summary["normalizedRows"] == 3
    assert summary["tableCells"] == 3
    assert summary["tableSourceCounts"] == {
        "heuristic_table_from_ocr_fragments": 1,
        "opencv_grid_text_aligned": 1,
    }
    assert summary["tableQualityFlagCounts"]["heuristic_table_fallback"] == 1
    assert summary["tableQualityFlagCounts"]["opencv_grid_structure"] == 1
    assert summary["seals"] == 3
    assert summary["readableSeals"] == 2
    assert summary["fragmentSeals"] == 1
    assert summary["visualCandidateSeals"] == 1
    assert summary["sealReviewRequired"] == 2
    assert summary["missingSealText"] == 1
    assert summary["sealSourceCounts"] == {"fragment_seal_text_fusion": 1, "unknown": 2}
    assert summary["sealQualityFlagCounts"]["fragment_seal_text"] == 1
    assert summary["sealQualityFlagCounts"]["requires_seal_ocr_text"] == 1
    assert summary["sealTypes"] == ["design_license_seal", "visual_red_seal_candidate"]
    assert summary["readableSealTypes"] == ["design_license_seal"]
    assert summary["sealTypeCounts"] == {
        "design_license_seal": 1,
        "unknown": 1,
        "visual_red_seal_candidate": 1,
    }
    assert summary["readableSealTypeCounts"] == {"design_license_seal": 1, "unknown": 1}
    assert summary["matchedExpectedSealTypes"] == ["design_license_seal"]
    assert summary["matchedExpectedSealTypeCount"] == 1
    assert summary["matchedExpectedSealTypeCounts"] == {"design_license_seal": 1}
    assert summary["missingExpectedSealTypes"] == ["inspection_testing_seal"]
    assert summary["missingExpectedSealTypeCount"] == 1
    assert summary["missingExpectedSealTypeCounts"] == {"inspection_testing_seal": 1}
    failures = module.collect_gate_failures(
        [summary],
        Namespace(
            min_fragments=0,
            min_tables=0,
            min_formal_tables=None,
            min_business_rows=None,
            max_heuristic_tables=None,
            max_table_review_required=None,
            min_seals=0,
            require_seal_type=[],
            max_missing_expected_seal_types=None,
            min_engine_cache_hit_rate=None,
            max_engine_duration_ms=None,
            max_single_engine_duration_ms=100000,
            fail_on_engine_failure=True,
            require_quality_status=None,
            min_evidence_completeness=None,
            max_low_confidence_fields=None,
            max_missing_evidence=None,
        ),
    )
    assert {item["code"] for item in failures} == {
        "ENGINE_RUN_FAILED",
        "SINGLE_ENGINE_DURATION_ABOVE_MAX",
    }


def test_ocr_sample_probe_can_gate_required_field_codes() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_sample_probe.py"
    spec = importlib.util.spec_from_file_location("ocr_sample_probe_field_gates", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    failures = module.collect_gate_failures(
        [
            {
                "source": "sample.png",
                "status": "success",
                "fragments": 10,
                "fields": 1,
                "fieldCodes": ["project_name"],
                "fieldConflictCount": 2,
                "missingRequiredFieldCount": 1,
                "tables": 1,
                "seals": 1,
                "engineRuns": [],
            }
        ],
        Namespace(
            min_fragments=1,
            min_fields=2,
            require_field_code=["project_name", "document_title"],
            max_field_conflicts=0,
            max_missing_required_fields=0,
            min_tables=1,
            min_formal_tables=None,
            min_business_rows=None,
            max_heuristic_tables=None,
            max_table_review_required=None,
            min_seals=1,
            min_readable_seals=None,
            min_fragment_seals=None,
            max_seal_review_required=None,
            min_engine_cache_hit_rate=None,
            max_engine_duration_ms=None,
            max_single_engine_duration_ms=None,
            fail_on_engine_failure=False,
            require_quality_status=None,
            min_evidence_completeness=None,
            max_low_confidence_fields=None,
            max_missing_evidence=None,
        ),
    )

    assert {item["code"] for item in failures} == {
        "FIELD_CONFLICTS_ABOVE_MAX",
        "FIELDS_BELOW_MIN",
        "MISSING_REQUIRED_FIELDS_ABOVE_MAX",
        "REQUIRED_FIELD_CODE_MISSING",
    }
    assert {item["metric"] for item in failures} == {
        "fieldConflictCount",
        "fieldCodes.document_title",
        "fields",
        "missingRequiredFieldCount",
    }


def test_ocr_sample_probe_can_gate_readable_and_fragment_seals() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_sample_probe.py"
    spec = importlib.util.spec_from_file_location("ocr_sample_probe_seal_gates", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    failures = module.collect_gate_failures(
        [
            {
                "source": "sample.png",
                "status": "success",
                "fragments": 10,
                "tables": 1,
                "seals": 1,
                "readableSeals": 0,
                "fragmentSeals": 0,
                "readableSealTypes": [],
                "missingExpectedSealTypeCount": 1,
                "sealReviewRequired": 2,
                "engineRuns": [],
            }
        ],
        Namespace(
            min_fragments=1,
            min_tables=1,
            min_formal_tables=None,
            min_business_rows=None,
            max_heuristic_tables=None,
            max_table_review_required=None,
            min_seals=1,
            min_readable_seals=1,
            min_fragment_seals=1,
            require_seal_type=["design_license_seal"],
            max_missing_expected_seal_types=0,
            max_seal_review_required=1,
            min_engine_cache_hit_rate=None,
            max_engine_duration_ms=None,
            max_single_engine_duration_ms=None,
            fail_on_engine_failure=False,
            require_quality_status=None,
            min_evidence_completeness=None,
            max_low_confidence_fields=None,
            max_missing_evidence=None,
        ),
    )

    assert {item["code"] for item in failures} == {
        "FRAGMENT_SEALS_BELOW_MIN",
        "MISSING_EXPECTED_SEAL_TYPES_ABOVE_MAX",
        "READABLE_SEALS_BELOW_MIN",
        "REQUIRED_SEAL_TYPE_MISSING",
        "SEAL_REVIEW_REQUIRED_ABOVE_MAX",
    }
    assert {item["metric"] for item in failures} == {
        "fragmentSeals",
        "missingExpectedSealTypeCount",
        "readableSeals",
        "readableSealTypes.design_license_seal",
        "sealReviewRequired",
    }


def test_ocr_sample_probe_can_gate_formal_tables_and_business_rows() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_sample_probe.py"
    spec = importlib.util.spec_from_file_location("ocr_sample_probe_table_gates", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    failures = module.collect_gate_failures(
        [
            {
                "source": "sample.png",
                "status": "success",
                "fragments": 10,
                "tables": 1,
                "formalTables": 0,
                "heuristicTables": 1,
                "tableReviewRequired": 1,
                "missingRequiredTableCount": 1,
                "businessRows": 0,
                "seals": 1,
                "engineRuns": [],
            }
        ],
        Namespace(
            min_fragments=1,
            min_tables=1,
            min_formal_tables=1,
            min_business_rows=1,
            max_heuristic_tables=0,
            max_table_review_required=0,
            max_missing_required_tables=0,
            min_seals=1,
            min_readable_seals=None,
            min_fragment_seals=None,
            max_seal_review_required=None,
            min_engine_cache_hit_rate=None,
            max_engine_duration_ms=None,
            max_single_engine_duration_ms=None,
            fail_on_engine_failure=False,
            require_quality_status=None,
            min_evidence_completeness=None,
            max_low_confidence_fields=None,
            max_missing_evidence=None,
        ),
    )

    assert {item["code"] for item in failures} == {
        "BUSINESS_ROWS_BELOW_MIN",
        "FORMAL_TABLES_BELOW_MIN",
        "HEURISTIC_TABLES_ABOVE_MAX",
        "MISSING_REQUIRED_TABLES_ABOVE_MAX",
        "TABLE_REVIEW_REQUIRED_ABOVE_MAX",
    }
    assert {item["metric"] for item in failures} == {
        "businessRows",
        "formalTables",
        "heuristicTables",
        "missingRequiredTableCount",
        "tableReviewRequired",
    }


def test_ocr_sample_probe_directory_summary_aggregates_diagnostics() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_sample_probe.py"
    spec = importlib.util.spec_from_file_location("ocr_sample_probe_directory", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    summary = module.build_directory_summary(
        [
            {
                "summary": {
                    "source": "slow.png",
                    "status": "success",
                    "qualityStatus": "needs_human_review",
                    "qualityReasons": ["FIELD_LOW_CONFIDENCE", "FIELD_EVIDENCE_MISSING"],
                    "evidenceCompleteness": 0.5,
                    "lowConfidenceFields": 2,
                    "missingEvidence": 1,
                    "missingEvidenceByType": {"field": 1},
                    "diagnosticCodes": ["TABLE_HEURISTIC_REVIEW_REQUIRED"],
                    "engineRuns": [
                        {"engine": "paddle_ocr_subprocess", "status": "success", "available": True, "durationMs": 100},
                        {"engine": "pp_structure_v3", "status": "unavailable", "available": False, "durationMs": 0},
                    ],
                    "totalEngineDurationMs": 100,
                    "fragments": 10,
                    "fields": 1,
                    "fieldCodeCounts": {"project_name": 1},
                    "fieldSourceCounts": {"paddle_ocr_subprocess": 1},
                    "fieldQualityFlagCounts": {"field_value_conflict": 1},
                    "fieldConflictCount": 1,
                    "missingRequiredFieldCount": 1,
                    "missingRequiredFieldCounts": {"drawing_no": 1},
                    "tables": 1,
                    "missingRequiredTableCount": 1,
                    "missingRequiredTableCounts": {"piping_characteristic_table": 1},
                    "formalTables": 0,
                    "heuristicTables": 1,
                    "tableReviewRequired": 1,
                    "businessRows": 0,
                    "normalizedRows": 1,
                    "tableSourceCounts": {"heuristic_table_from_ocr_fragments": 1},
                    "tableQualityFlagCounts": {"heuristic_table_fallback": 1},
                    "seals": 0,
                    "readableSeals": 0,
                    "fragmentSeals": 0,
                    "visualCandidateSeals": 1,
                    "sealReviewRequired": 1,
                    "missingExpectedSealTypeCount": 1,
                    "matchedExpectedSealTypeCounts": {},
                    "missingExpectedSealTypeCounts": {"design_license_seal": 1},
                    "sealTypeCounts": {"visual_red_seal_candidate": 1},
                    "readableSealTypeCounts": {},
                    "sealSourceCounts": {"visual_seal_candidate_subprocess": 1},
                    "sealQualityFlagCounts": {"requires_seal_ocr_text": 1},
                }
            },
            {
                "summary": {
                    "source": "fast.png",
                    "status": "success",
                    "qualityStatus": "auto_usable",
                    "qualityReasons": ["FIELD_LOW_CONFIDENCE"],
                    "evidenceCompleteness": 1.0,
                    "lowConfidenceFields": 1,
                    "missingEvidence": 0,
                    "missingEvidenceByType": {},
                    "diagnosticCodes": ["OPENCV_GRID_TABLE_ALIGNED"],
                    "engineRuns": [{"engine": "paddle_ocr_subprocess", "status": "success", "available": True, "durationMs": 10}],
                    "totalEngineDurationMs": 10,
                    "fragments": 20,
                    "fields": 2,
                    "fieldCodeCounts": {"document_title": 1, "project_name": 1},
                    "fieldSourceCounts": {"profile_rule": 2},
                    "fieldQualityFlagCounts": {},
                    "fieldConflictCount": 0,
                    "missingRequiredFieldCount": 0,
                    "missingRequiredFieldCounts": {},
                    "tables": 1,
                    "missingRequiredTableCount": 0,
                    "missingRequiredTableCounts": {},
                    "formalTables": 1,
                    "heuristicTables": 0,
                    "tableReviewRequired": 0,
                    "businessRows": 2,
                    "normalizedRows": 2,
                    "tableSourceCounts": {"opencv_grid_text_aligned": 1},
                    "tableQualityFlagCounts": {"opencv_grid_structure": 1},
                    "seals": 1,
                    "readableSeals": 1,
                    "fragmentSeals": 1,
                    "visualCandidateSeals": 0,
                    "sealReviewRequired": 0,
                    "missingExpectedSealTypeCount": 0,
                    "matchedExpectedSealTypeCounts": {"design_license_seal": 1},
                    "missingExpectedSealTypeCounts": {},
                    "sealTypeCounts": {"design_license_seal": 1},
                    "readableSealTypeCounts": {"design_license_seal": 1},
                    "sealSourceCounts": {"fragment_seal_text_fusion": 1},
                    "sealQualityFlagCounts": {"fragment_seal_text": 1},
                }
            },
        ]
    )

    assert summary["qualityReasonCounts"] == {"FIELD_LOW_CONFIDENCE": 2, "FIELD_EVIDENCE_MISSING": 1}
    assert summary["diagnosticCodeCounts"] == {
        "OPENCV_GRID_TABLE_ALIGNED": 1,
        "TABLE_HEURISTIC_REVIEW_REQUIRED": 1,
    }
    assert summary["engineStatusCounts"]["paddle_ocr_subprocess:success"] == 2
    assert summary["engineStatusCounts"]["pp_structure_v3:unavailable"] == 1
    assert summary["slowestFiles"][0]["source"] == "slow.png"
    assert summary["slowestFiles"][0]["totalEngineDurationMs"] == 100
    assert summary["fieldCodeCounts"] == {"project_name": 2, "document_title": 1}
    assert summary["fieldSourceCounts"] == {"profile_rule": 2, "paddle_ocr_subprocess": 1}
    assert summary["fieldQualityFlagCounts"] == {"field_value_conflict": 1}
    assert summary["totalFieldConflicts"] == 1
    assert summary["totalMissingRequiredFields"] == 1
    assert summary["missingRequiredFieldCounts"] == {"drawing_no": 1}
    assert summary["totalMissingRequiredTables"] == 1
    assert summary["missingRequiredTableCounts"] == {"piping_characteristic_table": 1}
    assert summary["totalFormalTables"] == 1
    assert summary["totalHeuristicTables"] == 1
    assert summary["totalTableReviewRequired"] == 1
    assert summary["totalBusinessRows"] == 2
    assert summary["totalNormalizedRows"] == 3
    assert summary["tableSourceCounts"] == {
        "heuristic_table_from_ocr_fragments": 1,
        "opencv_grid_text_aligned": 1,
    }
    assert summary["tableQualityFlagCounts"] == {
        "heuristic_table_fallback": 1,
        "opencv_grid_structure": 1,
    }
    assert summary["totalReadableSeals"] == 1
    assert summary["totalFragmentSeals"] == 1
    assert summary["totalVisualCandidateSeals"] == 1
    assert summary["totalSealReviewRequired"] == 1
    assert summary["totalMissingExpectedSealTypes"] == 1
    assert summary["matchedExpectedSealTypeCounts"] == {"design_license_seal": 1}
    assert summary["missingExpectedSealTypeCounts"] == {"design_license_seal": 1}
    assert summary["sealTypeCounts"] == {"design_license_seal": 1, "visual_red_seal_candidate": 1}
    assert summary["readableSealTypeCounts"] == {"design_license_seal": 1}
    assert summary["sealSourceCounts"] == {
        "fragment_seal_text_fusion": 1,
        "visual_seal_candidate_subprocess": 1,
    }
    assert summary["sealQualityFlagCounts"] == {
        "fragment_seal_text": 1,
        "requires_seal_ocr_text": 1,
    }


def test_ocr_result_cache_key_includes_profile_postprocess_version(tmp_path) -> None:
    from apps.ocr_service.result_cache import build_result_cache_key

    source = tmp_path / "sample.png"
    source.write_bytes(b"sample-image")
    base_profile = {
        "profileId": "piping_characteristic_list_v1",
        "documentType": "engineering_table_photo",
        "preprocessPolicy": {"variants": ["original"]},
        "postprocessVersion": "v1",
    }
    model_manifest = {"modelDirs": {"text": {"hash": "sha256:model"}}}

    first = build_result_cache_key(source, profile=base_profile, model_manifest=model_manifest)
    second = build_result_cache_key(
        source,
        profile={**base_profile, "postprocessVersion": "v2"},
        model_manifest=model_manifest,
    )

    assert first is not None
    assert second is not None
    assert first != second


def test_ocr_engine_result_cache_key_ignores_profile_postprocess_version(tmp_path) -> None:
    from apps.ocr_service.result_cache import build_engine_result_cache_key

    source = tmp_path / "sample.png"
    source.write_bytes(b"sample-image")
    base_profile = {
        "profileId": "piping_characteristic_list_v1",
        "documentType": "engineering_table_photo",
        "preprocessPolicy": {"variants": ["original"]},
        "postprocessVersion": "v1",
    }
    model_manifest = {"modelDirs": {"text": {"hash": "sha256:model"}}}
    engine_status = {"engine": "paddle_ocr_subprocess", "version": "test", "available": True}
    variant = {
        "variantId": "page_1_original",
        "imageHash": "sha256:variant",
        "preprocessChain": ["original"],
        "purpose": "general",
        "source": "original",
    }

    first = build_engine_result_cache_key(
        source,
        engine_status=engine_status,
        variant=variant,
        profile=base_profile,
        model_manifest=model_manifest,
    )
    second = build_engine_result_cache_key(
        source,
        engine_status=engine_status,
        variant=variant,
        profile={**base_profile, "postprocessVersion": "v2"},
        model_manifest=model_manifest,
    )
    changed_engine = build_engine_result_cache_key(
        source,
        engine_status={**engine_status, "version": "test-2"},
        variant=variant,
        profile=base_profile,
        model_manifest=model_manifest,
    )

    assert first is not None
    assert first == second
    assert changed_engine != first


def test_ocr_engine_result_cache_survives_profile_postprocess_change(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService
    from libs.ocr.profiles import profile_for

    class FakeEngine:
        name = "paddle_ocr_subprocess"
        version = "test"

        def __init__(self):
            self.calls = 0

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, source_path, *, file_name=None, profile=None, variant=None):
            self.calls += 1
            return {
                "ok": True,
                "fragments": [
                    {
                        "pageNo": 1,
                        "text": "管道特性表 PL8301 PL8302",
                        "bbox": [[0, 0], [200, 0], [200, 20], [0, 20]],
                        "confidence": 0.94,
                    }
                ],
                "diagnostics": [],
            }

    source = tmp_path / "sample.png"
    source.write_bytes(b"sample-image")
    monkeypatch.setenv("AICHECK_OCR_RESULT_CACHE_DIR", str(tmp_path / "result-cache"))
    monkeypatch.setenv("AICHECK_OCR_ENGINE_RESULT_CACHE_DIR", str(tmp_path / "engine-cache"))
    monkeypatch.setattr(
        "apps.ocr_service.service.probe_page_quality",
        lambda source_path, profile=None: [{"pageNo": 1, "quality": {"hasTableCandidate": False, "hasSealCandidate": False}}],
    )
    monkeypatch.setattr(
        "apps.ocr_service.service.generate_image_variants",
        lambda source_path, profile, page_quality, options=None: [
            {
                "variantId": "page_1_original",
                "pageNo": 1,
                "path": str(source_path),
                "preprocessChain": ["original"],
                "imageHash": "sha256:test",
                "purpose": "general",
                "source": "original",
            }
        ],
    )
    engine = FakeEngine()
    service = OcrService()
    service.pipeline = None
    service.engines = [engine]
    monkeypatch.setattr(service, "model_manifest", lambda: {"modelDirs": {"test": {"hash": "sha256:model"}}})
    base_profile = profile_for("piping_characteristic_list_v1")
    first_profile = {**base_profile, "postprocessVersion": "v1"}
    second_profile = {**base_profile, "postprocessVersion": "v2"}

    first = service.parse_with_local_engines(
        source,
        storage_key=str(source),
        file_name="sample.png",
        profile=first_profile,
        document_version_id="docv_1",
        business_pack_id="engineering_inspection_v1",
        options={"disableRemediation": True},
    )
    second = service.parse_with_local_engines(
        source,
        storage_key=str(source),
        file_name="sample.png",
        profile=second_profile,
        document_version_id="docv_2",
        business_pack_id="engineering_inspection_v1",
        options={"disableRemediation": True},
    )

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert engine.calls == 1
    assert first.get("resultCacheHit") is None
    assert second.get("resultCacheHit") is None
    assert second["engineRuns"][0]["engineCacheHit"] is True
    assert second["documentVersionId"] == "docv_2"


def test_ocr_remediation_cache_key_includes_remediation_context(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService
    from libs.ocr.profiles import profile_for

    class RemediationEngine:
        name = "paddleocr_vl_1_6"
        version = "test"

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, source_path, *, file_name=None, profile=None, variant=None):
            return {
                "ok": True,
                "fragments": [
                    {
                        "pageNo": 1,
                        "text": "remediated text",
                        "bbox": [1, 1, 10, 10],
                        "confidence": 0.9,
                    }
                ],
            }

    source = tmp_path / "sample.png"
    source.write_bytes(b"sample-image")
    captured_options = []

    def capture_cache_key(source_path, *, engine_status, variant, profile, model_manifest, options=None):
        captured_options.append(options or {})

    service = OcrService()
    service.engines = [RemediationEngine()]
    monkeypatch.setattr("apps.ocr_service.service.build_engine_result_cache_key", capture_cache_key)

    result = service.run_remediation_pass(
        {
            "status": "success",
            "quality": {"reasons": ["REQUIRED_FIELD_MISSING"]},
            "fragments": [],
            "fields": [],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        source_path=source,
        storage_key=str(source),
        file_name="sample.png",
        profile=profile_for("ndt_rt_report_v1"),
        variants=[
            {
                "variantId": "page_1_original",
                "pageNo": 1,
                "path": str(source),
                "preprocessChain": ["original"],
                "imageHash": "sha256:test",
                "purpose": "general",
                "source": "original",
            }
        ],
        page_quality=[{"pageNo": 1, "quality": {"isLowQuality": False}}],
        model_manifest={"modelDirs": {"test": {"hash": "sha256:model"}}},
        document_version_id="docv_1",
        business_pack_id="engineering_inspection_v1",
        options={},
    )

    assert result["remediationRuns"][0]["status"] == "success"
    assert captured_options
    assert captured_options[0]["runRemediation"] is True
    assert captured_options[0]["remediationReasons"] == ["REQUIRED_FIELD_MISSING"]


def test_ocr_parse_document_preserves_local_diagnostics_on_failure(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService

    class UnavailableEngine:
        name = "pp_structure_v3"
        version = "test"

        def available(self):
            return False

        def status(self):
            return {"engine": self.name, "version": self.version, "available": False}

    source = tmp_path / "sample.png"
    source.write_bytes(b"not-an-image-but-path-is-allowed")
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))
    monkeypatch.setattr(
        "apps.ocr_service.service.probe_page_quality",
        lambda source_path, profile=None: [{"pageNo": 1, "quality": {"hasTableCandidate": True, "hasSealCandidate": True}}],
    )
    monkeypatch.setattr(
        "apps.ocr_service.service.generate_image_variants",
        lambda source_path, profile, page_quality, options=None: [
            {
                "variantId": "page_1_original",
                "pageNo": 1,
                "path": str(source_path),
                "preprocessChain": ["original"],
                "imageHash": "sha256:test",
                "purpose": "general",
                "source": "original",
            }
        ],
    )

    service = OcrService()
    service.pipeline = None
    service.engines = [UnavailableEngine()]
    result = service.parse_document(
        str(source),
        file_name="sample.png",
        profile_id="piping_characteristic_list_v1",
        document_type="engineering_table_photo",
        options={"disableResultCache": True},
    )

    assert result["status"] == "failed"
    assert result["profileId"] == "piping_characteristic_list_v1"
    assert result["pageQuality"]
    assert result["imageVariants"][0]["variantId"] == "page_1_original"
    assert "table_line_enhanced" in result["preprocessStatus"]["missingVariants"]
    assert result["engineRuns"][0]["status"] == "unavailable"
    diagnostic_codes = {item["code"] for item in result["diagnostics"] if isinstance(item, dict)}
    assert "NO_LOCAL_OCR_RESULT" in diagnostic_codes
    assert "PREPROCESS_VARIANT_GENERATION_UNAVAILABLE" in diagnostic_codes


def test_ocr_parse_document_reads_text_documents_directly(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService

    source = tmp_path / "standard-update.md"
    source.write_text("# 标准更新\n\n直接进入知识库切片。", encoding="utf-8")
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))

    service = OcrService()
    service.pipeline = None
    service.engines = []
    result = service.parse_document(
        str(source),
        file_name="standard-update.md",
        options={"disableResultCache": True},
    )

    assert result["status"] == "success"
    assert result["fragments"][0]["text"].startswith("# 标准更新")
    assert result["pages"][0]["sourceType"] == "md"
    assert result["metadata"]["textDocument"] is True
    assert any(item.get("code") == "TEXT_DOCUMENT_DIRECT_PARSE" for item in result["diagnostics"] if isinstance(item, dict))


def test_ocr_parse_document_reads_docx_documents_directly(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService

    source = tmp_path / "standard.docx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>标准规范 Word 文本</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """,
        )
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))

    service = OcrService()
    service.pipeline = None
    service.engines = []
    result = service.parse_document(
        str(source),
        file_name="standard.docx",
        options={"disableResultCache": True},
    )

    assert result["status"] == "success"
    assert result["fragments"][0]["text"] == "标准规范 Word 文本"
    assert result["pages"][0]["sourceType"] == "docx"
    assert result["metadata"]["officeTextDocument"] is True
    assert any(item.get("code") == "DOCX_TEXT_DIRECT_PARSE" for item in result["diagnostics"] if isinstance(item, dict))


def test_ocr_parse_document_uses_pdf_text_layer_fast_path(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService

    source = tmp_path / "standard.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))

    class FakePdfTextLayerEngine:
        name = "pymupdf_text_layer"
        version = "fitz"

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, source_path, *, file_name=None, profile=None, variant=None):
            return {
                "ok": True,
                "text": "Pressure pipeline standard text layer",
                "pages": [{"pageNo": 1, "width": 100, "height": 100}],
                "fragments": [{"pageNo": 1, "text": "Pressure pipeline standard text layer", "confidence": 1.0}],
                "diagnostics": [],
            }

    service = OcrService()
    service.pipeline = None
    service.engines = [FakePdfTextLayerEngine()]
    result = service.parse_document(str(source), file_name="standard.pdf", options={"disableResultCache": True})

    assert result["status"] == "success"
    assert any("Pressure" in item.get("text", "") for item in result["fragments"])
    assert result["engineRuns"][0]["variantId"] == "pdf_text_layer_fast_path"
    assert any(item.get("code") == "PDF_TEXT_LAYER_FAST_PATH" for item in result["diagnostics"] if isinstance(item, dict))


def test_ocr_parse_document_deep_scan_options_skip_pdf_text_layer_fast_path(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService

    source = tmp_path / "welding-pqr.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))

    service = OcrService()
    service.pipeline = None
    captured = {}

    def fail_fast_path(*args, **kwargs):
        raise AssertionError("pdf text layer fast path must be skipped for deep scan requests")

    def fake_parse_with_local_engines(
        source_path,
        *,
        storage_key,
        file_name,
        profile,
        document_version_id,
        business_pack_id,
        options,
        candidate_results,
    ):
        captured["candidate_results"] = candidate_results
        return {
            "status": "success",
            "storageKey": storage_key,
            "fileName": file_name,
            "fragments": [{"pageNo": 1, "text": "承压设备焊接工艺评定报告 PQR-2021-001"}],
            "fields": [],
            "tables": [],
            "seals": [],
            "diagnostics": candidate_results[0]["diagnostics"],
            "metadata": candidate_results[0]["metadata"],
        }

    monkeypatch.setattr(service, "parse_pdf_text_layer_fast_path", fail_fast_path)
    monkeypatch.setattr(service, "parse_with_local_engines", fake_parse_with_local_engines)

    result = service.parse_document(
        str(source),
        file_name="welding-pqr.pdf",
        profile_id="welding_procedure_qualification_v1",
        options={"disableResultCache": True, "fullOcr": True, "deepScanPdf": True},
    )

    assert result["status"] == "success"
    assert captured["candidate_results"][0]["metadata"]["pdfTextLayerFastPathSkipped"] is True
    assert result["metadata"]["pageCoverageMode"] == "deep_scan"
    assert any(
        item.get("code") == "PDF_TEXT_LAYER_FAST_PATH_SKIPPED"
        for item in result["diagnostics"]
        if isinstance(item, dict)
    )


def test_ocr_parse_document_business_pdf_profile_defaults_to_deep_scan(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService

    source = tmp_path / "quality-certificate.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))

    service = OcrService()
    service.pipeline = None
    captured = {}

    def fail_fast_path(*args, **kwargs):
        raise AssertionError("business PDF profiles must not return from text-layer fast path by default")

    def fake_parse_with_local_engines(
        source_path,
        *,
        storage_key,
        file_name,
        profile,
        document_version_id,
        business_pack_id,
        options,
        candidate_results,
    ):
        captured["options"] = options
        captured["profile"] = profile
        return {
            "status": "success",
            "storageKey": storage_key,
            "fileName": file_name,
            "fragments": [{"pageNo": 1, "text": "产品质量证明书 GB/T 8163-2018"}],
            "fields": [],
            "tables": [],
            "seals": [],
            "diagnostics": candidate_results[0]["diagnostics"],
            "metadata": candidate_results[0]["metadata"],
        }

    monkeypatch.setattr(service, "parse_pdf_text_layer_fast_path", fail_fast_path)
    monkeypatch.setattr(service, "parse_with_local_engines", fake_parse_with_local_engines)

    result = service.parse_document(
        str(source),
        file_name="quality-certificate.pdf",
        profile_id="quality_certificate_v1",
        options={"disableResultCache": True},
    )

    assert result["status"] == "success"
    assert captured["profile"]["profileId"] == "quality_certificate_v1"
    assert captured["options"]["deepScanPdf"] is True
    assert captured["options"]["forceTableOcr"] is True
    assert captured["options"]["forceSealOcr"] is True
    assert result["metadata"]["pageCoverageMode"] == "deep_scan"


def test_ocr_parse_document_text_layer_only_does_not_run_visual_ocr(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService

    source = tmp_path / "scanned-standard.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))

    class EmptyPdfTextLayerEngine:
        name = "pymupdf_text_layer"
        version = "fitz"

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, source_path, *, file_name=None, profile=None, variant=None):
            return {"ok": True, "text": "", "fragments": [], "diagnostics": []}

    class VisualEngineShouldNotRun:
        name = "paddle_ocr_subprocess"

        def available(self):
            return True

        def parse(self, *args, **kwargs):
            raise AssertionError("visual OCR should not run for textLayerOnly standard PDFs")

    service = OcrService()
    service.pipeline = None
    service.engines = [EmptyPdfTextLayerEngine(), VisualEngineShouldNotRun()]
    result = service.parse_document(
        str(source),
        file_name="scanned-standard.pdf",
        options={"disableResultCache": True, "textLayerOnly": True},
    )

    assert result["status"] == "failed"
    assert any(item.get("code") == "PDF_TEXT_LAYER_UNAVAILABLE" for item in result["diagnostics"] if isinstance(item, dict))


def test_ocr_fusion_quality_gate_marks_missing_required_data_for_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [{"fieldCode": "company_name", "fieldName": "公司名称", "fieldValue": "A", "confidence": 0.9}],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    assert result["quality"]["status"] == "needs_human_review"
    assert "REQUIRED_FIELD_MISSING" in result["quality"]["reasons"]
    assert "REQUIRED_TABLE_MISSING" in result["quality"]["reasons"]
    assert "SEAL_NOT_FOUND" in result["quality"]["reasons"]
    assert result["quality"]["missingTables"] == ["piping_characteristic_table"]


def test_ocr_fusion_required_table_matches_business_schema_suffix() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "company_name", "fieldName": "公司名称", "fieldValue": "广东星燃石化设计院有限公司", "confidence": 0.9},
                {"fieldCode": "project_name", "fieldName": "项目名称", "fieldValue": "项目", "confidence": 0.9},
                {"fieldCode": "document_title", "fieldName": "文件标题", "fieldValue": "管道特性表", "confidence": 0.9},
                {"fieldCode": "drawing_no", "fieldName": "图纸编号", "fieldValue": "QX201903S-13-Y-07", "confidence": 0.9},
                {"fieldCode": "design_phase", "fieldName": "设计阶段", "fieldValue": "施工图", "confidence": 0.9},
                {"fieldCode": "pipe_no", "fieldName": "管道代号", "fieldValue": "PL8301", "confidence": 0.9},
            ],
            "tables": [
                {
                    "tableId": "piping_characteristic_table_1",
                    "businessSchema": "piping_characteristic_table_v1",
                    "structureConfidence": 0.9,
                    "bbox": [0, 0, 10, 10],
                }
            ],
            "seals": [
                {
                    "sealId": "seal_1",
                    "sealName": "广东星燃石化设计院有限公司压力管道设计许可章",
                    "ocrConfidence": 0.9,
                    "bbox": [0, 0, 10, 10],
                }
            ],
            "diagnostics": [],
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    assert result["quality"]["missingTables"] == []
    assert "REQUIRED_TABLE_MISSING" not in result["quality"]["reasons"]


def test_ocr_fusion_normalizes_common_business_field_aliases() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldName": "证书编号", "fieldValue": "QC-001", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldName": "生产厂家", "fieldValue": "河北广浩管件有限公司", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldName": "产品名称", "fieldValue": "带颈对焊法兰", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldName": "材质", "fieldValue": "20#", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldName": "规格型号", "fieldValue": "WN100", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldName": "炉批号", "fieldValue": "B001", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldName": "执行标准", "fieldValue": "HG/T20592-2009", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldName": "检验结论", "fieldValue": "检验合格", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldName": "签发日期", "fieldValue": "2021年3月18日", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldName": "seal", "fieldValue": "质检专用章", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
            ],
            "tables": [
                {
                    "tableId": "T1",
                    "businessSchema": "material_chemical_composition_table",
                    "businessSchemas": ["material_chemical_composition_table", "mechanical_property_table"],
                    "structureConfidence": 0.9,
                    "bbox": [0, 0, 10, 10],
                    "cells": [{"text": "化学成分", "isHeader": True}, {"text": "抗拉强度", "isHeader": True}],
                }
            ],
            "seals": [{"sealId": "seal_1", "sealType": "quality_seal", "sealName": "质检专用章", "ocrConfidence": 0.9, "bbox": [0, 0, 10, 10]}],
            "diagnostics": [],
        },
        profile=profile_for("quality_certificate_v1"),
    )

    field_codes = {field["fieldCode"] for field in result["fields"]}
    assert {
        "certificate_no",
        "manufacturer",
        "product_name",
        "material_grade",
        "specification",
        "batch_no",
        "standard_no",
        "inspection_conclusion",
        "issue_date",
        "seal",
    }.issubset(field_codes)
    assert result["quality"]["missingFields"] == []
    assert "REQUIRED_FIELD_MISSING" not in result["quality"]["reasons"]


def test_ocr_fusion_required_table_matches_header_aliases() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "company_name", "fieldValue": "广东星燃石化设计院有限公司", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "project_name", "fieldValue": "项目", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "document_title", "fieldValue": "管道特性表", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "drawing_no", "fieldValue": "QX201903S-13-Y-07", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "design_phase", "fieldValue": "施工图", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "pipe_no", "fieldValue": "PL8301", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
            ],
            "tables": [
                {
                    "tableId": "model_table_1",
                    "structureConfidence": 0.84,
                    "bbox": [0, 0, 200, 100],
                    "cells": [
                        {"text": "管号", "isHeader": True},
                        {"text": "DN", "isHeader": True},
                        {"text": "设计压力", "isHeader": True},
                        {"text": "介质", "isHeader": True},
                    ],
                }
            ],
            "seals": [{"sealId": "seal_1", "sealName": "广东星燃石化设计院有限公司压力管道设计许可章", "ocrConfidence": 0.9, "bbox": [0, 0, 10, 10]}],
            "diagnostics": [],
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    assert result["quality"]["missingTables"] == []
    assert result["tables"][0]["matchedRequiredTable"] == "piping_characteristic_table"
    assert "REQUIRED_TABLE_MISSING" not in result["quality"]["reasons"]


def test_ocr_fusion_unmatched_table_does_not_satisfy_required_schema() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "report_no", "fieldValue": "RT-2026-001", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "project_name", "fieldValue": "项目", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "detection_method", "fieldValue": "RT", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "weld_no", "fieldValue": "W-001", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "detection_date", "fieldValue": "2026年6月30日", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "evaluation_level", "fieldValue": "II", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "conclusion", "fieldValue": "合格", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "inspection_unit", "fieldValue": "检测有限公司", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "seal", "fieldValue": "检测专用章", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
            ],
            "tables": [
                {
                    "tableId": "unrelated_material_table",
                    "structureConfidence": 0.95,
                    "bbox": [0, 0, 200, 100],
                    "cells": [
                        {"text": "化学成分", "isHeader": True},
                        {"text": "C", "isHeader": True},
                        {"text": "Si", "isHeader": True},
                    ],
                }
            ],
            "seals": [{"sealId": "seal_1", "sealName": "检测有限公司检验检测专用章", "sealType": "inspection_testing_seal", "ocrConfidence": 0.9, "bbox": [0, 0, 10, 10]}],
            "diagnostics": [],
        },
        profile=profile_for("ndt_rt_report_v1"),
    )

    assert result["quality"]["missingTables"] == ["weld_detection_result_table"]
    assert "REQUIRED_TABLE_MISSING" in result["quality"]["reasons"]
    assert "matchedRequiredTable" not in result["tables"][0]
    assert result["tables"][0]["candidateForRequiredTables"] == ["weld_detection_result_table"]
    assert "required_table_unmatched_candidate" in result["tables"][0]["qualityFlags"]


def test_ocr_fusion_required_table_matches_row_zero_headers_without_header_flag() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "report_no", "fieldValue": "RT-2026-001", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "project_name", "fieldValue": "项目", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "detection_method", "fieldValue": "RT", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "weld_no", "fieldValue": "W-001", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "detection_date", "fieldValue": "2026年6月30日", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "evaluation_level", "fieldValue": "II", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "conclusion", "fieldValue": "合格", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "inspection_unit", "fieldValue": "检测有限公司", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "seal", "fieldValue": "检测专用章", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
            ],
            "tables": [
                {
                    "tableId": "rt_table",
                    "structureConfidence": 0.9,
                    "bbox": [0, 0, 200, 100],
                    "cells": [
                        {"row": 0, "col": 0, "text": "焊口号"},
                        {"row": 0, "col": 1, "text": "检测方法"},
                        {"row": 0, "col": 2, "text": "评定级别"},
                        {"row": 1, "col": 0, "text": "W-001"},
                    ],
                }
            ],
            "seals": [{"sealId": "seal_1", "sealName": "检测有限公司检验检测专用章", "sealType": "inspection_testing_seal", "ocrConfidence": 0.9, "bbox": [0, 0, 10, 10]}],
            "diagnostics": [],
        },
        profile=profile_for("ndt_rt_report_v1"),
    )

    assert result["quality"]["missingTables"] == []
    assert result["tables"][0]["matchedRequiredTable"] == "weld_detection_result_table"
    assert "REQUIRED_TABLE_MISSING" not in result["quality"]["reasons"]


def test_ocr_fusion_merges_duplicate_required_table_matches() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "certificate_no", "fieldValue": "QC-001", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "manufacturer", "fieldValue": "河北广浩管件有限公司", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "material_grade", "fieldValue": "20#", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "specification", "fieldValue": "WN100", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "batch_no", "fieldValue": "B001", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "standard_no", "fieldValue": "HG/T20592-2009", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "inspection_conclusion", "fieldValue": "检验合格", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "issue_date", "fieldValue": "2021年3月18日", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "seal", "fieldValue": "质检专用章", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
            ],
            "tables": [
                {
                    "tableId": "docling_table_10",
                    "businessSchema": "material_chemical_composition_table",
                    "businessSchemas": ["material_chemical_composition_table", "mechanical_property_table"],
                    "structureConfidence": 0.9,
                    "bbox": [0, 0, 100, 100],
                    "cells": [
                        {"text": "化学成分", "isHeader": True},
                        {"text": "碳C", "isHeader": True},
                        {"text": "抗拉强度", "isHeader": True},
                        {"text": "延伸率", "isHeader": True},
                    ],
                }
            ],
            "seals": [{"sealId": "seal_1", "sealType": "quality_seal", "sealName": "质检专用章", "ocrConfidence": 0.9, "bbox": [0, 0, 10, 10]}],
            "diagnostics": [],
        },
        profile=profile_for("quality_certificate_v1"),
    )

    assert len(result["tables"]) == 1
    assert result["tables"][0]["matchedRequiredTables"] == [
        "material_chemical_composition_table",
        "mechanical_property_table",
    ]
    assert result["quality"]["missingTables"] == []


def test_ocr_fusion_visual_seal_only_requires_human_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "company_name", "fieldName": "公司名称", "fieldValue": "广东星燃石化设计院有限公司", "confidence": 0.9},
                {"fieldCode": "project_name", "fieldName": "项目名称", "fieldValue": "项目", "confidence": 0.9},
                {"fieldCode": "document_title", "fieldName": "文件标题", "fieldValue": "管道特性表", "confidence": 0.9},
                {"fieldCode": "drawing_no", "fieldName": "图纸编号", "fieldValue": "QX201903S-13-Y-07", "confidence": 0.9},
                {"fieldCode": "design_phase", "fieldName": "设计阶段", "fieldValue": "施工图", "confidence": 0.9},
                {"fieldCode": "pipe_no", "fieldName": "管道代号", "fieldValue": "PL8301", "confidence": 0.9},
            ],
            "tables": [{"tableId": "piping_characteristic_table_1", "structureConfidence": 0.8, "bbox": [0, 0, 10, 10]}],
            "seals": [
                {
                    "sealId": "red_candidate_1",
                    "sealName": "视觉印章候选",
                    "visualConfidence": 0.95,
                    "ocrConfidence": 0,
                    "bbox": [0, 0, 10, 10],
                    "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
                }
            ],
            "diagnostics": [],
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    assert result["quality"]["status"] == "needs_human_review"
    assert "SEAL_TEXT_LOW_CONFIDENCE" in result["quality"]["reasons"]


def test_ocr_fusion_field_value_conflict_requires_human_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    profile = {
        "profileId": "conflict_profile_v1",
        "documentType": "quality_certificate",
        "requiredFields": ["report_no"],
        "requiredTables": [],
        "sealRules": {"required": False},
        "qualityRules": {},
    }

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {
                    "fieldCode": "report_no",
                    "fieldName": "报告编号",
                    "fieldValue": "RT-2026-001",
                    "confidence": 0.92,
                    "sourceEngine": "paddle_ocr_subprocess",
                    "variantId": "page_1_original",
                    "bbox": [0, 0, 10, 10],
                },
                {
                    "fieldCode": "report_no",
                    "fieldName": "报告编号",
                    "fieldValue": "RT-2026-00I",
                    "confidence": 0.89,
                    "sourceEngine": "paddleocr_vl_1_6",
                    "variantId": "page_1_vlm",
                    "bbox": [0, 0, 10, 10],
                },
            ],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile,
    )

    assert result["quality"]["status"] == "needs_human_review"
    assert "FIELD_VALUE_CONFLICT" in result["quality"]["reasons"]
    assert result["fields"][0]["fusionDecision"] == "conflict_highest_confidence_candidate"
    assert "field_value_conflict" in result["fields"][0]["qualityFlags"]
    assert {item["normalizedValue"] for item in result["fields"][0]["conflictingValues"]} == {
        "RT-2026-001",
        "RT-2026-00I",
    }


def test_ocr_profile_critical_conflict_fields_drive_quality_gate() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    profile = profile_for("piping_characteristic_list_v1")
    assert "drawing_no" in profile["qualityRules"]["criticalConflictFields"]

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {
                    "fieldCode": "drawing_no",
                    "fieldValue": "QX201903S-13-Y-07",
                    "confidence": 0.93,
                    "sourceEngine": "paddle_ocr_subprocess",
                    "bbox": [0, 0, 10, 10],
                },
                {
                    "fieldCode": "drawing_no",
                    "fieldValue": "QX2019035-13-Y-07",
                    "confidence": 0.89,
                    "sourceEngine": "paddleocr_vl_1_6",
                    "bbox": [0, 0, 10, 10],
                },
            ],
            "tables": [{"tableId": "T1", "structureConfidence": 0.9, "bbox": [0, 0, 10, 10]}],
            "seals": [
                {
                    "sealId": "seal_1",
                    "sealName": "广东星燃石化设计院有限公司压力管道设计许可章",
                    "ocrConfidence": 0.9,
                    "bbox": [0, 0, 10, 10],
                }
            ],
            "diagnostics": [],
        },
        profile={**profile, "requiredFields": []},
    )

    assert "field_value_conflict" in result["fields"][0]["qualityFlags"]
    assert result["quality"]["status"] == "needs_human_review"
    assert "FIELD_VALUE_CONFLICT" in result["quality"]["reasons"]


def test_ocr_fusion_ignores_weak_field_value_conflict_candidate() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    profile = {
        "profileId": "conflict_profile_v1",
        "documentType": "quality_certificate",
        "requiredFields": ["report_no"],
        "requiredTables": [],
        "sealRules": {"required": False},
        "qualityRules": {},
    }

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {
                    "fieldCode": "report_no",
                    "fieldValue": "RT-2026-001",
                    "confidence": 0.94,
                    "sourceEngine": "paddle_ocr_subprocess",
                    "bbox": [0, 0, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
                {
                    "fieldCode": "report_no",
                    "fieldValue": "RT-2026-00I",
                    "confidence": 0.55,
                    "sourceEngine": "low_confidence_candidate",
                    "bbox": [0, 0, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
            ],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile,
    )

    assert result["quality"]["status"] == "auto_usable"
    assert "FIELD_VALUE_CONFLICT" not in result["quality"]["reasons"]
    assert result["fields"][0]["fusionDecision"] == "highest_confidence_candidate"
    assert "qualityFlags" not in result["fields"][0]


def test_ocr_fusion_prefers_valid_field_candidate_over_invalid_high_confidence() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {
                    "fieldCode": "report_no",
                    "fieldValue": "@@@",
                    "confidence": 0.96,
                    "sourceEngine": "noisy_ocr",
                    "bbox": [0, 0, 10, 10],
                },
                {
                    "fieldCode": "report_no",
                    "fieldValue": "RT-2026-001",
                    "confidence": 0.86,
                    "sourceEngine": "profile_regex",
                    "bbox": [0, 0, 10, 10],
                },
            ],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile={
            "profileId": "field_candidate_profile_v1",
            "documentType": "ndt_report",
            "requiredFields": ["report_no"],
            "requiredTables": [],
            "sealRules": {"required": False},
            "qualityRules": {"minFieldConfidence": 0.75, "criticalConflictFields": []},
        },
    )

    assert result["fields"][0]["fieldValue"] == "RT-2026-001"
    assert result["fields"][0]["sourceEngine"] == "profile_regex"
    assert result["quality"]["invalidFields"] == []
    assert "FIELD_FORMAT_INVALID" not in result["quality"]["reasons"]


def test_ocr_fusion_low_confidence_required_field_requires_human_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "company_name", "fieldName": "公司名称", "fieldValue": "广东星燃石化设计院有限公司", "confidence": 0.9},
                {"fieldCode": "project_name", "fieldName": "项目名称", "fieldValue": "项目", "confidence": 0.52},
                {"fieldCode": "document_title", "fieldName": "文件标题", "fieldValue": "管道特性表", "confidence": 0.9},
                {"fieldCode": "drawing_no", "fieldName": "图纸编号", "fieldValue": "QX201903S-13-Y-07", "confidence": 0.9},
                {"fieldCode": "design_phase", "fieldName": "设计阶段", "fieldValue": "施工图", "confidence": 0.9},
                {"fieldCode": "pipe_no", "fieldName": "管道代号", "fieldValue": "PL8301", "confidence": 0.9},
            ],
            "tables": [{"tableId": "T1", "structureConfidence": 0.9, "bbox": [0, 0, 10, 10]}],
            "seals": [
                {
                    "sealId": "seal_1",
                    "sealName": "广东星燃石化设计院有限公司压力管道设计许可章",
                    "ocrConfidence": 0.9,
                    "bbox": [0, 0, 10, 10],
                }
            ],
            "diagnostics": [],
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    assert result["quality"]["status"] == "needs_human_review"
    assert "FIELD_LOW_CONFIDENCE" in result["quality"]["reasons"]
    assert result["quality"]["lowConfidenceFields"] == [
        {
            "fieldCode": "project_name",
            "fieldName": "项目名称",
            "fieldValue": "项目",
            "confidence": 0.52,
            "threshold": 0.75,
            "sourceEngine": None,
            "variantId": None,
        }
    ]
    flagged = next(field for field in result["fields"] if field["fieldCode"] == "project_name")
    assert "field_low_confidence" in flagged["qualityFlags"]


def test_ocr_fusion_low_confidence_optional_field_does_not_block_auto_usable() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [{"fieldCode": "optional_note", "fieldValue": "备注", "confidence": 0.2}],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile={
            "profileId": "optional_profile_v1",
            "documentType": "generic_document",
            "requiredFields": [],
            "requiredTables": [],
            "sealRules": {"required": False},
            "qualityRules": {"minFieldConfidence": 0.75, "criticalConflictFields": []},
        },
    )

    assert result["quality"]["status"] == "auto_usable"
    assert "FIELD_LOW_CONFIDENCE" not in result["quality"]["reasons"]
    assert result["quality"]["lowConfidenceFields"] == []
    assert "qualityFlags" not in result["fields"][0]


def test_ocr_fusion_invalid_required_field_format_requires_human_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "report_no", "fieldName": "报告编号", "fieldValue": "@@@", "confidence": 0.95, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "issue_date", "fieldName": "签发日期", "fieldValue": "2026年13月40日", "confidence": 0.95, "bbox": [0, 0, 10, 10]},
            ],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile={
            "profileId": "field_format_profile_v1",
            "documentType": "quality_certificate",
            "requiredFields": ["report_no", "issue_date"],
            "requiredTables": [],
            "sealRules": {"required": False},
            "qualityRules": {"minFieldConfidence": 0.75, "criticalConflictFields": []},
        },
    )

    assert result["quality"]["status"] == "needs_human_review"
    assert "FIELD_FORMAT_INVALID" in result["quality"]["reasons"]
    assert {item["fieldCode"] for item in result["quality"]["invalidFields"]} == {"report_no", "issue_date"}
    assert {item["reason"] for item in result["quality"]["invalidFields"]} == {
        "identifier_has_invalid_characters",
        "date_out_of_range",
    }
    assert all("field_format_invalid" in field["qualityFlags"] for field in result["fields"])


def test_ocr_fusion_valid_business_field_formats_do_not_block_auto_usable() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {
                    "fieldCode": "report_no",
                    "fieldValue": "RT-2026-001",
                    "confidence": 0.95,
                    "bbox": [0, 0, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
                {
                    "fieldCode": "issue_date",
                    "fieldValue": "2026年6月30日",
                    "confidence": 0.95,
                    "bbox": [0, 0, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
                {
                    "fieldCode": "pipe_no",
                    "fieldValue": "PL8301,VT8302",
                    "confidence": 0.95,
                    "bbox": [0, 0, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
                {
                    "fieldCode": "design_pressure",
                    "fieldValue": "0.55MPa",
                    "confidence": 0.95,
                    "bbox": [0, 0, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
                {
                    "fieldCode": "detection_method",
                    "fieldValue": "RT",
                    "confidence": 0.95,
                    "bbox": [0, 0, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
                {
                    "fieldCode": "conclusion",
                    "fieldValue": "合格",
                    "confidence": 0.95,
                    "bbox": [0, 0, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                },
            ],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile={
            "profileId": "field_format_profile_v1",
            "documentType": "engineering_table_photo",
            "requiredFields": ["report_no", "issue_date", "pipe_no", "design_pressure", "detection_method", "conclusion"],
            "requiredTables": [],
            "sealRules": {"required": False},
            "qualityRules": {"minFieldConfidence": 0.75, "criticalConflictFields": []},
        },
    )

    assert result["quality"]["status"] == "auto_usable"
    assert result["quality"]["invalidFields"] == []
    assert "FIELD_FORMAT_INVALID" not in result["quality"]["reasons"]


def test_ocr_fusion_invalid_optional_field_format_does_not_block_auto_usable() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [{"fieldCode": "report_no", "fieldValue": "@@@", "confidence": 0.95, "bbox": [0, 0, 10, 10]}],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile={
            "profileId": "optional_field_format_profile_v1",
            "documentType": "generic_document",
            "requiredFields": [],
            "requiredTables": [],
            "sealRules": {"required": False},
            "qualityRules": {"minFieldConfidence": 0.75, "criticalConflictFields": []},
        },
    )

    assert result["quality"]["status"] == "auto_usable"
    assert result["quality"]["invalidFields"] == []
    assert "qualityFlags" not in result["fields"][0]


def test_ocr_fusion_missing_required_evidence_requires_human_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "company_name", "fieldName": "公司名称", "fieldValue": "广东星燃石化设计院有限公司", "confidence": 0.9},
                {"fieldCode": "project_name", "fieldName": "项目名称", "fieldValue": "项目", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "document_title", "fieldName": "文件标题", "fieldValue": "管道特性表", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "drawing_no", "fieldName": "图纸编号", "fieldValue": "QX201903S-13-Y-07", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "design_phase", "fieldName": "设计阶段", "fieldValue": "施工图", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "pipe_no", "fieldName": "管道代号", "fieldValue": "PL8301", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
            ],
            "tables": [{"tableId": "T1", "structureConfidence": 0.9}],
            "seals": [
                {
                    "sealId": "seal_1",
                    "sealName": "广东星燃石化设计院有限公司压力管道设计许可章",
                    "ocrConfidence": 0.9,
                }
            ],
            "diagnostics": [],
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    assert result["quality"]["status"] == "needs_human_review"
    assert {"FIELD_EVIDENCE_MISSING", "TABLE_EVIDENCE_MISSING", "SEAL_EVIDENCE_MISSING"}.issubset(
        set(result["quality"]["reasons"])
    )
    assert {item["targetType"] for item in result["quality"]["missingEvidence"]} == {"field", "table", "seal"}
    field = next(item for item in result["fields"] if item["fieldCode"] == "company_name")
    table = result["tables"][0]
    seal = result["seals"][0]
    assert "field_evidence_missing" in field["qualityFlags"]
    assert "table_evidence_missing" in table["qualityFlags"]
    assert "seal_evidence_missing" in seal["qualityFlags"]


def test_ocr_fusion_missing_optional_evidence_does_not_block_auto_usable() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [{"fieldCode": "optional_note", "fieldValue": "备注", "confidence": 0.9}],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile={
            "profileId": "optional_profile_v1",
            "documentType": "generic_document",
            "requiredFields": [],
            "requiredTables": [],
            "sealRules": {"required": False},
            "qualityRules": {"minFieldConfidence": 0.75, "criticalConflictFields": []},
        },
    )

    assert result["quality"]["status"] == "auto_usable"
    assert result["quality"]["missingEvidence"] == []
    assert "FIELD_EVIDENCE_MISSING" not in result["quality"]["reasons"]
    assert "qualityFlags" not in result["fields"][0]


def test_ocr_fusion_noncritical_optional_field_conflict_does_not_block_auto_usable() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    profile = {
        "profileId": "conflict_profile_v1",
        "documentType": "engineering_table_photo",
        "requiredFields": [],
        "requiredTables": [],
        "sealRules": {"required": False},
        "qualityRules": {},
    }

    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {
                    "fieldCode": "date",
                    "fieldValue": "2024年6月21日",
                    "confidence": 0.93,
                    "sourceEngine": "agentdesign_seal_ocr_subprocess",
                    "bbox": [0, 0, 10, 10],
                },
                {
                    "fieldCode": "date",
                    "fieldValue": "2017年8月31日",
                    "confidence": 0.9,
                    "sourceEngine": "agentdesign_seal_ocr_subprocess",
                    "bbox": [0, 0, 10, 10],
                },
            ],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile,
    )

    assert result["fields"][0]["fusionDecision"] == "conflict_highest_confidence_candidate"
    assert "field_value_conflict" in result["fields"][0]["qualityFlags"]
    assert result["quality"]["status"] == "auto_usable"
    assert "FIELD_VALUE_CONFLICT" not in result["quality"]["reasons"]


def test_ocr_fusion_heuristic_table_requires_human_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from libs.ocr.profiles import profile_for

    complete_fields = [
        {"fieldCode": "company_name", "fieldName": "公司名称", "fieldValue": "广东星燃石化设计院有限公司", "confidence": 0.9},
        {"fieldCode": "project_name", "fieldName": "项目名称", "fieldValue": "项目", "confidence": 0.9},
        {"fieldCode": "document_title", "fieldName": "文件标题", "fieldValue": "管道特性表", "confidence": 0.9},
        {"fieldCode": "drawing_no", "fieldName": "图纸编号", "fieldValue": "QX201903S-13-Y-07", "confidence": 0.9},
        {"fieldCode": "design_phase", "fieldName": "设计阶段", "fieldValue": "施工图", "confidence": 0.9},
        {"fieldCode": "pipe_no", "fieldName": "管道代号", "fieldValue": "PL8301", "confidence": 0.9},
    ]
    for index, field in enumerate(complete_fields):
        field["bbox"] = [index, index, index + 1, index + 1]
        field["pageNo"] = 1
        field["coordinateSystem"] = "rendered_pixels"
    result = fuse_parse_result(
        {
            "status": "success",
            "fields": complete_fields,
            "tables": [
                {
                    "tableId": "piping_characteristic_table_1",
                    "structureConfidence": 0.86,
                    "bbox": [0, 0, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                    "sourceEngine": "heuristic_table_from_ocr_fragments",
                    "qualityFlags": ["heuristic_table_fallback"],
                }
            ],
            "seals": [
                {
                    "sealId": "seal_1",
                    "sealName": "广东星燃石化设计院有限公司压力管道设计许可章",
                    "ocrConfidence": 0.88,
                    "bbox": [0, 0, 10, 10],
                    "pageNo": 1,
                    "coordinateSystem": "rendered_pixels",
                }
            ],
            "diagnostics": [],
        },
        profile=profile_for("piping_characteristic_list_v1"),
    )

    assert result["quality"]["status"] == "needs_human_review"
    assert result["quality"]["reasons"] == ["TABLE_HEURISTIC_REVIEW_REQUIRED"]


def test_ocr_evaluation_scores_fields_tables_seals_and_quality() -> None:
    from apps.ocr_service.evaluation import evaluate_cases

    report = evaluate_cases(
        [
            {
                "caseId": "piping-golden-001",
                "profileId": "piping_characteristic_list_v1",
                "minScore": 1,
                "result": {
                    "parseResultId": "PARSE-EVAL-001",
                    "status": "success",
                    "profileId": "piping_characteristic_list_v1",
                    "fields": [
                        {
                            "fieldCode": "pipe_no",
                            "fieldValue": "PL8301,VT8301",
                            "bbox": [0, 0, 100, 20],
                            "confidence": 0.94,
                        }
                    ],
                    "tables": [
                        {
                            "tableId": "table_1",
                            "businessSchema": "piping_characteristic_table_v1",
                            "rows": 3,
                            "columns": 4,
                            "bbox": [10, 40, 300, 180],
                            "businessRows": [{"pipeNo": "PL8301", "designPressure": "0.1"}],
                        }
                    ],
                    "seals": [
                        {
                            "sealId": "seal_1",
                            "sealName": "广东星燃石化设计院有限公司压力管道设计许可章",
                            "sealType": "pressure_pipe_design_license_seal",
                            "ocrConfidence": 0.9,
                            "bbox": [320, 200, 420, 300],
                        }
                    ],
                    "quality": {
                        "status": "needs_human_review",
                        "reasons": ["TABLE_HEURISTIC_REVIEW_REQUIRED"],
                        "evidenceCompleteness": 1.0,
                    },
                },
                "expected": {
                    "fields": [{"fieldCode": "pipe_no", "value": "PL8301,VT8301", "bbox": [0, 0, 100, 20]}],
                    "tables": [
                        {
                            "businessSchema": "piping_characteristic_table_v1",
                            "minRows": 2,
                            "requiredBusinessKeys": ["pipeNo", "designPressure"],
                            "bbox": [10, 40, 300, 180],
                        }
                    ],
                    "seals": [{"nameContains": "压力管道设计许可章", "minConfidence": 0.8, "bbox": [320, 200, 420, 300]}],
                    "qualityStatus": "needs_human_review",
                    "qualityReasons": ["TABLE_HEURISTIC_REVIEW_REQUIRED"],
                    "minEvidenceCompleteness": 1.0,
                },
            }
        ]
    )

    assert report["ok"] is True
    assert report["summary"]["averageScore"] == 1
    assert report["cases"][0]["metrics"]["fieldEvidenceRecall"] == 1
    assert report["cases"][0]["metrics"]["fieldBboxHitRate"] == 1
    assert report["cases"][0]["metrics"]["tableEvidenceRecall"] == 1
    assert report["cases"][0]["metrics"]["tableBboxHitRate"] == 1
    assert report["cases"][0]["metrics"]["sealEvidenceRecall"] == 1
    assert report["cases"][0]["metrics"]["sealBboxHitRate"] == 1
    assert report["cases"][0]["metrics"]["qualityEvidenceCompletenessMatch"] == 1
    assert report["cases"][0]["details"]["fields"][0]["status"] == "matched"
    assert report["cases"][0]["details"]["fields"][0]["bestIou"] == 1
    assert report["cases"][0]["details"]["tables"][0]["status"] == "matched"
    assert report["cases"][0]["details"]["seals"][0]["status"] == "matched"


def test_ocr_evaluation_reports_missing_expected_items() -> None:
    from apps.ocr_service.evaluation import evaluate_cases

    report = evaluate_cases(
        [
            {
                "caseId": "piping-golden-missing",
                "result": {
                    "parseResultId": "PARSE-EVAL-002",
                    "status": "success",
                    "fields": [],
                    "tables": [],
                    "seals": [],
                    "quality": {"status": "auto_usable", "reasons": []},
                },
                "expected": {
                    "fields": [{"fieldCode": "pipe_no", "value": "PL8301"}],
                    "tables": [{"businessSchema": "piping_characteristic_table_v1"}],
                    "seals": [{"nameContains": "设计许可章"}],
                    "qualityStatus": "needs_human_review",
                    "qualityReasons": ["SEAL_TEXT_LOW_CONFIDENCE"],
                },
            }
        ]
    )

    findings = {item["code"] for item in report["cases"][0]["findings"]}

    assert report["ok"] is False
    assert report["cases"][0]["score"] < 0.5
    assert report["findingCounts"]["OCR_EVAL_FIELD_MISSING"] == 1
    assert report["scenarios"]["default"]["findingCounts"]["OCR_EVAL_TABLE_MISSING"] == 1
    assert "OCR_EVAL_FIELD_MISSING" in findings
    assert "OCR_EVAL_TABLE_MISSING" in findings
    assert "OCR_EVAL_SEAL_MISSING" in findings
    assert "OCR_EVAL_QUALITY_STATUS_MISMATCH" in findings


def test_ocr_evaluation_reports_bbox_mismatch() -> None:
    from apps.ocr_service.evaluation import evaluate_cases

    report = evaluate_cases(
        [
            {
                "caseId": "bbox-mismatch",
                "minScore": 0,
                "result": {
                    "parseResultId": "PARSE-EVAL-BBOX",
                    "status": "success",
                    "fields": [{"fieldCode": "pipe_no", "fieldValue": "PL8301", "bbox": [0, 0, 10, 10]}],
                    "tables": [{"businessSchema": "piping_characteristic_table_v1", "bbox": [20, 20, 100, 100]}],
                    "seals": [{"sealName": "pressure pipe design license seal", "bbox": [120, 120, 200, 200], "ocrConfidence": 0.9}],
                    "quality": {"status": "auto_usable", "reasons": []},
                },
                "expected": {
                    "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [200, 200, 220, 220]}],
                    "tables": [{"businessSchema": "piping_characteristic_table_v1", "bbox": [220, 220, 320, 320]}],
                    "seals": [{"nameContains": "design license", "bbox": [340, 340, 420, 420]}],
                },
            }
        ]
    )

    findings = {item["code"] for item in report["cases"][0]["findings"]}

    assert report["ok"] is False
    assert report["cases"][0]["metrics"]["fieldBboxHitRate"] == 0
    assert report["cases"][0]["metrics"]["tableBboxHitRate"] == 0
    assert report["cases"][0]["metrics"]["sealBboxHitRate"] == 0
    assert report["cases"][0]["details"]["fields"][0]["status"] == "bbox_mismatch"
    assert report["cases"][0]["details"]["fields"][0]["candidates"][0]["iou"] == 0
    assert report["cases"][0]["details"]["tables"][0]["status"] == "bbox_mismatch"
    assert report["cases"][0]["details"]["seals"][0]["status"] == "bbox_mismatch"
    assert "OCR_EVAL_FIELD_BBOX_MISMATCH" in findings
    assert "OCR_EVAL_TABLE_BBOX_MISMATCH" in findings
    assert "OCR_EVAL_SEAL_BBOX_MISMATCH" in findings


def test_ocr_evaluation_requires_field_evidence_even_when_value_matches() -> None:
    from apps.ocr_service.evaluation import evaluate_cases

    report = evaluate_cases(
        [
            {
                "caseId": "field-value-without-evidence",
                "minScore": 0,
                "result": {
                    "parseResultId": "PARSE-EVAL-NO-FIELD-EVIDENCE",
                    "status": "success",
                    "fields": [{"fieldCode": "pipe_no", "fieldValue": "PL8301"}],
                    "tables": [],
                    "seals": [],
                    "quality": {"status": "auto_usable", "reasons": []},
                },
                "expected": {
                    "fields": [{"fieldCode": "pipe_no", "value": "PL8301"}],
                },
            }
        ]
    )

    findings = {item["code"] for item in report["cases"][0]["findings"]}

    assert report["ok"] is False
    assert report["cases"][0]["metrics"]["fieldRecall"] == 1
    assert report["cases"][0]["metrics"]["fieldValueAccuracy"] == 1
    assert report["cases"][0]["metrics"]["fieldEvidenceRecall"] == 0
    assert "OCR_EVAL_FIELD_EVIDENCE_MISSING" in findings


def test_ocr_evaluation_requires_table_and_seal_evidence_when_matched() -> None:
    from apps.ocr_service.evaluation import evaluate_cases

    report = evaluate_cases(
        [
            {
                "caseId": "table-seal-without-evidence",
                "minScore": 0,
                "result": {
                    "parseResultId": "PARSE-EVAL-NO-TABLE-SEAL-EVIDENCE",
                    "status": "success",
                    "fields": [],
                    "tables": [
                        {
                            "tableId": "table_1",
                            "businessSchema": "piping_characteristic_table_v1",
                            "businessRows": [{"pipeNo": "PL8301"}],
                        }
                    ],
                    "seals": [{"sealName": "pressure pipe design license seal", "ocrConfidence": 0.9}],
                    "quality": {"status": "auto_usable", "reasons": []},
                },
                "expected": {
                    "tables": [
                        {
                            "businessSchema": "piping_characteristic_table_v1",
                            "requiredBusinessKeys": ["pipeNo"],
                        }
                    ],
                    "seals": [{"nameContains": "design license", "minConfidence": 0.8}],
                },
            }
        ]
    )

    findings = {item["code"] for item in report["cases"][0]["findings"]}

    assert report["ok"] is False
    assert report["cases"][0]["metrics"]["tableRecall"] == 1
    assert report["cases"][0]["metrics"]["tableEvidenceRecall"] == 0
    assert report["cases"][0]["metrics"]["sealRecall"] == 1
    assert report["cases"][0]["metrics"]["sealEvidenceRecall"] == 0
    assert report["cases"][0]["details"]["tables"][0]["status"] == "evidence_missing"
    assert report["cases"][0]["details"]["seals"][0]["status"] == "evidence_missing"
    assert "OCR_EVAL_TABLE_EVIDENCE_MISSING" in findings
    assert "OCR_EVAL_SEAL_EVIDENCE_MISSING" in findings


def test_ocr_evaluation_can_gate_fragment_seal_source_flags_and_fields() -> None:
    from apps.ocr_service.evaluation import evaluate_cases

    report = evaluate_cases(
        [
            {
                "caseId": "fragment-seal-contract",
                "result": {
                    "parseResultId": "PARSE-EVAL-FRAGMENT-SEAL",
                    "status": "success",
                    "seals": [
                        {
                            "sealId": "red_candidate_1",
                            "sealType": "design_license_seal",
                            "sealName": "压力管道 杨道红 TS1810648-2021 2017年8月31日",
                            "sourceEngine": "fragment_seal_text_fusion",
                            "bbox": [600, 420, 760, 560],
                            "ocrConfidence": 0.88,
                            "qualityFlags": ["fragment_seal_text"],
                            "fields": [
                                {
                                    "fieldCode": "seal_text",
                                    "fieldValue": "压力管道 杨道红 TS1810648-2021 2017年8月31日",
                                    "confidence": 0.88,
                                },
                                {"fieldCode": "license_no", "fieldValue": "TS1810648-2021", "confidence": 0.88},
                            ],
                        }
                    ],
                    "quality": {"status": "auto_usable", "reasons": [], "evidenceCompleteness": 1.0},
                },
                "expected": {
                    "seals": [
                        {
                            "sealType": "design_license_seal",
                            "sourceEngine": "fragment_seal_text_fusion",
                            "nameContains": "TS1810648-2021",
                            "minConfidence": 0.8,
                            "qualityFlags": ["fragment_seal_text"],
                            "bbox": [600, 420, 760, 560],
                            "bboxIouThreshold": 0.9,
                            "fields": [
                                {"fieldCode": "seal_text", "value": "压力管道", "contains": True},
                                {"fieldCode": "license_no", "value": "TS1810648-2021"},
                            ],
                        }
                    ],
                    "qualityStatus": "auto_usable",
                    "minEvidenceCompleteness": 1.0,
                },
            }
        ]
    )

    assert report["ok"] is True
    assert report["cases"][0]["metrics"]["sealRecall"] == 1
    assert report["cases"][0]["details"]["seals"][0]["status"] == "matched"


def test_ocr_evaluation_rejects_fragment_seal_without_expected_source_or_fields() -> None:
    from apps.ocr_service.evaluation import evaluate_cases

    report = evaluate_cases(
        [
            {
                "caseId": "fragment-seal-source-mismatch",
                "minScore": 0,
                "result": {
                    "parseResultId": "PARSE-EVAL-FRAGMENT-SEAL-MISMATCH",
                    "status": "success",
                    "seals": [
                        {
                            "sealId": "red_candidate_1",
                            "sealType": "design_license_seal",
                            "sealName": "压力管道 杨道红",
                            "sourceEngine": "visual_red_seal_candidate",
                            "bbox": [600, 420, 760, 560],
                            "ocrConfidence": 0.88,
                            "qualityFlags": ["visual_candidate_only"],
                            "fields": [{"fieldCode": "seal_text", "fieldValue": "压力管道 杨道红"}],
                        }
                    ],
                    "quality": {"status": "auto_usable", "reasons": [], "evidenceCompleteness": 1.0},
                },
                "expected": {
                    "seals": [
                        {
                            "sealType": "design_license_seal",
                            "sourceEngine": "fragment_seal_text_fusion",
                            "qualityFlags": ["fragment_seal_text"],
                            "fields": [{"fieldCode": "license_no", "value": "TS1810648-2021"}],
                            "bbox": [600, 420, 760, 560],
                        }
                    ],
                },
            }
        ]
    )

    findings = {item["code"] for item in report["cases"][0]["findings"]}

    assert report["ok"] is False
    assert report["cases"][0]["metrics"]["sealRecall"] == 0
    assert report["cases"][0]["details"]["seals"][0]["status"] == "missing"
    assert "OCR_EVAL_SEAL_MISSING" in findings


def test_ocr_evaluation_checks_quality_evidence_completeness_range() -> None:
    from apps.ocr_service.evaluation import evaluate_cases

    report = evaluate_cases(
        [
            {
                "caseId": "quality-evidence-completeness-mismatch",
                "minScore": 0,
                "result": {
                    "parseResultId": "PARSE-EVAL-QUALITY-EVIDENCE-RANGE",
                    "status": "success",
                    "fields": [],
                    "tables": [],
                    "seals": [],
                    "quality": {"status": "needs_human_review", "reasons": [], "evidenceCompleteness": 1.0},
                },
                "expected": {
                    "qualityStatus": "needs_human_review",
                    "maxEvidenceCompleteness": 0.5,
                },
            }
        ]
    )

    findings = {item["code"] for item in report["cases"][0]["findings"]}
    quality_detail = report["cases"][0]["details"]["quality"]

    assert report["ok"] is False
    assert report["cases"][0]["metrics"]["qualityEvidenceCompletenessMatch"] == 0
    assert quality_detail["actualEvidenceCompleteness"] == 1.0
    assert quality_detail["expectedMaxEvidenceCompleteness"] == 0.5
    assert quality_detail["evidenceCompletenessStatus"] == "range_mismatch"
    assert report["findingCounts"]["OCR_EVAL_QUALITY_EVIDENCE_COMPLETENESS_MISMATCH"] == 1
    assert "OCR_EVAL_QUALITY_EVIDENCE_COMPLETENESS_MISMATCH" in findings


def test_ocr_eval_markdown_report_summarizes_findings_and_quality_range() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_eval_set.py"
    spec = importlib.util.spec_from_file_location("ocr_eval_set_markdown", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = {
        "ok": False,
        "summary": {"cases": 1, "passed": 0, "failed": 1, "averageScore": 0.5},
        "metrics": {"qualityEvidenceCompletenessMatch": 0},
        "findingCounts": {"OCR_EVAL_QUALITY_EVIDENCE_COMPLETENESS_MISMATCH": 1},
        "thresholdFailures": [],
        "scenarios": {},
        "cases": [
            {
                "caseId": "quality-range",
                "scenario": "evidence_profile",
                "score": 0.5,
                "qualityStatus": "needs_human_review",
                "passed": False,
                "findings": [{"code": "OCR_EVAL_QUALITY_EVIDENCE_COMPLETENESS_MISMATCH"}],
                "details": {
                    "quality": {
                        "status": "matched",
                        "expectedStatus": "needs_human_review",
                        "actualStatus": "needs_human_review",
                        "missingReasons": [],
                        "evidenceCompletenessStatus": "range_mismatch",
                        "actualEvidenceCompleteness": 1.0,
                        "expectedMaxEvidenceCompleteness": 0.5,
                    }
                },
            }
        ],
    }

    markdown = module.markdown_report(report, eval_set_name="unit")

    assert "## Finding Summary" in markdown
    assert "OCR_EVAL_QUALITY_EVIDENCE_COMPLETENESS_MISMATCH" in markdown
    assert "evidenceCompleteness actual=1.0000" in markdown


def test_ocr_eval_compact_summary_preserves_gate_findings() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_eval_set.py"
    spec = importlib.util.spec_from_file_location("ocr_eval_set_compact_summary", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = {
        "ok": False,
        "summary": {"cases": 1, "passed": 0, "failed": 1, "averageScore": 0.5},
        "metrics": {"fieldRecall": 0.5},
        "findingCounts": {"OCR_EVAL_FIELD_MISSING": 1},
        "thresholdFailures": [{"scope": "overall", "metric": "averageScore", "actual": 0.5, "minimum": 0.98}],
        "scenarios": {
            "piping_table_profile": {
                "ok": False,
                "cases": 1,
                "passed": 0,
                "failed": 1,
                "averageScore": 0.5,
                "findingCounts": {"OCR_EVAL_FIELD_MISSING": 1},
                "thresholdFailures": [
                    {"scope": "piping_table_profile", "metric": "fieldRecall", "actual": 0.5, "minimum": 0.98}
                ],
                "metrics": {"fieldRecall": 0.5},
            }
        },
        "cases": [
            {
                "caseId": "missing-field",
                "scenario": "piping_table_profile",
                "score": 0.5,
                "minScore": 0.98,
                "passed": False,
                "qualityStatus": "needs_human_review",
                "findings": [{"code": "OCR_EVAL_FIELD_MISSING"}],
                "details": {"fields": [{"status": "missing"}]},
            }
        ],
    }

    summary = module.compact_evaluation_report(report)

    assert summary["ok"] is False
    assert summary["findingCounts"] == {"OCR_EVAL_FIELD_MISSING": 1}
    assert summary["thresholdFailures"][0]["metric"] == "averageScore"
    assert summary["scenarioMetrics"]["piping_table_profile"]["findingCounts"] == {"OCR_EVAL_FIELD_MISSING": 1}
    assert summary["failedCases"] == [
        {
            "caseId": "missing-field",
            "scenario": "piping_table_profile",
            "score": 0.5,
            "minScore": 0.98,
            "qualityStatus": "needs_human_review",
            "findings": ["OCR_EVAL_FIELD_MISSING"],
        }
    ]


def test_ocr_eval_set_resolves_relative_paths_from_eval_set_directory(tmp_path) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_eval_set.py"
    spec = importlib.util.spec_from_file_location("ocr_eval_set_paths", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    eval_dir = tmp_path / "release"
    fixture_dir = eval_dir / "fixtures"
    fixture_dir.mkdir(parents=True)
    result_path = fixture_dir / "result.json"
    source_path = fixture_dir / "sample.png"
    result_path.write_text("{}", encoding="utf-8")
    source_path.write_bytes(b"image")

    normalized = module.normalize_case_paths(
        [
            {"caseId": "relative", "resultPath": "fixtures/result.json", "source": "fixtures/sample.png"},
            {"caseId": "absolute", "resultPath": str(result_path), "source": str(source_path)},
            {"caseId": "uri", "resultPath": "minio://documents/result.json", "source": "minio://documents/sample.png"},
        ],
        base_dir=eval_dir,
        resolve_sources=True,
    )

    assert normalized[0]["resultPath"] == str(result_path.resolve())
    assert normalized[0]["source"] == str(source_path.resolve())
    assert normalized[1]["resultPath"] == str(result_path)
    assert normalized[1]["source"] == str(source_path)
    assert normalized[2]["resultPath"] == "minio://documents/result.json"
    assert normalized[2]["source"] == "minio://documents/sample.png"


def test_ocr_eval_set_can_force_disable_result_cache() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_eval_set.py"
    spec = importlib.util.spec_from_file_location("ocr_eval_set_options", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cases = module.with_ocr_option(
        [
            {"caseId": "plain"},
            {"caseId": "existing", "options": {"foo": "bar"}},
        ],
        "disableResultCache",
        True,
    )

    assert cases[0]["options"] == {"disableResultCache": True}
    assert cases[1]["options"] == {"foo": "bar", "disableResultCache": True}


def test_ocr_eval_set_creates_report_output_directories(tmp_path) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_eval_set.py"
    spec = importlib.util.spec_from_file_location("ocr_eval_set_output_dirs", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = {
        "ok": True,
        "summary": {"cases": 0, "passed": 0, "failed": 0, "averageScore": 1.0},
        "metrics": {},
        "findingCounts": {},
        "thresholdFailures": [],
        "scenarios": {},
        "cases": [],
    }
    json_output = tmp_path / "nested" / "reports" / "eval.json"
    markdown_output = tmp_path / "nested" / "reports" / "eval.md"

    module.write_text_file(json_output, json.dumps(report, ensure_ascii=False, indent=2))
    module.write_text_file(markdown_output, module.markdown_report(report, eval_set_name="unit"))

    assert json.loads(json_output.read_text(encoding="utf-8"))["ok"] is True
    assert "# OCR Evaluation Report: unit" in markdown_output.read_text(encoding="utf-8")


def test_ocr_evaluation_enforces_scenario_thresholds() -> None:
    from apps.ocr_service.evaluation import evaluate_cases

    report = evaluate_cases(
        [
            {
                "caseId": "seal-low-score",
                "scenario": "seal_text_profile",
                "minScore": 0,
                "result": {
                    "parseResultId": "PARSE-EVAL-THRESHOLD",
                    "status": "success",
                    "fields": [],
                    "tables": [],
                    "seals": [{"sealName": "visual seal candidate", "visualConfidence": 0.9}],
                    "quality": {"status": "needs_human_review", "reasons": ["SEAL_TEXT_LOW_CONFIDENCE"]},
                },
                "expected": {
                    "seals": [{"nameContains": "design license", "minConfidence": 0.8}],
                    "qualityStatus": "needs_human_review",
                    "qualityReasons": ["SEAL_TEXT_LOW_CONFIDENCE"],
                },
            }
        ],
        thresholds={
            "averageScore": 0.8,
            "metrics": {"sealRecall": 0.98},
            "scenarios": {
                "seal_text_profile": {
                    "averageScore": 0.8,
                    "metrics": {"sealRecall": 0.98},
                }
            },
        },
    )

    scenario_failures = report["scenarios"]["seal_text_profile"]["thresholdFailures"]

    assert report["ok"] is False
    assert "sealRecall" in {item["metric"] for item in report["thresholdFailures"]}
    assert scenario_failures[0]["scope"] == "seal_text_profile"
    assert "sealRecall" in {item["metric"] for item in scenario_failures}


def test_ocr_evaluation_enforces_min_cases_and_required_scenarios() -> None:
    from apps.ocr_service.evaluation import evaluate_cases

    report = evaluate_cases(
        [
            {
                "caseId": "perfect-piping",
                "scenario": "piping_table_profile",
                "minScore": 0,
                "result": {
                    "parseResultId": "PARSE-EVAL-SCALE",
                    "status": "success",
                    "fields": [{"fieldCode": "pipe_no", "fieldValue": "PL8301", "bbox": [0, 0, 10, 10]}],
                    "tables": [{"businessSchema": "piping_characteristic_table_v1", "bbox": [0, 0, 20, 20]}],
                    "seals": [],
                    "quality": {"status": "auto_usable", "reasons": [], "evidenceCompleteness": 1.0},
                },
                "expected": {
                    "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [0, 0, 10, 10]}],
                    "tables": [{"businessSchema": "piping_characteristic_table_v1", "bbox": [0, 0, 20, 20]}],
                    "qualityStatus": "auto_usable",
                    "minEvidenceCompleteness": 1.0,
                },
            }
        ],
        thresholds={
            "minCases": 2,
            "requiredScenarios": ["piping_table_profile", "seal_text_profile"],
            "scenarios": {"piping_table_profile": {"minCases": 2}},
        },
    )

    assert report["ok"] is False
    assert {"cases", "scenario.seal_text_profile"} <= {item["metric"] for item in report["thresholdFailures"]}
    assert report["scenarios"]["piping_table_profile"]["thresholdFailures"][0]["metric"] == "cases"


def test_ocr_100_thresholds_merge_keeps_stricter_custom_gates() -> None:
    from apps.ocr_service.evaluation import merge_thresholds, ocr_100_thresholds

    merged = merge_thresholds(
        {
            "averageScore": 0.98,
            "metrics": {"fieldRecall": 0.99},
            "requiredScenarios": ["custom_profile"],
            "scenarios": {"custom_profile": {"averageScore": 0.99}},
        },
        ocr_100_thresholds(),
    )

    assert merged["averageScore"] == 0.98
    assert merged["minCases"] == 100
    assert merged["metrics"]["fieldRecall"] == 0.99
    assert "custom_profile" in merged["requiredScenarios"]
    assert "piping_table_profile" in merged["requiredScenarios"]
    assert merged["scenarios"]["custom_profile"]["averageScore"] == 0.99
    assert merged["scenarios"]["piping_table_profile"]["minCases"] == 1


def test_ocr_eval_cli_strict_100_rejects_small_fixture_set(monkeypatch, tmp_path) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ocr_eval_set.py"
    spec = importlib.util.spec_from_file_location("ocr_eval_set_strict_100", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    eval_set = tmp_path / "eval.json"
    eval_set.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "small",
                        "scenario": "piping_table_profile",
                        "minScore": 0,
                        "result": {
                            "status": "success",
                            "fields": [{"fieldCode": "pipe_no", "fieldValue": "PL8301", "bbox": [0, 0, 10, 10]}],
                            "tables": [{"businessSchema": "piping_characteristic_table_v1", "bbox": [0, 0, 20, 20]}],
                            "seals": [],
                            "quality": {"status": "auto_usable", "evidenceCompleteness": 1.0, "reasons": []},
                        },
                        "expected": {
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [0, 0, 10, 10]}],
                            "tables": [{"businessSchema": "piping_characteristic_table_v1", "bbox": [0, 0, 20, 20]}],
                            "qualityStatus": "auto_usable",
                            "minEvidenceCompleteness": 1.0,
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["ocr_eval_set.py", str(eval_set), "--strict-100"])

    assert module.main() == 1


def test_ocr_100_scorecard_scores_perfect_gate() -> None:
    from apps.ocr_service.evaluation import OCR_100_REQUIRED_SCENARIOS, ocr_100_thresholds
    from apps.ocr_service.readiness import OCR_100_REQUIRED_ENGINES, build_ocr_100_scorecard

    thresholds = ocr_100_thresholds()
    evaluation_report = {
        "ok": True,
        "summary": {"cases": 100, "passed": 100, "failed": 0, "averageScore": 0.99},
        "metrics": {metric: 1.0 for metric in thresholds["metrics"]},
        "findingCounts": {},
        "thresholdFailures": [],
        "scenarios": {
            scenario: {"ok": True, "cases": 1, "passed": 1, "failed": 0, "averageScore": 0.99}
            for scenario in OCR_100_REQUIRED_SCENARIOS
        },
        "cases": [],
    }
    runtime_doctor = {
        "checks": [
            *[
                {"name": f"engine.{engine}", "status": "pass"}
                for engine in OCR_100_REQUIRED_ENGINES
            ],
            {"name": "policy.offline-only", "status": "pass"},
            {"name": "policy.network-disabled", "status": "pass"},
            {"name": "policy.placeholder-disabled", "status": "pass"},
        ]
    }
    sample = {
        "gatePassed": True,
        "qualityStatus": "auto_usable",
        "missingExpectedSealTypeCount": 0,
        "fields": 6,
        "formalTables": 1,
        "businessRows": 10,
        "readableSeals": 1,
        "fragmentSeals": 1,
        "evidenceCompleteness": 1.0,
    }

    scorecard = build_ocr_100_scorecard(
        evaluation_report=evaluation_report,
        runtime_doctor=runtime_doctor,
        sample_summaries=[sample],
    )

    assert scorecard["ok"] is True
    assert scorecard["score"] == 100
    assert scorecard["blockers"] == []


def test_ocr_100_scorecard_exposes_runtime_and_corpus_gaps() -> None:
    from apps.ocr_service.readiness import build_ocr_100_scorecard

    scorecard = build_ocr_100_scorecard(
        evaluation_report={
            "ok": False,
            "summary": {"cases": 7, "passed": 7, "failed": 0, "averageScore": 1.0},
            "metrics": {"fieldRecall": 1.0},
            "findingCounts": {},
            "thresholdFailures": [],
            "scenarios": {"piping_table_profile": {"ok": True, "cases": 1, "averageScore": 1.0}},
            "cases": [],
        },
        runtime_doctor={"checks": [{"name": "engine.paddle_ocr_subprocess", "status": "pass"}]},
        sample_summaries=[],
    )

    assert scorecard["ok"] is False
    assert scorecard["score"] < 100
    assert any("pp_structure_v3" in blocker for blocker in scorecard["blockers"])
    assert any("fewer than 100 cases" in blocker for blocker in scorecard["blockers"])
    assert any("sample probe summaries are missing" in blocker for blocker in scorecard["blockers"])


def test_ocr_100_scorecard_accepts_official_provider_capabilities() -> None:
    from apps.ocr_service.evaluation import OCR_100_REQUIRED_SCENARIOS, ocr_100_thresholds
    from apps.ocr_service.readiness import build_ocr_100_scorecard

    thresholds = ocr_100_thresholds()
    report = {
        "ok": True,
        "summary": {"cases": 100, "passed": 100, "failed": 0, "averageScore": 0.99},
        "metrics": {metric: 1.0 for metric in thresholds["metrics"]},
        "findingCounts": {},
        "thresholdFailures": [],
        "scenarios": {
            scenario: {"ok": True, "cases": 8, "passed": 8, "failed": 0, "averageScore": 0.99}
            for scenario in OCR_100_REQUIRED_SCENARIOS
        },
        "cases": [],
    }
    runtime = {
        "serviceReadiness": {
            "ocr": {
                "configured": True,
                "providerMode": "official",
                "localHeavyFallbackEnabled": False,
                "silentFallbackEnabled": False,
                "capacityControl": {"distributed": True, "ready": True},
            }
        },
        "officialOcrTelemetry": {"lastSuccessfulInferenceAt": "2026-07-12T00:00:00Z"},
    }
    sample = {
        "gatePassed": True,
        "qualityStatus": "auto_usable",
        "missingExpectedSealTypeCount": 0,
        "fields": 6,
        "formalTables": 1,
        "businessRows": 10,
        "readableSeals": 1,
        "fragmentSeals": 1,
        "evidenceCompleteness": 1.0,
    }

    scorecard = build_ocr_100_scorecard(
        evaluation_report=report,
        runtime_doctor=runtime,
        sample_summaries=[sample],
        runtime_profile="official",
    )

    assert scorecard["ok"] is True
    assert scorecard["runtimeProfile"] == "official"


def test_ocr_100_scorecard_rejects_fixture_derived_cases() -> None:
    from apps.ocr_service.evaluation import OCR_100_REQUIRED_SCENARIOS, ocr_100_thresholds
    from apps.ocr_service.readiness import OCR_100_REQUIRED_ENGINES, build_ocr_100_scorecard

    thresholds = ocr_100_thresholds()
    scorecard = build_ocr_100_scorecard(
        evaluation_report={
            "ok": True,
            "summary": {"cases": 100, "passed": 100, "failed": 0, "averageScore": 1.0},
            "metrics": {metric: 1.0 for metric in thresholds["metrics"]},
            "findingCounts": {},
            "thresholdFailures": [],
            "scenarios": {
                scenario: {"ok": True, "cases": 1, "passed": 1, "failed": 0, "averageScore": 1.0}
                for scenario in OCR_100_REQUIRED_SCENARIOS
            },
            "cases": [{"caseId": "fixture", "fixtureDerived": True}],
        },
        runtime_doctor={
            "checks": [
                *[
                    {"name": f"engine.{engine}", "status": "pass"}
                    for engine in OCR_100_REQUIRED_ENGINES
                ],
                {"name": "policy.offline-only", "status": "pass"},
                {"name": "policy.network-disabled", "status": "pass"},
                {"name": "policy.placeholder-disabled", "status": "pass"},
            ]
        },
        sample_summaries=[
            {
                "gatePassed": True,
                "qualityStatus": "auto_usable",
                "missingExpectedSealTypeCount": 0,
                "fields": 6,
                "formalTables": 1,
                "businessRows": 10,
                "readableSeals": 1,
                "fragmentSeals": 1,
                "evidenceCompleteness": 1.0,
            }
        ],
    )

    assert scorecard["ok"] is False
    assert scorecard["sections"][1]["status"] == "fail"
    assert any("fixture-derived" in blocker for blocker in scorecard["blockers"])


def test_ocr_service_adds_quality_variants_and_engine_run_metadata(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService
    from libs.ocr.profiles import profile_for

    class FakeEngine:
        name = "paddle_ocr_subprocess"
        version = "test"

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, source_path, *, file_name=None, profile=None, variant=None):
            return {
                "ok": True,
                "fragments": [
                    {
                        "pageNo": 1,
                        "text": "管道特性表 PL8301 PL8302",
                        "bbox": [[0, 0], [200, 0], [200, 20], [0, 20]],
                        "confidence": 0.94,
                    }
                ],
                "fields": [
                    {
                        "fieldCode": "document_title",
                        "fieldName": "文件标题",
                        "fieldValue": "管道特性表",
                        "bbox": [0, 0, 200, 20],
                        "confidence": 0.94,
                    }
                ],
                "diagnostics": [],
            }

    source = tmp_path / "sample.png"
    source.write_bytes(b"not-a-real-image")
    monkeypatch.setattr(
        "apps.ocr_service.service.probe_page_quality",
        lambda source_path, profile=None: [
            {
                "pageNo": 1,
                "quality": {
                    "isImageReadable": True,
                    "isLowQuality": False,
                    "hasTableCandidate": True,
                    "hasSealCandidate": False,
                },
            }
        ],
    )
    monkeypatch.setattr(
        "apps.ocr_service.service.generate_image_variants",
        lambda source_path, profile, page_quality, options=None: [
            {
                "variantId": "page_1_original",
                "pageNo": 1,
                "path": str(source_path),
                "preprocessChain": ["original"],
                "imageHash": "sha256:test",
                "purpose": "general",
                "source": "original",
            }
        ],
    )
    service = OcrService()
    service.pipeline = None
    service.engines = [FakeEngine()]

    result = service.parse_with_local_engines(
        source,
        storage_key=str(source),
        file_name="sample.png",
        profile=profile_for("piping_characteristic_list_v1"),
        document_version_id="docv_test",
        business_pack_id="engineering_inspection_v1",
        options={},
    )

    assert result["status"] == "success"
    assert result["pageQuality"][0]["quality"]["hasTableCandidate"] is True
    assert result["imageVariants"][0]["variantId"] == "page_1_original"
    assert result["engineRuns"][0]["variantId"] == "page_1_original"
    assert result["fields"][0]["candidates"][0]["variantId"] == "page_1_original"
    assert result["quality"]["status"] in {"auto_usable", "needs_human_review"}


def test_litellm_client_rejects_default_key_when_production_flags_are_enabled(monkeypatch) -> None:
    from libs.integrations.litellm_client import LiteLLMClient

    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")

    try:
        LiteLLMClient()
    except RuntimeError as exc:
        assert "LITELLM_API_KEY" in str(exc)
    else:
        raise AssertionError("production LiteLLM client must require an explicit key")

    client_with_key = LiteLLMClient(api_key="sk-production-test")
    assert client_with_key.api_key == "sk-production-test"


def test_ocr_client_sanitizes_http_and_business_errors() -> None:
    from libs.integrations.errors import IntegrationServiceError
    from libs.integrations.ocr_client import OcrClient

    def http_failure(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"message": "upstream OCR failed with sk-secret-ocr"})

    http_client = OcrClient(base_url="http://ocr", transport=httpx.MockTransport(http_failure))
    try:
        http_client.parse_sync("minio://documents/source.pdf")
    except IntegrationServiceError as exc:
        assert exc.status_code == 502
        assert "HTTP 502" in str(exc)
        assert "sk-secret-ocr" not in str(exc)
    else:
        raise AssertionError("OCR HTTP failure must raise a sanitized integration error")

    def business_failure(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 40001,
                "message": "source unavailable sk-secret-provider",
                "data": {"reason": "VALIDATION_ERROR"},
            },
        )

    business_client = OcrClient(base_url="http://ocr", transport=httpx.MockTransport(business_failure))
    try:
        business_client.parse_sync("minio://documents/source.pdf")
    except IntegrationServiceError as exc:
        assert exc.reason == "VALIDATION_ERROR"
        assert "VALIDATION_ERROR" in str(exc)
        assert "sk-secret-provider" not in str(exc)
    else:
        raise AssertionError("OCR business failure must raise a sanitized integration error")


def test_ocr_client_reads_runtime_doctor() -> None:
    from libs.integrations.ocr_client import OcrClient

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/ocr/doctor"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "schemaVersion": "aicheck-ocr-runtime-doctor-v1",
                    "ok": True,
                    "summary": {"pass": 1, "warn": 0, "fail": 0, "total": 1},
                    "checks": [],
                },
            },
        )

    client = OcrClient(base_url="http://ocr", transport=httpx.MockTransport(handler))
    report = client.runtime_doctor()

    assert report["ok"] is True
    assert report["schemaVersion"] == "aicheck-ocr-runtime-doctor-v1"


def test_ocr_client_parse_sync_sends_profile_and_options_payload() -> None:
    from libs.integrations.ocr_client import OcrClient

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"code": 0, "data": {"status": "success", "fragments": []}})

    http_client = OcrClient(base_url="http://ocr", transport=httpx.MockTransport(handler))
    result = http_client.parse_sync(
        "minio://documents/source.pdf",
        file_name="source.pdf",
        profile_id="quality_certificate_v1",
        document_type="quality_certificate",
        document_version_id="DOCV-CLIENT-001",
        options={"deepScanPdf": True},
    )

    assert result["status"] == "success"
    assert captured["storageKey"] == "minio://documents/source.pdf"
    assert captured["profileId"] == "quality_certificate_v1"
    assert captured["documentType"] == "quality_certificate"
    assert captured["documentVersionId"] == "DOCV-CLIENT-001"
    assert captured["options"]["deepScanPdf"] is True


def test_ocr_client_job_sync_returns_structured_failure_diagnostics() -> None:
    from libs.integrations.ocr_client import OcrClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/internal/document-parse/jobs":
            return httpx.Response(200, json={"code": 0, "data": {"jobId": "OCRJOB-FAIL"}})
        if request.method == "GET" and request.url.path == "/internal/document-parse/jobs/OCRJOB-FAIL":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "jobId": "OCRJOB-FAIL",
                        "status": "failed",
                        "diagnostics": ["engine failed"],
                    },
                },
            )
        raise AssertionError(f"unexpected OCR client request: {request.method} {request.url.path}")

    ocr_client = OcrClient(base_url="http://ocr", transport=httpx.MockTransport(handler))
    result = ocr_client.parse_via_job_sync({"storageKey": "minio://documents/source.pdf"})

    assert result["status"] == "failed"
    assert result["diagnostics"][0]["code"] == "OCR_JOB_FAILED"
    assert result["diagnostics"][0]["message"] == "engine failed"


def test_ocr_client_job_sync_returns_structured_timeout_diagnostics() -> None:
    from libs.integrations.ocr_client import OcrClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/internal/document-parse/jobs":
            return httpx.Response(200, json={"code": 0, "data": {"jobId": "OCRJOB-SLOW"}})
        if request.method == "GET" and request.url.path == "/internal/document-parse/jobs/OCRJOB-SLOW":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"jobId": "OCRJOB-SLOW", "status": "running"}},
            )
        raise AssertionError(f"unexpected OCR client request: {request.method} {request.url.path}")

    ocr_client = OcrClient(base_url="http://ocr", transport=httpx.MockTransport(handler))
    result = ocr_client.parse_via_job_sync(
        {"storageKey": "minio://documents/source.pdf"},
        timeout_seconds=0.01,
        poll_interval=0.01,
    )

    assert result["status"] == "failed"
    assert result["diagnostics"][0]["code"] == "OCR_JOB_TIMEOUT"
    assert result["diagnostics"][0]["timeoutSeconds"] == 0.01


def test_ocr_client_uses_local_fallback_only_outside_production(monkeypatch) -> None:
    from libs.integrations.ocr_client import DEFAULT_LOCAL_OCR_BASE_URL, OcrClient

    monkeypatch.delenv("AICHECK_OCR_BASE_URL", raising=False)
    monkeypatch.delenv("AICHECK_LOCAL_OCR_BASE_URL", raising=False)
    monkeypatch.delenv("AICHECK_OCR_ENABLE_LOCAL_FALLBACK", raising=False)
    monkeypatch.delenv("AICHECK_DATABASE_URL", raising=False)
    monkeypatch.delenv("AICHECK_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("AICHECK_STRICT_PRODUCTION", raising=False)

    local_client = OcrClient()
    assert local_client.enabled is True
    assert local_client.base_url == DEFAULT_LOCAL_OCR_BASE_URL

    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    production_client = OcrClient()
    assert production_client.enabled is False
    assert production_client.base_url == ""

    monkeypatch.setenv("AICHECK_OCR_ENABLE_LOCAL_FALLBACK", "true")
    explicit_fallback_client = OcrClient()
    assert explicit_fallback_client.enabled is True
    assert explicit_fallback_client.base_url == DEFAULT_LOCAL_OCR_BASE_URL


def test_fde_ocr_capability_test_defaults_to_generic_profile() -> None:
    from apps.api.routes import fde_capability_test_profile_document_type

    profile_id, document_type = fde_capability_test_profile_document_type("设计资料.pdf", {})

    assert profile_id == "generic_document_v1"
    assert document_type == "generic_document"

    explicit_profile_id, explicit_document_type = fde_capability_test_profile_document_type(
        "设计资料.pdf",
        {"profileId": "piping_characteristic_list_v1"},
    )

    assert explicit_profile_id == "piping_characteristic_list_v1"
    assert explicit_document_type == "engineering_table_photo"


def test_litellm_client_sanitizes_provider_response_body() -> None:
    from libs.integrations.errors import IntegrationServiceError
    from libs.integrations.litellm_client import LiteLLMClient

    def provider_failure(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": "invalid upstream key sk-secret-litellm",
                    "type": "auth_error",
                }
            },
        )

    litellm = LiteLLMClient(
        base_url="http://litellm",
        api_key="sk-test",
        transport=httpx.MockTransport(provider_failure),
    )
    try:
        litellm.chat_sync([{"role": "user", "content": "ping"}])
    except IntegrationServiceError as exc:
        assert exc.status_code == 401
        assert "HTTP 401" in str(exc)
        assert "sk-secret-litellm" not in str(exc)
    else:
        raise AssertionError("LiteLLM provider failure must raise a sanitized integration error")


def test_login_compatibility_paths() -> None:
    cases = {
        "inspection": "/ai-review-b",
        "contractor": "/workbench/contractor",
        "ndt": "/workbench/ndt",
        "owner": "/workbench/owner",
        "admin": "/admin/overview",
    }

    for username, default_path in cases.items():
        mock_user = assert_ok(client.post("/mock/user/login", json={"username": username, "password": username}))
        real_login = assert_ok(client.post("/api/auth/login", json={"username": username, "password": username}))

        assert mock_user["username"] == username
        assert mock_user["role"] == username
        assert mock_user["defaultPath"] == default_path
        assert real_login["token"]
        assert real_login["user"]["role"] == username
        assert real_login["user"]["defaultPath"] == default_path

        me = assert_ok(client.get("/api/auth/me", headers={"Authorization": f"Bearer {real_login['token']}"}))
        assert me["username"] == username
        assert me["defaultRole"] == username


def test_persistent_user_login_when_demo_users_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "false")
    repo.state["users"].append(
        {
            "id": "USER-PERSISTENT-001",
            "username": "persistent",
            "passwordHash": "plain:secret",
            "role": "inspection",
            "roleId": "2",
            "roleLabel": "监检人员",
            "displayName": "真实用户",
            "orgUnitName": "省特检院一部",
            "permissions": ["review:save"],
            "status": "启用",
            "defaultPath": "/workbench/inspection",
        }
    )

    login = assert_ok(client.post("/api/auth/login", json={"username": "persistent", "password": "secret"}))
    assert login["user"]["username"] == "persistent"
    assert login["user"]["role"] == "inspection"
    assert_error(client.post("/api/auth/login", json={"username": "inspection", "password": "inspection"}), "AUTH_REQUIRED")


def test_auth_login_is_public_logout_requires_auth_and_security_events_are_scoped_flushed(monkeypatch) -> None:
    from apps.api import main as api_main

    flush_calls: list[tuple[dict, list[str]]] = []
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setattr(
        api_main,
        "flush_mutation_records",
        lambda records, scopes: flush_calls.append((records, scopes)),
    )

    login = assert_ok(client.post("/api/auth/login", json={"username": "ndt", "password": "ndt"}))

    assert_ok(client.post("/api/auth/logout", headers={"Authorization": f"Bearer {login['token']}"}))
    assert_error(client.post("/api/auth/logout"), "AUTH_REQUIRED")
    assert_error(client.post("/auth/logout"), "AUTH_REQUIRED")
    assert len(flush_calls) == 4
    assert all(set(records) == {"audit_logs"} for records, _scopes in flush_calls)
    assert all(scopes == [] for _records, scopes in flush_calls)


def test_frontend_route_groups_return_success() -> None:
    project_id = "P-2026-HDCP-001"
    route_cases = [
        ("GET", f"/projects/{project_id}/workbench/context?role=inspection", None),
        ("GET", f"/projects/{project_id}/workbench/summary?role=inspection", None),
        ("GET", f"/projects/{project_id}/tree", None),
        ("GET", f"/projects/{project_id}/nodes/24/package", None),
        ("GET", f"/projects/{project_id}/documents/DOC-20260625-001", None),
        ("GET", f"/projects/{project_id}/owner/reports", None),
        ("GET", f"/projects/{project_id}/archive", None),
        ("GET", f"/projects/{project_id}/ndt/films", None),
        ("GET", f"/projects/{project_id}/ndt/records", None),
        ("GET", f"/projects/{project_id}/ndt/reports", None),
        ("GET", "/knowledge/overview", None),
        ("GET", "/knowledge/sources", None),
        ("GET", "/knowledge/project-files", None),
        ("GET", "/knowledge/tasks", None),
        ("GET", "/rules/versions", None),
        ("GET", "/admin/config-overview", None),
        ("GET", "/admin/integration-contract", None),
        ("GET", "/admin/audit-logs", None),
        ("GET", "/todos", None),
        ("GET", "/messages", None),
        ("GET", "/search?keyword=焊工", None),
    ]

    for method, path, body in route_cases:
        response = client.request(method, path, json=body)
        assert_ok(response)


def test_node_standard_references_resolve_to_previewable_knowledge_files() -> None:
    project_id = "P-2026-HDCP-001"
    package = assert_ok(client.get(f"/api/projects/{project_id}/nodes/24/package"))
    references = package["businessBasis"]["referencedStandards"]

    assert references
    assert all(item["sourceRelativePath"].startswith("rules/standards/") for item in references)
    assert all(item["knowledgeFileId"].startswith("KF-") for item in references)
    assert all(item["previewAvailable"] is True for item in references)
    assert all(
        item["previewUrl"]
        == f"/api/knowledge/files/{item['knowledgeFileId']}/original?disposition=inline"
        for item in references
    )


def test_submission_idempotency_replays_same_response() -> None:
    project_id = "P-2026-HDCP-001"
    payload = {
        "nodeId": 16,
        "nodeIds": [16],
        "bindingIds": ["BIND-16-001"],
        "submitterComment": "contract test",
    }
    headers = {"Idempotency-Key": "submit-once"}

    first = assert_ok(client.post(f"/projects/{project_id}/submissions", json=payload, headers=headers))
    second = assert_ok(client.post(f"/projects/{project_id}/submissions", json=payload, headers=headers))

    assert first["submissionId"] == second["submissionId"]
    assert first["snapshotId"] == second["snapshotId"]

    conflict_payload = {**payload, "submitterComment": "different body"}
    assert_error(
        client.post(f"/projects/{project_id}/submissions", json=conflict_payload, headers=headers),
        "IDEMPOTENCY_KEY_CONFLICT",
    )


def test_project_file_direct_submit_creates_node_binding() -> None:
    project_id = "P-2026-HDCP-001"
    payload = {
        "nodeId": 25,
        "nodeIds": [25],
        "bindingIds": [],
        "documentIds": ["DOC-20260625-005"],
        "submitterComment": "direct library submit",
    }

    result = assert_ok(client.post(f"/projects/{project_id}/submissions", json=payload))
    created_binding_ids = result["createdBindingIds"]
    created_binding = repo.find_one("bindings", created_binding_ids[0])
    stored_submission = next(item for item in repo.state["submissions"] if item["submissionId"] == result["submissionId"])

    assert result["nextStatus"] == "待审查"
    assert len(created_binding_ids) == 1
    assert created_binding["documentId"] == "DOC-20260625-005"
    assert created_binding["nodeId"] == 25
    assert created_binding["bindingStatus"] == "已提交"
    assert stored_submission["bindingIds"] == created_binding_ids
    assert repo.node(project_id, 25)["status"] == "待审查"


def test_project_level_submit_without_node_binding() -> None:
    project_id = "P-2026-HDCP-001"
    document_id = "DOC-20260625-005"
    document = repo.find_one("documents", document_id)
    assert document is not None
    document["poolSubmissionStatus"] = "未提交"
    before_bindings = [
        item
        for item in repo.state["bindings"]
        if item.get("projectId") == project_id and item.get("documentId") == document_id
    ]
    before_node_status = {
        node_id: repo.node(project_id, node_id)["status"]
        for node_id in (16, 24, 25, 40)
        if repo.node(project_id, node_id)
    }

    result = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions",
            json={
                "submissionType": "project",
                "documentIds": [document_id],
                "bindingIds": [],
                "nodeIds": [],
                "batchName": "资质证照资料池提交",
                "submitterComment": "project pool submit",
            },
        )
    )
    stored_submission = next(
        item for item in repo.state["submissions"] if item["submissionId"] == result["submissionId"]
    )
    todo = next(item for item in repo.state["todos"] if item["id"] in set(stored_submission["createdTodoIds"]))
    refreshed = repo.find_one("documents", document_id)
    after_bindings = [
        item
        for item in repo.state["bindings"]
        if item.get("projectId") == project_id and item.get("documentId") == document_id
    ]

    assert result["submissionType"] == "project"
    assert result["nextStatus"] == "资料池待处理"
    assert result["documentIds"] == [document_id]
    assert result["bindingIds"] == []
    assert result["createdBindingIds"] == []
    assert stored_submission["submissionType"] == "project"
    assert stored_submission["nodeIds"] == []
    assert stored_submission["documentIds"] == [document_id]
    assert refreshed["poolSubmissionStatus"] == "已提交"
    assert refreshed.get("poolSubmittedAt")
    assert todo["nodeId"] is None
    assert todo["targetType"] == "submission"
    assert len(after_bindings) == len(before_bindings)
    for node_id, status in before_node_status.items():
        assert repo.node(project_id, node_id)["status"] == status

    assert_error(
        client.post(
            f"/projects/{project_id}/submissions",
            json={
                "submissionType": "project",
                "documentIds": [document_id],
                "nodeIds": [],
            },
        ),
        "CONFLICT",
    )
    assert_error(
        client.delete(f"/projects/{project_id}/documents/{document_id}"),
        "CONFLICT",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/submissions",
            json={"submissionType": "project", "documentIds": [], "nodeIds": []},
        ),
        "EMPTY_PROJECT_PACKAGE",
    )


def test_global_idempotency_covers_mutations_without_explicit_route_parameter() -> None:
    project_id = "P-2026-HDCP-001"
    document_id = "DOC-20260625-003"
    headers = {"Idempotency-Key": "append-version-once"}
    payload = {"fileSize": 1024, "mode": "append"}
    before_count = len(repo.versions_for_document(document_id))

    first = assert_ok(client.post(f"/projects/{project_id}/documents/{document_id}/versions", json=payload, headers=headers))
    second = assert_ok(client.post(f"/projects/{project_id}/documents/{document_id}/versions", json=payload, headers=headers))

    assert first["version"]["id"] == second["version"]["id"]
    assert len(repo.versions_for_document(document_id)) == before_count + 1
    assert_error(
        client.post(
            f"/projects/{project_id}/documents/{document_id}/versions",
            json={**payload, "fileSize": 2048},
            headers=headers,
        ),
        "IDEMPOTENCY_KEY_CONFLICT",
    )


def test_global_audit_covers_mutations_without_explicit_audit_log(monkeypatch) -> None:
    project_id = "P-2026-HDCP-001"
    seed_reviewed_node_24(project_id)
    allow_test_ai_dispatch(monkeypatch)
    before = len(repo.state["audit_logs"])

    run = assert_ok(client.post(f"/projects/{project_id}/inspection/nodes/24/ai-recheck"))

    assert "runId" in run
    assert len(repo.state["audit_logs"]) == before + 1
    audit = repo.state["audit_logs"][0]
    assert audit["objectType"] == "ApiMutation"
    assert audit["objectId"] == f"/projects/{project_id}/inspection/nodes/24/ai-recheck"
    assert audit["operationId"].startswith("OP-")
    assert repo.verify_audit_chain(audit["tenantId"])["status"] == "verified"


def test_global_audit_does_not_duplicate_explicit_audit_log() -> None:
    project_id = "P-2026-HDCP-001"
    before = len(repo.state["audit_logs"])

    result = assert_ok(client.patch(f"/projects/{project_id}", json={"name": "审计不重复"}))

    assert result["auditLogId"]
    assert len(repo.state["audit_logs"]) == before + 1


def test_inspection_submitted_documents_excludes_uploads_and_uses_submission_time() -> None:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
    upload_only, _ = repo.create_document(
        project_id,
        "仅上传未提交.pdf",
        "application/pdf",
        source_org_name="中石化第五建设有限公司",
        uploader_name="李工",
    )
    pool_document, _ = repo.create_document(
        project_id,
        "项目资料池提交.pdf",
        "application/pdf",
        source_org_name="中石化第五建设有限公司",
        uploader_name="李工",
    )
    node_document, node_version = repo.create_document(
        project_id,
        "节点资料提交.pdf",
        "application/pdf",
        source_org_name="中石化第五建设有限公司",
        uploader_name="李工",
    )
    ndt_document, ndt_version = repo.create_document(
        project_id,
        "无损检测资料提交.pdf",
        "application/pdf",
        source_org_name="华测检测认证集团",
        uploader_name="王工",
        material_category="无损检测资料",
        material_type_code="ndt_quality_assurance_manual",
        material_type_name="无损检测单位质量保证手册",
    )
    node_binding = {
        "id": "BIND-INSPECTION-SUBMITTED-NODE",
        "projectId": project_id,
        "nodeId": 24,
        "documentId": node_document["id"],
        "documentVersionId": node_version["id"],
        "bindingStatus": "已提交",
        "boundAt": "2026-08-06 09:00:00",
    }
    ndt_binding = {
        "id": "BIND-INSPECTION-SUBMITTED-NDT",
        "projectId": project_id,
        "nodeId": 35,
        "documentId": ndt_document["id"],
        "documentVersionId": ndt_version["id"],
        "bindingStatus": "已提交",
        "boundAt": "2026-08-06 09:05:00",
    }
    node_draft_binding = {
        **node_binding,
        "id": "BIND-INSPECTION-UNSUBMITTED-SAME-DOCUMENT",
        "nodeId": 25,
        "bindingStatus": "草稿挂载",
    }
    node_second_submitted_binding = {
        **node_draft_binding,
        "id": "BIND-INSPECTION-SECOND-SUBMITTED-SAME-DOCUMENT",
        "bindingStatus": "已提交",
    }
    repo.state["bindings"].extend(
        [node_binding, node_draft_binding, node_second_submitted_binding, ndt_binding]
    )
    pool_document["poolSubmissionStatus"] = "已提交"
    pool_document["poolSubmittedAt"] = "2026-08-06 10:00:00"
    ndt_document["fileStatus"] = "已提交审批"
    ndt_document["submittedAt"] = "2026-08-06 12:00:00"
    ndt_document["updatedAt"] = "2026-08-06 18:00:00"
    repo.state["submissions"].extend(
        [
            {
                "submissionId": "SUB-INSPECTION-POOL",
                "snapshotId": "SNAP-INSPECTION-POOL",
                "projectId": project_id,
                "submissionType": "project",
                "nodeIds": [],
                "bindingIds": [],
                "documentIds": [pool_document["id"]],
                "submittedAt": "2026-08-06 10:00:00",
            },
            {
                "submissionId": "SUB-INSPECTION-NODE-EARLIER",
                "snapshotId": "SNAP-INSPECTION-NODE-EARLIER",
                "projectId": project_id,
                "submissionType": "document",
                "nodeIds": [25],
                "bindingIds": [node_second_submitted_binding["id"]],
                "documentIds": [],
                "submittedAt": "2026-08-06 10:30:00",
            },
            {
                "submissionId": "SUB-INSPECTION-NODE",
                "snapshotId": "SNAP-INSPECTION-NODE",
                "projectId": project_id,
                "submissionType": "document",
                "nodeIds": [24],
                "bindingIds": [node_binding["id"]],
                "documentIds": [],
                "submittedAt": "2026-08-06 11:00:00",
            },
            {
                "submissionId": "SUB-INSPECTION-NDT",
                "snapshotId": "SNAP-INSPECTION-NDT",
                "projectId": project_id,
                "submissionType": "ndt-material",
                "nodeIds": [35],
                "bindingIds": [ndt_binding["id"]],
                "documentIds": [ndt_document["id"]],
                "submittedAt": "2026-08-06 12:00:00",
            },
        ]
    )

    result = assert_ok(
        client.get(
            f"/projects/{project_id}/inspection/submitted-documents?page=1&pageSize=20",
            headers=headers,
        )
    )

    assert upload_only["id"] not in {item["documentId"] for item in result["items"]}
    assert [item["documentId"] for item in result["items"][:3]] == [
        ndt_document["id"],
        node_document["id"],
        pool_document["id"],
    ]
    assert [item["submittedAt"] for item in result["items"][:3]] == [
        "2026-08-06 12:00:00",
        "2026-08-06 11:00:00",
        "2026-08-06 10:00:00",
    ]
    assert result["total"] == 3
    node_row = next(item for item in result["items"] if item["documentId"] == node_document["id"])
    assert {item["id"] for item in node_row["submittedBindings"]} == {
        node_binding["id"],
        node_second_submitted_binding["id"],
    }

    search_result = assert_ok(
        client.get(
            f"/projects/{project_id}/inspection/submitted-documents?keyword=节点资料提交&page=1&pageSize=1",
            headers=headers,
        )
    )
    assert search_result["total"] == 1
    assert search_result["items"][0]["documentId"] == node_document["id"]

    for forbidden_headers in (
        {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"},
        {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"},
    ):
        assert_error(
            client.get(
                f"/projects/{project_id}/inspection/submitted-documents",
                headers=forbidden_headers,
            ),
            "FORBIDDEN",
        )


def test_inspection_sees_unsubmitted_documents_but_marked() -> None:
    """监检要能看见施工方刚上传、还没正式提交的资料——但要看得出没提交。

    ## 这条契约被**有意反转**过（0817 第 8 条）

    原先叫 test_inspection_node_package_does_not_expose_unsubmitted_documents_or_bindings，
    断言监检看不到草稿。用户明确要求改掉：

        「文件上传后，不用通过检查端，监检平台直接能看到」

    原来的行为下，施工方以为传了、监检以为没传，两边都没错，事情卡住。

    ## 但去掉门不等于去掉区分

    - 节点包：看得见，且每条带 submittedToInspection 标出有没有正式提交
    - 审查工作台的「提交内容」：仍然只含已提交的——**那是审查依据，要纯净**
    - 未提交的走 drafts 一栏单独呈现
    """
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
    draft_document, draft_version = repo.create_document(
        project_id,
        "监检可见但未提交.pdf",
        "application/pdf",
        source_org_name="中石化第五建设有限公司",
        uploader_name="李工",
    )
    draft_binding = {
        "id": "BIND-INSPECTION-VISIBLE-DRAFT",
        "projectId": project_id,
        "nodeId": 24,
        "documentId": draft_document["id"],
        "documentVersionId": draft_version["id"],
        "bindingStatus": "草稿挂载",
        "boundAt": "2026-08-06 08:00:00",
    }
    repo.state["bindings"].append(draft_binding)

    package = assert_ok(client.get(f"/projects/{project_id}/nodes/24/package", headers=headers))

    files_by_id = {item["id"]: item for item in package["projectFiles"]}
    assert draft_document["id"] in files_by_id, "监检看不到刚上传的资料——施工方传了他也不知道"
    assert files_by_id[draft_document["id"]]["submittedToInspection"] is False, (
        "没标出未提交，监检会以为施工方已经正式交付了"
    )

    bindings_by_id = {item["id"]: item for item in package["bindings"]}
    assert draft_binding["id"] in bindings_by_id
    assert bindings_by_id[draft_binding["id"]]["submittedToInspection"] is False

    # 已提交的那些要标成 True，否则这个字段等于恒假，什么也没说
    submitted = [item for item in package["bindings"] if item.get("bindingStatus") == "已提交"]
    if submitted:
        assert any(item["submittedToInspection"] for item in submitted), (
            "已提交的资料没被标成已提交，这个标记就成了摆设"
        )

    audit_workspace = assert_ok(
        client.get(
            f"/projects/{project_id}/inspection/nodes/24/audit-workspace",
            headers=headers,
        )
    )
    submission_content = audit_workspace["content"]["submission"]
    # 「提交内容」是审查依据，草稿不该混进来
    assert draft_binding["id"] not in {item["id"] for item in submission_content["bindings"]}


def test_submitted_items_cannot_be_withdrawn_by_submitter() -> None:
    project_id = "P-2026-HDCP-001"
    contractor_headers = {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"}
    payload = {
        "nodeId": 16,
        "nodeIds": [16],
        "bindingIds": ["BIND-16-001"],
        "submitterComment": "withdraw state machine test",
    }
    submission = assert_ok(client.post(f"/projects/{project_id}/submissions", json=payload))
    submission_id = submission["submissionId"]
    binding = next(item for item in repo.state["bindings"] if item["id"] == "BIND-16-001")
    node_status_before = repo.node(project_id, 16)["status"]
    response = client.post(
        f"/projects/{project_id}/submissions/{submission_id}/withdraw-items",
        json={"bindingIds": ["BIND-16-001"], "reason": "资料版本修正"},
        headers=contractor_headers,
    )

    assert response.status_code == 409
    error = response.json()
    assert error["data"]["reason"] == "SUBMISSION_WITHDRAW_NOT_ALLOWED"
    assert error["message"] == "资料已提交审查，不能撤回；如需修改，请联系监检人员退回后重新提交。"
    assert binding["bindingStatus"] == "已提交"
    assert repo.node(project_id, 16)["status"] == node_status_before
    stored_submission = next(item for item in repo.state["submissions"] if item["submissionId"] == submission_id)
    assert "withdrawnBindingIds" not in stored_submission
    assert "withdrawal" not in stored_submission


def test_submitted_document_cannot_be_withdrawn_through_document_endpoint() -> None:
    project_id = "P-2026-HDCP-001"
    contractor_headers = {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"}
    binding = next(item for item in repo.state["bindings"] if item["id"] == "BIND-16-001")
    document = next(item for item in repo.state["documents"] if item["id"] == binding["documentId"])
    original_status = document["fileStatus"]
    assert_ok(
        client.post(
            f"/projects/{project_id}/submissions",
            json={"nodeIds": [16], "bindingIds": [binding["id"]]},
            headers=contractor_headers,
        )
    )

    response = client.post(
        f"/projects/{project_id}/documents/{document['id']}/withdraw",
        headers=contractor_headers,
    )

    assert response.status_code == 409
    error = response.json()
    assert error["data"]["reason"] == "SUBMISSION_WITHDRAW_NOT_ALLOWED"
    assert document["fileStatus"] == original_status


def test_submitter_permissions_do_not_advertise_submission_withdraw() -> None:
    assert "submission:withdraw" not in repo.role_actions("contractor")
    assert "submission:withdraw" not in repo.role_actions("ndt")


def test_return_correction_updates_selected_submitted_bindings() -> None:
    project_id = "P-2026-HDCP-001"
    inspection_headers = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
    submission = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions",
            json={
                "nodeId": 16,
                "nodeIds": [16],
                "bindingIds": ["BIND-16-001"],
                "submitterComment": "等待监检退回测试",
            },
        )
    )

    result = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/16/actions/return-correction",
            json={"bindingIds": ["BIND-16-001"], "reason": "证书有效期信息需要补正"},
            headers=inspection_headers,
        )
    )

    binding = repo.find_one("bindings", "BIND-16-001")
    rectification = repo.find_one("rectifications", result["rectification"]["id"])
    assert binding["bindingStatus"] == "需补正"
    assert repo.node(project_id, 16)["status"] == "需补正"
    assert rectification["submissionId"] == submission["submissionId"]
    assert rectification["bindingIds"] == ["BIND-16-001"]
    assert rectification["returnedAt"]
    assert rectification["comment"] == "证书有效期信息需要补正"


def test_resubmission_preserves_original_submission_and_correction_history() -> None:
    project_id = "P-2026-HDCP-001"
    inspection_headers = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
    original = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions",
            json={"nodeIds": [16], "bindingIds": ["BIND-16-001"]},
        )
    )
    returned = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/16/actions/return-correction",
            json={"bindingIds": ["BIND-16-001"], "reason": "退回后重新提交测试"},
            headers=inspection_headers,
        )
    )
    rectification_id = returned["rectification"]["id"]
    original_record = next(
        item for item in repo.state["submissions"] if item["submissionId"] == original["submissionId"]
    )
    original_snapshot = deepcopy(original_record)

    resubmitted = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions",
            json={"nodeIds": [16], "bindingIds": ["BIND-16-001"]},
        )
    )

    resubmission_record = next(
        item
        for item in repo.state["submissions"]
        if item["submissionId"] == resubmitted["submissionId"]
    )
    rectification = repo.find_one("rectifications", rectification_id)
    assert resubmission_record["previousSubmissionId"] == original["submissionId"]
    assert resubmission_record["rectificationId"] == rectification_id
    assert resubmission_record["submittedAt"] >= rectification["returnedAt"]
    assert original_record == original_snapshot
    assert rectification["status"] == "已重新提交"
    assert rectification["resubmissionId"] == resubmitted["submissionId"]
    assert rectification["resubmittedAt"] == resubmission_record["submittedAt"]

    inspection_rows = assert_ok(
        client.get(
            f"/projects/{project_id}/inspection/submitted-documents?keyword={repo.find_one('bindings', 'BIND-16-001')['fileName']}",
            headers=inspection_headers,
        )
    )
    row = next(item for item in inspection_rows["items"] if item["submissionId"] == resubmitted["submissionId"])
    assert row["reviewStatus"] == "已重新提交"
    assert row["submittedAt"] == resubmission_record["submittedAt"]


def test_submit_rectification_updates_pending_item_and_enforces_scope() -> None:
    project_id = "P-2026-HDCP-001"
    submission_count_before = len(repo.state["submissions"])
    assert_error(
        client.post(
            f"/projects/{project_id}/rectifications",
            json={"nodeId": 24, "bindingIds": ["BIND-24-001"], "comment": "没有待反馈单"},
        ),
        "CONFLICT",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/rectifications",
            json={"nodeId": 16, "bindingIds": ["BIND-24-001"], "comment": "跨节点资料"},
        ),
        "CONFLICT",
    )

    feedback = assert_ok(
        client.post(
            f"/projects/{project_id}/rectifications",
            json={"nodeId": 16, "bindingIds": ["BIND-16-001"], "comment": "已补充炉批号差异说明。"},
        )
    )
    rectification = repo.find_one("rectifications", "REC-16-001")
    node = repo.node(project_id, 16)

    assert feedback["rectification"]["id"] == "REC-16-001"
    assert feedback["nextStatus"] == "复审中"
    assert rectification["status"] == "已重新提交"
    assert rectification["bindingIds"] == ["BIND-16-001"]
    assert rectification["resubmissionId"]
    assert rectification["resubmittedAt"]
    assert repo.find_one("bindings", "BIND-16-001")["bindingStatus"] == "已提交"
    resubmission = next(
        item
        for item in repo.state["submissions"]
        if item["submissionId"] == rectification["resubmissionId"]
    )
    assert resubmission["rectificationId"] == "REC-16-001"
    assert resubmission["bindingIds"] == ["BIND-16-001"]
    assert len(repo.state["submissions"]) == submission_count_before + 1
    assert node["status"] == "复审中"
    assert len([item for item in repo.state["rectifications"] if item["id"] == "REC-16-001"]) == 1
    assert_error(
        client.post(
            f"/projects/{project_id}/rectifications",
            json={"nodeId": 16, "bindingIds": ["BIND-16-001"], "comment": "重复反馈"},
        ),
        "CONFLICT",
    )


def test_generate_report_review_requires_existing_ready_node() -> None:
    project_id = "P-2026-HDCP-001"
    seed_reviewed_node_24(project_id)
    payload = {"includeEvidence": True, "reportScope": "currentNode"}

    assert_error(
        client.post(f"/projects/{project_id}/inspection/nodes/999/report-review", json=payload),
        "NOT_FOUND",
    )
    assert_error(
        client.post(f"/projects/{project_id}/inspection/nodes/16/report-review", json=payload),
        "CONFLICT",
    )

    report_count = len(repo.state["reports"])
    headers = {"Idempotency-Key": "report-review-once"}
    generated = assert_ok(client.post(f"/projects/{project_id}/inspection/nodes/24/report-review", json=payload, headers=headers))
    generated_replay = assert_ok(client.post(f"/projects/{project_id}/inspection/nodes/24/report-review", json=payload, headers=headers))
    assert generated["report"]["nodeIds"] == [24]
    assert generated_replay["report"]["id"] == generated["report"]["id"]
    assert generated["nextStatus"] == "报告生成/复核中"
    assert len(repo.state["reports"]) == report_count + 1


def test_report_detail_scope_and_archive_if_match() -> None:
    project_id = "P-2026-HDCP-001"
    report_id = "RPT-20260625-001"
    seed_report_scope(report_id, project_id, status="已签发")

    assert_error(client.get(f"/projects/NOT-A-PROJECT/reports/{report_id}"), "NOT_FOUND")
    detail = assert_ok(client.get(f"/projects/{project_id}/reports/{report_id}"))
    etag = detail["report"]["etag"]
    revision = detail["report"]["revision"]

    assert_error(
        client.post(
            f"/projects/{project_id}/reports/{report_id}/archive",
            json={"archiveNote": "stale"},
            headers={"If-Match": 'W/"report-stale-r0"'},
        ),
        "ETAG_CONFLICT",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/reports/{report_id}/archive",
            json={"archiveNote": "missing export"},
            headers={"If-Match": etag},
        ),
        "CONFLICT",
    )
    exported = assert_ok(
        client.post(
            f"/projects/{project_id}/reports/{report_id}/export",
            json={"format": "pdf"},
            headers={"Idempotency-Key": "report-export-before-archive"},
        )
    )
    export_task = repo.find_one("export_tasks", exported["exportId"])
    assert export_task is not None
    assert export_task["fileSize"] > 0
    assert not str(export_task["downloadUrl"]).startswith("mock://")
    archived = assert_ok(
        client.post(
            f"/projects/{project_id}/reports/{report_id}/archive",
            json={"archiveNote": "ready"},
            headers={"If-Match": etag, "Idempotency-Key": "report-archive-once"},
        )
    )
    archived_replay = assert_ok(
        client.post(
            f"/projects/{project_id}/reports/{report_id}/archive",
            json={"archiveNote": "ready"},
            headers={"If-Match": etag, "Idempotency-Key": "report-archive-once"},
        )
    )

    assert archived["nextStatus"] == "已归档"
    assert archived_replay["report"]["etag"] == archived["report"]["etag"]
    assert archived["report"]["revision"] == revision + 1
    assert archived["report"]["etag"] != etag
    assert repo.find_one("reports", report_id)["status"] == "已归档"


def test_report_update_if_match_increments_revision() -> None:
    project_id = "P-2026-HDCP-001"
    report_id = "RPT-20260625-001"
    evidence_ids = seed_report_scope(report_id, project_id)
    detail = assert_ok(client.get(f"/projects/{project_id}/reports/{report_id}"))
    etag = detail["report"]["etag"]
    revision = detail["report"]["revision"]

    assert_error(
        client.patch(
            f"/projects/{project_id}/reports/{report_id}",
            json={"title": "过期报告标题"},
            headers={"If-Match": 'W/"report-stale-r0"'},
        ),
        "ETAG_CONFLICT",
    )
    updated = assert_ok(
        client.patch(
            f"/projects/{project_id}/reports/{report_id}",
            json={"title": "并发控制后的报告标题"},
            headers={"If-Match": etag, "Idempotency-Key": "report-update-once"},
        )
    )
    updated_replay = assert_ok(
        client.patch(
            f"/projects/{project_id}/reports/{report_id}",
            json={"title": "并发控制后的报告标题"},
            headers={"If-Match": etag, "Idempotency-Key": "report-update-once"},
        )
    )

    assert updated["report"]["title"] == "并发控制后的报告标题"
    assert updated_replay["report"]["etag"] == updated["report"]["etag"]
    assert updated_replay["auditLogId"] == updated["auditLogId"]
    assert updated["report"]["revision"] == revision + 1
    assert updated["report"]["etag"] != etag

    updated_detail = assert_ok(client.get(f"/projects/{project_id}/reports/{report_id}"))
    sections = updated_detail["sections"]
    sections[0]["content"] = "复核后补充：证据链完整，报告结论可签发。"
    sections[0]["evidenceLinkIds"] = evidence_ids[:1]
    section_saved = assert_ok(
        client.patch(
            f"/projects/{project_id}/reports/{report_id}",
            json={"sections": sections, "remark": "补充检验结论"},
            headers={"If-Match": updated_detail["report"]["etag"], "Idempotency-Key": "report-section-update-once"},
        )
    )
    saved_detail = assert_ok(client.get(f"/projects/{project_id}/reports/{report_id}"))
    assert section_saved["report"]["revision"] == revision + 2
    assert saved_detail["sections"][0]["content"] == "复核后补充：证据链完整，报告结论可签发。"
    assert saved_detail["reviewTrail"][0]["title"] == "保存报告"
    assert saved_detail["reviewTrail"][0]["comment"] == "补充检验结论"
    assert saved_detail["versionHistory"][1]["summary"] == "补充检验结论"
    assert_error(
        client.patch(
            f"/projects/{project_id}/reports/{report_id}",
            json={"sections": [{**sections[0], "evidenceLinkIds": ["EV-NOT-FOUND"]}]},
            headers={"If-Match": saved_detail["report"]["etag"]},
        ),
        "VALIDATION_ERROR",
    )


def test_review_opinion_requires_current_node_confirmed_evidence() -> None:
    evidence_ids = seed_confirmed_node_24_evidence()

    no_evidence = assert_error(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "满足要求", "opinion": "无证据通过", "evidenceLinkIds": []},
        ),
        "VALIDATION_ERROR",
    )
    assert no_evidence["data"]["evidenceValidation"]["requiresEvidenceSelection"] is True

    cross_node = assert_error(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "满足要求", "opinion": "跨节点证据", "evidenceLinkIds": ["EV-16-001"]},
        ),
        "VALIDATION_ERROR",
    )
    assert cross_node["data"]["evidenceValidation"]["invalidEvidenceLinkIds"] == ["EV-16-001"]

    saved = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "满足要求", "opinion": "confirmed evidence only", "evidenceLinkIds": evidence_ids},
        )
    )
    assert saved["opinion"]["evidenceValidation"]["passed"] is True
    assert saved["opinion"]["readinessSnapshot"]["readyForAiFormal"] is True


def test_ai_recheck_dispatch_disabled_denies_gap_summary_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_ALLOW_LOCAL_GAP_PRECHECK_FALLBACK", raising=False)
    monkeypatch.delenv("AICHECK_STRICT_PRODUCTION", raising=False)
    seed_reviewed_node_24()
    before_run_count = len(repo.state["ai_runs"])
    before_status = repo.node("P-2026-HDCP-001", 24)["status"]

    formal = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
        json={"reviewMode": "formal"},
    )
    assert formal.status_code == 409
    assert repo.node("P-2026-HDCP-001", 24)["status"] == before_status
    assert len(repo.state["ai_runs"]) == before_run_count

    gap = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
        json={"reviewMode": "gap_precheck"},
    )
    assert gap.status_code == 409
    payload = gap.json()
    assert payload["data"]["reason"] == "CONFLICT"
    assert payload["data"]["dispatch"]["ready"] is False
    assert payload["data"]["requestedReviewMode"] == "gap_precheck"
    assert payload["data"]["fallbackPolicy"] == {
        "environmentVariable": "AICHECK_ALLOW_LOCAL_GAP_PRECHECK_FALLBACK",
        "explicitOptIn": False,
        "strictProduction": False,
        "allowed": False,
    }
    assert repo.node("P-2026-HDCP-001", 24)["status"] == before_status
    assert len(repo.state["ai_runs"]) == before_run_count


def test_ai_recheck_dispatch_disabled_allows_explicit_local_gap_summary(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_ALLOW_LOCAL_GAP_PRECHECK_FALLBACK", "true")
    monkeypatch.delenv("AICHECK_STRICT_PRODUCTION", raising=False)
    seed_reviewed_node_24()
    before_run_count = len(repo.state["ai_runs"])
    before_status = repo.node("P-2026-HDCP-001", 24)["status"]

    result = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
            json={"reviewMode": "gap_precheck"},
        )
    )
    latest_run = result["latestRun"]

    assert result["advisoryOnly"] is True
    assert result["reviewMode"] == "gap_precheck"
    assert result["dispatch"]["ready"] is False
    assert result["dispatch"]["mode"] == "local_disabled_fallback"
    assert result["status"] == "完成"
    assert latest_run["status"] == "完成"
    assert "本地降级复核摘要" in latest_run["reasoningProcess"]
    assert latest_run["llmMetadata"]["llmCalled"] is False
    assert latest_run["llmMetadata"]["deepThinkAvailable"] is False
    assert "deepThink" not in latest_run["llmMetadata"]
    assert latest_run["llmResultText"] == latest_run["suggestion"]["opinionDraft"]
    assert repo.node("P-2026-HDCP-001", 24)["status"] == before_status
    assert len(repo.state["ai_runs"]) == before_run_count + 1


def test_ai_recheck_strict_production_denies_local_gap_summary_even_with_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_ALLOW_LOCAL_GAP_PRECHECK_FALLBACK", "true")
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")
    seed_reviewed_node_24()
    before_run_count = len(repo.state["ai_runs"])
    before_status = repo.node("P-2026-HDCP-001", 24)["status"]

    response = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
        json={"reviewMode": "gap_precheck"},
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["data"]["reason"] == "CONFLICT"
    assert payload["data"]["fallbackPolicy"] == {
        "environmentVariable": "AICHECK_ALLOW_LOCAL_GAP_PRECHECK_FALLBACK",
        "explicitOptIn": True,
        "strictProduction": True,
        "allowed": False,
    }
    assert repo.node("P-2026-HDCP-001", 24)["status"] == before_status
    assert len(repo.state["ai_runs"]) == before_run_count


def test_owner_write_forbidden_and_archived_readonly() -> None:
    project_id = "P-2026-HDCP-001"
    owner_write = client.post(
        f"/projects/{project_id}/inspection/nodes/24/ai-recheck",
        headers={"X-Role": "owner"},
    )
    assert_error(owner_write, "FORBIDDEN")
    assert_error(client.post("/todos/TODO-001/complete", headers={"X-Role": "owner"}), "FORBIDDEN")
    assert_error(client.post("/messages/MSG-001/read", headers={"X-Role": "owner"}), "FORBIDDEN")
    assert_error(client.post("/messages/read-all", headers={"X-Role": "owner"}), "FORBIDDEN")

    archived = client.post(
        "/projects/P-2025-CQARCH-007/documents/upload-session",
        json={"files": [{"fileName": "readonly.pdf", "fileSize": 1, "fileType": "application/pdf"}]},
    )
    assert_error(archived, "ARCHIVED_READONLY")
    assert_error(
        client.post("/projects/P-2025-CQARCH-007/documents/batch-classify", json={}),
        "ARCHIVED_READONLY",
    )
    assert_error(
        client.post("/projects/P-2025-CQARCH-007/inspection/nodes/24/attachments", json={}),
        "ARCHIVED_READONLY",
    )
    assert_error(
        client.post("/projects/P-2025-CQARCH-007/inspection/nodes/24/file-bindings", json={"documentIds": ["DOC-20260625-001"]}),
        "ARCHIVED_READONLY",
    )


def test_inspection_attachment_can_be_uploaded_bound_and_submitted_to_current_node() -> None:
    project_id = "P-2026-HDCP-001"
    inspection_headers = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
    upload = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/21/attachments",
            json={
                "files": [
                    {
                        "fileName": "S01-PHOTO-001_标志移植现场核验图.jpg",
                        "fileSize": 36,
                        "fileType": "image/jpeg",
                    }
                ]
            },
            headers=inspection_headers,
        )
    )
    target = upload["uploadUrls"][0]
    image_bytes = b"\xff\xd8\xff\xe0inspection-photo-no-ocr\xff\xd9"
    assert_ok(client.put(target["url"], content=image_bytes, headers=target["headers"]))
    assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={
                "completedFiles": [
                    {
                        "documentVersionId": target["documentVersionId"],
                        "fileSize": len(image_bytes),
                    }
                ]
            },
            headers={**inspection_headers, "Idempotency-Key": "inspection-photo-complete"},
        )
    )
    document = repo.find_one("documents", target["documentId"])
    assert document["materialCategory"] == "监检现场补充证据"
    assert document["sourceOrgName"] == "省特检院一部"
    assert repo.fields_for_versions({target["documentVersionId"]}) == []

    bound = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/21/file-bindings",
            json={
                "bindings": [
                    {
                        "documentId": target["documentId"],
                        "documentVersionId": target["documentVersionId"],
                        "usage": "监检资料",
                    }
                ]
            },
            headers={**inspection_headers, "Idempotency-Key": "inspection-photo-bind"},
        )
    )
    assert len(bound["affectedIds"]) == 1
    binding_id = bound["affectedIds"][0]

    submitted = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/21/file-bindings/submit",
            json={"bindingIds": [binding_id], "batchName": "R21 监检现场资料"},
            headers={**inspection_headers, "Idempotency-Key": "inspection-photo-submit"},
        )
    )
    assert submitted["bindingIds"] == [binding_id]
    stored_binding = repo.find_one("bindings", binding_id)
    assert stored_binding["usage"] == "监检资料"
    assert stored_binding["bindingStatus"] == "已提交"
    assert repo.node(project_id, 21)["status"] == "待审查"

    assert_error(
        client.post(
            f"/projects/{project_id}/inspection/nodes/21/attachments",
            json={
                "files": [
                    {"fileName": "forbidden.jpg", "fileSize": 3, "fileType": "image/jpeg"}
                ]
            },
            headers={"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"},
        ),
        "FORBIDDEN",
    )


def test_r69_requires_inspection_workflow_evidence_and_keeps_human_decision_gate() -> None:
    project_id = "P-2026-HDCP-001"
    inspection_headers = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
    before = assert_ok(client.get(f"/projects/{project_id}/nodes/69/package", headers=inspection_headers))
    assert [item["id"] for item in before["requirements"]] == ["REQ-69-01"]
    assert before["node"]["requiredProgress"] == {"done": 0, "total": 1}
    assert before["node"]["requirementsSummary"]["missingCount"] == 1

    blocked = assert_error(
        client.post(
            f"/projects/{project_id}/inspection/nodes/69/review-opinions",
            json={"result": "满足要求", "opinion": "不得在无证据时保存", "evidenceLinkIds": []},
            headers=inspection_headers,
        ),
        "VALIDATION_ERROR",
    )
    assert blocked["data"]["evidenceValidation"]["requiresEvidenceSelection"] is True

    upload = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/69/attachments",
            json={
                "files": [
                    {
                        "fileName": "B00-R69-001_质量保证体系实施状况评价工作流记录.xlsx",
                        "fileSize": 28,
                        "fileType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    }
                ]
            },
            headers=inspection_headers,
        )
    )
    target = upload["uploadUrls"][0]
    workbook_bytes = b"PK\x03\x04r69-workflow-evidence"
    assert_ok(client.put(target["url"], content=workbook_bytes, headers=target["headers"]))
    assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={
                "completedFiles": [
                    {
                        "documentVersionId": target["documentVersionId"],
                        "fileSize": len(workbook_bytes),
                    }
                ]
            },
            headers={**inspection_headers, "Idempotency-Key": "r69-workflow-complete"},
        )
    )
    bound = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/69/file-bindings",
            json={
                "bindings": [
                    {
                        "documentId": target["documentId"],
                        "documentVersionId": target["documentVersionId"],
                        "usage": "监检资料",
                    }
                ]
            },
            headers={**inspection_headers, "Idempotency-Key": "r69-workflow-bind"},
        )
    )
    binding_id = bound["affectedIds"][0]
    assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/69/file-bindings/submit",
            json={"bindingIds": [binding_id], "batchName": "R69 人工评价证据"},
            headers={**inspection_headers, "Idempotency-Key": "r69-workflow-submit"},
        )
    )

    after = assert_ok(client.get(f"/projects/{project_id}/nodes/69/package", headers=inspection_headers))
    assert after["node"]["requiredProgress"] == {"done": 1, "total": 1}
    assert after["node"]["requirementsSummary"]["missingCount"] == 0
    r69_binding = next(item for item in after["bindings"] if item["id"] == binding_id)
    assert r69_binding["requirementId"] == "REQ-69-01"
    assert r69_binding["bindingStatus"] == "已提交"
    assert not after["reviewOpinions"]


def test_if_match_conflict_and_review_admin_guard() -> None:
    conflict = client.patch(
        "/projects/P-2026-HDCP-001",
        json={"name": "changed"},
        headers={"If-Match": "W/\"outdated\""},
    )
    assert_error(conflict, "ETAG_CONFLICT")

    admin_review = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
        headers={"X-Role": "admin"},
        json={"result": "满足要求", "opinion": "admin should not save", "evidenceLinkIds": []},
    )
    assert_error(admin_review, "FORBIDDEN")


def test_project_management_etag_idempotency_and_versioned_responses() -> None:
    project_id = "P-2026-HDCP-001"
    detail = assert_ok(client.get(f"/projects/{project_id}"))
    etag = detail["project"]["etag"]
    revision = detail["project"]["revision"]
    assert etag == f'W/"project-{project_id}-r{revision}"'

    stale_update = client.patch(
        f"/projects/{project_id}",
        json={"name": "过期项目名称"},
        headers={"If-Match": f'W/"project-{project_id}-r0"'},
    )
    assert_error(stale_update, "ETAG_CONFLICT")

    updated = assert_ok(
        client.patch(
            f"/projects/{project_id}",
            json={"name": "版本化项目名称"},
            headers={"If-Match": etag, "Idempotency-Key": "project-update-once"},
        )
    )
    replayed = assert_ok(
        client.patch(
            f"/projects/{project_id}",
            json={"name": "版本化项目名称"},
            headers={"If-Match": etag, "Idempotency-Key": "project-update-once"},
        )
    )
    assert updated["project"]["name"] == "版本化项目名称"
    assert updated["project"]["revision"] == revision + 1
    assert updated["project"]["etag"] != etag
    assert replayed["project"]["etag"] == updated["project"]["etag"]

    participant = assert_ok(
        client.post(
            f"/projects/{project_id}/participants",
            json={"unitType": "owner", "unitName": "版本化参建单位"},
            headers={"If-Match": updated["project"]["etag"], "Idempotency-Key": "participant-save-once"},
        )
    )
    participant_replay = assert_ok(
        client.post(
            f"/projects/{project_id}/participants",
            json={"unitType": "owner", "unitName": "版本化参建单位"},
            headers={"If-Match": updated["project"]["etag"], "Idempotency-Key": "participant-save-once"},
        )
    )
    assert participant["project"]["revision"] == updated["project"]["revision"] + 1
    assert participant_replay["project"]["etag"] == participant["project"]["etag"]
    assert participant["participantUnit"]["unitName"] == "版本化参建单位"
    assert participant["participantUnit"]["id"] == f"PU-{project_id}-owner"
    listed_participants = assert_ok(client.get(f"/projects/{project_id}/participants"))
    saved_owner = next(item for item in listed_participants if item["unitType"] == "owner")
    assert saved_owner["unitName"] == "版本化参建单位"

    patched_participant = assert_ok(
        client.patch(
            f"/projects/{project_id}/participants/{saved_owner['id']}",
            json={"contactName": "王工", "contactPhone": "13800000000"},
            headers={
                "If-Match": participant["project"]["etag"],
                "Idempotency-Key": "participant-patch-once",
            },
        )
    )
    assert patched_participant["participantUnit"]["contactName"] == "王工"
    assert patched_participant["participantUnit"]["contactPhone"] == "13800000000"
    participant = patched_participant

    initialized = assert_ok(
        client.post(
            f"/projects/{project_id}/initialize-workflow",
            headers={"If-Match": participant["project"]["etag"], "Idempotency-Key": "workflow-init-once"},
        )
    )
    initialized_replay = assert_ok(
        client.post(
            f"/projects/{project_id}/initialize-workflow",
            headers={"If-Match": participant["project"]["etag"], "Idempotency-Key": "workflow-init-once"},
        )
    )
    assert initialized["createdNodeCount"] == 69
    assert initialized["project"]["revision"] == participant["project"]["revision"] + 1
    assert initialized_replay["project"]["etag"] == initialized["project"]["etag"]


def test_document_mutations_are_idempotent_and_project_etag_guarded(monkeypatch) -> None:
    project_id = "P-2026-HDCP-001"
    project = assert_ok(client.get(f"/projects/{project_id}"))["project"]

    upload = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": [{"fileName": "幂等上传.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
            headers={"If-Match": project["etag"], "Idempotency-Key": "upload-session-once"},
        )
    )
    upload_target = upload["uploadUrls"][0]
    upload_body = b"%PDF-idempotent-upload".ljust(1024, b"0")
    assert_ok(client.put(upload_target["url"], content=upload_body, headers=upload_target["headers"]))
    completed_files = [
        {"documentVersionId": upload_target["documentVersionId"], "fileSize": len(upload_body)}
    ]
    completed = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={"completedFiles": completed_files},
            headers={"If-Match": project["etag"], "Idempotency-Key": "upload-complete-once"},
        )
    )
    completed_replay = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={"completedFiles": completed_files},
            headers={"If-Match": project["etag"], "Idempotency-Key": "upload-complete-once"},
        )
    )
    assert completed_replay["id"] == completed["id"]
    assert completed_replay["fileCount"] == completed["fileCount"] == 1

    before_versions = len(repo.versions_for_document("DOC-20260625-001"))
    appended = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/DOC-20260625-001/versions",
            json={"mode": "append", "fileSize": 2048},
            headers={"If-Match": project["etag"], "Idempotency-Key": "document-version-once"},
        )
    )
    appended_replay = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/DOC-20260625-001/versions",
            json={"mode": "append", "fileSize": 2048},
            headers={"If-Match": project["etag"], "Idempotency-Key": "document-version-once"},
        )
    )
    assert appended_replay["version"]["id"] == appended["version"]["id"]
    assert len(repo.versions_for_document("DOC-20260625-001")) == before_versions + 1

    updated_binding = assert_ok(
        client.patch(
            f"/projects/{project_id}/documents/bindings/BIND-24-001",
            json={"usage": "证明材料"},
            headers={"If-Match": project["etag"], "Idempotency-Key": "binding-update-once"},
        )
    )
    updated_binding_replay = assert_ok(
        client.patch(
            f"/projects/{project_id}/documents/bindings/BIND-24-001",
            json={"usage": "证明材料"},
            headers={"If-Match": project["etag"], "Idempotency-Key": "binding-update-once"},
        )
    )
    assert updated_binding["binding"]["usage"] == "证明材料"
    assert updated_binding_replay["binding"]["usage"] == updated_binding["binding"]["usage"]

    deleted = assert_ok(
        client.delete(
            f"/projects/{project_id}/documents/bindings/BIND-24-002",
            headers={"If-Match": project["etag"], "Idempotency-Key": "binding-delete-once"},
        )
    )
    deleted_replay = assert_ok(
        client.delete(
            f"/projects/{project_id}/documents/bindings/BIND-24-002",
            headers={"If-Match": project["etag"], "Idempotency-Key": "binding-delete-once"},
        )
    )
    assert deleted["nextStatus"] == "已解除挂载"
    assert deleted_replay["id"] == deleted["id"]
    assert repo.find_one("bindings", "BIND-24-002") is None

    submitted_delete = client.delete(
        f"/projects/{project_id}/documents/DOC-20260625-001",
        headers={"If-Match": project["etag"], "Idempotency-Key": "submitted-document-delete"},
    )
    assert_error(submitted_delete, "CONFLICT")

    removable_upload = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={
                "files": [
                    {
                        "fileName": "未提交可删除资料.pdf",
                        "fileSize": 1024,
                        "fileType": "application/pdf",
                    }
                ]
            },
            headers={"If-Match": project["etag"], "Idempotency-Key": "document-delete-upload"},
        )
    )
    removable_target = removable_upload["uploadUrls"][0]
    removable_body = b"%PDF-removable-upload".ljust(1024, b"0")
    assert_ok(
        client.put(
            removable_target["url"],
            content=removable_body,
            headers=removable_target["headers"],
        )
    )
    complete_url = (
        f"/projects/{project_id}/documents/upload-session/"
        f"{removable_upload['uploadSessionId']}/complete"
    )
    assert_ok(
        client.post(
            complete_url,
            json={
                "completedFiles": [
                    {
                        "documentVersionId": removable_target["documentVersionId"],
                        "fileSize": len(removable_body),
                    }
                ]
            },
            headers={"If-Match": project["etag"], "Idempotency-Key": "document-delete-complete"},
        )
    )
    document_id = removable_target["documentId"]
    version_id = removable_target["documentVersionId"]
    knowledge_file_id = f"KF-{document_id}"
    repo.apply_slice_result(knowledge_file_id, [{"pageNo": 1, "text": "删除前切片"}])
    repo.apply_embed_result(
        knowledge_file_id,
        vectors=[{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
    )
    assert any(item.get("fileId") == knowledge_file_id for item in repo.state.get("knowledge_chunks", []))
    assert any(item.get("fileId") == knowledge_file_id for item in repo.state.get("knowledge_vectors", []))
    from apps.api import main as api_main

    flush_calls: list[tuple[set[str] | None, set[str] | None]] = []
    monkeypatch.setattr(
        api_main,
        "flush_state",
        lambda selected_state_keys=None, selected_singleton_keys=None: flush_calls.append(
            (selected_state_keys, selected_singleton_keys)
        ),
    )
    deleted_document = assert_ok(
        client.delete(
            f"/projects/{project_id}/documents/{document_id}",
            headers={"If-Match": project["etag"], "Idempotency-Key": "document-delete-once"},
        )
    )
    assert flush_calls == [
        (
            {
                "audit_logs",
                "bindings",
                "documents",
                "evidence_links",
                "extracted_fields",
                "knowledge_chunks",
                "knowledge_files",
                "knowledge_tasks",
                "knowledge_vectors",
                "ocr_corrections",
                "ocr_jobs",
                "ocr_parse_results",
                "submission_drafts",
                "upload_sessions",
                "versions",
            },
            None,
        )
    ]
    deleted_document_replay = assert_ok(
        client.delete(
            f"/projects/{project_id}/documents/{document_id}",
            headers={"If-Match": project["etag"], "Idempotency-Key": "document-delete-once"},
        )
    )
    assert deleted_document["nextStatus"] == "已删除"
    assert deleted_document_replay["id"] == deleted_document["id"]
    assert deleted_document["removed"]["documents"] == 1
    assert deleted_document["removed"]["versions"] == 1
    assert deleted_document["removed"]["knowledgeFiles"] == 1
    assert deleted_document["removed"]["knowledgeChunks"] == 1
    assert deleted_document["removed"]["knowledgeVectors"] == 1
    assert deleted_document["removed"]["knowledgeTasks"] == 1
    assert deleted_document["removed"]["uploadSessionFiles"] == 1
    assert repo.find_one("documents", document_id) is None
    assert repo.find_one("versions", version_id) is None
    assert not any(
        item.get("documentId") == document_id for item in repo.state.get("knowledge_files", [])
    )


def test_project_mutations_reject_stale_if_match_header() -> None:
    project_id = "P-2026-HDCP-001"
    stale = {"If-Match": 'W/"project-stale-r0"'}

    assert_error(
        client.post(
            f"/projects/{project_id}/documents/bindings",
            json={"nodeId": 16, "bindings": [{"documentId": "DOC-20260625-003"}]},
            headers=stale,
        ),
        "ETAG_CONFLICT",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/submissions",
            json={"nodeId": 16, "nodeIds": [16], "bindingIds": ["BIND-16-001"]},
            headers=stale,
        ),
        "ETAG_CONFLICT",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/films",
            json={"nodeId": 40, "filmNo": "STALE-RT", "weldNo": "W-ST", "method": "RT"},
            headers=stale,
        ),
        "ETAG_CONFLICT",
    )

    created = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/films",
            json={"nodeId": 40, "filmNo": "FRESH-RT", "weldNo": "W-FR", "method": "RT"},
            headers={"If-Match": "*"},
        )
    )
    assert created["film"]["filmNo"] == "FRESH-RT"


def test_inspection_ai_suggestion_mutations_are_idempotent_and_etag_guarded() -> None:
    project_id = "P-2026-HDCP-001"
    project = assert_ok(client.get(f"/projects/{project_id}"))["project"]
    suggestion_id = "AIS-24-20260625-01"
    adopt_payload = {
        "result": "满足要求",
        "opinion": "采纳 AI 建议生成草稿。",
        "reason": "证据链一致。",
    }

    assert_error(
        client.post(
            f"/projects/{project_id}/inspection/nodes/24/ai-suggestions/{suggestion_id}/adopt",
            json=adopt_payload,
            headers={"If-Match": 'W/"project-stale-r0"'},
        ),
        "ETAG_CONFLICT",
    )

    audit_count = len(repo.state["audit_logs"])
    adopt_headers = {"If-Match": project["etag"], "Idempotency-Key": "ai-adopt-once"}
    adopted = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/24/ai-suggestions/{suggestion_id}/adopt",
            json=adopt_payload,
            headers=adopt_headers,
        )
    )
    adopted_replay = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/24/ai-suggestions/{suggestion_id}/adopt",
            json=adopt_payload,
            headers=adopt_headers,
        )
    )
    assert adopted["draftOpinion"]["id"] == adopted_replay["draftOpinion"]["id"]
    assert adopted["auditLogId"] == adopted_replay["auditLogId"]
    assert len(repo.state["audit_logs"]) == audit_count + 1

    assert_error(
        client.post(
            f"/projects/{project_id}/inspection/nodes/24/ai-suggestions/{suggestion_id}/adopt",
            json={**adopt_payload, "reason": "不同原因"},
            headers=adopt_headers,
        ),
        "IDEMPOTENCY_KEY_CONFLICT",
    )

    reject_headers = {"If-Match": project["etag"], "Idempotency-Key": "ai-reject-once"}
    rejected = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/24/ai-suggestions/{suggestion_id}/reject",
            json={"reason": "人工复核不采纳。"},
            headers=reject_headers,
        )
    )
    rejected_replay = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/24/ai-suggestions/{suggestion_id}/reject",
            json={"reason": "人工复核不采纳。"},
            headers=reject_headers,
        )
    )
    assert rejected["id"] == rejected_replay["id"]
    assert rejected["auditLogId"] == rejected_replay["auditLogId"]


def test_ndt_import_and_update_mutations_are_idempotent_and_etag_guarded() -> None:
    project_id = "P-2026-HDCP-001"
    project = assert_ok(client.get(f"/projects/{project_id}"))["project"]
    stale = {"If-Match": 'W/"project-stale-r0"'}

    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/films/import",
            json={"nodeId": 40, "rows": [{"filmNo": "STALE-F", "weldNo": "W-ST", "method": "RT"}]},
            headers=stale,
        ),
        "ETAG_CONFLICT",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/records/import",
            json={"nodeId": 40, "rows": [{"recordNo": "STALE-R", "weldNo": "W-ST", "method": "RT"}]},
            headers=stale,
        ),
        "ETAG_CONFLICT",
    )

    film_import_headers = {"If-Match": project["etag"], "Idempotency-Key": "ndt-film-import-once"}
    film_before = len(repo.state["ndt_films"])
    film_payload = {
        "nodeId": 40,
        "rows": [
            {
                "filmNo": "RT-IMP-001",
                "weldNo": "W-IMP-001",
                "method": "RT",
                "pipelineNo": "PL-IMP-001",
                "reportNo": "RT-IMP-RPT-001",
                "entrustNo": "WT-IMP-001",
                "filmPackageNo": "FILM-PKG-IMP-001",
                "imageFileName": "RT-IMP-001.dcm",
                "detectionRatio": "10%",
                "standardCode": "NB/T 47013.2-2015",
                "imageQualityIndicator": "Fe 10",
                "sensitivity": "2.0%",
                "density": "2.8",
                "geometricUnsharpness": "0.2mm",
                "evaluationLevel": "II",
                "defectLocation": "W-IMP-001 3 点方向",
                "evaluatorName": "王工",
                "reviewerName": "赵工",
            },
            {"filmNo": "UT-IMP-002", "weldNo": "W-IMP-002", "method": "UT"},
        ],
    }
    film_import = assert_ok(client.post(f"/projects/{project_id}/ndt/films/import", json=film_payload, headers=film_import_headers))
    film_import_replay = assert_ok(client.post(f"/projects/{project_id}/ndt/films/import", json=film_payload, headers=film_import_headers))
    assert film_import["imported"] == 2
    assert [item["id"] for item in film_import["films"]] == [item["id"] for item in film_import_replay["films"]]
    assert film_import["films"][0]["entrustNo"] == "WT-IMP-001"
    assert film_import["films"][0]["density"] == "2.8"
    assert film_import["films"][0]["imageFileName"] == "RT-IMP-001.dcm"
    assert len(repo.state["ndt_films"]) == film_before + 2

    update_headers = {"If-Match": project["etag"], "Idempotency-Key": "ndt-film-update-once"}
    updated = assert_ok(
        client.patch(
            f"/projects/{project_id}/ndt/films/{film_import['films'][0]['id']}",
            json={"pipelineNo": "P-IMP-001"},
            headers=update_headers,
        )
    )
    updated_replay = assert_ok(
        client.patch(
            f"/projects/{project_id}/ndt/films/{film_import['films'][0]['id']}",
            json={"pipelineNo": "P-IMP-001"},
            headers=update_headers,
        )
    )
    assert updated["film"]["pipelineNo"] == "P-IMP-001"
    assert updated["id"] == updated_replay["id"]
    assert updated["auditLogId"] == updated_replay["auditLogId"]

    record_import_headers = {"If-Match": project["etag"], "Idempotency-Key": "ndt-record-import-once"}
    record_before = len(repo.state["ndt_records"])
    record_payload = {
        "nodeId": 40,
        "rows": [
            {
                "recordNo": "REC-IMP-001",
                "weldNo": "W-IMP-001",
                "method": "RT",
                "pipelineNo": "PL-IMP-001",
                "entrustNo": "WT-IMP-001",
                "reportNo": "RT-IMP-RPT-001",
                "techniqueNo": "NDT-WI-IMP-001",
                "equipmentNo": "XRY-IMP-001",
                "personnelCertificateNo": "RT-II-IMP-001",
                "detectionRatio": "10%",
                "standardCode": "NB/T 47013.2-2015",
                "reviewerName": "赵工",
                "evaluationLevel": "II",
                "signatureStatus": "已签字",
                "stampStatus": "已盖章",
            },
            {"recordNo": "REC-IMP-002", "weldNo": "W-IMP-002", "method": "UT"},
        ],
    }
    record_import = assert_ok(client.post(f"/projects/{project_id}/ndt/records/import", json=record_payload, headers=record_import_headers))
    record_import_replay = assert_ok(client.post(f"/projects/{project_id}/ndt/records/import", json=record_payload, headers=record_import_headers))
    assert record_import["imported"] == 2
    assert [item["id"] for item in record_import["records"]] == [item["id"] for item in record_import_replay["records"]]
    assert record_import["records"][0]["reportNo"] == "RT-IMP-RPT-001"
    assert record_import["records"][0]["equipmentNo"] == "XRY-IMP-001"
    assert record_import["records"][0]["signatureStatus"] == "已签字"
    assert len(repo.state["ndt_records"]) == record_before + 2


def test_singleton_config_if_match_and_revision_guards() -> None:
    knowledge = assert_ok(client.get("/knowledge/config"))
    knowledge_etag = knowledge["etag"]
    knowledge_revision = knowledge["revision"]

    assert_error(
        client.put(
            "/knowledge/config",
            json={"chunkSize": 960, "revision": 0, "etag": 'W/"client-r0"'},
            headers={"If-Match": 'W/"knowledge-config-r0"'},
        ),
        "ETAG_CONFLICT",
    )
    updated_knowledge = assert_ok(
        client.put(
            "/knowledge/config",
            json={"chunkSize": 960, "revision": 0, "etag": 'W/"client-r0"'},
            headers={"If-Match": knowledge_etag, "Idempotency-Key": "knowledge-config-update-once"},
        )
    )
    updated_knowledge_replay = assert_ok(
        client.put(
            "/knowledge/config",
            json={"chunkSize": 960, "revision": 0, "etag": 'W/"client-r0"'},
            headers={"If-Match": knowledge_etag, "Idempotency-Key": "knowledge-config-update-once"},
        )
    )
    assert updated_knowledge["config"]["chunkSize"] == 960
    assert updated_knowledge_replay["etag"] == updated_knowledge["etag"]
    assert updated_knowledge_replay["auditLogId"] == updated_knowledge["auditLogId"]
    assert updated_knowledge["revision"] == knowledge_revision + 1
    assert updated_knowledge["etag"] != knowledge_etag
    assert "etag" not in repo.state["knowledge_config"]

    overview = assert_ok(client.get("/admin/config-overview"))
    admin_etag = overview["etag"]
    admin_revision = overview["revision"]
    assert_error(
        client.put(
            "/admin/config-items/todo-rule/TR-001",
            json={"values": {"deadlineHours": 72}},
            headers={"If-Match": 'W/"admin-config-r0"'},
        ),
        "ETAG_CONFLICT",
    )
    saved_config = assert_ok(
        client.put(
            "/admin/config-items/todo-rule/TR-001",
            json={"values": {"deadlineHours": 72}, "reason": "并发控制测试"},
            headers={"If-Match": admin_etag},
        )
    )
    assert saved_config["overview"]["todoRules"][0]["deadlineHours"] == 72
    assert saved_config["revision"] == admin_revision + 1
    assert saved_config["etag"] != admin_etag

    save_headers = {"If-Match": saved_config["etag"], "Idempotency-Key": "admin-config-save-once"}
    saved_idempotent = assert_ok(
        client.put(
            "/admin/config-items/todo-rule/TR-001",
            json={"values": {"deadlineHours": 96}, "reason": "幂等保存测试"},
            headers=save_headers,
        )
    )
    saved_replay = assert_ok(
        client.put(
            "/admin/config-items/todo-rule/TR-001",
            json={"values": {"deadlineHours": 96}, "reason": "幂等保存测试"},
            headers=save_headers,
        )
    )
    assert saved_idempotent["auditLogId"] == saved_replay["auditLogId"]
    assert saved_idempotent["etag"] == saved_replay["etag"]
    assert saved_idempotent["overview"]["todoRules"][0]["deadlineHours"] == 96

    message_count = len(repo.state["admin_config"].get("messageTemplates", []))
    create_headers = {"If-Match": saved_idempotent["etag"], "Idempotency-Key": "admin-config-create-once"}
    created_item = assert_ok(
        client.post(
            "/admin/config-items/message-template",
            json={"target": "message-template", "values": {"scene": "合同测试通知", "title": "配置变更", "content": "配置已更新。"}},
            headers=create_headers,
        )
    )
    created_item_replay = assert_ok(
        client.post(
            "/admin/config-items/message-template",
            json={"target": "message-template", "values": {"scene": "合同测试通知", "title": "配置变更", "content": "配置已更新。"}},
            headers=create_headers,
        )
    )
    assert created_item["auditLogId"] == created_item_replay["auditLogId"]
    assert created_item["diff"]["objectId"] == created_item_replay["diff"]["objectId"]
    assert len(repo.state["admin_config"]["messageTemplates"]) == message_count + 1

    workflow_count = len(repo.state["admin_config"].get("workflowStateMachines", []))
    workflow_headers = {"If-Match": created_item["etag"], "Idempotency-Key": "admin-workflow-create-once"}
    workflow = assert_ok(
        client.post(
            "/admin/workflow-state-machines",
            json={"name": "合同测试状态机", "version": "2026.07", "status": "启用"},
            headers=workflow_headers,
        )
    )
    workflow_replay = assert_ok(
        client.post(
            "/admin/workflow-state-machines",
            json={"name": "合同测试状态机", "version": "2026.07", "status": "启用"},
            headers=workflow_headers,
        )
    )
    assert workflow["item"]["id"] == workflow_replay["item"]["id"]
    assert workflow["auditLogId"] == workflow_replay["auditLogId"]
    assert len(repo.state["admin_config"]["workflowStateMachines"]) == workflow_count + 1

    workflow_update_headers = {"If-Match": workflow["etag"], "Idempotency-Key": "admin-workflow-update-once"}
    workflow_updated = assert_ok(
        client.patch(
            f"/admin/workflow-state-machines/{workflow['item']['id']}",
            json={"status": "停用"},
            headers=workflow_update_headers,
        )
    )
    workflow_updated_replay = assert_ok(
        client.patch(
            f"/admin/workflow-state-machines/{workflow['item']['id']}",
            json={"status": "停用"},
            headers=workflow_update_headers,
        )
    )
    assert workflow_updated["item"]["status"] == "停用"
    assert workflow_updated["auditLogId"] == workflow_updated_replay["auditLogId"]

    assert_error(
        client.post(
            "/admin/config-overview/publish",
            json={"scope": "all", "reason": "stale publish"},
            headers={"If-Match": admin_etag},
        ),
        "ETAG_CONFLICT",
    )
    publish_headers = {"If-Match": workflow_updated["etag"], "Idempotency-Key": "publish-config-once"}
    published = assert_ok(
        client.post(
            "/admin/config-overview/publish",
            json={"scope": "all", "reason": "publish with fresh etag"},
            headers=publish_headers,
        )
    )
    replayed = assert_ok(
        client.post(
            "/admin/config-overview/publish",
            json={"scope": "all", "reason": "publish with fresh etag"},
            headers=publish_headers,
        )
    )
    assert replayed["publishId"] == published["publishId"]
    assert published["revision"] == workflow_updated["revision"] + 1
    assert published["etag"] != workflow_updated["etag"]
    published_overview = assert_ok(client.get("/admin/config-overview"))
    assert published_overview["lastPublishedVersion"] == published["version"]
    assert published_overview["etag"] == published["etag"]


def test_prompt_template_management_api_and_audit_metadata() -> None:
    templates = assert_ok(client.get("/admin/prompt-templates?pageSize=100"))
    assert templates["total"] >= 1
    assert templates["items"][0]["systemPrompt"]
    assert templates["items"][0]["userPromptTemplate"]

    create_headers = {"Idempotency-Key": "prompt-template-create-once"}
    payload = {
        "name": "合同测试 Prompt 模板",
        "promptKey": "review_prompt",
        "version": "2026.07-test",
        "status": "draft",
        "businessPackId": "engineering_inspection_v1",
        "agentId": "compliance_review_agent",
        "systemPrompt": "你是工程监检审查助手。",
        "userPromptTemplate": "{{basePromptJson}}\n\n{{reviewTaskJson}}",
        "plannerPromptTemplate": "先读取上下文，再执行规则、检索证据并生成建议。",
        "criticPromptTemplate": "检查每条建议是否有规则和证据。",
        "outputSchema": {"type": "ReviewFindingDraftList"},
    }
    created = assert_ok(client.post("/admin/prompt-templates", json=payload, headers=create_headers))
    replayed_create = assert_ok(client.post("/admin/prompt-templates", json=payload, headers=create_headers))
    assert created["template"]["id"] == replayed_create["template"]["id"]
    assert created["auditLogId"] == replayed_create["auditLogId"]

    template = created["template"]
    updated = assert_ok(
        client.put(
            f"/admin/prompt-templates/{template['id']}",
            json={"systemPrompt": "你是工程监检审查助手，必须保留证据引用。"},
            headers={"If-Match": template["etag"], "Idempotency-Key": "prompt-template-update-once"},
        )
    )
    assert updated["template"]["revision"] == template["revision"] + 1
    assert "证据引用" in updated["template"]["systemPrompt"]

    published = assert_ok(
        client.post(
            f"/admin/prompt-templates/{template['id']}/publish",
            json={"reason": "合同测试发布"},
            headers={"If-Match": updated["template"]["etag"], "Idempotency-Key": "prompt-template-publish-once"},
        )
    )
    assert published["template"]["status"] == "production"
    assert_error(
        client.delete(
            f"/admin/prompt-templates/{template['id']}",
            headers={"If-Match": published["template"]["etag"], "Idempotency-Key": "prompt-template-delete-production"},
        ),
        "VALIDATION_ERROR",
    )


def test_report_template_management_publish_and_report_generation_snapshot() -> None:
    templates = assert_ok(client.get("/admin/report-templates?pageSize=100"))
    assert templates["total"] >= 1
    assert templates["items"][0]["sections"]

    invalid = client.post(
        "/admin/report-templates",
        json={"name": "无章节模板", "sections": []},
        headers={"Idempotency-Key": "report-template-invalid"},
    )
    assert_error(invalid, "VALIDATION_ERROR")

    payload = {
        "name": "合同测试报告模板",
        "version": "2026.07-test",
        "status": "draft",
        "businessPackId": "engineering_inspection_v1",
        "businessPackVersion": "2026.07-test",
        "exportTypes": ["report", "archive-package"],
        "sections": [
            {"code": "contract_summary", "title": "合同测试概况", "source": "project"},
            {"code": "contract_evidence", "title": "合同测试证据", "source": "evidence_links"},
        ],
    }
    create_headers = {"Idempotency-Key": "report-template-create-once"}
    created = assert_ok(client.post("/admin/report-templates", json=payload, headers=create_headers))
    replayed = assert_ok(client.post("/admin/report-templates", json=payload, headers=create_headers))
    assert replayed["template"]["id"] == created["template"]["id"]
    assert replayed["auditLogId"] == created["auditLogId"]

    template = created["template"]
    updated = assert_ok(
        client.patch(
            f"/admin/report-templates/{template['id']}",
            json={"name": "合同测试报告模板（已编辑）"},
            headers={
                "If-Match": template["etag"],
                "Idempotency-Key": "report-template-update-once",
            },
        )
    )
    assert updated["template"]["revision"] == template["revision"] + 1

    published = assert_ok(
        client.post(
            f"/admin/report-templates/{template['id']}/publish",
            json={"reason": "合同测试发布"},
            headers={
                "If-Match": updated["template"]["etag"],
                "Idempotency-Key": "report-template-publish-once",
            },
        )
    )
    assert published["template"]["status"] == "production"
    production_templates = assert_ok(
        client.get(
            "/admin/report-templates?businessPackId=engineering_inspection_v1&status=production&pageSize=100"
        )
    )
    assert [item["id"] for item in production_templates["items"]] == [template["id"]]

    project_id = "P-2026-HDCP-001"
    seed_reviewed_node_24(project_id)
    generated = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/24/report-review",
            json={"includeEvidence": True, "reportScope": "currentNode"},
            headers={"Idempotency-Key": "report-template-generation-once"},
        )
    )
    report = generated["report"]
    assert report["templateId"] == template["id"]
    assert report["templateVersion"] == "2026.07-test"
    assert report["templateSnapshot"]["name"] == "合同测试报告模板（已编辑）"
    assert [section["key"] for section in report["sections"]] == [
        "contract_summary",
        "contract_evidence",
    ]

    assert_error(
        client.patch(
            f"/admin/report-templates/{template['id']}",
            json={"name": "不允许直接编辑生产模板"},
            headers={
                "If-Match": published["template"]["etag"],
                "Idempotency-Key": "report-template-update-production",
            },
        ),
        "VALIDATION_ERROR",
    )

    assert_error(
        client.delete(
            f"/admin/report-templates/{template['id']}",
            headers={
                "If-Match": published["template"]["etag"],
                "Idempotency-Key": "report-template-delete-production",
            },
        ),
        "VALIDATION_ERROR",
    )


def test_reasoning_log_detail_exposes_masked_llm_audit_projection() -> None:
    detail = assert_ok(client.get("/reasoning/logs/AIRUN-24-20260625-01"))

    assert "promptAudit" not in detail["log"]
    assert "llmMetadata" not in detail["log"]
    assert detail["accessPolicy"]["rawAccess"] is False
    assert detail["llmAudit"]["visibility"] == "masked"
    assert detail["promptAudit"]["systemPrompt"]
    assert detail["promptAudit"]["userPrompt"]
    assert detail["promptAudit"]["plannerPrompt"]
    assert detail["promptAudit"]["criticPrompt"]
    assert detail["promptAudit"]["messagesHash"].startswith("sha256:")
    assert detail["llmMetadata"]["conversationId"] == "chatcmpl-aicheck-demo-24-001"
    assert detail["llmMetadata"]["promptHash"]
    assert detail["llmMetadata"]["responseHash"]
    assert detail["llmMetadata"]["resultText"]
    assert "reasoningProcess" not in detail["llmMetadata"]
    assert detail["llmAudit"]["reasoning"]["redactionPolicy"] == "audit_summary_only_no_raw_chain_of_thought"
    assert detail["llmAudit"]["reasoning"]["rawChainOfThoughtAvailable"] is False
    assert any(step.get("conversationId") == "chatcmpl-aicheck-demo-24-001" for step in detail["traceSteps"])


def test_knowledge_record_if_match_and_revision_guards() -> None:
    sources = assert_ok(client.get("/knowledge/sources"))
    source = sources["items"][0]
    assert "etag" in source

    assert_error(
        client.put(
            f"/knowledge/sources/{source['id']}",
            json={"name": "过期知识源"},
            headers={"If-Match": 'W/"knowledge-source-stale-r0"'},
        ),
        "ETAG_CONFLICT",
    )
    updated_source = assert_ok(
        client.put(
            f"/knowledge/sources/{source['id']}",
            json={"name": "版本化知识源"},
            headers={"If-Match": source["etag"], "Idempotency-Key": "knowledge-source-update-once"},
        )
    )
    replayed_source = assert_ok(
        client.put(
            f"/knowledge/sources/{source['id']}",
            json={"name": "版本化知识源"},
            headers={"If-Match": source["etag"], "Idempotency-Key": "knowledge-source-update-once"},
        )
    )
    assert replayed_source["source"]["id"] == updated_source["source"]["id"]
    assert updated_source["source"]["name"] == "版本化知识源"
    assert updated_source["source"]["revision"] == source["revision"] + 1
    assert updated_source["source"]["etag"] != source["etag"]

    task = assert_ok(client.get("/knowledge/tasks/KT-20260626-001"))["task"]
    assert_error(
        client.post(
            "/knowledge/tasks/KT-20260626-001/cancel",
            json={"reason": "stale cancel"},
            headers={"If-Match": 'W/"knowledge-task-stale-r0"'},
        ),
        "ETAG_CONFLICT",
    )
    cancelled = assert_ok(
        client.post(
            "/knowledge/tasks/KT-20260626-001/cancel",
            json={"reason": "fresh cancel"},
            headers={"If-Match": task["etag"], "Idempotency-Key": "knowledge-task-cancel-once"},
        )
    )
    replayed_cancel = assert_ok(
        client.post(
            "/knowledge/tasks/KT-20260626-001/cancel",
            json={"reason": "fresh cancel"},
            headers={"If-Match": task["etag"], "Idempotency-Key": "knowledge-task-cancel-once"},
        )
    )
    assert replayed_cancel["task"]["revision"] == cancelled["task"]["revision"]
    assert cancelled["task"]["status"] == "已取消"
    assert cancelled["task"]["revision"] == task["revision"] + 1
    assert cancelled["task"]["etag"] != task["etag"]

    rule = next(
        item
        for item in assert_ok(client.get("/rules/versions?pageSize=100"))["items"]
        if item["id"] == "RULE-NDT-202606"
    )
    assert_error(
        client.post(
            f"/rules/versions/{rule['id']}/publish",
            json={"reason": "stale rule publish"},
            headers={"If-Match": 'W/"rule-version-stale-r0"'},
        ),
        "ETAG_CONFLICT",
    )
    published_rule = assert_ok(
        client.post(
            f"/rules/versions/{rule['id']}/publish",
            json={"reason": "fresh rule publish"},
            headers={"If-Match": rule["etag"], "Idempotency-Key": "rule-version-publish-once"},
        )
    )
    replayed_rule = assert_ok(
        client.post(
            f"/rules/versions/{rule['id']}/publish",
            json={"reason": "fresh rule publish"},
            headers={"If-Match": rule["etag"], "Idempotency-Key": "rule-version-publish-once"},
        )
    )
    assert replayed_rule["rule"]["etag"] == published_rule["rule"]["etag"]
    assert published_rule["rule"]["status"] == "已发布"
    assert published_rule["rule"]["revision"] == rule["revision"] + 1
    assert published_rule["rule"]["etag"] != rule["etag"]


def test_todo_message_if_match_idempotency_and_revision_guards() -> None:
    todo = assert_ok(client.get("/todos"))["items"][0]
    assert "etag" in todo
    assert_error(
        client.post(
            f"/todos/{todo['id']}/complete",
            json={"comment": "stale complete"},
            headers={"If-Match": 'W/"todo-stale-r0"'},
        ),
        "ETAG_CONFLICT",
    )
    completed = assert_ok(
        client.post(
            f"/todos/{todo['id']}/complete",
            json={"comment": "fresh complete"},
            headers={"If-Match": todo["etag"], "Idempotency-Key": "todo-complete-once"},
        )
    )
    replayed_complete = assert_ok(
        client.post(
            f"/todos/{todo['id']}/complete",
            json={"comment": "fresh complete"},
            headers={"If-Match": todo["etag"], "Idempotency-Key": "todo-complete-once"},
        )
    )
    assert completed["nextStatus"] == "已完成"
    assert completed["todo"]["revision"] == todo["revision"] + 1
    assert completed["todo"]["etag"] != todo["etag"]
    assert replayed_complete["todo"]["etag"] == completed["todo"]["etag"]

    message = assert_ok(client.get("/messages"))["items"][0]
    assert_error(
        client.post(
            f"/messages/{message['id']}/read",
            headers={"If-Match": 'W/"message-stale-r0"'},
        ),
        "ETAG_CONFLICT",
    )
    read_message = assert_ok(
        client.post(
            f"/messages/{message['id']}/read",
            headers={"If-Match": message["etag"], "Idempotency-Key": "message-read-once"},
        )
    )
    replayed_read = assert_ok(
        client.post(
            f"/messages/{message['id']}/read",
            headers={"If-Match": message["etag"], "Idempotency-Key": "message-read-once"},
        )
    )
    assert read_message["message"]["read"] is True
    assert read_message["message"]["revision"] == message["revision"] + 1
    assert read_message["message"]["etag"] != message["etag"]
    assert replayed_read["message"]["etag"] == read_message["message"]["etag"]

    assert_error(
        client.post(
            "/messages/read-all",
            json={"projectId": "P-2026-HDCP-001"},
            headers={"If-Match": message["etag"]},
        ),
        "ETAG_CONFLICT",
    )
    bulk = assert_ok(
        client.post(
            "/messages/read-all",
            json={"projectId": "P-2026-HDCP-001"},
            headers={"If-Match": "*", "Idempotency-Key": "message-read-all-once"},
        )
    )
    replayed_bulk = assert_ok(
        client.post(
            "/messages/read-all",
            json={"projectId": "P-2026-HDCP-001"},
            headers={"If-Match": "*", "Idempotency-Key": "message-read-all-once"},
        )
    )
    assert bulk["affectedCount"] >= 0
    assert bulk["auditLogId"]
    assert replayed_bulk["affectedCount"] == bulk["affectedCount"]


def test_optional_jwt_action_and_node_scope_guards(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    unauthenticated = client.get("/api/auth/me")
    assert_error(unauthenticated, "AUTH_REQUIRED")

    role_spoof = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
        headers={"Authorization": "Bearer dev-token-contractor-contractor", "X-Role": "inspection"},
    )
    assert_error(role_spoof, "FORBIDDEN")

    action_forbidden = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
        headers={"Authorization": "Bearer dev-token-admin-admin", "X-Role": "contractor", "X-Action-Code": "review:save"},
    )
    assert_error(action_forbidden, "FORBIDDEN")

    inferred_node_forbidden = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/40/ai-recheck",
        headers={"Authorization": "Bearer dev-token-contractor-contractor", "X-Role": "contractor"},
    )
    assert_error(inferred_node_forbidden, "FORBIDDEN")

    node_forbidden = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/40/ai-recheck",
        headers={
            "Authorization": "Bearer dev-token-admin-admin",
            "X-Role": "contractor",
            "X-User-Id": "USER-CONTRACTOR-001",
        },
    )
    assert_error(node_forbidden, "FORBIDDEN")


def test_required_action_inference_covers_core_mutations() -> None:
    from libs.security.actions import required_action_for_request

    cases = [
        ("POST", "/api/projects/P-2026-HDCP-001/submissions", "submission:submit"),
        ("POST", "/api/projects/P-2026-HDCP-001/documents/batch-classify", "file:bind"),
        ("POST", "/api/projects/P-2026-HDCP-001/inspection/nodes/24/report-review", "report:generate"),
        ("POST", "/api/projects/P-2026-HDCP-001/reports/RPT-001/archive", "report:archive"),
        ("POST", "/api/projects/P-2026-HDCP-001/ndt/submissions", "ndt:submit"),
        ("POST", "/api/todos/TODO-001/complete", "todo:update"),
        ("POST", "/api/messages/MSG-001/read", "message:update"),
        ("POST", "/api/knowledge/retrieval-test", "knowledge:view"),
        ("POST", "/api/admin/config-overview/publish", "admin:config"),
        ("POST", "/api/fde/releases/REL-001/approve", "admin:config"),
        ("POST", "/api/fde/ocr-100/action-board/refresh", "fde:ocr-annotation:manage"),
        ("POST", "/api/fde/capability-tests/ocr/upload-session", "fde:ocr-quality:view"),
        ("POST", "/api/fde/capability-tests/ocr/upload-session/FDE-OCR-UP-001/file", "fde:ocr-quality:view"),
        ("PUT", "/api/fde/capability-tests/ocr/upload-session/FDE-OCR-UP-001/file", "fde:ocr-quality:view"),
        ("POST", "/api/fde/capability-tests/ocr/runs", "fde:ocr-quality:view"),
        ("POST", "/api/fde/capability-tests/ocr/runs/RUN-001/rerun", "fde:ocr-quality:view"),
        ("POST", "/api/fde/capability-tests/ocr/runs/RUN-001/to-annotation", "fde:ocr-annotation:manage"),
        ("POST", "/api/fde/capability-tests/ocr/runs/RUN-001/to-evaluation-case", "fde:evaluation:run"),
        ("POST", "/api/fde/vector-corrections", "fde:vector-quality:review"),
        ("POST", "/api/fde/vector-corrections/KVCR-001/approve", "fde:vector-quality:review"),
        ("POST", "/api/fde/vector-corrections/KVCR-001/reject", "fde:vector-quality:review"),
        ("POST", "/api/fde/vector-corrections/KVCR-001/apply", "fde:vector-quality:apply"),
        ("DELETE", "/api/fde/ocr-annotation/tasks/ANNO-001", "fde:ocr-annotation:manage"),
        ("PUT", "/api/admin/config-items/todo-rule/TR-001", "admin:config"),
        ("PATCH", "/api/knowledge/config", "knowledge:manage"),
        ("PUT", "/api/knowledge/config", "knowledge:manage"),
        ("POST", "/api/llm/compare", "llm:compare"),
    ]

    for method, path, expected in cases:
        assert required_action_for_request(method, path) == expected
    assert required_action_for_request("GET", "/api/admin/config-overview") is None


def test_fde_ocr_capability_run_requires_uploaded_file_for_mock_session() -> None:
    upload = assert_ok(
        client.post(
            "/api/fde/capability-tests/ocr/upload-session",
            json={
                "file": {
                    "fileName": "设计资料.pdf",
                    "fileType": "application/pdf",
                    "contentType": "application/pdf",
                    "fileSize": 128,
                }
            },
            headers={"X-Role": "fde"},
        )
    )["uploadSession"]

    payload = assert_error(
        client.post(
            "/api/fde/capability-tests/ocr/runs",
            json={"uploadSessionId": upload["uploadSessionId"]},
            headers={"X-Role": "fde"},
        ),
        "VALIDATION_ERROR",
    )

    assert "尚未上传" in payload["message"]


def test_fde_ocr_capability_upload_file_accepts_declared_put_method() -> None:
    upload = assert_ok(
        client.post(
            "/api/fde/capability-tests/ocr/upload-session",
            json={
                "file": {
                    "fileName": "设计资料.pdf",
                    "fileType": "application/pdf",
                    "contentType": "application/pdf",
                    "fileSize": 16,
                }
            },
            headers={"X-Role": "fde"},
        )
    )["uploadSession"]

    assert upload["method"] == "PUT"
    saved = assert_ok(
        client.put(
            f"/api/fde/capability-tests/ocr/upload-session/{upload['uploadSessionId']}/file",
            content=b"%PDF-1.4\nocr\n",
            headers={"X-Role": "fde", "Content-Type": "application/pdf"},
        )
    )["uploadSession"]

    assert saved["status"] == "uploaded"
    assert saved["fileSize"] > 0


def test_fde_ocr_capability_page_preview_requires_fde_permission(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    repo.state.setdefault("fde_capability_test_runs", []).append(
        {
            "id": "FDE-OCR-RUN-AUTH",
            "runId": "FDE-OCR-RUN-AUTH",
            "status": "success",
            "fileName": "设计资料.pdf",
            "contentType": "application/pdf",
            "storageKey": "/tmp/missing.pdf",
            "options": {},
        }
    )

    assert_error(
        client.get(
            "/api/fde/capability-tests/ocr/runs/FDE-OCR-RUN-AUTH/page-preview?pageNo=1",
            headers={"Authorization": "Bearer dev-token-contractor-contractor"},
        ),
        "FORBIDDEN",
    )


def test_all_non_public_mutating_routes_have_inferred_action_codes() -> None:
    from apps.api.routes import mock_router, router
    from libs.security.actions import MUTATING_METHODS, required_action_for_request

    public_mutations = {
        ("POST", "/mock/user/login"),
        ("POST", "/api/mock/user/login"),
        ("POST", "/auth/login"),
        ("POST", "/api/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/change-password"),
    }
    missing = []
    checked = 0
    for route in [*router.routes, *mock_router.routes]:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        for method in methods:
            if (method, path) in public_mutations:
                continue
            checked += 1
            if required_action_for_request(method, path) is None:
                missing.append(f"{method} {path}")

    assert checked >= 150
    assert missing == []


def test_project_mutating_routes_are_archived_readonly_guarded() -> None:
    from apps.api.routes import router
    from libs.security.actions import MUTATING_METHODS

    delegated_guard_routes = {
        ("POST", "/projects/{project_id}/inspection/nodes/{node_id}/attachments"),
        ("POST", "/projects/{project_id}/inspection/nodes/{node_id}/file-bindings"),
        ("POST", "/projects/{project_id}/nodes/{node_id}/evidence-links/{evidence_link_id}/confirm"),
        ("POST", "/projects/{project_id}/nodes/{node_id}/evidence-links/{evidence_link_id}/reject"),
        # The endpoint is a thin wrapper after the upload workflow extraction;
        # upload_session_file_workflow owns the tested mutation_guard call.
        (
            "PUT",
            "/projects/{project_id}/documents/upload-session/{session_id}/files/{document_version_id}",
        ),
    }
    missing = []
    checked = 0
    for route in router.routes:
        path = getattr(route, "path", "")
        if "{project_id}" not in path:
            continue
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        for method in methods:
            checked += 1
            if (method, path) in delegated_guard_routes:
                continue
            endpoint = getattr(route, "endpoint", None)
            source = inspect.getsource(endpoint) if endpoint is not None else ""
            if "mutation_guard(" not in source:
                missing.append(f"{method} {path}")

    assert checked >= 45
    assert missing == []


def test_all_non_public_mutating_routes_are_audit_logged() -> None:
    from apps.api.main import audit_scope
    from apps.api.routes import mock_router, router
    from libs.security.actions import MUTATING_METHODS

    unaudited_public_routes = {
        ("POST", "/mock/user/login"),
        ("POST", "/api/mock/user/login"),
        ("POST", "/auth/login"),
        ("POST", "/api/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/change-password"),
    }
    missing = []
    checked = 0
    for route in [*router.routes, *mock_router.routes]:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        for method in methods:
            if (method, path) in unaudited_public_routes:
                continue
            checked += 1
            assert audit_scope(type("Req", (), {"method": method, "url": type("Url", (), {"path": path})()})()) is not None
            endpoint = getattr(route, "endpoint", None)
            source = inspect.getsource(endpoint) if endpoint is not None else ""
            has_explicit_audit = "mutation_result" in source or "add_audit" in source or "auditLogId" in source
            if not has_explicit_audit and audit_scope(type("Req", (), {"method": method, "url": type("Url", (), {"path": path})()})()) is None:
                missing.append(f"{method} {path}")

    assert checked >= 150
    assert missing == []


def test_inferred_action_codes_block_role_bypass_when_auth_required(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    project_id = "P-2026-HDCP-001"
    contractor_headers = {"Authorization": "Bearer dev-token-contractor-contractor"}
    inspection_headers = {"Authorization": "Bearer dev-token-inspection-inspection"}
    ndt_headers = {"Authorization": "Bearer dev-token-ndt-ndt"}
    admin_headers = {"Authorization": "Bearer dev-token-admin-admin"}

    assert_error(
        client.post(
            f"/api/projects/{project_id}/inspection/nodes/24/report-review",
            json={"includeEvidence": True, "reportScope": "currentNode"},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            "/api/admin/config-overview/publish",
            json={"scope": "all"},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            f"/api/projects/{project_id}/submissions",
            json={"nodeIds": [16], "bindingIds": ["BIND-16-001"]},
            headers=inspection_headers,
        ),
        "FORBIDDEN",
    )

    mark_ndt_report_ready("NDT-RPT-001")
    ndt_submit = assert_ok(
        client.post(
            f"/api/projects/{project_id}/ndt/submissions",
            json={"nodeId": 40, "reportIds": ["NDT-RPT-001"], "filmIds": ["FILM-RT-001"]},
            headers=ndt_headers,
        )
    )
    admin_preview = assert_ok(
        client.post(
            "/api/admin/config-overview/publish-preview",
            json={"scope": "all", "reason": "验证管理员发布权限与影响预览"},
            headers=admin_headers,
        )
    )
    admin_publish = assert_ok(
        client.post(
            "/api/admin/config-overview/publish",
            json={
                "scope": "all",
                "reason": "验证管理员发布权限与影响预览",
                "previewId": admin_preview["previewId"],
            },
            headers=admin_headers,
        )
    )

    assert ndt_submit["nextStatus"] == "待审查"
    assert admin_publish["status"] == "已发布"


def test_body_node_scope_is_enforced_for_project_mutations(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    project_id = "P-2026-HDCP-001"
    contractor_headers = {"Authorization": "Bearer dev-token-contractor-contractor"}
    ndt_headers = {"Authorization": "Bearer dev-token-ndt-ndt"}

    assert_error(
        client.post(
            f"/api/projects/{project_id}/submissions",
            json={"nodeIds": [40], "bindingIds": ["BIND-40-001"]},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            f"/api/projects/{project_id}/documents/bindings",
            json={"nodeId": 40, "bindings": [{"documentId": "DOC-20260625-004"}]},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            f"/api/projects/{project_id}/ndt/records/import",
            json={"nodeId": 24, "rows": [{"recordNo": "OUT-OF-SCOPE", "weldNo": "W-24", "method": "RT"}]},
            headers=ndt_headers,
        ),
        "FORBIDDEN",
    )

    contractor_submit = assert_ok(
        client.post(
            f"/api/projects/{project_id}/submissions",
            json={"nodeIds": [16], "bindingIds": ["BIND-16-001"]},
            headers=contractor_headers,
        )
    )
    ndt_import = assert_ok(
        client.post(
            f"/api/projects/{project_id}/ndt/records/import",
            json={"nodeId": 40, "rows": [{"recordNo": "IN-SCOPE", "weldNo": "W-40", "method": "RT"}]},
            headers=ndt_headers,
        )
    )

    assert contractor_submit["nextStatus"] == "待审查"
    assert ndt_import["records"][0]["nodeId"] == 40


def test_resource_id_node_scope_is_enforced_for_project_mutations(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    project_id = "P-2026-HDCP-001"
    contractor_headers = {"Authorization": "Bearer dev-token-contractor-contractor"}
    inspection_headers = {"Authorization": "Bearer dev-token-inspection-inspection"}

    assert_error(
        client.post(
            f"/api/projects/{project_id}/documents/DOC-20260625-004/withdraw",
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.patch(
            f"/api/projects/{project_id}/documents/bindings/BIND-40-001",
            json={"usage": "越权修改"},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )

    own_document = assert_ok(
        client.post(
            f"/api/projects/{project_id}/documents/DOC-20260625-002/withdraw",
            headers=contractor_headers,
        )
    )
    assert own_document["nextStatus"] == "已撤回"

    inspection_member = next(item for item in repo.state["project_members"] if item["userId"] == "USER-INSPECTION-001")
    inspection_member["nodeScope"] = [24]
    assert_error(
        client.post(
            f"/api/projects/{project_id}/reports/RPT-20260625-001/export",
            json={"format": "pdf"},
            headers=inspection_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            f"/api/projects/{project_id}/reports/RPT-20250618-007/export",
            json={"format": "pdf"},
            headers=inspection_headers,
        ),
        "NOT_FOUND",
    )


def test_read_project_scope_enforces_url_query_and_resource_nodes(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    project_id = "P-2026-HDCP-001"
    contractor_headers = {"Authorization": "Bearer dev-token-contractor-contractor"}
    owner_headers = {"Authorization": "Bearer dev-token-owner-owner"}
    ndt_headers = {"Authorization": "Bearer dev-token-ndt-ndt"}
    admin_headers = {"Authorization": "Bearer dev-token-admin-admin"}
    repo.state["todos"].extend(
        [
            {
                "id": "TODO-SCOPE-40",
                "title": "节点 40 越权待办",
                "projectId": project_id,
                "nodeId": 40,
                "targetType": "node",
                "targetId": "40",
                "status": "待处理",
                "priority": "高",
                "actions": ["review:save"],
            },
            {
                "id": "TODO-SCOPE-RPT",
                "title": "跨节点报告待办",
                "projectId": project_id,
                "targetType": "report",
                "targetId": "RPT-20260625-001",
                "status": "待处理",
                "priority": "中",
                "actions": ["report:review"],
            },
        ]
    )
    repo.state["messages"].append(
        {
            "id": "MSG-SCOPE-40",
            "title": "节点 40 越权消息",
            "content": "节点 40 有新状态。",
            "projectId": project_id,
            "targetType": "node",
            "targetId": "40",
            "read": False,
            "createdAt": "2026-06-27 09:00:00",
        }
    )
    repo.state["ai_runs"].append(
        {
            "id": "AIRUN-SCOPE-40",
            "projectId": project_id,
            "nodeId": 40,
            "subject": "无损检测资料",
            "model": "review-chat",
            "status": "完成",
            "startedAt": "2026-06-27 09:00:00",
            "steps": [],
        }
    )
    repo.state["llm_compare_runs"].append(
        {
            "runId": "CMP-SCOPE-40",
            "question": "节点 40 对比",
            "modelCodes": ["default-chat"],
            "createdAt": "2026-06-27 09:00:00",
            "projectId": project_id,
            "nodeId": 40,
            "status": "完成",
            "results": [],
        }
    )

    assert_error(
        client.get(f"/api/projects/{project_id}/nodes/40/package", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/documents?nodeId=40", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/documents/DOC-20260625-004", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/reports/RPT-20260625-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/workbench/context?role=inspection", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/todos/TODO-SCOPE-40", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.post("/api/messages/MSG-SCOPE-40/read", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/knowledge/files/KF-DOC-20260625-004", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/knowledge/tasks/KT-20260626-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    # 施工方现在在**角色闸**就被拦下，轮不到范围校验（2026-08-14 审计 F-1）：
    # /reasoning/logs 返回的是与 /nodes/{n}/ai-runs 同一个 ai_runs 集合，
    # 那边对被检方是 403，这边却曾经放行——一道门拦住、另一道敞着，等于没拦。
    #
    # 接的是既有的 review_process_read_error，它用真 HTTP 403（与 ai-runs 一致），
    # 而不是本用例其余部分的「HTTP 200 + 业务码」。两套拒绝机制并存是既有问题
    # （审计 F-6），此处按被复用守卫的既定行为断言，不在这里另立一套。
    denied = client.get("/api/reasoning/logs/AIRUN-SCOPE-40", headers=contractor_headers)
    assert denied.status_code == 403
    assert denied.json()["code"] == 403
    assert_error(
        client.get("/api/llm/compare-runs/CMP-SCOPE-40", headers=contractor_headers),
        "FORBIDDEN",
    )
    for ndt_path in (
        f"/api/projects/{project_id}/ndt/films/FILM-RT-001",
        f"/api/projects/{project_id}/ndt/reports/NDT-RPT-001",
        f"/api/projects/{project_id}/ndt/inspection-feedback/NDT-FB-001",
    ):
        ndt_denied = client.get(ndt_path, headers=contractor_headers)
        assert ndt_denied.status_code == 403
        assert ndt_denied.json()["code"] == 403
    assert_error(
        client.get(f"/api/projects/{project_id}/export-tasks/EXP-RPT-20260625-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/exports/EXP-RPT-20260625-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/exports/EXP-RPT-20260625-001/download-url", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            "/api/exports",
            json={"projectId": project_id, "exportType": "report", "reportId": "RPT-20260625-001"},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/archive/evidence-package?nodeId=40", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/admin/config-overview", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/knowledge/sources", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/rules/versions", headers=contractor_headers),
        "FORBIDDEN",
    )

    own_node = assert_ok(client.get(f"/api/projects/{project_id}/nodes/16/package", headers=contractor_headers))
    own_document = assert_ok(client.get(f"/api/projects/{project_id}/documents/DOC-20260625-003", headers=contractor_headers))
    admin_overview = assert_ok(client.get("/api/admin/config-overview", headers=admin_headers))
    me = assert_ok(client.get("/api/auth/me", headers=contractor_headers))
    workbench_projects = assert_ok(client.get("/api/workbench/projects?role=contractor", headers=contractor_headers))
    project_page = assert_ok(client.get("/api/projects", headers=contractor_headers))
    summary = assert_ok(client.get(f"/api/projects/{project_id}/workbench/summary?role=contractor", headers=contractor_headers))
    tree = assert_ok(client.get(f"/api/projects/{project_id}/tree", headers=contractor_headers))
    documents = assert_ok(client.get(f"/api/projects/{project_id}/documents", headers=contractor_headers))
    bindings = assert_ok(client.get(f"/api/projects/{project_id}/documents/bindings", headers=contractor_headers))
    # 施工方的动作表没有 report:view（issue #18）。这里原先是 assert_ok，
    # 等于把越权读取当成了既有行为——报告读取现在按动作表拒绝。
    contractor_reports = client.get(f"/api/projects/{project_id}/reports", headers=contractor_headers)
    assert contractor_reports.status_code == 403, contractor_reports.text
    todos = assert_ok(client.get(f"/api/todos?projectId={project_id}", headers=contractor_headers))
    messages = assert_ok(client.get(f"/api/messages?projectId={project_id}", headers=contractor_headers))
    search_results = assert_ok(client.get(f"/api/search?projectId={project_id}&keyword=RT", headers=contractor_headers))
    knowledge_files = assert_ok(client.get(f"/api/knowledge/project-files?projectId={project_id}", headers=contractor_headers))
    knowledge_tasks = assert_ok(client.get("/api/knowledge/tasks", headers=contractor_headers))
    # 施工方读 AI 推理日志已在角色闸被拦（2026-08-14 审计 F-1）。
    # 这里改用监检身份验「范围过滤仍然生效」——原意就是查范围，
    # 而施工方现在压根到不了这一步。
    reasoning_denied = client.get(
        f"/api/reasoning/logs?projectId={project_id}", headers=contractor_headers
    )
    assert reasoning_denied.status_code == 403, reasoning_denied.text

    compare_runs = assert_ok(client.get(f"/api/llm/compare-runs?projectId={project_id}", headers=contractor_headers))
    ndt_summary = assert_ok(client.get(f"/api/projects/{project_id}/ndt/summary", headers=contractor_headers))
    ndt_films = assert_ok(client.get(f"/api/projects/{project_id}/ndt/films", headers=contractor_headers))
    ndt_records = assert_ok(client.get(f"/api/projects/{project_id}/ndt/records", headers=contractor_headers))
    ndt_reports = assert_ok(client.get(f"/api/projects/{project_id}/ndt/reports", headers=contractor_headers))
    ndt_feedback = assert_ok(client.get(f"/api/projects/{project_id}/ndt/inspection-feedback", headers=contractor_headers))
    ndt_visible_records = assert_ok(client.get(f"/api/projects/{project_id}/ndt/records", headers=ndt_headers))
    # 施工方的动作表也没有 archive:view（issue #18）——归档包读取同样按动作表拒绝。
    contractor_archive = client.get(f"/api/projects/{project_id}/archive/package", headers=contractor_headers)
    assert contractor_archive.status_code == 403, contractor_archive.text
    archive_package = assert_ok(client.get(f"/api/projects/{project_id}/archive/package", headers=owner_headers))
    owner_reports = assert_ok(client.get(f"/api/projects/{project_id}/owner/reports", headers=owner_headers))

    assert own_node["node"]["nodeId"] == 16
    assert own_document["document"]["id"] == "DOC-20260625-003"
    assert "metrics" in admin_overview
    assert {item["userId"] for item in me["projectAuthorizations"]} == {"USER-CONTRACTOR-001"}
    expected_contractor_projects = {project_id, "P-2026-GDLNG-002"}
    assert {item["id"] for item in workbench_projects} == expected_contractor_projects
    assert {item["id"] for item in project_page["items"]} == expected_contractor_projects
    assert not any(item["id"] in {"TODO-SCOPE-40", "TODO-SCOPE-RPT"} for item in summary["todos"])
    visible_node_ids = {node["nodeId"] for group in tree["groups"] for node in group["nodes"]}
    assert visible_node_ids.issubset({16, 24, 25})
    assert "DOC-20260625-004" not in {item["id"] for item in documents["items"]}
    assert "BIND-40-001" not in {item["id"] for item in bindings}
    # 报告的节点范围过滤本身仍要验，只是换用有 report:view 的角色（建设方）来读。
    # 建设方的节点范围是 [1, 16, 24, 40, 59, 68]，报告只能落在其中。
    owner_scope_node_ids = {1, 16, 24, 40, 59, 68}
    owner_all_reports = assert_ok(
        client.get(f"/api/projects/{project_id}/reports", headers=owner_headers)
    )
    assert all(
        set(report.get("nodeIds") or []).issubset(owner_scope_node_ids)
        for report in owner_all_reports
    )
    assert "TODO-SCOPE-40" not in {item["id"] for item in todos["items"]}
    assert "TODO-SCOPE-RPT" not in {item["id"] for item in todos["items"]}
    assert "MSG-SCOPE-40" not in {item["id"] for item in messages["items"]}
    assert "DOC-20260625-004" not in {item["id"] for item in search_results["items"]}
    assert "KF-DOC-20260625-004" not in {item["id"] for item in knowledge_files["items"]}
    assert "KT-20260626-001" not in {item["id"] for item in knowledge_tasks["items"]}
    # 原先这里断言施工方读 /reasoning/logs 时 AIRUN-SCOPE-40 被范围过滤掉。
    # 现在施工方在角色闸就被拦下（上面已断言 403），范围过滤对它已无从表达；
    # 而监检本就能看本项目全部节点，换成监检断言等于断言一件不成立的事。
    # 该端点的安全性由角色闸保证，节点范围过滤在其余端点（documents /
    # knowledge-files / search / todos）仍有断言覆盖。
    assert "CMP-SCOPE-40" not in {item["runId"] for item in compare_runs["items"]}
    assert ndt_summary == {"filmCount": 0, "recordCount": 0, "reportCount": 0, "feedbackCount": 0}
    assert ndt_films["items"] == []
    assert ndt_records["items"] == []
    assert ndt_reports["items"] == []
    assert ndt_feedback["items"] == []
    assert any(item["id"] == "NDT-REC-001" for item in ndt_visible_records["items"])
    assert archive_package["itemCount"] == 2
    # RPT-20260625-001 在节点范围内，但状态是「复核中」——签发前属于监检机构的内部
    # 工作稿，不对建设方开放（issue #18）。定稿后同一份报告必须照常可见，
    # 否则就是把建设方彻底挡在报告之外了。
    assert not any(report["id"] == "RPT-20260625-001" for report in owner_reports)
    settled_report = next(
        item for item in repo.state["reports"] if item["id"] == "RPT-20260625-001"
    )
    original_status = settled_report["status"]
    try:
        settled_report["status"] = "已签发"
        settled_reports = assert_ok(
            client.get(f"/api/projects/{project_id}/owner/reports", headers=owner_headers)
        )
        assert any(report["id"] == "RPT-20260625-001" for report in settled_reports)
    finally:
        settled_report["status"] = original_status


def test_upload_creates_knowledge_task_and_retrieval_works() -> None:
    upload = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/documents/upload-session",
            json={"files": [{"fileName": "E2E.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
        )
    )
    assert upload["uploadUrls"][0]["method"] == "PUT"

    tasks = assert_ok(client.get("/knowledge/tasks"))
    assert any(task["targetName"] == "E2E.pdf" for task in tasks["items"])

    retrieval = assert_ok(
        client.post(
            "/knowledge/retrieval-test",
            json={"question": "焊工资格证有效期如何校验？", "scope": ["standard"], "topK": 5},
        )
    )
    assert retrieval["hits"]
    assert retrieval["retrievalTrace"]["queryType"] == "interactive_retrieval_test"
    assert retrieval["retrievalTrace"]["selectedRoute"] == "hybrid_review_basis_search"
    assert retrieval["retrievalTrace"]["queryRouter"]["selectedRoute"] == "hybrid_review_basis_search"
    assert retrieval["retrievalTrace"]["selectedClauses"][0]["clauseId"]
    assert any(item["type"] == "clause_index" for item in retrieval["retrievalTrace"]["retrievers"])
    assert any(item["type"] == "hybrid_bm25_dense" for item in retrieval["retrievalTrace"]["retrievers"])
    clauses = assert_ok(client.get("/knowledge/clauses", params={"keyword": "焊工资格证", "nodeId": 24}))
    assert clauses["items"]
    assert clauses["items"][0]["clauseId"]


def test_knowledge_and_compare_inputs_do_not_fall_back_to_demo_values() -> None:
    assert_error(client.post("/knowledge/retrieval-test", json={}), "VALIDATION_ERROR")
    assert_error(
        client.post("/llm/compare", json={"question": "材料证明是否一致？", "modelCodes": ["default-chat"]}),
        "VALIDATION_ERROR",
    )
    assert_error(
        client.post("/llm/compare", json={"question": "材料证明是否一致？", "modelCodes": ["LLM-A", "LLM-B"]}),
        "VALIDATION_ERROR",
    )
    assert_error(client.post("/knowledge/sources", json={}), "VALIDATION_ERROR")

    overview = assert_ok(client.get("/knowledge/overview"))
    standard_library = next(item for item in overview["libraries"] if item["key"] == "KS-STANDARD-RULES")
    source_file_ids = {
        item["id"]
        for item in repo.state["knowledge_files"]
        if item.get("sourceId") == "KS-STANDARD-RULES"
    }
    assert standard_library["chunkCount"] == len(
        [item for item in repo.state["knowledge_chunks"] if item.get("fileId") in source_file_ids]
    )
    assert standard_library["vectorCount"] == len(
        [item for item in repo.state["knowledge_vectors"] if item.get("fileId") in source_file_ids]
    )


def test_standard_aliases_normalize_ocr_glyphs_and_business_phrases() -> None:
    normalized = canonical_standard_text("犌犅／犜３０８７—２０２２").replace(" ", "")
    assert "GB/T3087-2022" in normalized

    low_pressure_candidate = {
        "sourceRelativePath": "rules/standards/GBT+3087-2022.pdf",
        "title": "GBT+3087-2022.pdf",
        "tags": [],
    }
    high_pressure_candidate = {
        "sourceRelativePath": "rules/standards/GBT+5310-2023.pdf",
        "title": "GBT+5310-2023.pdf",
        "tags": [],
    }

    assert standard_alias_matches("低中压锅炉管验收依据")[0]["number"] == "3087"
    assert standard_alias_match_score(low_pressure_candidate, "低中压锅炉管验收依据") >= 100
    assert standard_alias_match_score(low_pressure_candidate, "高压锅炉管验收依据") == 0
    assert standard_alias_match_score(high_pressure_candidate, "高压锅炉管验收依据") >= 100

    welding_storage_candidate = {
        "sourceRelativePath": "rules/standards/JB∕T 3223-2017 焊接材料质量管理规程.pdf",
        "title": "焊接材料质量管理规程",
        "tags": [],
    }
    paut_candidate = {
        "sourceRelativePath": "rules/standards/NB_T_47013_split/NBT47013.15-2021 承压设备无损检测 第15部分：相控阵超声检测_可搜索.pdf",
        "title": "相控阵超声检测",
        "tags": [],
    }
    tofd_candidate = {
        "sourceRelativePath": "rules/standards/NB_T_47013_split/NB_T 47013.10-2015 承压设备无损检测 第10部分 衍射时差法超声检测.pdf",
        "title": "衍射时差法超声检测",
        "tags": [],
    }
    ut_candidate = {
        "sourceRelativePath": "rules/standards/NB_T_47013_split/NBT 47013.3-2023 承压设备无损检测 第3部分 超声检测.pdf",
        "title": "超声检测",
        "tags": [],
    }

    welding_matches = standard_alias_matches("焊材烘干和保管依据是什么？")
    assert welding_matches[0]["aliasId"] == "jbt-3223-welding-material-quality-management"
    assert welding_matches[0]["targetStandard"] == "JB/T 3223-2017"
    assert standard_alias_match_score(welding_storage_candidate, "焊材烘干和保管依据是什么？") >= 100
    assert standard_alias_candidate_matches(welding_storage_candidate, "焊材烘干和保管依据是什么？")[0]["source"]

    assert standard_alias_match_score(ut_candidate, "普通超声检测报告依据") >= 100
    assert standard_alias_match_score(ut_candidate, "相控阵检测报告依据") == 0
    assert standard_alias_match_score(paut_candidate, "相控阵检测报告依据") >= 100
    assert standard_alias_match_score(tofd_candidate, "TOFD 超声检测报告依据") >= 100

    business_bias = retrieval_quality_bias(
        {
            "sourceRelativePath": "rules/业务规则.md",
            "scope": {"contextType": "business_rule_context"},
            "tags": ["业务规则上下文"],
        },
        "锅炉钢管复验报告应该引用什么标准？",
    )
    standard_bias = retrieval_quality_bias(
        {
            "sourceRelativePath": "rules/standards/GBT+3087-2022.pdf",
            "scope": {"contextType": "standard_reference", "sourceMethod": "remote_ocr"},
            "tags": ["标准规范"],
        },
        "锅炉钢管复验报告应该引用什么标准？",
    )
    assert business_bias < standard_bias


def test_knowledge_retrieval_query_router_supports_exact_clause_and_pageindex_routes() -> None:
    exact = assert_ok(
        client.post(
            "/knowledge/retrieval-test",
            json={"question": "请解释 TSG-D7006-D2.4.1 质量证明文件要求", "topK": 3},
        )
    )
    exact_trace = exact["retrievalTrace"]
    assert exact_trace["selectedRoute"] == "exact_clause_lookup"
    assert exact_trace["routerSignals"]["exactClauseRefs"] == ["tsg-d7006-d2.4.1"]
    assert exact_trace["selectedClauses"][0]["clauseNo"] == "D2.4.1"
    assert exact_trace["selectedClauses"][0]["retrievalMode"] == "exact_clause_lookup"
    assert any(item["type"] == "exact_clause_lookup" and item["enabled"] for item in exact_trace["retrievers"])

    pageindex = assert_ok(
        client.post(
            "/knowledge/retrieval-test",
            json={"question": "请结合正文和附录跨章节说明无损检测报告签章要求", "topK": 3},
        )
    )
    pageindex_trace = pageindex["retrievalTrace"]
    assert pageindex_trace["selectedRoute"] == "pageindex_tree_search"
    assert pageindex_trace["queryRouter"]["signals"]["needsPageIndex"] is True
    assert any(item["type"] == "pageindex_tree" and item["enabled"] for item in pageindex_trace["retrievers"])
    assert pageindex_trace["selectedClauses"][0]["retrievalMode"] == "pageindex_tree_local"
    assert pageindex_trace["pageIndexTree"]["selectedNodes"]
    assert pageindex_trace["pageIndexTree"]["selectedNodes"][0]["pageIndexNodeId"] == "PIN-NB-T-47013-NDT"
    assert "NB-T-47013-NDT-REPORT" in pageindex_trace["pageIndexTree"]["linkedClauseIds"]
    assert pageindex_trace["selectedClauses"][0]["pageIndexNodeIds"] == ["PIN-NB-T-47013-NDT"]

    nodes = assert_ok(client.get("/knowledge/page-index-nodes", params={"keyword": "无损检测"}))
    assert nodes["items"]
    assert nodes["items"][0]["pageIndexNodeId"] == "PIN-NB-T-47013-NDT"

    overview = assert_ok(client.get("/knowledge/overview"))
    scorecard = overview["scorecard"]
    assert scorecard["targetScore"] == 100
    assert scorecard["schemaVersion"] == "aicheck-knowledge-rule-scorecard-v1"
    assert {"source-index", "rule-clause", "retrieval-router", "evaluation-governance"} <= {
        item["name"] for item in scorecard["sections"]
    }
    probes = scorecard["retrievalProbes"]
    assert {"exact_clause_lookup", "hybrid_review_basis_search", "pageindex_tree_search"} <= {
        item["expectedRoute"] for item in probes
    }
    assert any(
        item["expectedRoute"] == "pageindex_tree_search"
        and item["selectedRoute"] == "pageindex_tree_search"
        and item["pageIndexNodeCount"] >= 1
        for item in probes
    )
    assert all(item["selectedClauseCount"] >= 1 for item in probes)
    assert all(item["evidenceBacked"] is True for item in probes)
    assert scorecard["score"] == 100
    assert scorecard["ok"] is True
    assert scorecard["blockers"] == []


def test_import_rules_standards_folder_uploads_local_standard_files(monkeypatch, tmp_path) -> None:
    import apps.api.routes as api_routes

    workspace = tmp_path / "workspace"
    standards_root = workspace / "rules" / "standards"
    split_root = standards_root / "NB_T_47013_split"
    split_root.mkdir(parents=True)
    business_rules_path = workspace / "rules" / "业务规则.md"
    business_rules_path.write_text("# 业务规则\n\n引用 TSG31-2025 和 NB/T 47013。", encoding="utf-8")
    (standards_root / "TSG31-2025.pdf").write_bytes(b"%PDF-1.4\nstandard")
    (split_root / "NB_T 47013.11-2023.md").write_text("射线数字成像检测", encoding="utf-8")
    (standards_root / ".DS_Store").write_bytes(b"ignored")

    monkeypatch.setattr(api_routes, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(api_routes, "RULES_STANDARDS_ROOT", standards_root)
    monkeypatch.setattr(api_routes, "RULES_BUSINESS_RULES_PATH", business_rules_path)
    monkeypatch.setattr(api_routes, "KNOWLEDGE_UPLOAD_ROOT", workspace / "output" / "knowledge_uploads")

    imported = assert_ok(client.post("/knowledge/standards/import-from-rules", json={}))
    assert imported["summary"]["scanned"] == 3
    assert imported["summary"]["standardFiles"] == 2
    assert imported["summary"]["businessRuleContextFiles"] == 1
    assert imported["summary"]["imported"] == 3
    assert imported["summary"]["skipped"] == 0
    assert imported["source"]["id"] == "KS-STANDARD-RULES"
    assert imported["source"]["fileCount"] == 3
    assert {item["sourceId"] for item in imported["files"]} == {"KS-STANDARD-RULES"}
    assert {item["sourceRelativePath"] for item in imported["files"]} == {
        "rules/业务规则.md",
        "rules/standards/TSG31-2025.pdf",
        "rules/standards/NB_T_47013_split/NB_T 47013.11-2023.md",
    }
    business_file = next(item for item in imported["files"] if item["sourceRelativePath"] == "rules/业务规则.md")
    assert business_file["contextType"] == "business_rule_context"
    project_files = assert_ok(client.get("/knowledge/project-files?pageSize=100"))
    assert all(item.get("sourceId") != "KS-STANDARD-RULES" for item in project_files["items"])

    repeated = assert_ok(client.post("/knowledge/standards/import-from-rules", json={}))
    assert repeated["summary"]["imported"] == 0
    assert repeated["summary"]["skipped"] == 3
    assert repeated["source"]["fileCount"] == 3
    imported_ids_by_path = {item["sourceRelativePath"]: item["id"] for item in imported["files"]}

    legacy_path = "rules/standards/TSG31-2025.pdf"
    legacy_file = next(item for item in repo.state["knowledge_files"] if item.get("sourceRelativePath") == legacy_path)
    old_file_id = legacy_file["id"]
    legacy_file["id"] = "KF-KB-LEGACY-STANDARD"
    for task in repo.state["knowledge_tasks"]:
        if task.get("targetId") == old_file_id:
            task["targetId"] = legacy_file["id"]

    (standards_root / "TSG31-2025.pdf").write_bytes(b"%PDF-1.4\nstandard reset")
    reset = assert_ok(client.post("/knowledge/standards/import-from-rules", json={"reset": True}))
    assert reset["summary"]["reset"] is True
    assert reset["summary"]["removed"] == 3
    assert reset["summary"]["imported"] == 3
    assert reset["summary"]["skipped"] == 0
    assert reset["source"]["fileCount"] == 3
    reset_ids_by_path = {item["sourceRelativePath"]: item["id"] for item in reset["files"]}
    assert reset_ids_by_path["rules/standards/NB_T_47013_split/NB_T 47013.11-2023.md"] == imported_ids_by_path[
        "rules/standards/NB_T_47013_split/NB_T 47013.11-2023.md"
    ]
    legacy_detail = assert_ok(client.get("/knowledge/files/KF-KB-LEGACY-STANDARD"))
    assert legacy_detail["file"]["id"] == reset_ids_by_path[legacy_path]
    assert legacy_detail["file"]["sourceRelativePath"] == legacy_path


def test_offline_hash_vectorizer_is_stable_normalized_and_rankable() -> None:
    from libs.knowledge_indexing import (
        OFFLINE_VECTOR_DIMENSIONS,
        cosine_similarity,
        offline_hash_embedding,
    )

    text = "无损检测报告签章要求"
    same = offline_hash_embedding(text)
    related = offline_hash_embedding("无损检测报告签章和页码证据")
    unrelated = offline_hash_embedding("焊接热处理温度记录")

    assert len(same) == OFFLINE_VECTOR_DIMENSIONS
    assert same == offline_hash_embedding(text)
    assert abs(sum(value * value for value in same) ** 0.5 - 1.0) < 0.0001
    assert cosine_similarity(same, related) > cosine_similarity(same, unrelated)


def test_embed_knowledge_batches_all_chunks_offline(monkeypatch) -> None:
    from apps.worker import tasks
    from libs.knowledge_indexing import OFFLINE_EMBEDDING_MODEL, OFFLINE_VECTOR_DIMENSIONS

    knowledge_file = repo.find_one("knowledge_files", "KF-DOC-20260625-004")
    repo.state["knowledge_chunks"] = [
        item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") != knowledge_file["id"]
    ]
    for index in range(35):
        repo.state["knowledge_chunks"].append(
            {
                "id": f"CHK-BATCH-{index + 1}",
                "fileId": knowledge_file["id"],
                "documentId": knowledge_file["documentId"],
                "documentVersionId": knowledge_file["documentVersionId"],
                "chunkNo": index + 1,
                "text": f"批量向量化文本 {index + 1}",
                "pageNo": index + 1,
                "sectionPath": ["批量标准", f"第 {index + 1} 页"],
                "tokenCount": 12,
                "createdAt": "2026-07-05 00:00:00",
            }
        )
    knowledge_file["sliceStatus"] = "已切片"
    knowledge_file["chunkCount"] = 35

    class FailingLiteLLM:
        def __init__(self, *args, **kwargs):
            raise AssertionError("knowledge embedding must stay offline")

    monkeypatch.setattr(tasks, "LiteLLMClient", FailingLiteLLM)
    result = tasks.embed_knowledge.run(knowledge_file["id"])
    vectors = [item for item in repo.state["knowledge_vectors"] if item.get("fileId") == knowledge_file["id"]]

    assert result["status"] == "success"
    assert len(vectors) == 35
    assert all(item["embeddingModel"] == OFFLINE_EMBEDDING_MODEL for item in vectors)
    assert all(item["dimensions"] == OFFLINE_VECTOR_DIMENSIONS for item in vectors)
    assert knowledge_file["vectorStatus"] == "已向量化"
    assert knowledge_file["vectorCount"] == 35


def test_standard_file_crud_replace_and_delete_refreshes_source_counts() -> None:
    initial_count = repo.find_one("knowledge_sources", "KS-STANDARD-RULES")["fileCount"]
    imported = assert_ok(
        client.post(
            "/knowledge/files/import",
            data={
                "sourceId": "KS-STANDARD-RULES",
                "sourceName": "标准规范库（业务规则引用标准）",
                "sourceType": "standard",
                "sourceVersion": "rules-standards-test",
                "sourceStatus": "启用",
                "relativePaths": "rules/standards/old.md",
                "fileNames": "旧标准.md",
                "contextDescriptions": "旧版本",
            },
            files=[("files", ("old.md", b"# old standard", "text/markdown"))],
        )
    )
    file = imported["files"][0]
    file_id = file["id"]
    assert imported["source"]["fileCount"] == initial_count + 1

    updated = assert_ok(
        client.patch(
            f"/knowledge/files/{file_id}",
            json={
                "fileName": "新标准.md",
                "sourceRelativePath": "rules/standards/new.md",
                "contextDescription": "更新后的标准说明",
            },
        )
    )
    assert updated["file"]["fileName"] == "新标准.md"
    assert updated["file"]["sourceRelativePath"] == "rules/standards/new.md"
    assert updated["file"]["contextDescription"] == "更新后的标准说明"

    repo.apply_slice_result(file_id, [{"pageNo": 1, "text": "旧切片"}])
    repo.apply_embed_result(file_id, 1)
    assert repo.find_one("knowledge_files", file_id)["chunkCount"] == 1

    replaced = assert_ok(
        client.post(
            f"/knowledge/files/{file_id}/replace",
            data={
                "fileName": "替换标准.md",
                "relativePath": "rules/standards/replaced.md",
                "contextDescription": "替换后的标准说明",
            },
            files=[("files", ("replaced.md", b"# replacement standard", "text/markdown"))],
        )
    )
    assert replaced["file"]["id"] == file_id
    assert replaced["file"]["fileName"] == "替换标准.md"
    assert replaced["file"]["sourceRelativePath"] == "rules/standards/replaced.md"
    assert replaced["file"]["chunkCount"] == 0
    assert replaced["file"]["vectorStatus"] == "待向量化"
    assert replaced["currentVersion"]["versionNo"] == "V2"
    assert repo.find_one("knowledge_sources", "KS-STANDARD-RULES")["fileCount"] == initial_count + 1
    assert [item for item in repo.state["knowledge_chunks"] if item.get("fileId") == file_id] == []

    original = client.get(f"/knowledge/files/{file_id}/original?disposition=inline")
    assert original.status_code == 200
    assert original.content == b"# replacement standard"

    deleted = assert_ok(client.delete(f"/knowledge/files/{file_id}"))
    assert deleted["removed"]["files"] == 1
    assert deleted["removed"]["documents"] == 1
    assert deleted["removed"]["versions"] == 2
    assert deleted["source"]["fileCount"] == initial_count
    assert_error(client.get(f"/knowledge/files/{file_id}"), "NOT_FOUND")


def test_standard_source_reindex_can_requeue_ocr_pipeline() -> None:
    imported = assert_ok(
        client.post(
            "/knowledge/files/import",
            data={
                "sourceId": "KS-STANDARD-REINDEX-TEST",
                "sourceName": "标准规范库重建测试",
                "sourceType": "standard",
                "sourceVersion": "rules-standards-reindex-test",
                "sourceStatus": "启用",
                "relativePaths": "rules/standards/reindex.md",
                "fileNames": "重建标准.md",
            },
            files=[("files", ("reindex.md", b"# standard reindex", "text/markdown"))],
        )
    )
    file_id = imported["files"][0]["id"]
    repo.apply_slice_result(file_id, [{"pageNo": 1, "text": "旧标准切片"}])
    repo.apply_embed_result(file_id, 1)

    result = assert_ok(
        client.post(
            "/knowledge/reindex",
            json={
                "scope": "source",
                "sourceId": "KS-STANDARD-REINDEX-TEST",
                "sourceType": "standard",
                "includeOcr": True,
                "onlyIncomplete": True,
            },
        )
    )

    file = repo.find_one("knowledge_files", file_id)
    ocr_task = next(
        item
        for item in repo.state["knowledge_tasks"]
        if item.get("taskType") == "ocr" and item.get("targetId") == file_id
    )

    assert result["summary"]["matched"] == 1
    assert result["summary"]["includeOcr"] is True
    assert result["summary"]["dispatched"] == 1
    assert result["dispatches"][0]["taskType"] == "ocr"
    assert result["dispatches"][0]["knowledgeTaskId"] == ocr_task["id"]
    assert file["ocrStatus"] == "识别中"
    assert file["sliceStatus"] == "未切片"
    assert file["vectorStatus"] == "待向量化"
    assert file["chunkCount"] == 0
    assert file["vectorCount"] == 0
    assert [item for item in repo.state["knowledge_chunks"] if item.get("fileId") == file_id] == []
    assert [item for item in repo.state["knowledge_vectors"] if item.get("fileId") == file_id] == []
    assert ocr_task["status"] == "排队中"
    assert ocr_task["lastDispatch"]["mode"] == "disabled"


def test_standard_source_reindex_migrates_local_file_to_object_storage(monkeypatch, tmp_path) -> None:
    import apps.api.routes as api_routes

    workspace = tmp_path / "workspace"
    monkeypatch.setattr(api_routes, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(api_routes, "KNOWLEDGE_UPLOAD_ROOT", workspace / "output" / "knowledge_uploads")

    imported = assert_ok(
        client.post(
            "/knowledge/files/import",
            data={
                "sourceId": "KS-STANDARD-LOCAL-MIGRATION",
                "sourceName": "标准规范本地迁移测试",
                "sourceType": "standard",
                "sourceVersion": "rules-standards-local-migration",
                "sourceStatus": "启用",
                "relativePaths": "rules/standards/local-migration.pdf",
                "fileNames": "本地标准.pdf",
            },
            files=[("files", ("local-migration.pdf", b"%PDF-1.4\nlocal standard", "application/pdf"))],
        )
    )
    file_id = imported["files"][0]["id"]
    version = repo.find_one("versions", imported["files"][0]["documentVersionId"])
    assert version["storageKey"].startswith("local://")

    stored_objects: list[tuple[str, str, bytes, str]] = []

    def fake_put_bytes(bucket: str, object_name: str, data: bytes, *, content_type: str):
        stored_objects.append((bucket, object_name, data, content_type))
        return f"minio://{bucket}/{object_name}"

    dispatch_args: list[tuple[str, str, str, str | None]] = []

    def fake_dispatch_parse_document(document_id: str, version_id: str, storage_key: str, file_name: str | None = None):
        dispatch_args.append((document_id, version_id, storage_key, file_name))
        return {"mode": "disabled", "taskId": None}

    monkeypatch.setattr(api_routes.object_storage, "endpoint", "minio:9000")
    monkeypatch.setattr(api_routes.object_storage, "put_bytes", fake_put_bytes)
    monkeypatch.setattr(api_routes.task_dispatcher, "dispatch_parse_document", fake_dispatch_parse_document)

    result = assert_ok(
        client.post(
            "/knowledge/reindex",
            json={
                "scope": "source",
                "sourceId": "KS-STANDARD-LOCAL-MIGRATION",
                "sourceType": "standard",
                "includeOcr": True,
                "onlyIncomplete": True,
            },
        )
    )

    migrated_version = repo.find_one("versions", version["id"])
    assert result["summary"]["dispatched"] == 1
    assert result["dispatches"][0]["storageMigration"]["storageBucket"] == "documents"
    assert stored_objects == [
        (
            "documents",
            f"knowledge/KS-STANDARD-LOCAL-MIGRATION/{file_id}/本地标准.pdf",
            b"%PDF-1.4\nlocal standard",
            "application/pdf",
        )
    ]
    assert migrated_version["storageBucket"] == "documents"
    assert migrated_version["storageKey"] == stored_objects[0][1]
    assert dispatch_args[-1][2] == f"minio://documents/{stored_objects[0][1]}"


def test_slice_knowledge_uses_latest_ocr_parse_fragments_for_index_text(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setattr(tasks, "refresh_worker_state", lambda: None)

    imported = assert_ok(
        client.post(
            "/knowledge/files/import",
            data={
                "sourceId": "KS-STANDARD-SLICE-FRAGMENTS",
                "sourceName": "标准规范切片测试",
                "sourceType": "standard",
                "sourceVersion": "rules-standards-slice-fragments",
                "sourceStatus": "启用",
                "relativePaths": "rules/standards/slice.md",
                "fileNames": "切片标准.md",
            },
            files=[("files", ("slice.md", b"# fallback", "text/markdown"))],
        )
    )
    file = imported["files"][0]
    file_id = file["id"]
    long_text = "标准正文片段 " * 500
    repo.state.setdefault("ocr_parse_results", []).insert(
        0,
        {
            "id": "PARSE-SLICE-FRAGMENTS",
            "parseResultId": "PARSE-SLICE-FRAGMENTS",
            "documentId": file["documentId"],
            "documentVersionId": file["documentVersionId"],
            "status": "success",
            "fragments": [{"pageNo": 1, "text": long_text}],
            "createdAt": "2026-07-05 00:00:00",
            "finishedAt": "2026-07-05 00:00:00",
        },
    )
    repo.upsert_knowledge_task(
        task_type="slice",
        target_id=file_id,
        target_name=file["fileName"],
        document_id=file["documentId"],
        version_id=file["documentVersionId"],
    )

    result = tasks.slice_knowledge.run(file_id)
    chunks = [item for item in repo.state["knowledge_chunks"] if item.get("fileId") == file_id]

    assert result["status"] == "success"
    assert len(chunks) >= 2
    assert chunks[0]["text"].startswith("标准正文片段")
    assert all("OCR文本:" not in item["text"] for item in chunks)


def test_import_project_file_keeps_project_scope_and_filtering() -> None:
    project_id = "P-2026-HDCP-001"

    imported = assert_ok(
        client.post(
            "/knowledge/files/import",
            data={
                "sourceId": "KS-PROJECT-FILE",
                "sourceName": "项目文件知识库",
                "sourceType": "project-file",
                "sourceVersion": "proj-test",
                "sourceStatus": "启用",
                "projectId": project_id,
            },
            files=[("files", ("project-file.md", b"# project file knowledge", "text/markdown"))],
        )
    )

    knowledge_file = imported["files"][0]
    file_id = knowledge_file["id"]
    assert knowledge_file["sourceId"] == "KS-PROJECT-FILE"
    assert knowledge_file["sourceType"] == "project-file"
    assert knowledge_file["projectId"] == project_id
    assert knowledge_file["projectName"] == "华东成品油管道改造工程"

    scoped = assert_ok(client.get(f"/knowledge/project-files?projectId={project_id}&pageSize=100"))
    assert any(item["id"] == file_id for item in scoped["items"])

    keyword = assert_ok(client.get("/knowledge/project-files?keyword=华东成品油管道改造工程&pageSize=100"))
    assert any(item["id"] == file_id for item in keyword["items"])

    updated = assert_ok(
        client.patch(
            f"/knowledge/files/{file_id}",
            json={"fileName": "项目文件-更新.md", "projectId": project_id},
        )
    )
    assert updated["file"]["fileName"] == "项目文件-更新.md"
    assert updated["file"]["projectId"] == project_id


def test_ndt_atomic_upload_creates_independent_draft_bindings() -> None:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    file_specs = [
        {
            "fileName": "质量保证手册-正文.pdf",
            "fileSize": 1024,
            "fileType": "application/pdf",
            "materialCategory": "无损检测资料",
            "materialTypeCode": "ndt_quality_assurance_manual",
            "materialTypeName": "无损检测单位质量保证手册",
            "nodeIds": [35],
        },
        {
            "fileName": "质量保证手册-批准页.pdf",
            "fileSize": 1024,
            "fileType": "application/pdf",
            "materialCategory": "无损检测资料",
            "materialTypeCode": "ndt_quality_assurance_manual",
            "materialTypeName": "无损检测单位质量保证手册",
            "nodeIds": [35],
        },
    ]
    upload = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": file_specs},
            headers=headers,
        )
    )

    completed_files = []
    for target in upload["uploadUrls"]:
        body = b"%PDF-ndt-atomic".ljust(1024, b"0")
        assert_ok(client.put(target["url"], content=body, headers=target["headers"]))
        completed_files.append(
            {"documentVersionId": target["documentVersionId"], "fileSize": len(body)}
        )

    complete = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={"completedFiles": completed_files},
            headers=headers,
        )
    )

    assert len(complete["documents"]) == 2
    document_ids = [item["documentId"] for item in complete["documents"]]
    assert len(set(document_ids)) == 2
    for item in complete["documents"]:
        assert item["materialTypeCode"] == "ndt_quality_assurance_manual"
        assert item["materialTypeName"] == "无损检测单位质量保证手册"
        assert item["nodeIds"] == [35]
        assert len(item["bindingIds"]) == 1

        document = repo.find_one("documents", item["documentId"])
        assert document["materialCategory"] == "无损检测资料"
        assert document["materialTypeCode"] == "ndt_quality_assurance_manual"
        assert document["materialTypeName"] == "无损检测单位质量保证手册"

        binding = repo.find_one("bindings", item["bindingIds"][0])
        assert binding["documentId"] == item["documentId"]
        assert binding["nodeId"] == 35
        assert binding["bindingStatus"] == "草稿挂载"


def test_ndt_user_validation_messages_use_business_language() -> None:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    response = client.post(
        f"/projects/{project_id}/documents/upload-session",
        json={
            "files": [
                {
                    "fileName": "质量保证手册.pdf",
                    "fileSize": 1024,
                    "fileType": "application/pdf",
                    "materialCategory": "无损检测资料",
                    "nodeIds": [35],
                }
            ]
        },
        headers=headers,
    )
    payload = assert_error(response, "VALIDATION_ERROR")
    assert payload["message"] == "质量保证手册.pdf 必须选择资料类型。"
    assert "原子" not in payload["message"]
    assert "规则挂载" not in payload["message"]


def mark_document_pipeline_complete(document_id: str) -> None:
    document = repo.find_one("documents", document_id)
    version = repo.find_one("versions", document["currentVersionId"])
    knowledge_file = next(
        item
        for item in repo.state["knowledge_files"]
        if item.get("documentVersionId") == document["currentVersionId"]
    )
    document["currentOcrStatus"] = "已识别"
    version["ocrStatus"] = "已识别"
    version["sliceStatus"] = "已切片"
    version["vectorStatus"] = "已向量化"
    knowledge_file["ocrStatus"] = "已识别"
    knowledge_file["sliceStatus"] = "已切片"
    knowledge_file["vectorStatus"] = "已向量化"


def upload_ndt_atomic_documents(
    file_specs: list[dict[str, object]],
    *,
    pipeline_complete: bool = True,
) -> list[dict[str, object]]:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    upload = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": file_specs},
            headers=headers,
        )
    )
    completed_files = []
    for target in upload["uploadUrls"]:
        body = b"%PDF-ndt-atomic".ljust(1024, b"0")
        assert_ok(client.put(target["url"], content=body, headers=target["headers"]))
        completed_files.append({"documentVersionId": target["documentVersionId"], "fileSize": len(body)})
    complete = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={"completedFiles": completed_files},
            headers=headers,
        )
    )
    documents = complete["documents"]
    if pipeline_complete:
        for document in documents:
            mark_document_pipeline_complete(str(document["documentId"]))
    return documents


def test_retry_failed_upload_reuses_stored_original_and_current_version(monkeypatch) -> None:
    project_id = "P-2026-HDCP-001"
    headers = {
        "X-Role": "ndt",
        "X-User-Id": "USER-NDT-001",
        "Idempotency-Key": "retry-failed-upload-once",
    }
    uploaded = upload_ndt_atomic_documents(
        [
            {
                "fileName": "失败后重新上传.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_plan",
                "materialTypeName": "无损检测方案",
                "nodeIds": [36],
            }
        ]
    )[0]
    document_id = str(uploaded["documentId"])
    document = repo.find_one("documents", document_id)
    version_id = str(document["currentVersionId"])
    version = repo.find_one("versions", version_id)
    knowledge_file = next(
        item
        for item in repo.state["knowledge_files"]
        if item.get("documentVersionId") == version_id
    )
    binding_ids = [item["id"] for item in repo.bindings_for_project(project_id) if item.get("documentId") == document_id]
    document["currentOcrStatus"] = "识别失败"
    version["ocrStatus"] = "识别失败"
    version["sliceStatus"] = "切片失败"
    version["vectorStatus"] = "向量化失败"
    knowledge_file["ocrStatus"] = "识别失败"
    knowledge_file["sliceStatus"] = "切片失败"
    knowledge_file["vectorStatus"] = "向量化失败"
    repo.apply_slice_result(knowledge_file["id"], [{"pageNo": 1, "text": "旧切片"}])
    repo.apply_embed_result(knowledge_file["id"], 1)
    dispatched: list[tuple[str, str, str, str | None]] = []

    def fake_dispatch(document_id: str, version_id: str, storage_key: str, file_name: str | None = None):
        dispatched.append((document_id, version_id, storage_key, file_name))
        return {"mode": "test", "taskId": "retry-upload-task"}

    monkeypatch.setattr(task_dispatcher, "dispatch_parse_document", fake_dispatch)

    first = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/{document_id}/retry-upload",
            headers=headers,
        )
    )
    replay = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/{document_id}/retry-upload",
            headers=headers,
        )
    )

    assert first == replay
    assert first["documentId"] == document_id
    assert first["documentVersionId"] == version_id
    assert first["uploadStatus"] == "上传中"
    assert document["currentOcrStatus"] == "识别中"
    assert version["sliceStatus"] == "未切片"
    assert version["vectorStatus"] == "待向量化"
    assert knowledge_file["chunkCount"] == 0
    assert knowledge_file["vectorCount"] == 0
    assert [item for item in repo.state["knowledge_chunks"] if item.get("fileId") == knowledge_file["id"]] == []
    assert [item for item in repo.state["knowledge_vectors"] if item.get("fileId") == knowledge_file["id"]] == []
    assert binding_ids == [item["id"] for item in repo.bindings_for_project(project_id) if item.get("documentId") == document_id]
    assert dispatched == [(document_id, version_id, version["storageKey"], document["fileName"])]


def test_retry_failed_upload_rejects_document_without_failed_stage() -> None:
    project_id = "P-2026-HDCP-001"
    uploaded = upload_ndt_atomic_documents(
        [
            {
                "fileName": "仍在正常处理.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_plan",
                "materialTypeName": "无损检测方案",
                "nodeIds": [36],
            }
        ]
    )[0]

    payload = assert_error(
        client.post(
            f"/projects/{project_id}/documents/{uploaded['documentId']}/retry-upload",
            headers={"X-Role": "ndt", "X-User-Id": "USER-NDT-001"},
        ),
        "VALIDATION_ERROR",
    )

    assert payload["message"] == "仅处理失败的文件可以重新上传。"


def test_retry_failed_upload_rejects_missing_stored_original(monkeypatch) -> None:
    project_id = "P-2026-HDCP-001"
    uploaded = upload_ndt_atomic_documents(
        [
            {
                "fileName": "原文件已丢失.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_plan",
                "materialTypeName": "无损检测方案",
                "nodeIds": [36],
            }
        ]
    )[0]
    document = repo.find_one("documents", uploaded["documentId"])
    document["currentOcrStatus"] = "识别失败"
    monkeypatch.setattr("apps.api.routes.project_document_local_original_path", lambda *_args: None)
    monkeypatch.setattr("apps.api.routes.project_document_storage_object", lambda *_args: None)

    payload = assert_error(
        client.post(
            f"/projects/{project_id}/documents/{uploaded['documentId']}/retry-upload",
            headers={"X-Role": "ndt", "X-User-Id": "USER-NDT-001"},
        ),
        "VALIDATION_ERROR",
    )

    assert payload["message"] == "原文件已不存在，请重新选择本地文件上传。"


def test_retry_failed_upload_rejects_non_business_role() -> None:
    project_id = "P-2026-HDCP-001"
    uploaded = upload_ndt_atomic_documents(
        [
            {
                "fileName": "监检人员不可重传.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_plan",
                "materialTypeName": "无损检测方案",
                "nodeIds": [36],
            }
        ]
    )[0]
    document = repo.find_one("documents", uploaded["documentId"])
    document["currentOcrStatus"] = "识别失败"

    payload = assert_error(
        client.post(
            f"/projects/{project_id}/documents/{uploaded['documentId']}/retry-upload",
            headers={"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"},
        ),
        "FORBIDDEN",
    )

    assert payload["message"] == "当前角色不能重新上传该文件。"


def test_ndt_atomic_submission_refreshes_latest_document_state_before_validation(monkeypatch) -> None:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    document = upload_ndt_atomic_documents(
        [
            {
                "fileName": "质量保证手册-并发更新.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_quality_assurance_manual",
                "materialTypeName": "无损检测单位质量保证手册",
                "nodeIds": [35],
            }
        ],
        pipeline_complete=False,
    )[0]
    persisted_document = repo.find_one("documents", document["documentId"])
    persisted_document["currentOcrStatus"] = "排队中"
    refreshed_state_keys: list[set[str]] = []

    def refresh_latest_state(state_keys: set[str]) -> None:
        refreshed_state_keys.append(state_keys)
        mark_document_pipeline_complete(str(document["documentId"]))

    repo.postgres_dsn = "postgresql://refresh-latest-state-test"
    monkeypatch.setattr("apps.api.routes.load_state", refresh_latest_state)

    result = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": document["documentId"], "bindingIds": document["bindingIds"]},
            headers=headers,
        )
    )

    assert result["documentId"] == document["documentId"]
    assert refreshed_state_keys == [
        {"documents", "versions", "bindings", "tree_nodes", "knowledge_files"}
    ]
    assert repo.find_one("documents", document["documentId"])["currentOcrStatus"] == "已识别"


def test_ndt_atomic_submission_reloads_external_ocr_update_from_sqlite(tmp_path) -> None:
    from libs.db.repository import InMemoryRepository

    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    sqlite_path = str(tmp_path / "ndt-concurrent-submission.sqlite3")
    repo.configure_sqlite(sqlite_path)
    repo.flush_to_sqlite()
    document = upload_ndt_atomic_documents(
        [
            {
                "fileName": "质量保证手册-OCR并发更新.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_quality_assurance_manual",
                "materialTypeName": "无损检测单位质量保证手册",
                "nodeIds": [35],
            }
        ],
        pipeline_complete=False,
    )[0]
    stale_document = repo.find_one("documents", document["documentId"])
    assert stale_document["currentOcrStatus"] == "排队中"

    ocr_worker_view = InMemoryRepository()
    ocr_worker_view.configure_sqlite(sqlite_path)
    ocr_worker_view.load_from_sqlite({"documents", "versions", "knowledge_files"})
    ocr_document = ocr_worker_view.find_one("documents", document["documentId"])
    ocr_version = ocr_worker_view.find_one("versions", ocr_document["currentVersionId"])
    ocr_knowledge_file = next(
        item
        for item in ocr_worker_view.state["knowledge_files"]
        if item.get("documentVersionId") == ocr_document["currentVersionId"]
    )
    ocr_document["currentOcrStatus"] = "已识别"
    ocr_version["ocrStatus"] = "已识别"
    ocr_version["sliceStatus"] = "已切片"
    ocr_version["vectorStatus"] = "已向量化"
    ocr_knowledge_file["ocrStatus"] = "已识别"
    ocr_knowledge_file["sliceStatus"] = "已切片"
    ocr_knowledge_file["vectorStatus"] = "已向量化"
    ocr_worker_view.sync_state_records_to_sqlite(
        {
            "documents": [ocr_document],
            "versions": [ocr_version],
            "knowledge_files": [ocr_knowledge_file],
        },
        {},
    )

    result = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": document["documentId"], "bindingIds": document["bindingIds"]},
            headers=headers,
        )
    )

    assert result["nextStatus"] == "待审查"
    refreshed_document = repo.find_one("documents", document["documentId"])
    assert refreshed_document["currentOcrStatus"] == "已识别"
    assert refreshed_document["fileStatus"] == "已提交审批"


def test_ndt_atomic_submission_uses_exact_scoped_persistence(monkeypatch) -> None:
    import apps.api.main as api_main

    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    document = upload_ndt_atomic_documents(
        [
            {
                "fileName": "质量保证手册-精确提交.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_quality_assurance_manual",
                "materialTypeName": "无损检测单位质量保证手册",
                "nodeIds": [35],
            }
        ]
    )[0]
    full_flushes: list[dict[str, object]] = []
    scoped_flushes: list[dict[str, list[dict[str, object]]]] = []
    monkeypatch.setattr(api_main, "flush_state", lambda **kwargs: full_flushes.append(kwargs))
    monkeypatch.setattr("apps.api.routes.load_state", lambda _state_keys: None)
    monkeypatch.setattr(
        api_main,
        "flush_mutation_records",
        lambda records, _scopes: scoped_flushes.append(records),
    )

    assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": document["documentId"], "bindingIds": document["bindingIds"]},
            headers=headers,
        )
    )

    assert full_flushes == []
    assert len(scoped_flushes) == 1
    assert set(scoped_flushes[0]) == {
        "documents",
        "bindings",
        "tree_nodes",
        "submissions",
        "todos",
        "audit_logs",
    }
    assert [item["id"] for item in scoped_flushes[0]["documents"]] == [document["documentId"]]
    assert {item["id"] for item in scoped_flushes[0]["bindings"]} == set(document["bindingIds"])


def test_ndt_resubmission_persists_linked_rectification_in_exact_scope(monkeypatch) -> None:
    import apps.api.main as api_main

    project_id = "P-2026-HDCP-001"
    ndt_headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    inspection_headers = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
    document = upload_ndt_atomic_documents(
        [
            {
                "fileName": "质量保证手册-退回重提.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_quality_assurance_manual",
                "materialTypeName": "无损检测单位质量保证手册",
                "nodeIds": [35],
            }
        ]
    )[0]
    assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": document["documentId"], "bindingIds": document["bindingIds"]},
            headers=ndt_headers,
        )
    )
    returned = assert_ok(
        client.post(
            f"/projects/{project_id}/inspection/nodes/35/actions/return-correction",
            json={"bindingIds": document["bindingIds"], "reason": "NDT 资料退回重提"},
            headers=inspection_headers,
        )
    )
    rectification_id = returned["rectification"]["id"]
    scoped_flushes: list[dict[str, list[dict[str, object]]]] = []
    monkeypatch.setattr(api_main, "flush_state", lambda **_kwargs: None)
    monkeypatch.setattr(
        api_main,
        "flush_mutation_records",
        lambda records, _scopes: scoped_flushes.append(records),
    )

    assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": document["documentId"], "bindingIds": document["bindingIds"]},
            headers=ndt_headers,
        )
    )

    assert len(scoped_flushes) == 1
    assert [item["id"] for item in scoped_flushes[0]["rectifications"]] == [rectification_id]


def test_ndt_atomic_submission_returns_clear_resource_state_conflict(monkeypatch) -> None:
    import apps.api.main as api_main
    from libs.db.repository import ConcurrentPersistenceError

    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    document = upload_ndt_atomic_documents(
        [
            {
                "fileName": "质量保证手册-并发冲突.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_quality_assurance_manual",
                "materialTypeName": "无损检测单位质量保证手册",
                "nodeIds": [35],
            }
        ]
    )[0]
    monkeypatch.setattr("apps.api.routes.load_state", lambda _state_keys: None)

    def raise_concurrent_update(_records, _scopes) -> None:
        raise ConcurrentPersistenceError(
            f"Concurrent persistence update detected for documents/{document['documentId']}"
        )

    monkeypatch.setattr(api_main, "flush_mutation_records", raise_concurrent_update)

    response = client.post(
        f"/projects/{project_id}/ndt/material-submissions",
        json={"documentId": document["documentId"], "bindingIds": document["bindingIds"]},
        headers=headers,
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["data"]["reason"] == "RESOURCE_STATE_CHANGED"
    assert payload["message"] == "文件状态已更新，请刷新后重试。"
    assert payload["data"]["reason"] != "EXTERNAL_TOOL_FAILED"


def test_ndt_atomic_documents_require_upload_success_before_submission() -> None:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    documents = upload_ndt_atomic_documents(
        [
            {
                "fileName": "质量保证手册.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_quality_assurance_manual",
                "materialTypeName": "无损检测单位质量保证手册",
                "nodeIds": [35],
            },
            {
                "fileName": "检测方案.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_plan",
                "materialTypeName": "无损检测方案",
                "nodeIds": [36],
            },
        ],
        pipeline_complete=False,
    )
    first, second = documents
    first_document = repo.find_one("documents", first["documentId"])
    second_document = repo.find_one("documents", second["documentId"])
    first_document["currentOcrStatus"] = "排队中"
    second_document["currentOcrStatus"] = "识别失败"

    first_blocked = assert_error(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": first["documentId"], "bindingIds": first["bindingIds"]},
            headers=headers,
        ),
        "VALIDATION_ERROR",
    )
    second_blocked = assert_error(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": second["documentId"], "bindingIds": second["bindingIds"]},
            headers=headers,
        ),
        "VALIDATION_ERROR",
    )

    # 文案要指名卡住的环节。原先三个入口统一说「文件上传处理尚未成功」，
    # 而上传早就成功了——线上照着这句去查上传，什么也查不出来。
    assert "上传" not in first_blocked["message"], "又把锅甩给上传了"
    assert first_blocked["data"]["blockedDocuments"][0]["stage"] in {"ocr", "slice", "vector"}
    assert first_blocked["data"]["incompleteDocumentIds"] == [first["documentId"]]
    assert second_blocked["data"]["incompleteDocumentIds"] == [second["documentId"]]
    assert repo.find_one("bindings", first["bindingIds"][0])["bindingStatus"] == "草稿挂载"
    assert repo.find_one("bindings", second["bindingIds"][0])["bindingStatus"] == "草稿挂载"
    assert first_document["fileStatus"] == "已上传"
    assert second_document["fileStatus"] == "已上传"

    first_version = repo.find_one("versions", first_document["currentVersionId"])
    first_knowledge_file = next(
        item
        for item in repo.state["knowledge_files"]
        if item.get("documentVersionId") == first_document["currentVersionId"]
    )
    first_document["currentOcrStatus"] = "已识别"
    first_version["ocrStatus"] = "已识别"
    first_version["sliceStatus"] = "已切片"
    first_version["vectorStatus"] = "已向量化"
    first_knowledge_file["ocrStatus"] = "已识别"
    first_knowledge_file["sliceStatus"] = "已切片"
    first_knowledge_file["vectorStatus"] = "已向量化"

    first_result = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": first["documentId"], "bindingIds": first["bindingIds"]},
            headers=headers,
        )
    )

    assert first_result["documentId"] == first["documentId"]
    assert repo.find_one("bindings", first["bindingIds"][0])["bindingStatus"] == "已提交"
    assert repo.find_one("bindings", second["bindingIds"][0])["bindingStatus"] == "草稿挂载"
    assert first_document["fileStatus"] == "已提交审批"
    assert second_document["fileStatus"] == "已上传"


def test_contractor_project_submission_requires_upload_success() -> None:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"}
    upload = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={
                "files": [
                    {
                        "fileName": "施工方案-等待处理.pdf",
                        "fileSize": 32,
                        "fileType": "application/pdf",
                        "materialCategory": "施工方案",
                    }
                ]
            },
            headers=headers,
        )
    )
    target = upload["uploadUrls"][0]
    body = b"%PDF-contractor-upload-success"
    assert_ok(client.put(target["url"], content=body, headers=target["headers"]))
    assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={
                "completedFiles": [
                    {"documentVersionId": target["documentVersionId"], "fileSize": len(body)}
                ]
            },
            headers=headers,
        )
    )
    document_id = target["documentId"]
    submission = {
        "submissionType": "project",
        "documentIds": [document_id],
        "bindingIds": [],
        "nodeIds": [],
    }

    blocked = assert_error(
        client.post(f"/projects/{project_id}/submissions", json=submission, headers=headers),
        "VALIDATION_ERROR",
    )
    assert "上传" not in blocked["message"], "又把锅甩给上传了"
    assert blocked["data"]["blockedDocuments"][0]["stage"] in {"ocr", "slice", "vector"}
    assert blocked["data"]["incompleteDocumentIds"] == [document_id]

    document = repo.find_one("documents", document_id)
    version = repo.find_one("versions", target["documentVersionId"])
    knowledge_file = next(
        item
        for item in repo.state["knowledge_files"]
        if item.get("documentVersionId") == target["documentVersionId"]
    )
    document["currentOcrStatus"] = "已识别"
    version["ocrStatus"] = "已识别"
    version["sliceStatus"] = "已切片"
    version["vectorStatus"] = "已向量化"
    knowledge_file["ocrStatus"] = "已识别"
    knowledge_file["sliceStatus"] = "已切片"
    knowledge_file["vectorStatus"] = "已向量化"

    result = assert_ok(
        client.post(f"/projects/{project_id}/submissions", json=submission, headers=headers)
    )
    assert result["documentIds"] == [document_id]


def test_contractor_bound_submission_requires_upload_success() -> None:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"}
    upload = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={
                "files": [
                    {
                        "fileName": "节点施工资料-等待处理.pdf",
                        "fileSize": 30,
                        "fileType": "application/pdf",
                        "materialCategory": "施工方案",
                    }
                ]
            },
            headers=headers,
        )
    )
    target = upload["uploadUrls"][0]
    body = b"%PDF-contractor-node-upload"
    assert_ok(client.put(target["url"], content=body, headers=target["headers"]))
    assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={
                "completedFiles": [
                    {"documentVersionId": target["documentVersionId"], "fileSize": len(body)}
                ]
            },
            headers=headers,
        )
    )
    bound = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/bindings",
            json={
                "nodeIds": [16],
                "bindings": [
                    {
                        "documentId": target["documentId"],
                        "documentVersionId": target["documentVersionId"],
                        "usage": "原始提交",
                    }
                ],
            },
            headers=headers,
        )
    )
    submission = {"nodeIds": [16], "bindingIds": bound["affectedIds"]}

    blocked = assert_error(
        client.post(f"/projects/{project_id}/submissions", json=submission, headers=headers),
        "VALIDATION_ERROR",
    )
    assert blocked["data"]["incompleteDocumentIds"] == [target["documentId"]]

    document = repo.find_one("documents", target["documentId"])
    version = repo.find_one("versions", target["documentVersionId"])
    knowledge_file = next(
        item
        for item in repo.state["knowledge_files"]
        if item.get("documentVersionId") == target["documentVersionId"]
    )
    document["currentOcrStatus"] = "已识别"
    version["sliceStatus"] = "已切片"
    version["vectorStatus"] = "已向量化"
    knowledge_file["sliceStatus"] = "已切片"
    knowledge_file["vectorStatus"] = "已向量化"

    result = assert_ok(
        client.post(f"/projects/{project_id}/submissions", json=submission, headers=headers)
    )
    assert result["bindingIds"] == bound["affectedIds"]


def test_ndt_atomic_submission_rejects_mixed_document_bindings_atomically() -> None:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    documents = upload_ndt_atomic_documents(
        [
            {
                "fileName": "人员明细表.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_person_roster",
                "materialTypeName": "无损检测人员明细表",
                "nodeIds": [38],
            },
            {
                "fileName": "人员资格证.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_person_certificate",
                "materialTypeName": "无损检测人员资格证",
                "nodeIds": [38],
            },
        ]
    )
    first, second = documents
    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={
                "documentId": first["documentId"],
                "bindingIds": [first["bindingIds"][0], second["bindingIds"][0]],
            },
            headers=headers,
        ),
        "VALIDATION_ERROR",
    )
    assert repo.find_one("bindings", first["bindingIds"][0])["bindingStatus"] == "草稿挂载"
    assert repo.find_one("bindings", second["bindingIds"][0])["bindingStatus"] == "草稿挂载"


def test_ndt_atomic_document_rules_can_be_replaced_before_submission() -> None:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    document = upload_ndt_atomic_documents(
        [
            {
                "fileName": "无损检测委托单.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_entrustment",
                "materialTypeName": "无损检测委托单",
                "nodeIds": [37, 42],
            }
        ]
    )[0]

    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": document["documentId"], "bindingIds": [document["bindingIds"][0]]},
            headers=headers,
        ),
        "VALIDATION_ERROR",
    )
    assert all(
        repo.find_one("bindings", binding_id)["bindingStatus"] == "草稿挂载"
        for binding_id in document["bindingIds"]
    )

    adjusted = assert_ok(
        client.put(
            f"/projects/{project_id}/ndt/documents/{document['documentId']}/bindings",
            json={"nodeIds": [37]},
            headers=headers,
        )
    )
    assert adjusted["documentId"] == document["documentId"]
    assert adjusted["nodeIds"] == [37]
    assert len(adjusted["bindingIds"]) == 1
    bindings = [
        item
        for item in repo.state["bindings"]
        if item.get("projectId") == project_id and item.get("documentId") == document["documentId"]
    ]
    assert [item["nodeId"] for item in bindings] == [37]
    assert bindings[0]["bindingStatus"] == "草稿挂载"

    assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": document["documentId"], "bindingIds": adjusted["bindingIds"]},
            headers=headers,
        )
    )
    assert_error(
        client.put(
            f"/projects/{project_id}/ndt/documents/{document['documentId']}/bindings",
            json={"nodeIds": [42]},
            headers=headers,
        ),
        "CONFLICT",
    )


def test_ndt_atomic_document_can_submit_without_business_rule_bindings() -> None:
    project_id = "P-2026-HDCP-001"
    headers = {"X-Role": "ndt", "X-User-Id": "USER-NDT-001"}
    document = upload_ndt_atomic_documents(
        [
            {
                "fileName": "射线检测报告-无规则.pdf",
                "fileSize": 1024,
                "fileType": "application/pdf",
                "materialCategory": "无损检测资料",
                "materialTypeCode": "ndt_report",
                "materialTypeName": "无损检测报告",
                "nodeIds": [40, 41, 42],
            }
        ]
    )[0]
    binding_id_set = set(document["bindingIds"])
    repo.state["bindings"] = [
        item for item in repo.state["bindings"] if item.get("id") not in binding_id_set
    ]
    persisted = repo.find_one("documents", document["documentId"])
    persisted["nodeId"] = 40

    result = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": document["documentId"], "bindingIds": []},
            headers=headers,
        )
    )
    assert result["documentId"] == document["documentId"]
    assert result["bindingIds"] == []
    assert result["nodeIds"] == [40]
    assert result["nextStatus"] == "待审查"
    assert persisted["fileStatus"] == "已提交审批"
    assert len(result["createdTodos"]) == 1
    assert result["createdTodos"][0]["nodeId"] == 40

    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/material-submissions",
            json={"documentId": document["documentId"], "bindingIds": []},
            headers=headers,
        ),
        "CONFLICT",
    )


def test_upload_and_ndt_validation_errors_match_contract() -> None:
    project_id = "P-2026-HDCP-001"
    project = assert_ok(client.get(f"/projects/{project_id}"))["project"]

    assert_error(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": [{"fileName": "empty.pdf", "fileSize": 0, "fileType": "application/pdf"}]},
        ),
        "VALIDATION_ERROR",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": [{"fileName": "tool.exe", "fileSize": 1024, "fileType": "application/x-msdownload"}]},
        ),
        "UNSUPPORTED_FILE_TYPE",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": [{"fileName": "huge.pdf", "fileSize": 500 * 1024 * 1024 + 1, "fileType": "application/pdf"}]},
        ),
        "FILE_TOO_LARGE",
    )

    upload = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": [{"fileName": "match.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
        )
    )
    ndt_material_upload = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={
                "files": [
                    {
                        "fileName": "ndt-original-record.pdf",
                        "fileSize": 2048,
                        "fileType": "application/pdf",
                        "materialCategory": "检测记录",
                    }
                ]
            },
            headers={"X-Role": "ndt", "X-User-Id": "USER-NDT-001"},
        )
    )
    ndt_material_doc = repo.find_one("documents", ndt_material_upload["uploadUrls"][0]["documentId"])
    assert ndt_material_doc["materialCategory"] == "检测记录"
    assert ndt_material_doc["sourceOrgName"] == "华测检测有限公司"
    assert_error(
        client.post(f"/projects/NOT-A-PROJECT/documents/upload-session/{upload['uploadSessionId']}/complete"),
        "NOT_FOUND",
    )

    assert_error(
        client.post(f"/projects/{project_id}/ndt/films", json={"nodeId": 40, "filmNo": "F-1", "weldNo": "W-1"}),
        "NDT_FILM_REQUIRED",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/records/import",
            json={"nodeId": 40, "rows": [{"recordNo": "R-1", "weldNo": "W-1"}]},
        ),
        "NDT_RECORD_REQUIRED",
    )
    assert_error(
        client.post(f"/projects/{project_id}/ndt/reports/upload-session", json={"nodeId": 40, "files": []}),
        "NDT_REPORT_REQUIRED",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/reports/upload-session",
            json={"nodeId": 40, "files": [{"fileName": "scan.exe", "fileSize": 1024, "fileType": "application/x-msdownload"}]},
        ),
        "UNSUPPORTED_NDT_FILE_TYPE",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/reports/upload-session",
            json={"nodeId": 40, "files": [{"fileName": "scan.dcm", "fileSize": 500 * 1024 * 1024 + 1, "fileType": "application/dicom"}]},
        ),
        "NDT_FILE_TOO_LARGE",
    )
    assert_error(
        client.post(f"/projects/{project_id}/ndt/submissions", json={"nodeId": 40, "reportIds": []}),
        "NDT_REPORT_REQUIRED",
    )
    assert_error(
        client.post(f"/projects/{project_id}/ndt/rectifications", json={"nodeId": 40, "reportIds": ["NDT-RPT-001"]}),
        "NDT_RECTIFICATION_REQUIRED",
    )
    report_count = len(repo.state["ndt_reports"])
    document_count = len(repo.state["documents"])
    upload_payload = {
        "nodeId": 40,
        "reportNo": "RT-IDEMPOTENT-001",
        "entrustNo": "WT-IDEMPOTENT-001",
        "method": "RT",
        "detectionRatio": "10%",
        "standardCode": "NB/T 47013.2-2015",
        "evaluatorName": "王工",
        "reviewerName": "赵工",
        "conclusion": "检测报告字段完整，报告与底片对应关系完整。",
        "files": [{"fileName": "RT-IDEMPOTENT.pdf", "fileSize": 2048, "fileType": "application/pdf"}],
    }
    upload_headers = {"If-Match": project["etag"], "Idempotency-Key": "ndt-report-upload-once"}
    upload = assert_ok(client.post(f"/projects/{project_id}/ndt/reports/upload-session", json=upload_payload, headers=upload_headers))
    upload_replay = assert_ok(client.post(f"/projects/{project_id}/ndt/reports/upload-session", json=upload_payload, headers=upload_headers))
    assert upload_replay["uploadSessionId"] == upload["uploadSessionId"]
    assert upload_replay["uploadUrls"][0]["documentId"] == upload["uploadUrls"][0]["documentId"]
    assert not str(upload["uploadUrls"][0]["url"]).startswith("mock://")
    assert len(repo.state["ndt_reports"]) == report_count
    assert len(repo.state["documents"]) == document_count + 1
    upload_target = upload["uploadUrls"][0]
    incomplete = client.post(
        f"/projects/{project_id}/ndt/reports/upload-session/{upload['uploadSessionId']}/complete",
        json={
            "completedFiles": [
                {"documentVersionId": upload_target["documentVersionId"], "fileSize": 2048}
            ]
        },
        headers={"If-Match": project["etag"], "Idempotency-Key": "ndt-report-complete-incomplete"},
    )
    assert_error(incomplete, "VALIDATION_ERROR")
    assert len(repo.state["ndt_reports"]) == report_count
    upload_body = b"%PDF-ndt-report-upload".ljust(2048, b"0")
    assert_ok(client.put(upload_target["url"], content=upload_body, headers=upload_target["headers"]))
    complete = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/reports/upload-session/{upload['uploadSessionId']}/complete",
            json={
                "completedFiles": [
                    {
                        "documentVersionId": upload_target["documentVersionId"],
                        "fileSize": len(upload_body),
                    }
                ]
            },
            headers={"If-Match": project["etag"], "Idempotency-Key": "ndt-report-complete-once"},
        )
    )
    assert len(repo.state["ndt_reports"]) == report_count + 1
    assert complete["fileCount"] == 1
    assert complete["queuedTasks"][0]["mode"] in {"disabled", "inline", "celery"}
    created_report = next(item for item in repo.state["ndt_reports"] if item["reportNo"] == "RT-IDEMPOTENT-001")
    assert created_report["entrustNo"] == "WT-IDEMPOTENT-001"
    assert created_report["standardCode"] == "NB/T 47013.2-2015"
    created_document = repo.find_one("documents", upload["uploadUrls"][0]["documentId"])
    assert created_document["materialCategory"] == "无损检测资料"
    assert created_document["materialTypeCode"] == "ndt_report"
    assert created_document["materialTypeName"] == "无损检测报告"
    assert complete["documents"][0]["nodeIds"] == [40, 41, 42]
    assert len(complete["documents"][0]["bindingIds"]) == 3
    assert created_document["sourceOrgName"] == "华测检测有限公司"


def test_cross_node_submission_scope_expands_empty_binding_ids() -> None:
    project_id = "P-2026-HDCP-001"
    draft = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions/drafts",
            json={"nodeIds": [16, 25], "bindingIds": [], "batchName": "scope draft"},
        )
    )
    assert draft["bindingIds"]

    submission = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions",
            json={"nodeIds": [16, 25], "bindingIds": [], "batchName": "scope submit"},
        )
    )
    assert submission["nextStatus"] == "待审查"


def test_exact_multi_node_document_submission_does_not_bind_the_active_node() -> None:
    project_id = "P-2026-HDCP-001"
    document_id = "DOC-20260625-001"
    version_id = "DV-20260625-001-V2"
    active_node_binding_count = len(
        [
            item
            for item in repo.bindings_for_project(project_id)
            if item["documentId"] == document_id and int(item["nodeId"]) == 16
        ]
    )
    bound = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/bindings",
            json={
                "nodeIds": [21, 24, 69],
                "bindings": [
                    {
                        "documentId": document_id,
                        "documentVersionId": version_id,
                        "usage": "原始提交",
                    }
                ],
            },
            headers={"Idempotency-Key": "exact-multi-node-bind"},
        )
    )
    created = {
        int(repo.find_one("bindings", binding_id)["nodeId"]): repo.find_one("bindings", binding_id)
        for binding_id in bound["affectedIds"]
    }
    assert sorted(created) == [21, 24, 69]
    created[24]["bindingStatus"] = "已通过"

    submitted = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions",
            json={
                "nodeIds": [21, 69],
                "bindingIds": [created[21]["id"], created[69]["id"]],
                "batchName": "文件真实挂载范围提交",
            },
            headers={"Idempotency-Key": "exact-multi-node-submit"},
        )
    )
    assert submitted["bindingIds"] == [created[21]["id"], created[69]["id"]]
    assert created[21]["bindingStatus"] == "已提交"
    assert created[24]["bindingStatus"] == "已通过"
    assert created[69]["bindingStatus"] == "已提交"
    assert len(
        [
            item
            for item in repo.bindings_for_project(project_id)
            if item["documentId"] == document_id and int(item["nodeId"]) == 16
        ]
    ) == active_node_binding_count
    stored_submission = next(
        item for item in repo.state["submissions"] if item["submissionId"] == submitted["submissionId"]
    )
    assert stored_submission["nodeIds"] == [21, 69]


def test_ndt_submit_updates_reports_films_and_traceable_snapshot() -> None:
    project_id = "P-2026-HDCP-001"
    mark_ndt_report_ready("NDT-RPT-001")
    repo.find_one("ndt_reports", "NDT-RPT-001")["conclusion"] = "RT II级合格"
    project = assert_ok(client.get(f"/projects/{project_id}"))["project"]
    film = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/films",
            json={"nodeId": 40, "filmNo": "RT-FOLLOW-001", "weldNo": "W-40-RT-999", "method": "RT"},
        )
    )["film"]
    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/submissions",
            json={"nodeId": 40, "reportIds": ["NDT-RPT-001"], "filmIds": [film["id"], "FILM-MISSING"]},
        ),
        "NDT_FILM_REQUIRED",
    )

    submit = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/submissions",
            json={"nodeId": 40, "reportIds": ["NDT-RPT-001"], "filmIds": [film["id"]]},
            headers={"If-Match": project["etag"], "Idempotency-Key": "ndt-submit-trace"},
        )
    )
    replay = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/submissions",
            json={"nodeId": 40, "reportIds": ["NDT-RPT-001"], "filmIds": [film["id"]]},
            headers={"If-Match": project["etag"], "Idempotency-Key": "ndt-submit-trace"},
        )
    )

    assert submit["nextStatus"] == "待审查"
    assert submit["submissionId"] == replay["submissionId"]
    assert submit["snapshotId"] == replay["snapshotId"]
    assert submit["submittedReportIds"] == ["NDT-RPT-001"]
    assert submit["submittedFilmIds"] == [film["id"]]

    reports = assert_ok(client.get(f"/projects/{project_id}/ndt/reports"))
    assert any(report["id"] == "NDT-RPT-001" and report["status"] == "待审查" for report in reports["items"])
    stored_film = repo.find_one("ndt_films", film["id"])
    stored_submission = next(item for item in repo.state["submissions"] if item["submissionId"] == submit["submissionId"])
    detail = assert_ok(client.get(f"/projects/{project_id}/submissions/{submit['submissionId']}"))

    assert stored_film["status"] == "待审查"
    assert stored_film["submittedAt"]
    assert stored_submission["submissionType"] == "ndt"
    assert stored_submission["reportIds"] == ["NDT-RPT-001"]
    assert stored_submission["filmIds"] == [film["id"]]
    assert stored_submission["snapshot"]["reports"][0]["id"] == "NDT-RPT-001"
    assert stored_submission["snapshot"]["films"][0]["id"] == film["id"]
    assert detail["submissionType"] == "ndt"
    assert detail["snapshot"]["reports"][0]["status"] == "待审查"
    assert detail["snapshot"]["films"][0]["status"] == "待审查"
    assert detail["createdTodos"][0]["targetId"] == submit["submissionId"]
    assert repo.node(project_id, 40)["status"] == "待审查"

    rectification = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/rectifications",
            json={"rectificationId": "NDT-FB-001", "description": "已补充底片索引。"},
            headers={"If-Match": project["etag"], "Idempotency-Key": "ndt-rectification-once"},
        )
    )
    rectification_replay = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/rectifications",
            json={"rectificationId": "NDT-FB-001", "description": "已补充底片索引。"},
            headers={"If-Match": project["etag"], "Idempotency-Key": "ndt-rectification-once"},
        )
    )
    assert rectification["rectification"]["status"] == "已反馈"
    assert rectification_replay["rectification"]["id"] == rectification["rectification"]["id"]
    feedback = assert_ok(client.get(f"/projects/{project_id}/ndt/inspection-feedback"))
    assert feedback["items"][0]["status"] == "已反馈"


def test_admin_config_diff_export_publish_and_project_members() -> None:
    project_id = "P-2026-HDCP-001"
    create_diff = assert_ok(
        client.post(
            "/admin/config-items/todo-rule",
            json={"target": "todo-rule", "values": {"name": "E2E 待办规则", "triggerStatus": "E2E 待处理"}},
        )
    )
    assert any(row["after"] == "E2E 待办规则" for row in create_diff["diff"]["changed"])

    export = assert_ok(client.post("/admin/config-export", json={"scope": "all"}))
    assert export["task"]["fileName"].startswith("后台配置包-all-")
    assert export["task"]["fileName"].endswith(".zip")

    messages_before = len(repo.state["messages"])
    todos_before = len(repo.state["todos"])
    preview = assert_ok(
        client.post(
            "/admin/config-overview/publish-preview",
            json={"scope": "all", "reason": "验证配置发布影响范围"},
        )
    )
    publish = assert_ok(
        client.post(
            "/admin/config-overview/publish",
            json={
                "scope": "all",
                "reason": "验证配置发布影响范围",
                "previewId": preview["previewId"],
            },
        )
    )
    assert publish["version"].startswith("config-r")
    assert all(impact["status"] == "已发布" for impact in publish["impacts"])
    assert publish["impactSummary"]["pushedMessages"] == 0
    assert publish["impactSummary"]["reviewTodos"] == 0

    messages = assert_ok(client.get(f"/messages?projectId={project_id}"))
    todos = assert_ok(client.get(f"/todos?projectId={project_id}"))
    assert len(repo.state["messages"]) == messages_before
    assert len(repo.state["todos"]) == todos_before
    assert all(publish["publishId"] not in str(item) for item in messages["items"])
    assert all(publish["publishId"] not in str(item) for item in todos["items"])

    project_before_member = assert_ok(client.get(f"/projects/{project_id}"))
    project_member_etag = project_before_member["project"]["etag"]
    member_headers = {
        "X-Role": "admin",
        "X-User-Id": "USER-ADMIN-001",
        "If-Match": project_member_etag,
        "Idempotency-Key": "member-authorize-once",
    }
    member = assert_ok(
        client.post(
            f"/projects/{project_id}/members",
            json={"userId": "USER-ADMIN-001", "role": "admin", "nodeScope": [16, 24, 40, 59]},
            headers=member_headers,
        )
    )
    replayed_member = assert_ok(
        client.post(
            f"/projects/{project_id}/members",
            json={"userId": "USER-ADMIN-001", "role": "admin", "nodeScope": [16, 24, 40, 59]},
            headers=member_headers,
        )
    )
    assert member["member"]["name"] == "系统管理员"
    assert replayed_member["member"]["id"] == member["member"]["id"]
    assert replayed_member["auditLogId"] == member["auditLogId"]
    detail = assert_ok(client.get(f"/projects/{project_id}"))
    assert len(detail["members"]) == 5

    updated_member = assert_ok(
        client.post(
            f"/projects/{project_id}/members",
            json={"userId": "USER-INSPECTION-001", "role": "inspection", "nodeScope": [2, 3, 4]},
            headers={"X-Role": "admin", "X-User-Id": "USER-ADMIN-001"},
        )
    )
    assert updated_member["member"]["id"] == "PM-INSPECTION-001"
    assert {2, 3, 4, 24}.issubset(set(updated_member["member"]["nodeScope"]))
    detail = assert_ok(client.get(f"/projects/{project_id}"))
    assert len(detail["members"]) == 5
    inspection_member = next(item for item in detail["members"] if item["id"] == "PM-INSPECTION-001")
    assert inspection_member["etag"].startswith('W/"project-member-PM-INSPECTION-001-r')
    assert_error(
        client.put(
            f"/projects/{project_id}/members/{inspection_member['id']}",
            json={"status": "停用"},
            headers={"X-Role": "admin", "X-User-Id": "USER-ADMIN-001", "If-Match": 'W/"project-member-stale-r0"'},
        ),
        "ETAG_CONFLICT",
    )
    status_update = assert_ok(
        client.put(
            f"/projects/{project_id}/members/{inspection_member['id']}",
            json={"status": "停用"},
            headers={
                "X-Role": "admin",
                "X-User-Id": "USER-ADMIN-001",
                "If-Match": inspection_member["etag"],
                "Idempotency-Key": "member-status-once",
            },
        )
    )
    replayed_status_update = assert_ok(
        client.put(
            f"/projects/{project_id}/members/{inspection_member['id']}",
            json={"status": "停用"},
            headers={
                "X-Role": "admin",
                "X-User-Id": "USER-ADMIN-001",
                "If-Match": inspection_member["etag"],
                "Idempotency-Key": "member-status-once",
            },
        )
    )
    assert status_update["member"]["status"] == "停用"
    assert status_update["member"]["revision"] == inspection_member["revision"] + 1
    assert status_update["member"]["etag"] != inspection_member["etag"]
    assert replayed_status_update["member"]["etag"] == status_update["member"]["etag"]


def test_project_creation_routes_are_idempotent_and_return_initial_members() -> None:
    initial_project_count = len(repo.state["projects"])
    admin_payload = admin_project_create_payload("P-E2E-001", "E2E 立项项目")
    created = assert_ok(
        client.post(
            "/admin/projects",
            json=admin_payload,
            headers={"Idempotency-Key": "admin-project-create-once"},
        )
    )
    replayed = assert_ok(
        client.post(
            "/admin/projects",
            json=admin_payload,
            headers={"Idempotency-Key": "admin-project-create-once"},
        )
    )
    assert len(created["detail"]["members"]) == 4
    assert "businessPackSnapshot" not in created["project"]
    assert "businessPackSnapshot" not in created["detail"]["project"]
    assert created["project"]["businessPackVersion"]
    assert created["project"]["businessPackSnapshotHash"]
    assert created["createdNodeCount"] == 69
    assert created["createdRequirementCount"] > 0
    stored_project = repo.require_project(created["project"]["id"])
    assert stored_project is not None
    assert stored_project["businessPackSnapshot"]["snapshotHash"]
    assert replayed["project"]["id"] == created["project"]["id"]
    assert replayed["auditLogId"] == created["auditLogId"]
    assert len([item for item in repo.state["projects"] if item["id"] == "P-E2E-001"]) == 1
    assert len([item for item in repo.state["project_members"] if item["projectId"] == "P-E2E-001"]) == 4

    compatibility_payload = admin_project_create_payload("P-E2E-COMPAT-001", "E2E 兼容立项项目")
    compatibility_created = assert_ok(
        client.post(
            "/projects",
            json=compatibility_payload,
            headers={"Idempotency-Key": "compat-project-create-once"},
        )
    )
    compatibility_replayed = assert_ok(
        client.post(
            "/projects",
            json=compatibility_payload,
            headers={"Idempotency-Key": "compat-project-create-once"},
        )
    )
    assert len(compatibility_created["detail"]["members"]) == 4
    assert compatibility_replayed["project"]["id"] == compatibility_created["project"]["id"]
    assert compatibility_replayed["auditLogId"] == compatibility_created["auditLogId"]
    assert len([item for item in repo.state["projects"] if item["id"] == "P-E2E-COMPAT-001"]) == 1
    assert len([item for item in repo.state["project_members"] if item["projectId"] == "P-E2E-COMPAT-001"]) == 4
    assert_error(
        client.post(
            "/projects",
            json={**compatibility_payload, "name": "E2E 兼容立项项目-不同请求体"},
            headers={"Idempotency-Key": "compat-project-create-once"},
        ),
        "IDEMPOTENCY_KEY_CONFLICT",
    )
    assert len(repo.state["projects"]) == initial_project_count + 2

    gaps = assert_ok(client.get("/admin/integration-contract?status=后端缺失"))
    assert gaps["fields"] == []
    all_contracts = assert_ok(client.get("/admin/integration-contract"))
    assert all_contracts["summary"]["blockers"] == 0
    assert all_contracts["summary"]["pending"] == 0
    assert all_contracts["summary"]["aligned"] == all_contracts["summary"]["total"]


def test_project_creation_rejects_missing_or_invalid_real_configuration_without_partial_writes() -> None:
    initial_projects = len(repo.state["projects"])
    initial_members = len(repo.state["project_members"])
    missing = assert_error(
        client.post("/admin/projects", json={"code": "P-INVALID-EMPTY", "name": "缺配置项目"}),
        "VALIDATION_ERROR",
    )
    missing_fields = missing["data"]["missingFields"]
    assert "region" not in missing_fields
    assert "ownerOrgName" in missing_fields
    assert "contractorOrgName" in missing_fields
    assert len(repo.state["projects"]) == initial_projects
    assert len(repo.state["project_members"]) == initial_members

    invalid_payload = admin_project_create_payload("P-INVALID-MEMBER", "成员无效项目")
    invalid_payload["memberUserIds"] = {
        **invalid_payload["memberUserIds"],
        "inspection": "USER-NOT-FOUND",
    }
    invalid = assert_error(client.post("/admin/projects", json=invalid_payload), "VALIDATION_ERROR")
    assert invalid["data"]["memberErrors"][0]["role"] == "inspection"
    assert len(repo.state["projects"]) == initial_projects
    assert len(repo.state["project_members"]) == initial_members


def test_project_creation_accepts_member_with_matching_org_id_after_org_rename() -> None:
    org = {
        "id": "ORG-CONTRACTOR-RENAMED",
        "name": "施工单位新名称",
        "type": "contractor",
        "status": "启用",
    }
    user = {
        "id": "USER-CONTRACTOR-RENAMED",
        "username": "contractor_renamed",
        "name": "更名施工人员",
        "role": "contractor",
        "status": "启用",
        "orgId": org["id"],
        "orgName": "施工单位旧名称",
    }
    repo.state["admin_config"]["orgUnits"].append(org)
    repo.state["admin_config"]["users"].append(user)
    payload = admin_project_create_payload("P-ORG-ID-MATCH", "组织 ID 匹配项目")
    payload["contractorOrgName"] = org["name"]
    payload["ndtOrgName"] = "粤检无损检测"
    payload["memberUserIds"] = {
        **payload["memberUserIds"],
        "contractor": user["id"],
    }

    created = assert_ok(client.post("/admin/projects", json=payload))

    assert len(created["detail"]["members"]) == 4
    contractor = next(item for item in created["detail"]["members"] if item["role"] == "contractor")
    assert contractor["userId"] == user["id"]
    assert contractor["orgName"] == org["name"]


def test_project_creation_rejects_member_with_different_org_id_despite_matching_name() -> None:
    selected_org = {
        "id": "ORG-CONTRACTOR-SELECTED",
        "name": "同名施工单位",
        "type": "contractor",
        "status": "启用",
    }
    other_org = {
        "id": "ORG-CONTRACTOR-OTHER",
        "name": "其他施工单位",
        "type": "contractor",
        "status": "启用",
    }
    user = {
        "id": "USER-CONTRACTOR-OTHER-ORG",
        "username": "contractor_other_org",
        "name": "其他组织施工人员",
        "role": "contractor",
        "status": "启用",
        "orgId": other_org["id"],
        "orgName": selected_org["name"],
    }
    repo.state["admin_config"]["orgUnits"].extend([selected_org, other_org])
    repo.state["admin_config"]["users"].append(user)
    initial_projects = len(repo.state["projects"])
    initial_members = len(repo.state["project_members"])
    payload = admin_project_create_payload("P-ORG-ID-MISMATCH", "组织 ID 不匹配项目")
    payload["contractorOrgName"] = selected_org["name"]
    payload["ndtOrgName"] = "粤检无损检测"
    payload["memberUserIds"] = {
        **payload["memberUserIds"],
        "contractor": user["id"],
    }

    invalid = assert_error(client.post("/admin/projects", json=payload), "VALIDATION_ERROR")

    assert invalid["data"]["memberErrors"][0]["role"] == "contractor"
    assert len(repo.state["projects"]) == initial_projects
    assert len(repo.state["project_members"]) == initial_members


def test_admin_user_org_crud_and_project_member_batch_authorization_defaults() -> None:
    project_id = "P-2026-HDCP-001"

    org = assert_ok(
        client.post(
            "/admin/org-units",
            json={
                "name": "合同测试施工组织",
                "type": "contractor",
                "contactName": "陈工",
                "contactPhone": "13900001111",
            },
        )
    )["orgUnit"]

    assert_error(
        client.post(
            "/admin/users",
            json={"username": "contractor_without_org", "name": "无组织施工", "role": "contractor"},
        ),
        "VALIDATION_ERROR",
    )

    user = assert_ok(
        client.post(
            "/admin/users",
            json={
                "username": "contractor_batch_user",
                "name": "批量施工用户",
                "role": "contractor",
                "orgId": org["id"],
                "mobile": "13900002222",
                "password": "Contractor!2026",
            },
        )
    )["user"]
    assert user["role"] == "contractor"
    assert user["orgId"] == org["id"]

    login = assert_ok(client.post("/api/auth/login", json={"username": "contractor_batch_user", "password": "Contractor!2026"}))
    assert login["user"]["role"] == "contractor"

    project = assert_ok(client.get(f"/projects/{project_id}"))["project"]
    batch = assert_ok(
        client.post(
            f"/projects/{project_id}/members",
            json={"userIds": [user["id"]]},
            headers={"X-Role": "admin", "X-User-Id": "USER-ADMIN-001", "If-Match": project["etag"]},
        )
    )
    member = batch["members"][0]
    assert batch["successCount"] == 1
    assert member["userId"] == user["id"]
    assert member["role"] == user["role"]
    assert member["orgId"] == org["id"]
    assert "submission:submit" in member["actions"]
    assert len(member["nodeScope"]) > 10

    assert_error(
        client.delete(f"/admin/org-units/{org['id']}", headers={"If-Match": org["etag"]}),
        "CONFLICT",
    )

    removed = assert_ok(
        client.delete(
            f"/projects/{project_id}/members/{member['id']}",
            headers={"X-Role": "admin", "X-User-Id": "USER-ADMIN-001", "If-Match": member["etag"]},
        )
    )
    assert removed["deleted"] is True
    assert not any(item.get("id") == member["id"] for item in repo.state["project_members"])

    deleted_user = assert_ok(client.delete(f"/admin/users/{user['id']}", headers={"If-Match": user["etag"]}))
    assert deleted_user["deleted"] is True
    deleted_org = assert_ok(client.delete(f"/admin/org-units/{org['id']}", headers={"If-Match": org["etag"]}))
    assert deleted_org["deleted"] is True


def test_project_delete_removes_empty_project_and_archives_project_with_business_data() -> None:
    created = assert_ok(
        client.post(
            "/admin/projects",
            json=admin_project_create_payload("P-DELETE-001", "待删除空项目"),
        )
    )["project"]
    deleted = assert_ok(client.delete(f"/projects/{created['id']}", headers={"If-Match": created["etag"]}))
    assert deleted["deleted"] is True
    assert not any(item["id"] == created["id"] for item in repo.state["projects"])

    seeded = assert_ok(client.get("/projects/P-2026-HDCP-001"))["project"]
    archived = assert_ok(client.delete(f"/projects/{seeded['id']}", headers={"If-Match": seeded["etag"]}))
    assert archived["archived"] is True
    assert archived["project"]["status"] == "已归档"


def test_upload_complete_inline_ocr_writes_fields_and_slice_task(monkeypatch) -> None:
    from apps.worker import tasks
    from libs.knowledge_indexing import OFFLINE_EMBEDDING_MODEL, OFFLINE_VECTOR_DIMENSIONS

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")
    monkeypatch.setenv("AICHECK_WORKER_OCR_ALLOW_IN_PROCESS", "true")

    def fake_parse(storage_key: str, *, file_name: str | None = None, **kwargs):
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "证书编号 TS6J-2026-0001", "confidence": 0.91}],
            "fields": [{"fieldName": "证书编号", "fieldValue": "TS6J-2026-0001", "confidence": 0.94}],
            "seals": [],
            "diagnostics": [],
        }

    class FailingLiteLLMClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("knowledge embedding must stay offline")

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)
    monkeypatch.setattr(tasks, "LiteLLMClient", FailingLiteLLMClient)
    upload = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/documents/upload-session",
            json={"files": [{"fileName": "OCR-inline.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
        )
    )
    created = upload["uploadUrls"][0]
    body = b"%PDF-1.4\n" + (b"0" * (1024 - len(b"%PDF-1.4\n")))
    stored = assert_ok(client.put(created["url"], content=body, headers=created["headers"]))
    assert stored["fileSize"] == len(body)
    complete = assert_ok(
        client.post(
            f"/projects/P-2026-HDCP-001/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={
                "completedFiles": [
                    {
                        "documentVersionId": created["documentVersionId"],
                        "fileSize": len(body),
                    }
                ]
            },
        )
    )

    assert complete["queuedTasks"][0]["mode"] == "inline"
    fields = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{created['documentId']}/ocr-fields"))
    assert any(field["fieldValue"] == "TS6J-2026-0001" for field in fields)

    knowledge_file_id = f"KF-{created['documentId']}"
    slice_task = next(
        item for item in repo.state["knowledge_tasks"] if item["taskType"] == "slice" and item["targetId"] == knowledge_file_id
    )
    assert slice_task["status"] == "成功"

    chunks = assert_ok(client.get(f"/knowledge/files/{knowledge_file_id}/chunks"))
    assert chunks["total"] == 1
    assert chunks["items"][0]["text"].startswith("证书编号")
    vector_task = next(
        item for item in repo.state["knowledge_tasks"] if item["taskType"] == "vector" and item["targetId"] == knowledge_file_id
    )
    assert vector_task["status"] == "成功"
    vectors = assert_ok(client.get(f"/knowledge/files/{knowledge_file_id}/vectors"))
    assert vectors["storedVectorCount"] == 1
    vector = next(item for item in repo.state["knowledge_vectors"] if item.get("fileId") == knowledge_file_id)
    assert vector["embeddingModel"] == OFFLINE_EMBEDDING_MODEL
    assert vector["dimensions"] == OFFLINE_VECTOR_DIMENSIONS
    assert len(vector["embedding"]) == OFFLINE_VECTOR_DIMENSIONS


def test_document_preview_and_download_use_current_version_signed_get(monkeypatch) -> None:
    captured: list[tuple[str, str | None]] = []

    def fake_presigned_get(url: str, *, file_name: str | None = None):
        captured.append((url, file_name))
        return f"https://minio.local/{url.removeprefix('minio://')}"

    monkeypatch.setattr("libs.db.repository.object_storage.presigned_get_url", fake_presigned_get)
    document, version = repo.create_document("P-2026-HDCP-001", "field-report.pdf", "application/pdf")

    preview = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{document['id']}/preview-url"))
    download = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{document['id']}/download-url"))
    detail = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{document['id']}"))

    expected_storage_url = f"minio://documents/{version['storageKey']}"
    assert preview["url"].startswith("https://minio.local/documents/")
    assert download["url"].startswith("https://minio.local/documents/")
    assert detail["preview"]["url"] == preview["url"]
    assert detail["download"]["url"] == download["url"]
    assert preview["previewType"] == "pdf"
    assert preview["contentType"] == "application/pdf"
    assert download["contentType"] == "application/pdf"
    assert (expected_storage_url, "field-report.pdf") in captured
    assert "mock://" not in preview["url"]
    assert "mock://" not in download["url"]
    assert_error(client.get(f"/projects/NOT-A-PROJECT/documents/{document['id']}/download-url"), "NOT_FOUND")


def test_project_document_detail_streams_existing_local_original_file() -> None:
    body = b"%PDF-1.4\nexisting-local-original\n%%EOF\n"
    document, version = repo.create_document("P-2026-GDLNG-002", "existing-local.pdf", "application/pdf")
    workspace_root = Path(__file__).resolve().parents[2]
    target = workspace_root / "output" / "document_uploads" / "test-contract" / version["id"] / "existing-local.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    version["storageKey"] = f"local://{target.relative_to(workspace_root)}"
    version["storageBucket"] = "local"
    version["fileSize"] = len(body)
    try:
        detail = assert_ok(client.get(f"/projects/P-2026-GDLNG-002/documents/{document['id']}"))
        preview = assert_ok(client.get(f"/projects/P-2026-GDLNG-002/documents/{document['id']}/preview-url"))
        download = assert_ok(client.get(f"/projects/P-2026-GDLNG-002/documents/{document['id']}/download-url"))

        expected_preview_url = f"/api/projects/P-2026-GDLNG-002/documents/{document['id']}/original?disposition=inline"
        expected_download_url = f"/api/projects/P-2026-GDLNG-002/documents/{document['id']}/original?disposition=attachment"
        assert detail["preview"]["url"] == expected_preview_url
        assert preview["url"] == expected_preview_url
        assert download["url"] == expected_download_url
        assert preview["sourceUrl"].startswith("local://output/document_uploads/")
        assert "mock://" not in preview["url"]
        original = client.get(expected_preview_url)
        assert original.status_code == 200
        assert original.content == body
    finally:
        target.unlink(missing_ok=True)
        for parent in (target.parent, target.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                pass


def test_project_document_local_heic_inline_preview_renders_png(monkeypatch) -> None:
    body = b"fake-heic-original"
    rendered = b"\x89PNG\r\n\x1a\nrendered-preview"
    document, version = repo.create_document("P-2026-GDLNG-002", "IMG_6528.heic", "heic")
    workspace_root = Path(__file__).resolve().parents[2]
    target = workspace_root / "output" / "document_uploads" / "test-contract" / version["id"] / "IMG_6528.heic"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    version["storageKey"] = f"local://{target.relative_to(workspace_root)}"
    version["storageBucket"] = "local"
    version["fileSize"] = len(body)
    monkeypatch.setattr("apps.api.routes.fde_render_heic_page_preview", lambda path: (rendered, "image/png"))
    try:
        detail = assert_ok(client.get(f"/projects/P-2026-GDLNG-002/documents/{document['id']}"))
        preview_url = f"/api/projects/P-2026-GDLNG-002/documents/{document['id']}/original?disposition=inline"
        download_url = f"/api/projects/P-2026-GDLNG-002/documents/{document['id']}/original?disposition=attachment"

        assert detail["preview"]["url"] == preview_url
        assert detail["preview"]["previewType"] == "image"
        assert detail["preview"]["contentType"] == "image/png"
        assert detail["preview"]["sourceContentType"] == "image/heic"
        assert detail["download"]["url"] == download_url
        assert detail["download"]["contentType"] == "image/heic"

        original = client.get(preview_url)
        assert original.status_code == 200
        assert original.content == rendered
        assert original.headers["content-type"].startswith("image/png")
        assert original.headers["content-disposition"].startswith("inline")

        download = client.get(download_url)
        assert download.status_code == 200
        assert download.content == body
        assert download.headers["content-type"].startswith("image/heic")
        assert download.headers["content-disposition"].startswith("attachment")
    finally:
        target.unlink(missing_ok=True)
        for parent in (target.parent, target.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                pass


def test_heic_preview_sips_fallback_caps_preview_size(monkeypatch, tmp_path) -> None:
    from apps.api import routes

    source = tmp_path / "source.heic"
    source.write_bytes(b"heic")
    captured: list[list[str]] = []

    def fake_run(command, **kwargs):
        captured.append([str(item) for item in command])
        Path(command[-1]).write_bytes(b"\x89PNG\r\n\x1a\nsmall-preview")

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(routes, "fde_render_image_page_preview", lambda _path: None)
    # HEIC 预览的实现已搬到 libs.fde_console_views，patch 点跟着走。
    # 原先 patch 的是 routes.shutil——函数搬走后那个 patch 什么也不影响，
    # 测试会静默变成「没在测东西」。这次它响亮地报了 AttributeError，
    # 是因为 routes.py 里 shutil 的 import 也一并清掉了。
    from libs import fde_console_views

    monkeypatch.setattr(
        fde_console_views.shutil, "which", lambda name: "/usr/bin/sips" if name == "sips" else None
    )
    monkeypatch.setattr(fde_console_views.subprocess, "run", fake_run)

    content, content_type = routes.fde_render_heic_page_preview(source) or (b"", "")

    assert content.startswith(b"\x89PNG")
    assert content_type == "image/png"
    assert captured
    assert captured[0][:4] == ["sips", "-Z", "1600", "-s"]


def test_knowledge_file_chunks_do_not_fabricate_and_original_streams_local_file() -> None:
    workspace_root = Path(__file__).resolve().parents[2]
    target = workspace_root / "tmp" / "knowledge-original-test.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    body = b"%PDF-1.4\n% local original test\n"
    target.write_bytes(body)
    try:
        document, version = repo.create_document(
            "P-2026-HDCP-001",
            "knowledge-original-test.pdf",
            "application/pdf",
        )
        file_id = f"KF-{document['id']}"
        version["storageKey"] = f"local://{target.relative_to(workspace_root)}"
        version["storageBucket"] = "local"
        version["fileSize"] = len(body)

        chunks = assert_ok(client.get(f"/knowledge/files/{file_id}/chunks?page=1&pageSize=5"))
        assert chunks["total"] == 0
        assert chunks["items"] == []
        refs = assert_ok(client.get(f"/knowledge/files/{file_id}/reasoning-references?page=1&pageSize=5"))
        assert refs["total"] == 0
        assert refs["items"] == []

        detail = assert_ok(client.get(f"/knowledge/files/{file_id}"))
        assert detail["preview"]["url"].endswith(f"/knowledge/files/{file_id}/original?disposition=inline")
        assert detail["download"]["url"].endswith(f"/knowledge/files/{file_id}/original?disposition=attachment")

        original = client.get(f"/knowledge/files/{file_id}/original?disposition=inline")
        assert original.status_code == 200
        assert original.headers["content-type"].startswith("application/pdf")
        assert original.content == body
    finally:
        target.unlink(missing_ok=True)


def test_knowledge_file_reasoning_references_only_return_real_file_links() -> None:
    refs = assert_ok(client.get("/knowledge/files/KF-DOC-20260625-001/reasoning-references?page=1&pageSize=5"))
    assert refs["total"] == 1
    assert refs["items"][0]["runId"] == "AIRUN-24-20260625-01"
    assert refs["items"][0]["nodeId"] == 24
    assert refs["items"][0]["quotedText"] == "TS6J-2024-03158"

    unrelated = assert_ok(client.get("/knowledge/files/KF-DOC-20260625-004/reasoning-references?page=1&pageSize=5"))
    assert unrelated["total"] == 0
    assert unrelated["items"] == []


def test_production_signed_url_rejects_mock_storage(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_OBJECT_STORAGE", "true")

    response = client.get("/downloads/prod-storage-required/signed-url")
    assert_error(response, "OBJECT_STORAGE_REQUIRED")


def test_operability_runtime_context_and_empty_overview_are_truthful(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_DATA", "false")
    monkeypatch.setenv("AICHECK_UI_DEMO_MODE", "false")
    repo.reset()

    runtime = assert_ok(client.get("/runtime/ui-context"))
    assert runtime["demoDataAllowed"] is False
    assert runtime["serverTime"]
    assert runtime["release"]["releaseId"] == runtime["buildVersion"]

    overview = assert_ok(client.get("/operations/overview?area=admin", headers={"X-Role": "admin"}))
    assert overview["totals"]["projects"] == 0
    assert overview["totals"]["users"] == 0
    assert overview["attentionItems"] == []
    assert overview["dataAsOf"] is None


def test_concrete_admin_routes_precede_the_dynamic_admin_route() -> None:
    from apps.api.routes import router

    paths = [
        str(getattr(route, "path", ""))
        for route in router.routes
        if "GET" in (getattr(route, "methods", set()) or set())
    ]
    assert paths.index("/admin/audit-logs") < paths.index("/admin/{kind}")


def test_admin_audit_logs_use_postgres_page_contract(monkeypatch) -> None:
    from datetime import datetime

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return list(self.rows)

    class Connection:
        def __init__(self):
            now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
            self.rows = [
                ("AUD-PG-3", {"id": "AUD-PG-3", "action": "发布规则", "result": "成功"}, now),
                ("AUD-PG-2", {"id": "AUD-PG-2", "action": "更新规则", "result": "成功"}, now),
                ("AUD-PG-1", {"id": "AUD-PG-1", "action": "登录", "result": "成功"}, now),
            ]

        def execute(self, sql, params=None):
            statement = " ".join(str(sql).split())
            if statement.startswith("SELECT count(*) FROM aicheck_state"):
                return Cursor([(len(self.rows),)])
            if statement.startswith("SELECT object_id, payload, updated_at FROM aicheck_state"):
                limit, offset = int(params[-2]), int(params[-1])
                return Cursor(self.rows[offset : offset + limit])
            return Cursor([])

        def commit(self):
            return None

    connection = Connection()
    repo.sync_postgres = connection
    repo.postgres_enabled = True
    repo.postgres_dsn = "postgresql://test"
    monkeypatch.setattr(repo, "configure_sync_postgres", lambda dsn=None: None)

    data = assert_ok(client.get("/admin/audit-logs?page=2&pageSize=2", headers={"X-Role": "admin"}))
    assert data["page"] == 2
    assert data["pageSize"] == 2
    assert data["total"] == 3
    assert [item["id"] for item in data["items"]] == ["AUD-PG-1"]
    assert data["paginationMode"] == "offset"
    assert data["integrity"]["coverageStatus"] in {
        "complete",
        "legacy_unverified_sealed",
        "legacy_unverified_unsealed",
    }

    invalid = client.get("/admin/audit-logs?cursor=not-base64", headers={"X-Role": "admin"})
    assert_error(invalid, "VALIDATION_ERROR")


def test_operations_and_search_enforce_role_and_project_scope() -> None:
    project_id = "P-2026-HDCP-001"
    assert_error(
        client.get("/operations/overview?area=fde", headers={"X-Role": "contractor"}),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/search?scope=admin&keyword=项目", headers={"X-Role": "contractor"}),
        "FORBIDDEN",
    )

    task_page = assert_ok(
        client.get(
            f"/operations/tasks?area=workbench&projectId={project_id}&pageSize=100",
            headers={"X-Role": "inspection"},
        )
    )
    assert all(item.get("projectId") == project_id for item in task_page["items"])

    results = assert_ok(
        client.get(
            f"/search?scope=workbench&projectId={project_id}&keyword=报告&pageSize=100",
            headers={"X-Role": "inspection"},
        )
    )
    assert all(project_id in str(item.get("route") or "") for item in results["items"])


def test_rule_publish_preview_is_user_bound_single_use_and_required_in_strict(monkeypatch) -> None:
    rule = repo.find_one("rule_versions", "RULE-NDT-202606")
    assert rule is not None
    rule_view = next(item for item in assert_ok(client.get("/rules/versions?pageSize=100"))["items"] if item["id"] == rule["id"])
    headers = {"X-Role": "admin", "X-User-Id": "USER-ADMIN"}
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")

    assert_error(
        client.post(
            f"/rules/versions/{rule['id']}/publish",
            json={"reason": "正式发布"},
            headers={**headers, "If-Match": rule_view["etag"]},
        ),
        "VALIDATION_ERROR",
    )

    preview = assert_ok(
        client.post(
            f"/rules/versions/{rule['id']}/publish-preview",
            json={"reason": "正式发布"},
            headers=headers,
        )
    )
    assert preview["impact"]["ruleVersionId"] == rule["id"]
    assert preview["impact"]["linkedProjects"] >= 0

    assert_error(
        client.post(
            f"/rules/versions/{rule['id']}/publish",
            json={"reason": "正式发布", "previewId": preview["previewId"]},
            headers={"X-Role": "admin", "X-User-Id": "USER-OTHER", "If-Match": rule_view["etag"]},
        ),
        "FORBIDDEN",
    )

    published = assert_ok(
        client.post(
            f"/rules/versions/{rule['id']}/publish",
            json={"reason": "正式发布", "previewId": preview["previewId"]},
            headers={**headers, "If-Match": rule_view["etag"], "Idempotency-Key": "strict-rule-preview-once"},
        )
    )
    assert published["rule"]["status"] == "已发布"
    assert next(item for item in repo.state["operation_previews"] if item["previewId"] == preview["previewId"])["consumedAt"]

    assert_error(
        client.post(
            f"/rules/versions/{rule['id']}/publish",
            json={"reason": "正式发布", "previewId": preview["previewId"]},
            headers={**headers, "If-Match": published["rule"]["etag"], "Idempotency-Key": "strict-rule-preview-second"},
        ),
        "CONFLICT",
    )


def test_rule_diff_and_rollback_reject_unrelated_or_missing_targets() -> None:
    rule = repo.find_one("rule_versions", "RULE-NDT-202606")
    assert rule is not None
    assert_error(
        client.get(f"/rules/versions/{rule['id']}/diff?targetVersionId=NOT-A-RULE"),
        "NOT_FOUND",
    )
    assert_error(
        client.post(
            f"/rules/versions/{rule['id']}/rollback-preview",
            json={"reason": "回滚验证", "targetVersionId": rule["id"]},
            headers={"X-Role": "admin", "X-User-Id": "USER-ADMIN"},
        ),
        "VALIDATION_ERROR",
    )


def test_upload_session_storage_failure_does_not_create_dirty_records(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_OBJECT_STORAGE", "true")
    monkeypatch.setattr("libs.db.repository.object_storage.presigned_put_url", lambda *args, **kwargs: None)
    tracked_collections = ("documents", "versions", "knowledge_files", "knowledge_tasks", "upload_sessions")
    before = {collection: len(repo.state[collection]) for collection in tracked_collections}

    assert_error(
        client.post(
            "/projects/P-2026-HDCP-001/documents/upload-session",
            json={"files": [{"fileName": "should-not-persist.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
        ),
        "OBJECT_STORAGE_REQUIRED",
    )

    after = {collection: len(repo.state[collection]) for collection in tracked_collections}
    assert after == before


def test_upload_session_uses_local_direct_upload_when_storage_optional(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_OBJECT_STORAGE", "false")
    monkeypatch.setattr("libs.db.repository.object_storage.presigned_put_url", lambda *args, **kwargs: None)
    body = b"%PDF-local-document-upload"

    upload = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/documents/upload-session",
            json={
                "files": [
                    {
                        "fileName": "local-direct-upload.pdf",
                        "fileSize": len(body),
                        "fileType": "application/pdf",
                    }
                ],
                "requireSignedUrls": True,
            },
        )
    )
    target = upload["uploadUrls"][0]
    assert target["url"].startswith("/api/projects/P-2026-HDCP-001/documents/upload-session/")
    assert "mock://" not in target["url"]

    stored = assert_ok(client.put(target["url"], content=body, headers=target["headers"]))
    version = repo.find_one("versions", target["documentVersionId"])
    assert stored["fileSize"] == len(body)
    assert version["storageBucket"] == "local"
    assert version["storageKey"].startswith("local://output/document_uploads/")
    assert (Path(__file__).resolve().parents[2] / version["storageKey"].removeprefix("local://")).read_bytes() == body

    completed = assert_ok(
        client.post(
            f"/projects/P-2026-HDCP-001/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={"completedFiles": [{"documentVersionId": target["documentVersionId"], "fileSize": len(body)}]},
        )
    )
    assert completed["fileCount"] == 1

    preview = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{target['documentId']}/preview-url"))
    download = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{target['documentId']}/download-url"))
    assert preview["url"] == f"/api/projects/P-2026-HDCP-001/documents/{target['documentId']}/original?disposition=inline"
    assert download["url"] == f"/api/projects/P-2026-HDCP-001/documents/{target['documentId']}/original?disposition=attachment"
    assert preview["fileSize"] == len(body)
    assert download["fileSize"] == len(body)
    original = client.get(f"/api/projects/P-2026-HDCP-001/documents/{target['documentId']}/original")
    assert original.status_code == 200
    assert original.content == body


def test_contractor_default_project_upload_uses_local_direct_upload(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_OBJECT_STORAGE", "false")
    monkeypatch.setattr("libs.db.repository.object_storage.presigned_put_url", lambda *args, **kwargs: None)
    body = b"contractor-default-project-upload"

    upload = assert_ok(
        client.post(
            "/projects/P-2026-GDLNG-002/documents/upload-session",
            json={
                "files": [
                    {
                        "fileName": "contractor-default-project-auth.pdf",
                        "fileSize": len(body),
                        "fileType": "application/pdf",
                        "materialCategory": "设计资料",
                    }
                ],
                "requireSignedUrls": True,
            },
            headers={"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"},
        )
    )
    target = upload["uploadUrls"][0]
    assert target["url"].startswith("/api/projects/P-2026-GDLNG-002/documents/upload-session/")
    assert target["materialCategory"] == "设计资料"
    assert target["headers"]["X-Role"] == "contractor"
    assert target["headers"]["X-User-Id"] == "USER-CONTRACTOR-001"

    stored = assert_ok(client.put(target["url"], content=body, headers=target["headers"]))
    document = repo.find_one("documents", target["documentId"])
    assert stored["storageBucket"] == "local"
    assert document["sourceOrgName"] == "粤海安装工程有限公司"
    assert document["materialCategory"] == "设计资料"

    completed = assert_ok(
        client.post(
            f"/projects/P-2026-GDLNG-002/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={"completedFiles": [{"documentVersionId": target["documentVersionId"], "fileSize": len(body)}]},
            headers={"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"},
        )
    )
    inspection_files = assert_ok(
        client.get(
            "/projects/P-2026-GDLNG-002/documents?page=1&pageSize=100",
            headers={"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"},
        )
    )
    assert completed["fileCount"] == 1
    uploaded_document = next(item for item in inspection_files["items"] if item["id"] == target["documentId"])
    assert uploaded_document["materialCategory"] == "设计资料"


def test_contractor_upload_persists_mineru_job_without_celery(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_REQUIRE_OBJECT_STORAGE", "false")
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    monkeypatch.setenv("AICHECK_MINERU_EXECUTION_MODE", "postgres")
    monkeypatch.setenv("AICHECK_OCR_DEFAULT_PROVIDER", "mineru")
    monkeypatch.setattr("libs.db.repository.object_storage.presigned_put_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tasks.parse_document,
        "apply_async",
        lambda **_kwargs: pytest.fail("MinerU upload completion must not call Celery"),
    )
    body = b"contractor-postgres-mineru-upload"

    upload = assert_ok(
        client.post(
            "/projects/P-2026-GDLNG-002/documents/upload-session",
            json={
                "files": [
                    {
                        "fileName": "contractor-postgres-mineru.pdf",
                        "fileSize": len(body),
                        "fileType": "application/pdf",
                        "materialCategory": "设计资料",
                    }
                ],
                "requireSignedUrls": True,
            },
            headers={"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"},
        )
    )
    target = upload["uploadUrls"][0]
    assert_ok(client.put(target["url"], content=body, headers=target["headers"]))

    completed = assert_ok(
        client.post(
            f"/projects/P-2026-GDLNG-002/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={"completedFiles": [{"documentVersionId": target["documentVersionId"], "fileSize": len(body)}]},
            headers={"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"},
        )
    )

    assert completed["fileCount"] == 1
    assert completed["queuedTasks"][0]["mode"] == "postgres"
    jobs = [
        job
        for job in repo.state["ocr_jobs"]
        if job.get("documentId") == target["documentId"]
        and job.get("documentVersionId") == target["documentVersionId"]
        and job.get("provider") == "mineru"
    ]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "queued"
    assert jobs[0]["stage"] == "queued"


def test_worker_uses_ocr_http_client_when_configured(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_OCR_BASE_URL", "http://ocr")

    class FakeOcrClient:
        enabled = True

        def parse_sync(self, storage_key: str, *, file_name: str | None = None, **kwargs):
            return {
                "storageKey": storage_key,
                "fileName": file_name,
                "status": "success",
                "fragments": [{"pageNo": 1, "text": "HTTP OCR 证书编号 TS-HTTP", "confidence": 0.93}],
                "fields": [{"fieldName": "证书编号", "fieldValue": "TS-HTTP", "confidence": 0.95}],
                "seals": [],
                "diagnostics": [],
            }

    monkeypatch.setattr(tasks, "OcrClient", lambda: FakeOcrClient())
    doc, version = repo.create_document("P-2026-HDCP-001", "HTTP-OCR.pdf", "pdf")
    result = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])

    assert result["applied"]["status"] == "success"
    assert result["ocrJobRecordId"]
    assert result["ocrParseResultId"]
    assert repo.state["ocr_jobs"][0]["documentVersionId"] == version["id"]
    assert repo.state["ocr_parse_results"][0]["documentVersionId"] == version["id"]
    fields = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{doc['id']}/ocr-fields"))
    assert any(field["fieldValue"] == "TS-HTTP" for field in fields)


def test_worker_in_process_ocr_requires_explicit_development_switch(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.delenv("AICHECK_OCR_BASE_URL", raising=False)
    monkeypatch.delenv("AICHECK_WORKER_OCR_ALLOW_IN_PROCESS", raising=False)
    monkeypatch.setenv("AICHECK_WORKER_OCR_ENABLE_LOCAL_FALLBACK", "false")

    with pytest.raises(RuntimeError, match="AICHECK_OCR_BASE_URL"):
        tasks.parse_with_ocr_service("local://fake.pdf", file_name="fake.pdf")


def test_worker_prefers_ocr_job_api_when_available(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_OCR_BASE_URL", "http://ocr")

    class FakeOcrClient:
        enabled = True
        called_job_api = False

        def parse_via_job_sync(self, payload, **kwargs):
            FakeOcrClient.called_job_api = True
            return {
                "jobId": "OCRJOB-REMOTE-001",
                "externalJobId": "OCRJOB-REMOTE-001",
                "parseResultId": "PARSE-REMOTE-001",
                "storageKey": payload["storageKey"],
                "fileName": payload["fileName"],
                "status": "success",
                "parserVersion": "document-intelligence@1",
                "engineVersion": "local-paddle@profiled",
                "fragments": [{"pageNo": 1, "text": "HTTP JOB OCR 证书编号 TS-JOB", "confidence": 0.93}],
                "fields": [{"fieldName": "证书编号", "fieldValue": "TS-JOB", "confidence": 0.95}],
                "tables": [],
                "seals": [],
                "diagnostics": [],
                "engineRuns": [{"engine": "job-api", "status": "success"}],
            }

        def parse_sync(self, storage_key: str, *, file_name: str | None = None, **kwargs):
            raise AssertionError("parse_sync should not be used when job API is available")

    monkeypatch.setattr(tasks, "OcrClient", lambda: FakeOcrClient())
    doc, version = repo.create_document("P-2026-HDCP-001", "HTTP-OCR-job.pdf", "pdf")
    result = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])

    assert FakeOcrClient.called_job_api is True
    assert result["parseResultId"] == "PARSE-REMOTE-001"
    assert repo.state["ocr_jobs"][0]["jobId"] == "OCRJOB-REMOTE-001"
    assert repo.state["ocr_parse_results"][0]["parseResultId"] == "PARSE-REMOTE-001"


def test_worker_ocr_job_api_preserves_business_profile_and_options(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_OCR_BASE_URL", "http://ocr")
    captured = {}

    class FakeOcrClient:
        enabled = True

        def parse_via_job_sync(self, payload, **kwargs):
            captured.update(payload)
            return {
                "jobId": "OCRJOB-BUSINESS-001",
                "externalJobId": "OCRJOB-BUSINESS-001",
                "parseResultId": "PARSE-BUSINESS-001",
                "storageKey": payload["storageKey"],
                "fileName": payload["fileName"],
                "status": "success",
                "fragments": [{"pageNo": 1, "text": "产品质量证明书 GB/T 8163-2018", "confidence": 0.93}],
                "fields": [{"fieldName": "执行标准", "fieldValue": "GB/T 8163-2018", "confidence": 0.95}],
                "tables": [],
                "seals": [],
                "diagnostics": [],
                "engineRuns": [{"engine": "job-api", "status": "success"}],
            }

        def parse_sync(self, storage_key: str, *, file_name: str | None = None, **kwargs):
            raise AssertionError("parse_sync should not be used when job API is available")

    monkeypatch.setattr(tasks, "OcrClient", lambda: FakeOcrClient())
    doc, version = repo.create_document("P-2026-HDCP-001", "quality-certificate.pdf", "application/pdf")
    doc["ocrProfileId"] = "quality_certificate_v1"
    doc["documentType"] = "quality_certificate"
    version["ocrProfileId"] = "quality_certificate_v1"
    version["documentType"] = "quality_certificate"

    result = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])

    assert result["parseResultId"] == "PARSE-BUSINESS-001"
    assert captured["documentId"] == doc["id"]
    assert captured["documentVersionId"] == version["id"]
    assert captured["profileId"] == "quality_certificate_v1"
    assert captured["documentType"] == "quality_certificate"
    assert captured["options"]["engineAllowlist"] == tasks.ACCURACY_BASELINE_TEXT_ENGINES
    assert captured["options"]["enableTables"] is False
    assert captured["options"]["enableSeals"] is False
    assert captured["options"]["enableFallback"] is True


def test_worker_local_ocr_fallback_preserves_business_profile(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.delenv("AICHECK_OCR_BASE_URL", raising=False)
    monkeypatch.setenv("AICHECK_WORKER_OCR_ENABLE_LOCAL_FALLBACK", "false")
    monkeypatch.setenv("AICHECK_WORKER_OCR_ALLOW_IN_PROCESS", "true")
    captured = {}

    def fake_parse(storage_key: str, *, file_name: str | None = None, **kwargs):
        captured.update({"storageKey": storage_key, "fileName": file_name, **kwargs})
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "产品质量证明书 GB/T 8163-2018", "confidence": 0.94}],
            "fields": [{"fieldName": "执行标准", "fieldValue": "GB/T 8163-2018", "confidence": 0.94}],
            "tables": [],
            "seals": [],
            "diagnostics": [],
        }

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)
    doc, version = repo.create_document("P-2026-HDCP-001", "quality-certificate.pdf", "application/pdf")
    doc["ocrProfileId"] = "quality_certificate_v1"
    doc["documentType"] = "quality_certificate"
    version["ocrProfileId"] = "quality_certificate_v1"
    version["documentType"] = "quality_certificate"

    result = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])

    assert result["applied"]["status"] == "success"
    assert captured["profile_id"] == "quality_certificate_v1"
    assert captured["document_type"] == "quality_certificate"
    assert captured["document_version_id"] == version["id"]
    assert captured["options"]["engineAllowlist"] == tasks.ACCURACY_BASELINE_TEXT_ENGINES
    assert captured["options"]["enableTables"] is False
    assert captured["options"]["enableSeals"] is False


def test_failed_knowledge_task_retry_dispatches_worker_and_is_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")
    monkeypatch.delenv("AICHECK_OCR_BASE_URL", raising=False)
    monkeypatch.setenv("AICHECK_WORKER_OCR_ALLOW_IN_PROCESS", "true")

    def fake_parse(storage_key: str, *, file_name: str | None = None, **kwargs):
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "炉批号 H240315A07", "confidence": 0.92}],
            "fields": [{"fieldName": "炉批号", "fieldValue": "H240315A07", "confidence": 0.92}],
            "seals": [],
            "diagnostics": [],
        }

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)

    first = assert_ok(
        client.post(
            "/knowledge/tasks/KT-20260626-002/retry",
            headers={"Idempotency-Key": "retry-ocr-once"},
        )
    )
    second = assert_ok(
        client.post(
            "/knowledge/tasks/KT-20260626-002/retry",
            headers={"Idempotency-Key": "retry-ocr-once"},
        )
    )
    task = repo.find_one("knowledge_tasks", "KT-20260626-002")

    assert first["dispatches"][0]["mode"] == "inline"
    assert second["task"]["attempts"] == first["task"]["attempts"]
    assert task["attempts"] == 1
    assert task["status"] == "成功"
    assert task["progress"] == 100
    assert task["lastDispatch"]["mode"] == "inline"
    logs = assert_ok(client.get("/knowledge/tasks/KT-20260626-002/logs"))
    assert any("重试已投递" in item["message"] for item in logs)
    assert any("OCR 任务完成" in item["message"] for item in logs)


def test_knowledge_task_list_prioritizes_failed_tasks_before_new_queued_items() -> None:
    for index in range(12):
        repo.state["knowledge_tasks"].insert(
            0,
            {
                "id": f"KT-NEW-{index}",
                "taskType": "ocr",
                "targetType": "file",
                "targetId": f"KF-NEW-{index}",
                "targetName": f"新上传资料-{index}.pdf",
                "status": "排队中",
                "progress": 0,
                "createdAt": f"2026-06-27 18:{index:02d}:00",
                "updatedAt": f"2026-06-27 18:{index:02d}:00",
                "actions": ["knowledge:task-retry"],
                "revision": 1,
            },
        )

    tasks = assert_ok(client.get("/knowledge/tasks?pageSize=10"))["items"]

    assert tasks[0]["id"] == "KT-20260626-002"
    assert tasks[0]["targetName"] == "钢管质量证明书.pdf"
    assert tasks[0]["status"] == "失败"


def test_cancelled_knowledge_task_is_not_processed_by_worker() -> None:
    from apps.worker import tasks

    cancelled = assert_ok(client.post("/knowledge/tasks/KT-20260626-001/cancel"))
    assert cancelled["task"]["status"] == "已取消"

    result = tasks.embed_knowledge.run("KF-DOC-20260625-004")
    task = repo.find_one("knowledge_tasks", "KT-20260626-001")

    assert result["status"] == "canceled"
    assert task["status"] == "已取消"
    logs = assert_ok(client.get("/knowledge/tasks/KT-20260626-001/logs"))
    assert any("任务已取消" in item["message"] for item in logs)


def test_ocr_service_reports_missing_source_before_running_pipeline() -> None:
    from apps.ocr_service.service import OcrService

    service = OcrService()
    service.pipeline = lambda source_path: {"text": f"unexpected {source_path}"}

    result = service.parse_document("missing-object.pdf", file_name="missing-object.pdf")

    assert result["status"] == "failed"
    assert "OCR source file is unavailable" in result["diagnostics"][0]


def test_ocr_service_rejects_unapproved_local_file_path(tmp_path, monkeypatch) -> None:
    from apps.ocr_service.service import OcrService

    outside = tmp_path / "outside.pdf"
    allowed = tmp_path / "allowed"
    outside.write_text("not a real pdf", encoding="utf-8")
    allowed.mkdir()
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(allowed))
    monkeypatch.setenv("AICHECK_OCR_ALLOW_DIRECT_PATHS", "false")
    service = OcrService()
    service.pipeline = lambda source_path: {"text": f"unexpected {source_path}"}

    result = service.parse_document(str(outside), file_name="outside.pdf")

    assert result["status"] == "failed"
    assert "OCR source file is unavailable" in result["diagnostics"][0]


def test_worker_records_ocr_client_failure_without_leaking_provider_details(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_OCR_BASE_URL", "http://ocr")

    class FailingOcrClient:
        enabled = True

        def parse_sync(self, storage_key: str, *, file_name: str | None = None, **kwargs):
            raise RuntimeError("provider failed with sk-secret-ocr")

    monkeypatch.setattr(tasks, "OcrClient", lambda: FailingOcrClient())
    doc, version = repo.create_document("P-2026-HDCP-001", "OCR-fail.pdf", "pdf")

    result = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])
    task = repo.ocr_task_for(doc["id"], version["id"], doc["fileName"])

    assert result["status"] == "failed"
    assert result["applied"]["status"] == "failed"
    assert task["status"] == "失败"
    assert "OCR 服务 调用失败" in task["errorMessage"]
    assert "sk-secret-ocr" not in task["errorMessage"]


def test_missing_knowledge_file_workers_mark_tasks_failed() -> None:
    from apps.worker import tasks

    slice_task = {
        "id": "KT-MISSING-SLICE",
        "taskType": "slice",
        "targetType": "file",
        "targetId": "KF-MISSING",
        "targetName": "missing.pdf",
        "status": "排队中",
        "progress": 0,
        "createdAt": "2026-06-27 00:00:00",
    }
    vector_task = {
        "id": "KT-MISSING-VECTOR",
        "taskType": "vector",
        "targetType": "file",
        "targetId": "KF-MISSING",
        "targetName": "missing.pdf",
        "status": "排队中",
        "progress": 0,
        "createdAt": "2026-06-27 00:00:00",
    }
    repo.state["knowledge_tasks"].extend([slice_task, vector_task])

    sliced = tasks.slice_knowledge.run("KF-MISSING")
    embedded = tasks.embed_knowledge.run("KF-MISSING")

    assert sliced["status"] == "missing"
    assert embedded["status"] == "missing"
    assert slice_task["status"] == "失败"
    assert vector_task["status"] == "失败"
    assert "找不到关联知识文件" in slice_task["errorMessage"]
    assert "找不到关联知识文件" in vector_task["errorMessage"]


def test_litellm_failure_maps_to_ai_run_failed(monkeypatch) -> None:
    from apps.worker import tasks

    seed_reviewed_node_24()
    allow_test_ai_dispatch(monkeypatch)
    run = assert_ok(client.post("/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck"))

    class FailingLiteLLM:
        def chat_sync(self, *args, **kwargs):
            raise RuntimeError("provider unavailable sk-secret-litellm")

    monkeypatch.setattr(tasks, "LiteLLMClient", FailingLiteLLM)
    result = tasks.ai_recheck.run("P-2026-HDCP-001", 24, run["runId"])
    stored = repo.find_one("ai_runs", run["runId"])

    assert result["status"] == "失败"
    assert stored["status"] == "失败"
    assert stored["errorCode"] == "AI_RUN_FAILED"
    assert "QwenRuntime AI 复核 调用失败" in stored["errorMessage"]
    assert "sk-secret-litellm" not in stored["errorMessage"]


def test_grounded_review_input_formats_table_and_blocks_weak_ocr_evidence() -> None:
    from libs.review_grounding import build_grounded_review_input, unsupported_claims

    state = {
        "extracted_fields": [
            {
                "id": "FIELD-GROUND-1",
                "documentVersionId": "DV-GROUND-1",
                "fieldName": "证书编号",
                "fieldValue": "TS1810648-2021",
                "pageNo": 1,
                "bbox": [10, 20, 180, 42],
                "confidence": 0.96,
                "evidenceLinkId": "EV-GROUND-1",
            }
        ],
        "ocr_parse_results": [
            {
                "parseResultId": "PARSE-GROUND-1",
                "documentVersionId": "DV-GROUND-1",
                "status": "success",
                "tables": [
                    {
                        "tableId": "TBL-GROUND-1",
                        "pageNo": 1,
                        "bbox": [80, 260, 1040, 700],
                        "structureConfidence": 0.94,
                        "cells": [
                            {"rowIndex": 0, "columnIndex": 0, "text": "名称", "confidence": 0.95},
                            {"rowIndex": 0, "columnIndex": 1, "text": "图号", "confidence": 0.95},
                            {"rowIndex": 1, "columnIndex": 0, "text": "工艺图纸目录", "confidence": 0.94},
                            {"rowIndex": 1, "columnIndex": 1, "text": "QX201903S-13-Y-00", "confidence": 0.94},
                        ],
                    }
                ],
                "seals": [
                    {
                        "sealId": "SEAL-GROUND-1",
                        "sealName": "红章候选",
                        "pageNo": 1,
                        "bbox": [190, 758, 593, 1005],
                        "visualConfidence": 0.91,
                        "qualityFlags": ["visual_candidate_only"],
                    }
                ],
                "fragments": [],
            }
        ],
        "evidence_links": [
            {
                "id": "EV-GROUND-1",
                "documentVersionId": "DV-GROUND-1",
                "pageNo": 1,
                "quotedText": "TS1810648-2021",
                "bbox": [10, 20, 180, 42],
                "confidence": 0.96,
            }
        ],
    }

    grounded = build_grounded_review_input(state, {"DV-GROUND-1"})
    table = grounded["tables"][0]
    issue_codes = {item["code"] for item in grounded["blockingIssues"]}
    unsupported = unsupported_claims("资料符合要求，建议通过。", grounded["evidenceTextCorpus"])

    assert "| 名称 | 图号 |" in table["contentMarkdown"]
    assert "QX201903S-13-Y-00" in table["contentMarkdown"]
    assert table["cellsSummary"][0]["text"] == "名称"
    assert grounded["groundingStatus"] == "insufficient_evidence"
    assert "OCR_GROUNDING_SEAL_TEXT_RISK" in issue_codes
    assert unsupported[0]["reason"] == "positive_claim_without_specific_evidence_token"


def test_ai_recheck_downgrades_unsupported_litellm_claims(monkeypatch) -> None:
    from apps.worker import tasks

    class FakeLiteLLM:
        def chat_sync(self, *args, **kwargs):
            return {
                "id": "chatcmpl-unsupported-claim",
                "choices": [
                    {
                        "message": {
                            "content": "焊工王建国证书编号、有效期和持证项目与焊接工艺要求匹配，建议通过。"
                        }
                    }
                ],
                "usage": {"total_tokens": 80},
            }

        @staticmethod
        def first_message_text(response):
            return response["choices"][0]["message"]["content"]

    monkeypatch.setattr(tasks, "LiteLLMClient", FakeLiteLLM)

    seed_reviewed_node_24()
    allow_test_ai_dispatch(monkeypatch)
    run = assert_ok(client.post("/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck"))
    result = tasks.ai_recheck.run("P-2026-HDCP-001", 24, run["runId"])
    stored = repo.find_one("ai_runs", run["runId"])
    draft = stored["findingDrafts"][0]

    assert result["status"] == "完成"
    assert draft["groundingStatus"] == "insufficient_evidence"
    assert draft["unsupportedClaims"]
    assert "证据不足" in draft["title"]
    assert "王建国" not in draft["description"]
    assert stored["suggestion"]["confidence"] <= 0.5
    assert stored["llmMetadata"]["groundingStatus"] == "insufficient_evidence"


def test_offline_embed_and_compare_failures_do_not_leak_provider_details(monkeypatch) -> None:
    from apps.worker import tasks

    class FailingLiteLLM:
        def chat_sync(self, *args, **kwargs):
            raise RuntimeError("chat failed sk-secret-chat")

    repo.state.setdefault("knowledge_chunks", []).append(
        {
            "id": "CHK-FAIL-1",
            "fileId": "KF-DOC-20260625-004",
            "documentId": "DOC-20260625-004",
            "documentVersionId": "DV-20260625-004-V1",
            "chunkNo": 1,
            "text": "待向量化文本",
            "pageNo": 1,
            "tokenCount": 6,
            "createdAt": "2026-06-27 00:00:00",
        }
    )
    monkeypatch.setattr(tasks, "LiteLLMClient", FailingLiteLLM)

    embedded = tasks.embed_knowledge.run("KF-DOC-20260625-004")
    vector_task = repo.find_one("knowledge_tasks", "KT-20260626-001")
    compare = assert_ok(
        client.post(
            "/llm/compare",
            json={"question": "材料证明是否一致？", "modelCodes": ["default-chat", "compare-fast"]},
        )
    )
    compared = tasks.llm_compare.run(compare["runId"])
    compare_run = repo.find_one("llm_compare_runs", compare["runId"], id_field="runId")

    assert embedded["status"] == "success"
    assert vector_task["status"] == "成功"
    assert compared["status"] == "失败"
    assert compare_run["errorCode"] == "EXTERNAL_TOOL_FAILED"
    assert "QwenRuntime 模型对比 调用失败" in compare_run["errorMessage"]
    assert "sk-secret-chat" not in compare_run["errorMessage"]


def test_llm_compare_dispatches_to_worker_inline(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")

    class FakeLiteLLM:
        def chat_sync(self, *args, **kwargs):
            return {"choices": [{"message": {"content": f"{kwargs.get('model')} 完成对比"}}]}

        @staticmethod
        def first_message_text(response):
            return response["choices"][0]["message"]["content"]

    monkeypatch.setattr(tasks, "LiteLLMClient", FakeLiteLLM)
    compare = assert_ok(
        client.post(
            "/llm/compare",
            json={"question": "材料证明是否一致？", "modelCodes": ["default-chat", "compare-fast"]},
        )
    )
    stored = repo.find_one("llm_compare_runs", compare["runId"], id_field="runId")

    assert compare["dispatch"]["mode"] == "inline"
    assert stored["status"] == "完成"
    assert len(stored["results"]) == 2


def test_llm_compare_uses_grounded_compare_only_payload(monkeypatch) -> None:
    from apps.worker import tasks

    captured_messages = []

    class FakeLiteLLM:
        def chat_sync(self, messages, *args, **kwargs):
            captured_messages.append(messages)
            return {"choices": [{"message": {"content": "证书有效，资料符合要求，建议通过。"}}]}

        @staticmethod
        def first_message_text(response):
            return response["choices"][0]["message"]["content"]

    monkeypatch.setattr(tasks, "LiteLLMClient", FakeLiteLLM)
    compare = assert_ok(
        client.post(
            "/llm/compare",
            json={
                "question": "焊工资格证是否可以作为通过依据？",
                "modelCodes": ["default-chat", "compare-fast"],
                "evidenceLinkIds": ["EV-24-001"],
            },
        )
    )
    result = tasks.llm_compare.run(compare["runId"])
    stored = repo.find_one("llm_compare_runs", compare["runId"], id_field="runId")
    payload = json.loads(captured_messages[0][1]["content"])

    assert result["status"] == "完成"
    assert payload["compareOnly"] is True
    assert payload["strictGroundingPolicy"] == "evidence_only"
    assert "groundedOcrEvidence" in payload
    assert stored["promptAudit"]["payloadPolicy"] == "compare_only_grounded_ocr_evidence"
    assert stored["results"][0]["compareOnly"] is True
    assert stored["results"][0]["requiresHumanConfirmation"] is True
    assert stored["results"][0]["groundingStatus"] == "insufficient_evidence"
    assert stored["results"][0]["confidence"] <= 0.5
    assert "证据不足" in stored["results"][0]["answer"]


def test_completed_ocr_worker_is_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_WORKER_OCR_ALLOW_IN_PROCESS", "true")
    calls = {"ocr": 0, "options": None}

    def fake_parse(storage_key: str, *, file_name: str | None = None, **kwargs):
        calls["ocr"] += 1
        calls["options"] = kwargs.get("options")
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "证书编号 OCR-IDEMPOTENT", "confidence": 0.94}],
            "fields": [{"fieldName": "证书编号", "fieldValue": "OCR-IDEMPOTENT", "confidence": 0.94}],
            "seals": [],
            "diagnostics": [],
        }

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)
    doc, version = repo.create_document("P-2026-HDCP-001", "OCR-idempotent.pdf", "application/pdf")
    version["ocrOptions"] = {"disableResultCache": True}

    first = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])
    task = repo.ocr_task_for(doc["id"], version["id"], doc["fileName"])
    logs_after_first = list(task.get("logs", []))
    field_count_after_first = len(
        [item for item in repo.state["extracted_fields"] if item.get("documentVersionId") == version["id"]]
    )
    second = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])

    assert first["applied"]["status"] == "success"
    assert second["alreadyCompleted"] is True
    assert calls["ocr"] == 1
    assert calls["options"]["disableResultCache"] is True
    assert task.get("logs") == logs_after_first
    assert len([item for item in repo.state["extracted_fields"] if item.get("documentVersionId") == version["id"]]) == field_count_after_first


def test_completed_slice_and_embed_workers_are_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_WORKER_OCR_ALLOW_IN_PROCESS", "true")
    def fake_parse(storage_key: str, *, file_name: str | None = None, **kwargs):
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "炉批号 SLICE-EMBED-IDEMPOTENT", "confidence": 0.92}],
            "fields": [{"fieldName": "炉批号", "fieldValue": "SLICE-EMBED-IDEMPOTENT", "confidence": 0.92}],
            "seals": [],
            "diagnostics": [],
        }

    class FailingLiteLLM:
        def __init__(self, *args, **kwargs):
            raise AssertionError("knowledge embedding must stay offline")

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)
    monkeypatch.setattr(tasks, "LiteLLMClient", FailingLiteLLM)
    doc, version = repo.create_document("P-2026-HDCP-001", "slice-embed-idempotent.pdf", "application/pdf")
    tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])
    file_id = f"KF-{doc['id']}"

    first_slice = tasks.slice_knowledge.run(file_id)
    slice_task = next(item for item in repo.state["knowledge_tasks"] if item["taskType"] == "slice" and item["targetId"] == file_id)
    slice_logs_after_first = list(slice_task.get("logs", []))
    chunk_count_after_first = len([item for item in repo.state["knowledge_chunks"] if item.get("fileId") == file_id])
    second_slice = tasks.slice_knowledge.run(file_id)

    first_embed = tasks.embed_knowledge.run(file_id)
    vector_task = next(item for item in repo.state["knowledge_tasks"] if item["taskType"] == "vector" and item["targetId"] == file_id)
    vector_logs_after_first = list(vector_task.get("logs", []))
    vector_count_after_first = len([item for item in repo.state["knowledge_vectors"] if item.get("fileId") == file_id])
    second_embed = tasks.embed_knowledge.run(file_id)

    assert first_slice["status"] == "success"
    assert second_slice["alreadyCompleted"] is True
    assert slice_task.get("logs") == slice_logs_after_first
    assert len([item for item in repo.state["knowledge_chunks"] if item.get("fileId") == file_id]) == chunk_count_after_first
    assert first_embed["status"] == "success"
    assert second_embed["alreadyCompleted"] is True
    assert len([item for item in repo.state["knowledge_vectors"] if item.get("fileId") == file_id]) == vector_count_after_first
    assert vector_task.get("logs") == vector_logs_after_first


def test_completed_ai_and_compare_workers_are_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    class FakeLiteLLM:
        chat_calls = 0

        def chat_sync(self, *args, **kwargs):
            FakeLiteLLM.chat_calls += 1
            return {"choices": [{"message": {"content": f"{kwargs.get('model')} completed"}}]}

        @staticmethod
        def first_message_text(response):
            return response["choices"][0]["message"]["content"]

    monkeypatch.setattr(tasks, "LiteLLMClient", FakeLiteLLM)

    seed_reviewed_node_24()
    allow_test_ai_dispatch(monkeypatch)
    ai_run = assert_ok(client.post("/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck"))
    first_ai = tasks.ai_recheck.run("P-2026-HDCP-001", 24, ai_run["runId"])
    second_ai = tasks.ai_recheck.run("P-2026-HDCP-001", 24, ai_run["runId"])

    compare = assert_ok(
        client.post(
            "/llm/compare",
            json={"question": "材料证明是否一致？", "modelCodes": ["default-chat", "compare-fast"]},
        )
    )
    first_compare = tasks.llm_compare.run(compare["runId"])
    calls_after_first_compare = FakeLiteLLM.chat_calls
    second_compare = tasks.llm_compare.run(compare["runId"])

    assert first_ai["status"] == "完成"
    assert second_ai["alreadyCompleted"] is True
    assert first_compare["status"] == "完成"
    assert second_compare["alreadyCompleted"] is True
    assert calls_after_first_compare == 3
    assert FakeLiteLLM.chat_calls == calls_after_first_compare


def test_completed_export_worker_is_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    stored: list[tuple[str, str, int]] = []

    def fake_put(bucket: str, object_name: str, data: bytes, *, content_type: str):
        stored.append((bucket, object_name, len(data)))
        return f"minio://{bucket}/{object_name}"

    monkeypatch.setattr("libs.db.repository.object_storage.put_bytes", fake_put)
    task = {
        "id": "EXP-IDEMPOTENT-001",
        "projectId": "P-2026-HDCP-001",
        "nodeIds": [24],
        "exportType": "config-package",
        "status": "排队中",
        "progress": 0,
        "fileName": "idempotent-export.zip",
        "fileSize": 0,
        "createdAt": "2026-06-27 00:00:00",
    }
    repo.state["export_tasks"].insert(0, task)

    first = tasks.export_package.run(task["id"])
    logs_after_first = list(task.get("logs", []))
    second = tasks.export_package.run(task["id"])

    assert first["status"] == "可下载"
    assert second["alreadyCompleted"] is True
    assert len(stored) == 1
    assert stored[0][0] == "exports"
    assert task.get("logs") == logs_after_first


def test_export_artifact_uses_object_storage_when_available(monkeypatch) -> None:
    stored = {}
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")

    def fake_put(bucket: str, object_name: str, data: bytes, *, content_type: str):
        stored["bucket"] = bucket
        stored["objectName"] = object_name
        stored["contentType"] = content_type
        stored["size"] = len(data)
        stored["data"] = data
        return f"minio://{bucket}/{object_name}"

    def fake_get(url: str, *, file_name: str | None = None):
        return f"https://minio.local/{url.removeprefix('minio://')}"

    monkeypatch.setattr("libs.db.repository.object_storage.put_bytes", fake_put)
    monkeypatch.setattr("libs.db.repository.object_storage.presigned_get_url", fake_get)

    repo.state["export_tasks"].extend(
        [
            {
                "id": "EXP-NOT-READY-001",
                "projectId": "P-2026-HDCP-001",
                "exportType": "archive-package",
                "status": "排队中",
                "fileName": "pending.zip",
                "createdAt": "2026-06-27 09:00:00",
            },
            {
                "id": "EXP-EXPIRED-001",
                "projectId": "P-2026-HDCP-001",
                "exportType": "archive-package",
                "status": "已过期",
                "fileName": "expired.zip",
                "createdAt": "2026-06-26 09:00:00",
            },
        ]
    )
    assert_error(client.get("/exports/EXP-NOT-READY-001/download-url"), "EXPORT_TASK_NOT_READY")
    assert_error(client.get("/exports/EXP-EXPIRED-001/download-url"), "EXPORT_TASK_EXPIRED")

    seed_report_scope(status="复核完成")
    export = assert_ok(client.post("/exports", json={"projectId": "P-2026-HDCP-001", "fileName": "contract.zip"}))
    signed = assert_ok(client.get(f"/exports/{export['exportId']}/download-url"))

    assert export["task"]["downloadUrl"].startswith("minio://exports/")
    assert stored["bucket"] == "exports"
    assert stored["contentType"] == "application/zip"
    assert stored["size"] > 0
    assert signed["url"].startswith("https://minio.local/exports/")
    with zipfile.ZipFile(io.BytesIO(stored["data"])) as archive:
        names = set(archive.namelist())
        assert {
            "manifest.json",
            "task.json",
            "project.json",
            "reports.json",
            "documents.json",
            "archive_items.json",
            "evidence_links.json",
            "README.txt",
        }.issubset(names)
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["schemaVersion"] == "aicheck-export-v1"
        assert manifest["taskId"] == export["exportId"]
        assert manifest["projectId"] == "P-2026-HDCP-001"
        assert manifest["counts"]["documents"] >= 1
    task = repo.find_one("export_tasks", export["exportId"])
    assert task is not None
    assert [entry["message"] for entry in task["logs"]] == ["导出 worker 开始处理。", "导出任务完成。"]

    report_export = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/reports/RPT-20260625-001/export",
            json={"format": "pdf"},
        )
    )
    assert report_export["exportId"].startswith("EXP-RPT-")
    assert stored["contentType"] == "application/pdf"
    assert stored["data"].startswith(b"%PDF-1.4")
    assert b"AIcheck Export Report" in stored["data"]


def test_archive_and_evidence_packages_write_queryable_audit_artifacts(monkeypatch) -> None:
    seed_confirmed_node_24_evidence()
    stored: dict[str, bytes | str | int] = {}

    def fake_put(bucket: str, object_name: str, data: bytes, *, content_type: str):
        stored[object_name] = data
        return f"minio://{bucket}/{object_name}"

    monkeypatch.setattr("libs.db.repository.object_storage.put_bytes", fake_put)

    archive = assert_ok(client.get("/projects/P-2026-HDCP-001/archive/package"))
    evidence = assert_ok(client.get("/projects/P-2026-HDCP-001/archive/evidence-package?nodeId=24"))
    archive_task = repo.find_one("export_tasks", archive["exportId"])
    evidence_task = repo.find_one("export_tasks", evidence["exportId"])

    assert archive_task["status"] == "可下载"
    assert archive_task["progress"] == 100
    assert archive_task["manifestHash"] == archive["manifestHash"]
    assert archive_task["storageKey"] in stored
    assert evidence_task["status"] == "可下载"
    assert evidence_task["manifestHash"] == evidence["manifestHash"]
    assert evidence_task["storageKey"] in stored
    with zipfile.ZipFile(io.BytesIO(stored[archive_task["storageKey"]])) as archive_zip:
        assert {"manifest.json", "archive_items.json", "archive_items.csv", "reports.json", "export_tasks.json"}.issubset(
            set(archive_zip.namelist())
        )
        manifest = json.loads(archive_zip.read("manifest.json").decode("utf-8"))
        assert manifest["exportType"] == "archive-package"
        assert manifest["schemaVersion"] == "aicheck-archive-package-v2"
        assert manifest["manifestHash"] == archive["manifestHash"]
        assert manifest["counts"]["archiveItems"] >= 1
    with zipfile.ZipFile(io.BytesIO(stored[evidence_task["storageKey"]])) as evidence_zip:
        assert {"manifest.json", "evidence_links.json", "evidence_links.csv"}.issubset(
            set(evidence_zip.namelist())
        )
        manifest = json.loads(evidence_zip.read("manifest.json").decode("utf-8"))
        assert manifest["exportType"] == "evidence-package"
        assert manifest["schemaVersion"] == "aicheck-evidence-package-v2"
        assert manifest["manifestHash"] == evidence["manifestHash"]
        assert manifest["nodeId"] == 24
        assert manifest["counts"]["evidenceLinks"] >= 1
        evidence_rows = json.loads(evidence_zip.read("evidence_links.json").decode("utf-8"))
        assert all(row.get("documentVersionId") in set(manifest["documentVersionIds"]) for row in evidence_rows)


def test_evidence_package_requires_explicit_node_or_report_scope() -> None:
    assert_error(
        client.get("/projects/P-2026-HDCP-001/archive/evidence-package"),
        "VALIDATION_ERROR",
    )


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length=None):
        return [dict(item) for item in self.docs]


class FakeCollection:
    def __init__(self):
        self.docs = []
        self.session_calls = 0

    async def count_documents(self, query):
        return len(self.docs)

    async def delete_many(self, query, session=None):
        if session is not None:
            self.session_calls += 1
        self.docs.clear()

    async def insert_many(self, docs, session=None):
        if session is not None:
            self.session_calls += 1
        self.docs.extend([dict(item) for item in docs])

    def find(self, query):
        return FakeCursor(self.docs)

    async def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None

    async def replace_one(self, query, replacement, upsert=False, session=None):
        if session is not None:
            self.session_calls += 1
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = dict(replacement)
                return
        if upsert:
            self.docs.append(dict(replacement))


class FakeTransaction:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        self.client.transactions_started += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.client.transactions_closed += 1
        return False


class FakeSession:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        self.client.sessions_started += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.client.sessions_closed += 1
        return False

    def start_transaction(self):
        return FakeTransaction(self.client)


class FakeClient:
    def __init__(self):
        self.sessions_started = 0
        self.sessions_closed = 0
        self.transactions_started = 0
        self.transactions_closed = 0

    async def start_session(self):
        return FakeSession(self)


class FakeDatabase(dict):
    def __init__(self, *, with_client: bool = False):
        super().__init__()
        if with_client:
            self.client = FakeClient()

    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeCollection()
        return dict.__getitem__(self, key)


class FakeIndexCollection:
    def __init__(self):
        self.indexes = []

    async def create_index(self, keys, **kwargs):
        self.indexes.append((list(keys), dict(kwargs)))


class FakeIndexDatabase(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeIndexCollection()
        return dict.__getitem__(self, key)


class FakePostgresTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.transactions_started += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.connection.transactions_closed += 1
        return False


class FakePostgresCursor:
    def __init__(self, rows, *, rowcount: int | None = None):
        self.rows = rows
        self.rowcount = len(rows) if rowcount is None else rowcount

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakePostgresConnection:
    def __init__(self):
        self.state_rows: dict[tuple[str, str], dict] = {}
        self.singleton_rows: dict[str, dict] = {}
        self.idempotency_rows: dict[str, dict] = {}
        self.transactions_started = 0
        self.transactions_closed = 0
        self.commits = 0
        self.executed: list[str] = []

    def transaction(self):
        return FakePostgresTransaction(self)

    def commit(self):
        self.commits += 1

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        self.executed.append(normalized)
        if normalized.startswith("SELECT collection, object_id, payload, updated_at FROM aicheck_state"):
            # updated_at 是增量刷新的水位线来源（见 refresh_collections_incrementally）；
            # 假连接不给这一列的话，加载路径拿不到水位线，会退回整表重载。
            return FakePostgresCursor(
                [
                    (collection, object_id, payload, None)
                    for (collection, object_id), payload in sorted(self.state_rows.items())
                ]
            )
        if normalized.startswith("SELECT payload FROM aicheck_state"):
            collection, object_id = params[-2:]
            payload = self.state_rows.get((collection, object_id))
            return FakePostgresCursor([(payload,)] if payload is not None else [])
        if normalized.startswith("SELECT name, payload FROM aicheck_singletons"):
            return FakePostgresCursor(list(self.singleton_rows.items()))
        if normalized.startswith("SELECT payload FROM aicheck_singletons"):
            payload = self.singleton_rows.get(params[-1])
            return FakePostgresCursor([(payload,)] if payload is not None else [])
        if normalized.startswith("SELECT scope, payload FROM idempotency_records"):
            return FakePostgresCursor(list(self.idempotency_rows.items()))
        if normalized.startswith("SELECT payload FROM idempotency_records"):
            payload = self.idempotency_rows.get(params[-1])
            return FakePostgresCursor([(payload,)] if payload is not None else [])
        if normalized.startswith("DELETE FROM aicheck_state WHERE"):
            self.state_rows.pop((params[-2], params[-1]), None)
        elif normalized.startswith("DELETE FROM aicheck_singletons"):
            self.singleton_rows.clear()
        elif normalized.startswith("DELETE FROM idempotency_records"):
            self.idempotency_rows.clear()
        elif normalized.startswith("UPDATE aicheck_state SET payload"):
            payload, collection, object_id = params[0], params[-2], params[-1]
            self.state_rows[(collection, object_id)] = json.loads(payload)
        elif normalized.startswith("INSERT INTO aicheck_state"):
            collection, object_id, payload = params[-3:]
            self.state_rows[(collection, object_id)] = json.loads(payload)
            return FakePostgresCursor([], rowcount=1)
        elif normalized.startswith("INSERT INTO aicheck_singletons"):
            name, payload = params[-2:]
            self.singleton_rows[name] = json.loads(payload)
        elif normalized.startswith("INSERT INTO idempotency_records"):
            scope, payload = params[-2:]
            self.idempotency_rows[scope] = json.loads(payload)
        return FakePostgresCursor([], rowcount=0)


def test_postgres_indexes_include_jsonb_and_idempotency_specs() -> None:
    assert "aicheck_state" in POSTGRES_INDEXES
    assert {"name": "idx_aicheck_state_payload_gin", "fields": ["payload"], "type": "gin"} in POSTGRES_INDEXES["aicheck_state"]
    assert {
        "name": "idempotency_records_pkey",
        "fields": ["tenant_id", "scope"],
        "unique": True,
    } in POSTGRES_INDEXES["idempotency_records"]


def test_persistence_baseline_conflict_uses_dedicated_exception() -> None:
    import libs.db.repository as repository_module

    key = ("documents", "DOC-CONCURRENT")
    repo._persistence_baseline[key] = repo.canonical_persistence_payload(
        {"id": "DOC-CONCURRENT", "currentOcrStatus": "排队中"}
    )

    with pytest.raises(repository_module.ConcurrentPersistenceError):
        repo.assert_persistence_baseline(
            key,
            {"id": "DOC-CONCURRENT", "currentOcrStatus": "已识别"},
        )


def test_postgres_jsonb_state_table_covers_all_persisted_collections() -> None:
    persisted_collections = set(STATE_COLLECTIONS.values()) | set(SINGLETON_COLLECTIONS.values()) | {IDEMPOTENCY_COLLECTION}

    assert persisted_collections
    assert {"aicheck_state", "aicheck_singletons", "idempotency_records"} <= set(POSTGRES_INDEXES)


def test_postgres_state_round_trip_persists_planned_collections() -> None:
    database = FakePostgresConnection()
    repo.sync_postgres = database
    repo.postgres_dsn = "postgresql://fake"
    repo.postgres_enabled = True
    repo.state["projects"][0]["name"] = "Postgres round trip"
    repo.flush_to_sync_postgres()

    repo.reset()
    repo.sync_postgres = database
    repo.postgres_dsn = "postgresql://fake"
    repo.postgres_enabled = True
    repo.load_from_sync_postgres()

    assert repo.require_project("P-2026-HDCP-001")["name"] == "Postgres round trip"
    assert any(key[0] == "project_nodes" for key in database.state_rows)
    assert any(key[0] == "document_versions" for key in database.state_rows)
    assert any(key[0] == "node_bindings" for key in database.state_rows)
    assert "admin_config" in database.singleton_rows


def test_load_state_uses_postgres_when_database_url_is_configured(monkeypatch) -> None:
    from libs.db.repository import load_state

    database = FakePostgresConnection()
    repo.sync_postgres = database
    repo.postgres_dsn = "postgresql://fake"
    repo.postgres_enabled = True
    repo.state["projects"][0]["name"] = "Loaded from env postgres"
    repo.flush_to_sync_postgres()

    repo.reset()
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.postgres_enabled = False
    monkeypatch.setenv("AICHECK_DATABASE_URL", "postgresql://fake")

    def fake_configure_sync_postgres(dsn=None):
        repo.sync_postgres = database
        repo.postgres_dsn = dsn or "postgresql://fake"
        repo.postgres_enabled = True

    monkeypatch.setattr(repo, "configure_sync_postgres", fake_configure_sync_postgres)

    load_state()

    assert repo.require_project("P-2026-HDCP-001")["name"] == "Loaded from env postgres"
    assert repo.postgres_enabled is True


def test_postgres_flush_uses_transaction() -> None:
    database = FakePostgresConnection()
    repo.sync_postgres = database
    repo.postgres_dsn = "postgresql://fake"
    repo.postgres_enabled = True

    repo.flush_to_sync_postgres()

    assert database.transactions_started >= 1
    assert database.transactions_closed >= 1
    assert database.commits == 1
    assert database.state_rows
    assert database.singleton_rows


def test_postgres_flush_skips_pgvector_when_vectors_are_unchanged(monkeypatch) -> None:
    database = FakePostgresConnection()
    repo.sync_postgres = database
    repo.postgres_dsn = "postgresql://fake"
    repo.postgres_enabled = True
    repo.state["knowledge_vectors"] = [{"id": "KVI-TEST", "dimensions": 1024}]
    flushes: list[str] = []
    monkeypatch.setattr(repo, "flush_knowledge_vectors_to_pgvector", lambda: flushes.append("flush"))

    repo.flush_to_sync_postgres()
    assert flushes == ["flush"]
    flushes.clear()

    repo.state["audit_logs"].append({"id": "AUD-NON-VECTOR", "action": "audit only"})
    repo.flush_to_sync_postgres()

    assert flushes == []


def test_postgres_flush_syncs_pgvector_when_vector_payload_changes(monkeypatch) -> None:
    database = FakePostgresConnection()
    repo.sync_postgres = database
    repo.postgres_dsn = "postgresql://fake"
    repo.postgres_enabled = True
    repo.state["knowledge_vectors"] = [{"id": "KVI-TEST", "dimensions": 1024}]
    flushes: list[str] = []
    monkeypatch.setattr(repo, "flush_knowledge_vectors_to_pgvector", lambda: flushes.append("flush"))

    repo.flush_to_sync_postgres()
    flushes.clear()
    repo.state["knowledge_vectors"][0]["indexVersion"] = "V2"
    repo.flush_to_sync_postgres()

    assert flushes == ["flush"]


async def test_postgres_transaction_probe_reports_skipped_without_postgres(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_DATABASE_URL", raising=False)
    result = await run_transaction_probe(None)

    assert result["postgresEnabled"] is False
    assert result["transactionsConfigured"] is False
    assert result["transactionProbe"] == "skipped"
    assert result["reason"] == "postgres_not_configured"
