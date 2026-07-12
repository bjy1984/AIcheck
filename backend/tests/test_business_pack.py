from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
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


def test_engineering_pack_nodes_all_have_document_requirements() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    nodes = build_project_tree("P-ENG-REQ", pack)
    requirements = build_project_requirements(pack, project_id="P-ENG-REQ")
    evaluation_only_node_ids = {69}
    requirement_codes_by_node: dict[int, set[str]] = {}
    for requirement in requirements:
        requirement_codes_by_node.setdefault(int(requirement["nodeId"]), set()).add(requirement["materialTypeCode"])
        assert requirement.get("responsibleParty")
        assert requirement.get("applicability")

    missing_nodes = [
        int(node["nodeId"])
        for node in nodes
        if int(node["nodeId"]) not in evaluation_only_node_ids
        and int(node["nodeId"]) not in requirement_codes_by_node
    ]
    assert missing_nodes == []

    assert {"design_license", "design_document"} <= requirement_codes_by_node[1]
    assert {"quality_system_document", "ndt_report"} <= requirement_codes_by_node[37]
    assert {"ndt_report", "radiographic_film"} <= requirement_codes_by_node[65]
    assert 69 not in requirement_codes_by_node


def test_engineering_pack_has_fixed_standard_clause_bindings() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    bindings = pack["standardClauseBindings"]
    primary = [item for item in bindings if item["bindingRole"] == "primary"]
    supplemental = [item for item in bindings if item["bindingRole"] == "supplemental"]

    assert len(bindings) == 68
    assert len(primary) == 68
    assert len(supplemental) == 0
    assert {item["ruleId"] for item in primary} == {item["id"] for item in pack["ruleSets"]}
    assert all(item["verificationStatus"] == "source_verified" for item in bindings)
    assert all(item["lifecycleStatus"] == "published" for item in bindings)
    assert all(item["sourceLocatorId"] in {locator["locatorId"] for locator in item["locators"]} for item in bindings)
    assert all(item["knowledgeFileId"] and item["documentVersionId"] for item in bindings)

    r10 = next(item for item in bindings if item["sourceRuleId"] == "R10")
    assert r10["standardRef"] == "STD-TSG-31-2025"
    assert r10["clauseNo"] == "1.9(3)"

    invalid_pack = deepcopy(pack)
    candidate = invalid_pack["standardClauseBindings"][0]
    candidate["verificationStatus"] = "candidate"
    validation = validate_business_pack(invalid_pack)
    assert validation["ok"] is False
    assert any("must be source_verified before publication" in item for item in validation["errors"])


def test_engineering_pack_has_complete_standard_clause_packages_and_atomic_checks() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    packages = pack["standardClausePackages"]
    checks = pack["atomicChecks"]
    catalog = {item["id"] for item in pack["standardCatalog"]}

    assert len(packages) == 68
    assert len(checks) >= 136
    assert {item["sourceRuleId"] for item in packages} == {f"R{index:02d}" for index in range(1, 69)}
    assert all(len(item["atomicCheckIds"]) >= 2 for item in packages)
    assert all(item["decisionModel"]["ruleExecution"] == "deterministic_tools_only" for item in packages)
    assert all(
        clause["standardRef"] in catalog
        for package in packages
        for clause in package["professionalClauses"]
    )
    professional_clauses = [clause for package in packages for clause in package["professionalClauses"]]
    assert len(professional_clauses) == 100
    assert all(clause["knowledgeFileId"] and clause["documentVersionId"] for clause in professional_clauses)
    assert all(clause["locators"] for clause in professional_clauses)
    assert all(
        clause["sourceLocatorId"] in {locator["locatorId"] for locator in clause["locators"]}
        for clause in professional_clauses
    )
    assert all(
        locator["startPage"] <= locator["endPage"]
        for clause in professional_clauses
        for locator in clause["locators"]
    )

    conditional = {item["sourceRuleId"] for item in packages if item["applicability"]["type"] == "conditional"}
    assert {"R10", "R33", "R34", "R44", "R45", "R46", "R51", "R52", "R53", "R60", "R64", "R65"} <= conditional

    r10 = next(item for item in packages if item["sourceRuleId"] == "R10")
    assert "其他标准" in r10["applicability"]["expression"]
    assert any(item["clauseNo"] == "3.1.3.1" for item in r10["professionalClauses"])

    invalid_pack = deepcopy(pack)
    invalid_pack["standardClausePackages"][0]["atomicCheckIds"] = []
    validation = validate_business_pack(invalid_pack)
    assert validation["ok"] is False
    assert any("at least two atomic checks" in item for item in validation["errors"])

    invalid_locator_pack = deepcopy(pack)
    del invalid_locator_pack["standardClausePackages"][0]["professionalClauses"][0]["locators"]
    validation = validate_business_pack(invalid_locator_pack)
    assert validation["ok"] is False
    assert any("missing locator keys" in item for item in validation["errors"])


def test_node_standards_exposes_fixed_clause_page_locators() -> None:
    assert len(repo.state["standard_document_versions"]) == 29
    assert len(repo.state["standard_clause_packages_db"]) == 68
    assert len(repo.state["standard_clause_package_items"]) == 168
    assert len(repo.state["standard_clause_locators"]) == 216
    assert len(
        [item for item in repo.state["project_node_clause_packages"] if item["projectId"] == "P-2026-HDCP-001"]
    ) == 68

    standards = assert_ok(
        client.get("/api/projects/P-2026-HDCP-001/inspection/nodes/1/standards")
    )
    fixed = [item for item in standards if item.get("fixedBinding")]

    assert fixed
    assert fixed[0]["referenceRole"] == "primary"
    assert fixed[0]["sourcePage"] == 27
    assert fixed[0]["previewUrl"].endswith("#page=27")
    assert any(item["referenceRole"] == "professional" for item in fixed)
    assert all(item["knowledgeFileId"] and item["documentVersionId"] for item in fixed)
    assert all(item["sourceLocatorId"] in {locator["locatorId"] for locator in item["locators"]} for item in fixed)

    package_detail = assert_ok(client.get("/api/business-packs/engineering_inspection_v1"))
    assert len(package_detail["standardClausePackages"]) == 68
    assert len(package_detail["standardCatalog"]) == 29

    node_binding = next(
        item
        for item in repo.state["project_node_clause_packages"]
        if item["projectId"] == "P-2026-HDCP-001" and item["nodeId"] == 1
    )
    stored_package = next(
        item for item in repo.state["standard_clause_packages_db"] if item["id"] == node_binding["packageId"]
    )
    stored_package["compiledPayload"]["clauses"][1]["purpose"] = "DATABASE_ONLY_PREVIEW_MARKER"
    database_backed = assert_ok(
        client.get("/api/projects/P-2026-HDCP-001/inspection/nodes/1/standards")
    )
    assert any(item.get("title") == "DATABASE_ONLY_PREVIEW_MARKER" for item in database_backed)


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
                "type": "长输压力管道",
                "region": "华东",
                "ownerOrgName": "华东管网建设公司",
                "contractorOrgName": "中石化安装有限公司",
                "inspectionOrgName": "省特检院一部",
                "memberUserIds": {
                    "owner": "USER-OWNER-001",
                    "contractor": "USER-CONTRACTOR-001",
                    "inspection": "USER-INSPECTION-001",
                },
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
    first_node = tree["groups"][0]["nodes"][0]
    assert first_node["requirementsSummary"]["hasRequirementDetails"] is True
    assert first_node["requirementsSummary"]["requiredCount"] == 2
    assert first_node["requirementsSummary"]["satisfiedCount"] == 0
    assert {item["materialTypeCode"] for item in first_node["requirementsSummary"]["missingRequirements"]} == {
        "policy_document",
        "org_chart",
    }

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
                "type": "公用压力管道",
                "region": "华东",
                "ownerOrgName": "华东管网建设公司",
                "contractorOrgName": "中石化安装有限公司",
                "inspectionOrgName": "省特检院一部",
                "memberUserIds": {
                    "owner": "USER-OWNER-001",
                    "contractor": "USER-CONTRACTOR-001",
                    "inspection": "USER-INSPECTION-001",
                },
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
    assert validation["scorecard"]["targetScore"] == 100
    assert validation["scorecard"]["score"] == 100
    assert validation["scorecard"]["ok"] is True
    assert validation["scorecard"]["blockers"] == []
    assert {"catalog", "core-boundary", "fixtures", "delivery"} <= {
        item["name"] for item in validation["scorecard"]["sections"]
    }
    assert all(item["score"] == 100 for item in validation["scorecard"]["packs"])
    assert {item["packId"] for item in validation["scorecard"]["packs"]} >= {
        "engineering_inspection_v1",
        "compliance_audit_v1",
        "device_inspection_v1",
    }
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

    evidence_link_id = "NEL-BP-CONFIRMED-24"
    repo.state["node_evidence_links"].append(
        {
            "id": evidence_link_id,
            "projectId": "P-2026-HDCP-001",
            "nodeId": 24,
            "documentId": "DOC-20260625-001",
            "documentVersionId": "DV-20260625-001-V2",
            "fileName": "焊工资格证-王建国.pdf",
            "pageNo": 1,
            "bbox": [10, 20, 180, 42],
            "quotedText": "证书编号 TS6J-2024-03158",
            "supportStatus": "supported",
            "manualStatus": "confirmed",
            "confidence": 0.96,
            "createdAt": "2026-07-08 00:00:00",
        }
    )

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
                "evidenceLinkIds": [evidence_link_id],
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
