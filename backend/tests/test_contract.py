from __future__ import annotations

import io
import importlib.util
import json
import inspect
import sys
import zipfile
from argparse import Namespace
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from libs.db.indexes import POSTGRES_INDEXES
from libs.db.postgres import bootstrap_local_roles_if_configured, run_transaction_probe
from apps.api.main import app
from libs.db.repository import IDEMPOTENCY_COLLECTION, SINGLETON_COLLECTIONS, STATE_COLLECTIONS, repo


client = TestClient(app)


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None


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


def test_response_envelope_and_api_prefix_compatibility() -> None:
    data = assert_ok(client.get("/workbench/projects?role=inspection"))
    prefixed = assert_ok(client.get("/api/workbench/projects?role=inspection"))

    assert data[0]["id"] == "P-2026-HDCP-001"
    assert prefixed[0]["currentNodeId"] == 24
    assert prefixed[0]["riskLevel"] == "高"


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


def test_local_role_bootstrap_creates_login_accounts_without_postgres(monkeypatch) -> None:
    passwords = {
        "admin": "Local!2026-SystemZ",
        "inspection": "Local!2026-InspectZ",
        "contractor": "Local!2026-BuildZ",
        "ndt": "Local!2026-TestZ",
        "owner": "Local!2026-ViewZ",
    }
    monkeypatch.setenv("AICHECK_BOOTSTRAP_LOCAL_ROLES", "true")
    for role, password in passwords.items():
        monkeypatch.setenv(f"AICHECK_BOOTSTRAP_PASSWORD_{role.upper()}", password)

    bootstrap_local_roles_if_configured()

    assert {user["username"] for user in repo.state["users"]} >= set(passwords)
    assert {member["role"] for member in repo.state["project_members"]} >= set(passwords)
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
    from apps.ocr_service.profiles import profile_for

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


def test_visual_seal_candidate_enriched_from_ocr_fragments_can_satisfy_required_seal() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.profiles import profile_for

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
                {"text": "压力管道", "confidence": 0.99, "bbox": [4378, 2466, 4730, 2569]},
                {"text": "杨道红", "confidence": 0.99, "bbox": [4428, 2540, 4685, 2626]},
                {"text": "TS1810648-2021", "confidence": 0.99, "bbox": [4362, 2605, 4758, 2688]},
                {"text": "2017年8月31日", "confidence": 0.99, "bbox": [4361, 2660, 4768, 2753]},
            ],
            "fields": [
                {"fieldCode": code, "fieldName": code, "fieldValue": code, "confidence": 0.9, "bbox": [1, 1, 2, 2]}
                for code in required_fields
            ],
            "tables": [
                {
                    "tableId": "grid",
                    "businessSchema": "piping_characteristic_table_v1",
                    "sourceEngine": "opencv_grid_text_aligned",
                    "bbox": [1, 1, 10, 10],
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
    assert "visual_candidate_only" not in seal["qualityFlags"]
    assert "SEAL_TEXT_LOW_CONFIDENCE" not in fused["quality"]["reasons"]
    assert fused["quality"]["matchedSealTypes"] == ["design_license_seal"]
    assert fused["quality"]["missingExpectedSealTypes"] == []
    assert fused["quality"]["sealCompleteness"] == 1.0
    assert fused["quality"]["status"] == "auto_usable"


def test_agentdesign_seal_payload_normalizes_to_readable_formal_seal() -> None:
    from apps.ocr_service.engines import normalize_agentdesign_seal_result
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.profiles import profile_for

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
    from apps.ocr_service.profiles import profile_for

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
    from apps.ocr_service.profiles import profile_for
    from apps.ocr_service.service import align_piping_text_table_with_grid

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
    from apps.ocr_service.profiles import profile_for
    from apps.ocr_service.service import enrich_parse_result

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
    assert result["tables"][0]["tableId"] == "piping_characteristic_table_1"
    assert result["tables"][0]["normalizedRows"][0]["pipeNo"] == "PL8301"
    assert "HEURISTIC_TABLE_INFERRED" in {item["code"] for item in result["diagnostics"] if isinstance(item, dict)}
    assert {"company_name", "project_name", "document_title", "drawing_no", "design_phase", "pipe_no"} <= field_codes


def test_piping_profile_maps_formal_table_rows_to_business_fields() -> None:
    from apps.ocr_service.profiles import profile_for
    from apps.ocr_service.service import enrich_parse_result

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
    monkeypatch.setattr("apps.ocr_service.engines.subprocess.run", fake_run)

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


def test_ocr_routing_keeps_text_ocr_on_original_by_default() -> None:
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

    assert routed[0]["variantId"] == "page_1_original"


def test_ocr_preprocess_variant_cache_round_trips(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.preprocess import load_cached_variants, save_cached_variants, variant_cache_dir

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
    from apps.ocr_service.profiles import profile_for

    requested = requested_variant_names(
        profile_for("piping_characteristic_list_v1"),
        [{"pageNo": 1, "quality": {"hasTableCandidate": True, "hasSealCandidate": True, "isLowQuality": False}}],
    )

    assert requested[:3] == ["original", "table_line_enhanced", "seal_color_mask"]
    assert len(requested) <= 4


def test_ocr_service_result_cache_skips_repeated_engine_run(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.profiles import profile_for
    from apps.ocr_service.service import OcrService

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
        options={},
    )
    second = service.parse_with_local_engines(
        source,
        storage_key=str(source),
        file_name="sample.png",
        profile=profile,
        document_version_id="docv_2",
        business_pack_id="engineering_inspection_v1",
        options={},
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
    from apps.ocr_service.profiles import profile_for
    from apps.ocr_service.service import OcrService

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
        options={},
    )
    second = service.parse_with_local_engines(
        source,
        storage_key=str(source),
        file_name="sample.png",
        profile=second_profile,
        document_version_id="docv_2",
        business_pack_id="engineering_inspection_v1",
        options={},
    )

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert engine.calls == 1
    assert first.get("resultCacheHit") is None
    assert second.get("resultCacheHit") is None
    assert second["engineRuns"][0]["engineCacheHit"] is True
    assert second["documentVersionId"] == "docv_2"


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


def test_ocr_fusion_quality_gate_marks_missing_required_data_for_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.profiles import profile_for

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
    from apps.ocr_service.profiles import profile_for

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


def test_ocr_fusion_visual_seal_only_requires_human_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.profiles import profile_for

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
    from apps.ocr_service.profiles import profile_for

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
                },
                {
                    "fieldCode": "report_no",
                    "fieldValue": "RT-2026-00I",
                    "confidence": 0.55,
                    "sourceEngine": "low_confidence_candidate",
                    "bbox": [0, 0, 10, 10],
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


def test_ocr_fusion_low_confidence_required_field_requires_human_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.profiles import profile_for

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


def test_ocr_fusion_missing_required_evidence_requires_human_review() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.profiles import profile_for

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
    from apps.ocr_service.profiles import profile_for

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
    result = fuse_parse_result(
        {
            "status": "success",
            "fields": complete_fields,
            "tables": [
                {
                    "tableId": "piping_characteristic_table_1",
                    "structureConfidence": 0.86,
                    "bbox": [0, 0, 10, 10],
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
    from apps.ocr_service.profiles import profile_for
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
        "inspection": "/workbench/inspection",
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


def test_global_audit_covers_mutations_without_explicit_audit_log() -> None:
    project_id = "P-2026-HDCP-001"
    before = len(repo.state["audit_logs"])

    run = assert_ok(client.post(f"/projects/{project_id}/inspection/nodes/24/ai-recheck"))

    assert "runId" in run
    assert len(repo.state["audit_logs"]) == before + 1
    audit = repo.state["audit_logs"][0]
    assert audit["objectType"] == "ApiMutation"
    assert audit["objectId"] == f"/projects/{project_id}/inspection/nodes/24/ai-recheck"
    assert audit["operationId"].startswith("OP-")


def test_global_audit_does_not_duplicate_explicit_audit_log() -> None:
    project_id = "P-2026-HDCP-001"
    before = len(repo.state["audit_logs"])

    result = assert_ok(client.patch(f"/projects/{project_id}", json={"name": "审计不重复"}))

    assert result["auditLogId"]
    assert len(repo.state["audit_logs"]) == before + 1


def test_withdraw_submission_items_enforces_batch_and_locked_state() -> None:
    project_id = "P-2026-HDCP-001"
    payload = {
        "nodeId": 16,
        "nodeIds": [16],
        "bindingIds": ["BIND-16-001"],
        "submitterComment": "withdraw state machine test",
    }
    submission = assert_ok(client.post(f"/projects/{project_id}/submissions", json=payload))
    submission_id = submission["submissionId"]

    assert_error(
        client.post(
            f"/projects/{project_id}/submissions/SUB-MISSING/withdraw-items",
            json={"bindingIds": ["BIND-16-001"]},
        ),
        "NOT_FOUND",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/submissions/{submission_id}/withdraw-items",
            json={"bindingIds": ["BIND-24-001"]},
        ),
        "CONFLICT",
    )

    binding = next(item for item in repo.state["bindings"] if item["id"] == "BIND-16-001")
    binding["bindingStatus"] = "已通过"
    assert_error(
        client.post(
            f"/projects/{project_id}/submissions/{submission_id}/withdraw-items",
            json={"bindingIds": ["BIND-16-001"]},
        ),
        "WITHDRAW_LOCKED",
    )

    binding["bindingStatus"] = "已提交"
    withdrawn = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions/{submission_id}/withdraw-items",
            json={"bindingIds": ["BIND-16-001"], "reason": "资料版本修正"},
        )
    )
    stored_submission = next(item for item in repo.state["submissions"] if item["submissionId"] == submission_id)

    assert withdrawn["nextStatus"] == "部分提交"
    assert binding["bindingStatus"] == "草稿挂载"
    assert stored_submission["withdrawnBindingIds"] == ["BIND-16-001"]
    assert stored_submission["withdrawal"]["bindingCount"] == 1


def test_submit_rectification_updates_pending_item_and_enforces_scope() -> None:
    project_id = "P-2026-HDCP-001"
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
    assert rectification["status"] == "已反馈"
    assert rectification["bindingIds"] == ["BIND-16-001"]
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


def test_document_mutations_are_idempotent_and_project_etag_guarded() -> None:
    project_id = "P-2026-HDCP-001"
    project = assert_ok(client.get(f"/projects/{project_id}"))["project"]

    upload = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": [{"fileName": "幂等上传.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
            headers={"If-Match": project["etag"], "Idempotency-Key": "upload-session-once"},
        )
    )
    completed = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={"completedFiles": []},
            headers={"If-Match": project["etag"], "Idempotency-Key": "upload-complete-once"},
        )
    )
    completed_replay = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session/{upload['uploadSessionId']}/complete",
            json={"completedFiles": []},
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
            {"filmNo": "RT-IMP-001", "weldNo": "W-IMP-001", "method": "RT"},
            {"filmNo": "UT-IMP-002", "weldNo": "W-IMP-002", "method": "UT"},
        ],
    }
    film_import = assert_ok(client.post(f"/projects/{project_id}/ndt/films/import", json=film_payload, headers=film_import_headers))
    film_import_replay = assert_ok(client.post(f"/projects/{project_id}/ndt/films/import", json=film_payload, headers=film_import_headers))
    assert film_import["imported"] == 2
    assert [item["id"] for item in film_import["films"]] == [item["id"] for item in film_import_replay["films"]]
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
            {"recordNo": "REC-IMP-001", "weldNo": "W-IMP-001", "method": "RT"},
            {"recordNo": "REC-IMP-002", "weldNo": "W-IMP-002", "method": "UT"},
        ],
    }
    record_import = assert_ok(client.post(f"/projects/{project_id}/ndt/records/import", json=record_payload, headers=record_import_headers))
    record_import_replay = assert_ok(client.post(f"/projects/{project_id}/ndt/records/import", json=record_payload, headers=record_import_headers))
    assert record_import["imported"] == 2
    assert [item["id"] for item in record_import["records"]] == [item["id"] for item in record_import_replay["records"]]
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

    rule = next(item for item in assert_ok(client.get("/rules/versions"))["items"] if item["id"] == "RULE-NDT-202606")
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
        ("PUT", "/api/admin/config-items/todo-rule/TR-001", "admin:config"),
        ("PATCH", "/api/knowledge/config", "knowledge:manage"),
        ("PUT", "/api/knowledge/config", "knowledge:manage"),
        ("POST", "/api/llm/compare", "llm:compare"),
    ]

    for method, path, expected in cases:
        assert required_action_for_request(method, path) == expected
    assert required_action_for_request("GET", "/api/admin/config-overview") is None


def test_all_non_public_mutating_routes_have_inferred_action_codes() -> None:
    from libs.security.actions import MUTATING_METHODS, required_action_for_request

    public_mutations = {
        ("POST", "/mock/user/login"),
        ("POST", "/api/mock/user/login"),
        ("POST", "/auth/login"),
        ("POST", "/api/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/api/auth/logout"),
    }
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        for method in methods:
            if (method, path) in public_mutations:
                continue
            if required_action_for_request(method, path) is None:
                missing.append(f"{method} {path}")

    assert missing == []


def test_project_mutating_routes_are_archived_readonly_guarded() -> None:
    from libs.security.actions import MUTATING_METHODS

    delegated_guard_routes = {
        ("POST", "/projects/{project_id}/inspection/nodes/{node_id}/attachments"),
        ("POST", "/projects/{project_id}/inspection/nodes/{node_id}/file-bindings"),
        ("POST", "/api/projects/{project_id}/inspection/nodes/{node_id}/attachments"),
        ("POST", "/api/projects/{project_id}/inspection/nodes/{node_id}/file-bindings"),
    }
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if "{project_id}" not in path:
            continue
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        for method in methods:
            if (method, path) in delegated_guard_routes:
                continue
            endpoint = getattr(route, "endpoint", None)
            source = inspect.getsource(endpoint) if endpoint is not None else ""
            if "mutation_guard(" not in source:
                missing.append(f"{method} {path}")

    assert missing == []


def test_all_non_public_mutating_routes_are_audit_logged() -> None:
    from apps.api.main import audit_scope
    from libs.security.actions import MUTATING_METHODS

    unaudited_public_routes = {
        ("POST", "/mock/user/login"),
        ("POST", "/api/mock/user/login"),
        ("POST", "/auth/login"),
        ("POST", "/api/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/api/auth/logout"),
    }
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        for method in methods:
            if (method, path) in unaudited_public_routes:
                continue
            assert audit_scope(type("Req", (), {"method": method, "url": type("Url", (), {"path": path})()})()) is not None
            endpoint = getattr(route, "endpoint", None)
            source = inspect.getsource(endpoint) if endpoint is not None else ""
            has_explicit_audit = "mutation_result" in source or "add_audit" in source or "auditLogId" in source
            if not has_explicit_audit and audit_scope(type("Req", (), {"method": method, "url": type("Url", (), {"path": path})()})()) is None:
                missing.append(f"{method} {path}")

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

    ndt_submit = assert_ok(
        client.post(
            f"/api/projects/{project_id}/ndt/submissions",
            json={"nodeId": 40, "reportIds": ["NDT-RPT-001"], "filmIds": ["FILM-RT-001"]},
            headers=ndt_headers,
        )
    )
    admin_publish = assert_ok(
        client.post(
            "/api/admin/config-overview/publish",
            json={"scope": "all"},
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

    assert contractor_submit["nextStatus"] == "AI 预审中"
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
            f"/api/projects/{project_id}/documents/DOC-20260625-003/withdraw",
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
    assert_error(
        client.get("/api/reasoning/logs/AIRUN-SCOPE-40", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/llm/compare-runs/CMP-SCOPE-40", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/ndt/films/FILM-RT-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/ndt/reports/NDT-RPT-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/ndt/inspection-feedback/NDT-FB-001", headers=contractor_headers),
        "FORBIDDEN",
    )
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
    reports = assert_ok(client.get(f"/api/projects/{project_id}/reports", headers=contractor_headers))
    todos = assert_ok(client.get(f"/api/todos?projectId={project_id}", headers=contractor_headers))
    messages = assert_ok(client.get(f"/api/messages?projectId={project_id}", headers=contractor_headers))
    search_results = assert_ok(client.get(f"/api/search?projectId={project_id}&keyword=RT", headers=contractor_headers))
    knowledge_files = assert_ok(client.get(f"/api/knowledge/project-files?projectId={project_id}", headers=contractor_headers))
    knowledge_tasks = assert_ok(client.get("/api/knowledge/tasks", headers=contractor_headers))
    reasoning = assert_ok(client.get(f"/api/reasoning/logs?projectId={project_id}", headers=contractor_headers))
    compare_runs = assert_ok(client.get(f"/api/llm/compare-runs?projectId={project_id}", headers=contractor_headers))
    ndt_summary = assert_ok(client.get(f"/api/projects/{project_id}/ndt/summary", headers=contractor_headers))
    ndt_films = assert_ok(client.get(f"/api/projects/{project_id}/ndt/films", headers=contractor_headers))
    ndt_records = assert_ok(client.get(f"/api/projects/{project_id}/ndt/records", headers=contractor_headers))
    ndt_reports = assert_ok(client.get(f"/api/projects/{project_id}/ndt/reports", headers=contractor_headers))
    ndt_feedback = assert_ok(client.get(f"/api/projects/{project_id}/ndt/inspection-feedback", headers=contractor_headers))
    ndt_visible_records = assert_ok(client.get(f"/api/projects/{project_id}/ndt/records", headers=ndt_headers))
    archive_package = assert_ok(client.get(f"/api/projects/{project_id}/archive/package", headers=contractor_headers))
    owner_reports = assert_ok(client.get(f"/api/projects/{project_id}/owner/reports", headers=owner_headers))

    assert own_node["node"]["nodeId"] == 16
    assert own_document["document"]["id"] == "DOC-20260625-003"
    assert "metrics" in admin_overview
    assert {item["userId"] for item in me["projectAuthorizations"]} == {"USER-CONTRACTOR-001"}
    assert {item["id"] for item in workbench_projects} == {project_id}
    assert {item["id"] for item in project_page["items"]} == {project_id}
    assert not any(item["id"] in {"TODO-SCOPE-40", "TODO-SCOPE-RPT"} for item in summary["todos"])
    visible_node_ids = {node["nodeId"] for group in tree["groups"] for node in group["nodes"]}
    assert visible_node_ids.issubset({16, 24, 25})
    assert "DOC-20260625-004" not in {item["id"] for item in documents["items"]}
    assert "BIND-40-001" not in {item["id"] for item in bindings}
    assert all(set(report.get("nodeIds") or []).issubset({16, 24, 25}) for report in reports)
    assert "TODO-SCOPE-40" not in {item["id"] for item in todos["items"]}
    assert "TODO-SCOPE-RPT" not in {item["id"] for item in todos["items"]}
    assert "MSG-SCOPE-40" not in {item["id"] for item in messages["items"]}
    assert "DOC-20260625-004" not in {item["id"] for item in search_results["items"]}
    assert "KF-DOC-20260625-004" not in {item["id"] for item in knowledge_files["items"]}
    assert "KT-20260626-001" not in {item["id"] for item in knowledge_tasks["items"]}
    assert "AIRUN-SCOPE-40" not in {item["id"] for item in reasoning["items"]}
    assert "CMP-SCOPE-40" not in {item["runId"] for item in compare_runs["items"]}
    assert ndt_summary == {"filmCount": 0, "recordCount": 0, "reportCount": 0, "feedbackCount": 0}
    assert ndt_films["items"] == []
    assert ndt_records["items"] == []
    assert ndt_reports["items"] == []
    assert ndt_feedback["items"] == []
    assert any(item["id"] == "NDT-REC-001" for item in ndt_visible_records["items"])
    assert archive_package["itemCount"] == 2
    assert any(report["id"] == "RPT-20260625-001" for report in owner_reports)


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


def test_knowledge_retrieval_query_router_supports_exact_clause_and_pageindex_routes() -> None:
    exact = assert_ok(
        client.post(
            "/knowledge/retrieval-test",
            json={"question": "请解释第5.3.2条质量证明文件要求", "topK": 3},
        )
    )
    exact_trace = exact["retrievalTrace"]
    assert exact_trace["selectedRoute"] == "exact_clause_lookup"
    assert exact_trace["routerSignals"]["exactClauseRefs"] == ["5.3.2"]
    assert exact_trace["selectedClauses"][0]["clauseNo"] == "5.3.2"
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
    assert pageindex_trace["pageIndexTree"]["selectedNodes"][0]["pageIndexNodeId"] == "PIN-TSG-D7005-7"
    assert "TSG-D7005-7.4" in pageindex_trace["pageIndexTree"]["linkedClauseIds"]
    assert pageindex_trace["selectedClauses"][0]["pageIndexNodeIds"] == ["PIN-TSG-D7005-7"]

    nodes = assert_ok(client.get("/knowledge/page-index-nodes", params={"keyword": "无损检测"}))
    assert nodes["items"]
    assert nodes["items"][0]["pageIndexNodeId"] == "PIN-TSG-D7005-7"

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
        "files": [{"fileName": "RT-IDEMPOTENT.pdf", "fileSize": 2048, "fileType": "application/pdf"}],
    }
    upload_headers = {"If-Match": project["etag"], "Idempotency-Key": "ndt-report-upload-once"}
    upload = assert_ok(client.post(f"/projects/{project_id}/ndt/reports/upload-session", json=upload_payload, headers=upload_headers))
    upload_replay = assert_ok(client.post(f"/projects/{project_id}/ndt/reports/upload-session", json=upload_payload, headers=upload_headers))
    assert upload_replay["uploadSessionId"] == upload["uploadSessionId"]
    assert upload_replay["uploadUrls"][0]["documentId"] == upload["uploadUrls"][0]["documentId"]
    assert len(repo.state["ndt_reports"]) == report_count + 1
    assert len(repo.state["documents"]) == document_count + 1


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
    assert submission["nextStatus"] == "AI 预审中"


def test_ndt_submit_updates_reports_films_and_traceable_snapshot() -> None:
    project_id = "P-2026-HDCP-001"
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
    assert export["task"]["fileName"] == "后台配置包-all-20260626.zip"

    publish = assert_ok(client.post("/admin/config-overview/publish", json={"scope": "all"}))
    assert publish["version"].startswith("config-v")
    assert any("权限矩阵已同步到工作台动作权限" in impact["trace"] for impact in publish["impacts"])

    messages = assert_ok(client.get(f"/messages?projectId={project_id}"))
    todos = assert_ok(client.get(f"/todos?projectId={project_id}"))
    assert any("后台配置已发布：config-v" in item["title"] for item in messages["items"])
    assert any(item["title"] == "字段映射配置发布影响" for item in todos["items"])

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
    created = assert_ok(
        client.post(
            "/admin/projects",
            json={
                "code": "P-E2E-001",
                "name": "E2E 立项项目",
                "memberUserIds": {
                    "owner": "USER-OWNER-001",
                    "contractor": "USER-CONTRACTOR-001",
                    "ndt": "USER-NDT-001",
                    "inspection": "USER-INSPECTION-001",
                },
            },
            headers={"Idempotency-Key": "admin-project-create-once"},
        )
    )
    replayed = assert_ok(
        client.post(
            "/admin/projects",
            json={
                "code": "P-E2E-001",
                "name": "E2E 立项项目",
                "memberUserIds": {
                    "owner": "USER-OWNER-001",
                    "contractor": "USER-CONTRACTOR-001",
                    "ndt": "USER-NDT-001",
                    "inspection": "USER-INSPECTION-001",
                },
            },
            headers={"Idempotency-Key": "admin-project-create-once"},
        )
    )
    assert len(created["detail"]["members"]) == 4
    assert replayed["project"]["id"] == created["project"]["id"]
    assert replayed["auditLogId"] == created["auditLogId"]
    assert len([item for item in repo.state["projects"] if item["id"] == "P-E2E-001"]) == 1
    assert len([item for item in repo.state["project_members"] if item["projectId"] == "P-E2E-001"]) == 4

    compatibility_created = assert_ok(
        client.post(
            "/projects",
            json={
                "code": "P-E2E-COMPAT-001",
                "name": "E2E 兼容立项项目",
                "memberUserIds": {
                    "owner": "USER-OWNER-001",
                    "contractor": "USER-CONTRACTOR-001",
                    "ndt": "USER-NDT-001",
                    "inspection": "USER-INSPECTION-001",
                },
            },
            headers={"Idempotency-Key": "compat-project-create-once"},
        )
    )
    compatibility_replayed = assert_ok(
        client.post(
            "/projects",
            json={
                "code": "P-E2E-COMPAT-001",
                "name": "E2E 兼容立项项目",
                "memberUserIds": {
                    "owner": "USER-OWNER-001",
                    "contractor": "USER-CONTRACTOR-001",
                    "ndt": "USER-NDT-001",
                    "inspection": "USER-INSPECTION-001",
                },
            },
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
            json={
                "code": "P-E2E-COMPAT-001",
                "name": "E2E 兼容立项项目-不同请求体",
                "memberUserIds": {
                    "owner": "USER-OWNER-001",
                    "contractor": "USER-CONTRACTOR-001",
                    "ndt": "USER-NDT-001",
                    "inspection": "USER-INSPECTION-001",
                },
            },
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


def test_upload_complete_inline_ocr_writes_fields_and_slice_task(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")

    def fake_parse(storage_key: str, *, file_name: str | None = None):
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "证书编号 TS6J-2026-0001", "confidence": 0.91}],
            "fields": [{"fieldName": "证书编号", "fieldValue": "TS6J-2026-0001", "confidence": 0.94}],
            "seals": [],
            "diagnostics": [],
        }

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)
    upload = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/documents/upload-session",
            json={"files": [{"fileName": "OCR-inline.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
        )
    )
    created = upload["uploadUrls"][0]
    complete = assert_ok(
        client.post(f"/projects/P-2026-HDCP-001/documents/upload-session/{upload['uploadSessionId']}/complete")
    )

    assert complete["queuedTasks"][0]["mode"] == "inline"
    fields = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{created['documentId']}/ocr-fields"))
    assert any(field["fieldValue"] == "TS6J-2026-0001" for field in fields)

    knowledge_file_id = f"KF-{created['documentId']}"
    slice_task = next(
        item for item in repo.state["knowledge_tasks"] if item["taskType"] == "slice" and item["targetId"] == knowledge_file_id
    )
    assert slice_task["status"] == "排队中"

    sliced = tasks.slice_knowledge.run(knowledge_file_id)
    chunks = assert_ok(client.get(f"/knowledge/files/{knowledge_file_id}/chunks"))
    assert sliced["chunkCount"] == chunks["total"]
    assert chunks["items"][0]["text"].startswith("证书编号")


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


def test_worker_uses_ocr_http_client_when_configured(monkeypatch) -> None:
    from apps.worker import tasks

    class FakeOcrClient:
        enabled = True

        def parse_sync(self, storage_key: str, *, file_name: str | None = None):
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


def test_worker_prefers_ocr_job_api_when_available(monkeypatch) -> None:
    from apps.worker import tasks

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

        def parse_sync(self, storage_key: str, *, file_name: str | None = None):
            raise AssertionError("parse_sync should not be used when job API is available")

    monkeypatch.setattr(tasks, "OcrClient", lambda: FakeOcrClient())
    doc, version = repo.create_document("P-2026-HDCP-001", "HTTP-OCR-job.pdf", "pdf")
    result = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])

    assert FakeOcrClient.called_job_api is True
    assert result["parseResultId"] == "PARSE-REMOTE-001"
    assert repo.state["ocr_jobs"][0]["jobId"] == "OCRJOB-REMOTE-001"
    assert repo.state["ocr_parse_results"][0]["parseResultId"] == "PARSE-REMOTE-001"


def test_failed_knowledge_task_retry_dispatches_worker_and_is_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")
    monkeypatch.delenv("AICHECK_OCR_BASE_URL", raising=False)

    def fake_parse(storage_key: str, *, file_name: str | None = None):
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

    class FailingOcrClient:
        enabled = True

        def parse_sync(self, storage_key: str, *, file_name: str | None = None):
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
    assert "LiteLLM AI 复核 调用失败" in stored["errorMessage"]
    assert "sk-secret-litellm" not in stored["errorMessage"]


def test_embed_and_compare_failures_do_not_leak_provider_details(monkeypatch) -> None:
    from apps.worker import tasks

    class FailingLiteLLM:
        def chat_sync(self, *args, **kwargs):
            raise RuntimeError("chat failed sk-secret-chat")

        def embed_sync(self, *args, **kwargs):
            raise RuntimeError("embed failed sk-secret-embed")

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

    assert embedded["status"] == "failed"
    assert vector_task["status"] == "失败"
    assert "EXTERNAL_TOOL_FAILED" in vector_task["errorMessage"]
    assert "sk-secret-embed" not in vector_task["errorMessage"]
    assert compared["status"] == "失败"
    assert compare_run["errorCode"] == "EXTERNAL_TOOL_FAILED"
    assert "LiteLLM 模型对比 调用失败" in compare_run["errorMessage"]
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


def test_completed_ocr_worker_is_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    calls = {"ocr": 0}

    def fake_parse(storage_key: str, *, file_name: str | None = None):
        calls["ocr"] += 1
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
    assert task.get("logs") == logs_after_first
    assert len([item for item in repo.state["extracted_fields"] if item.get("documentVersionId") == version["id"]]) == field_count_after_first


def test_completed_slice_and_embed_workers_are_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    def fake_parse(storage_key: str, *, file_name: str | None = None):
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "炉批号 SLICE-EMBED-IDEMPOTENT", "confidence": 0.92}],
            "fields": [{"fieldName": "炉批号", "fieldValue": "SLICE-EMBED-IDEMPOTENT", "confidence": 0.92}],
            "seals": [],
            "diagnostics": [],
        }

    class FakeLiteLLM:
        calls = 0

        def embed_sync(self, *args, **kwargs):
            FakeLiteLLM.calls += 1
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)
    monkeypatch.setattr(tasks, "LiteLLMClient", FakeLiteLLM)
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
    second_embed = tasks.embed_knowledge.run(file_id)

    assert first_slice["status"] == "success"
    assert second_slice["alreadyCompleted"] is True
    assert slice_task.get("logs") == slice_logs_after_first
    assert len([item for item in repo.state["knowledge_chunks"] if item.get("fileId") == file_id]) == chunk_count_after_first
    assert first_embed["status"] == "success"
    assert second_embed["alreadyCompleted"] is True
    assert FakeLiteLLM.calls == 1
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
    assert archive_task["storageKey"] in stored
    assert evidence_task["status"] == "可下载"
    assert evidence_task["storageKey"] in stored
    with zipfile.ZipFile(io.BytesIO(stored[archive_task["storageKey"]])) as archive_zip:
        manifest = json.loads(archive_zip.read("manifest.json").decode("utf-8"))
        assert manifest["exportType"] == "archive-package"
        assert manifest["counts"]["archiveItems"] >= 1
    with zipfile.ZipFile(io.BytesIO(stored[evidence_task["storageKey"]])) as evidence_zip:
        manifest = json.loads(evidence_zip.read("manifest.json").decode("utf-8"))
        assert manifest["exportType"] == "evidence-package"
        assert manifest["counts"]["evidenceLinks"] >= 1


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
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return list(self.rows)


class FakePostgresConnection:
    def __init__(self):
        self.state_rows: dict[tuple[str, str], dict] = {}
        self.singleton_rows: dict[str, dict] = {}
        self.idempotency_rows: dict[str, dict] = {}
        self.transactions_started = 0
        self.transactions_closed = 0
        self.executed: list[str] = []

    def transaction(self):
        return FakePostgresTransaction(self)

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        self.executed.append(normalized)
        if normalized.startswith("SELECT collection, payload FROM aicheck_state"):
            return FakePostgresCursor([(collection, payload) for (collection, _), payload in sorted(self.state_rows.items())])
        if normalized.startswith("SELECT name, payload FROM aicheck_singletons"):
            return FakePostgresCursor(list(self.singleton_rows.items()))
        if normalized.startswith("SELECT scope, payload FROM idempotency_records"):
            return FakePostgresCursor(list(self.idempotency_rows.items()))
        if normalized.startswith("DELETE FROM aicheck_state"):
            self.state_rows.clear()
        elif normalized.startswith("DELETE FROM aicheck_singletons"):
            self.singleton_rows.clear()
        elif normalized.startswith("DELETE FROM idempotency_records"):
            self.idempotency_rows.clear()
        elif normalized.startswith("INSERT INTO aicheck_state"):
            collection, object_id, payload = params
            self.state_rows[(collection, object_id)] = json.loads(payload)
        elif normalized.startswith("INSERT INTO aicheck_singletons"):
            name, payload = params
            self.singleton_rows[name] = json.loads(payload)
        elif normalized.startswith("INSERT INTO idempotency_records"):
            scope, payload = params
            self.idempotency_rows[scope] = json.loads(payload)
        return FakePostgresCursor([])


def test_postgres_indexes_include_jsonb_and_idempotency_specs() -> None:
    assert "aicheck_state" in POSTGRES_INDEXES
    assert {"name": "idx_aicheck_state_payload_gin", "fields": ["payload"], "type": "gin"} in POSTGRES_INDEXES["aicheck_state"]
    assert {"name": "idempotency_records_pkey", "fields": ["scope"], "unique": True} in POSTGRES_INDEXES["idempotency_records"]


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


def test_postgres_flush_uses_transaction() -> None:
    database = FakePostgresConnection()
    repo.sync_postgres = database
    repo.postgres_dsn = "postgresql://fake"
    repo.postgres_enabled = True

    repo.flush_to_sync_postgres()

    assert database.transactions_started >= 1
    assert database.transactions_closed >= 1
    assert database.state_rows
    assert database.singleton_rows


async def test_postgres_transaction_probe_reports_skipped_without_postgres(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_DATABASE_URL", raising=False)
    result = await run_transaction_probe(None)

    assert result["postgresEnabled"] is False
    assert result["transactionsConfigured"] is False
    assert result["transactionProbe"] == "skipped"
    assert result["reason"] == "postgres_not_configured"
