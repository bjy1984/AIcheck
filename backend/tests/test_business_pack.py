from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.business_pack import (
    business_pack_fixtures,
    build_ai_review_prompt,
    build_project_requirements,
    build_project_tree,
    list_business_packs,
    load_business_pack,
    matching_rule_for_node,
    validate_business_pack,
)
from libs.business_pack.boundary import scan_core_boundary
from libs.db.repository import repo


client = TestClient(app)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def setup_function() -> None:
    repo.reset()
    repo.mongo = None
    repo.sync_mongo = None


def assert_ok(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    return payload["data"]


def assert_business_error(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] != 0
    return payload


def test_business_pack_loader_validates_engineering_and_compliance_packs() -> None:
    packs = {item["id"]: item for item in list_business_packs()}

    assert set(packs) >= {"engineering_inspection_v1", "compliance_audit_v1", "device_inspection_v1"}
    assert packs["engineering_inspection_v1"]["nodeCount"] == 69
    assert packs["compliance_audit_v1"]["nodeCount"] == 8
    assert packs["device_inspection_v1"]["nodeCount"] == 6

    for pack_id in ["engineering_inspection_v1", "compliance_audit_v1", "device_inspection_v1"]:
        pack = load_business_pack(pack_id)
        validation = validate_business_pack(pack)
        assert validation["ok"], validation
        assert pack["snapshotHash"]
        assert build_project_tree("P-TST", pack)
        assert build_project_requirements(pack, project_id="P-TST")
        assert business_pack_fixtures(pack)["projects"]


def test_business_pack_api_and_compliance_project_generation() -> None:
    packs = assert_ok(client.get("/api/business-packs"))
    assert {item["id"] for item in packs} >= {
        "engineering_inspection_v1",
        "compliance_audit_v1",
        "device_inspection_v1",
    }

    validation = assert_ok(client.post("/api/business-packs/compliance_audit_v1/validate"))
    assert validation["validation"]["ok"] is True

    created = assert_ok(
        client.post(
            "/api/projects",
            json={
                "businessPackId": "compliance_audit_v1",
                "code": "P-CA-TEST-001",
                "name": "合规审计复用验证项目",
            },
            headers={"Idempotency-Key": "bp-compliance-project"},
        )
    )

    assert created["project"]["businessPackId"] == "compliance_audit_v1"
    assert created["createdNodeCount"] == 8
    assert created["createdRequirementCount"] == 14

    tree = assert_ok(client.get("/api/projects/P-CA-TEST-001/tree"))
    node_count = sum(len(group["nodes"]) for group in tree["groups"])
    assert node_count == 8
    assert tree["project"]["domainType"] == "compliance_audit"

    requirements = assert_ok(client.get("/api/projects/P-CA-TEST-001/nodes/1/requirements"))
    assert {item["materialTypeCode"] for item in requirements} == {"policy_document", "org_chart"}

    project_snapshot = assert_ok(client.get("/api/projects/P-CA-TEST-001/business-pack/snapshot"))
    assert project_snapshot["businessPackId"] == "compliance_audit_v1"
    assert project_snapshot["snapshot"]["id"] == "compliance_audit_v1"
    assert project_snapshot["businessPackSnapshotHash"] == project_snapshot["snapshot"]["snapshotHash"]

    device_created = assert_ok(
        client.post(
            "/api/projects",
            json={
                "businessPackId": "device_inspection_v1",
                "code": "P-DI-TEST-001",
                "name": "设备年检迁移验证项目",
            },
            headers={"Idempotency-Key": "bp-device-project"},
        )
    )
    assert device_created["project"]["businessPackId"] == "device_inspection_v1"
    assert device_created["createdNodeCount"] == 6
    assert device_created["createdRequirementCount"] == 7


def test_business_pack_snapshot_and_validate_all_apis() -> None:
    snapshot = assert_ok(client.get("/api/business-packs/engineering_inspection_v1/snapshot"))
    assert snapshot["id"] == "engineering_inspection_v1"
    assert snapshot["snapshotHash"]

    validation = assert_ok(client.post("/api/business-packs/validate-all"))
    assert validation["ok"] is True
    assert {item["summary"]["id"] for item in validation["results"]} >= {
        "engineering_inspection_v1",
        "compliance_audit_v1",
        "device_inspection_v1",
    }


def test_business_pack_fixtures_seed_non_engineering_review_workbench() -> None:
    compliance = assert_ok(client.get("/api/projects/P-CA-FIXTURE-001/review-workbench"))
    assert compliance["project"]["businessPackId"] == "compliance_audit_v1"
    assert compliance["businessPack"]["domainType"] == "compliance_audit"
    assert [item["id"] for item in compliance["findings"]] == ["FND-CA-FIXTURE-001"]

    device = assert_ok(client.get("/api/projects/P-DI-FIXTURE-001/review-workbench"))
    assert device["project"]["businessPackId"] == "device_inspection_v1"
    assert device["businessPack"]["domainType"] == "device_inspection"
    assert [item["id"] for item in device["findings"]] == ["FND-DI-FIXTURE-001"]

    device_tree = assert_ok(client.get("/api/projects/P-DI-FIXTURE-001/tree"))
    device_node_count = sum(len(group["nodes"]) for group in device_tree["groups"])
    assert device_node_count == 6


def test_ai_review_finding_requires_evidence_and_rule_refs() -> None:
    missing_refs = assert_business_error(
        client.post(
            "/api/review/findings",
            json={
                "projectId": "P-2026-HDCP-001",
                "nodeId": 24,
                "source": "ai",
                "title": "缺少引用的 AI 发现",
            },
            headers={"Idempotency-Key": "bp-finding-missing-refs"},
        )
    )
    assert missing_refs["data"]["reason"] == "VALIDATION_ERROR"

    created = assert_ok(
        client.post(
            "/api/review/findings",
            json={
                "projectId": "P-2026-HDCP-001",
                "nodeId": 24,
                "source": "ai",
                "findingType": "field_missing",
                "title": "证书编号缺失",
                "description": "AI 未识别到证书编号字段。",
                "evidenceLinkIds": ["EV-24-001"],
                "ruleRefs": [{"ruleSetId": "RULE-WELDER-202606", "ruleCode": "welder-qualification"}],
                "confidence": 0.82,
            },
            headers={"Idempotency-Key": "bp-finding-with-refs"},
        )
    )

    assert created["finding"]["businessPackId"] == "engineering_inspection_v1"
    assert created["finding"]["status"] == "draft"

    accepted = assert_ok(
        client.post(
            f"/api/review/findings/{created['finding']['id']}/accept",
            json={"result": "需补正"},
            headers={"Idempotency-Key": "bp-finding-accept"},
        )
    )
    assert accepted["finding"]["status"] == "accepted"
    assert accepted["opinion"]["ruleRefs"]


def test_ai_run_feedback_records_structured_human_review() -> None:
    feedback = assert_ok(
        client.post(
            "/api/ai/runs/AIRUN-24-20260625-01/feedback",
            json={
                "feedbackType": "edited",
                "accepted": True,
                "comment": "结论可采纳，补充证据说明。",
                "shouldEnterEvaluationSet": True,
            },
            headers={"Idempotency-Key": "bp-ai-feedback"},
        )
    )

    assert feedback["feedback"]["aiRunId"] == "AIRUN-24-20260625-01"
    assert feedback["feedback"]["shouldEnterEvaluationSet"] is True
    assert feedback["aiRun"]["status"] == "已人工确认"


def test_ai_prompt_uses_business_pack_context_without_hardcoded_industry_instruction() -> None:
    pack = load_business_pack("compliance_audit_v1")
    node = build_project_tree("P-CA", pack)[2]
    rule = matching_rule_for_node(pack, int(node["nodeId"]))
    prompt = build_ai_review_prompt(
        pack,
        node=node,
        rule=rule,
        fields=[{"fieldName": "制度编号", "fieldValue": "POL-001", "confidence": 0.91}],
    )

    combined = f"{prompt['system']}\n{prompt['user']}"
    assert "compliance_audit_v1" in combined
    assert "压力管道" not in combined
    assert "监检" not in combined


def test_business_pack_validation_script_and_create_script_dry_run() -> None:
    validate = subprocess.run(
        [sys.executable, "scripts/validate_business_packs.py", "--json"],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stderr
    assert '"ok": true' in validate.stdout

    create = subprocess.run(
        [
            sys.executable,
            "scripts/create_business_pack.py",
            "--id",
            "dry_run_pack_v1",
            "--template",
            "compliance_audit_v1",
            "--dry-run",
        ],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert create.returncode == 0, create.stderr
    assert "would copy" in create.stdout


def test_business_pack_core_boundary_has_no_industry_terms() -> None:
    assert scan_core_boundary() == []
