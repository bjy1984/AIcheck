from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.responses import JSONResponse
from libs.db.repository import repo

from scripts.deployment_report import (
    REQUIRED_STORAGE_BUCKETS,
    DeploymentReportBuilder,
    backend_action_coverage_check,
    backend_mutation_idempotency_check,
    backup_recoverability_contract_section,
    called_function_names,
    export_artifact_contract_check,
    fde_governance_contract_check,
    feedback_hr_contract_check,
    frontend_mutation_header_check,
    frontend_mutation_helper_check,
    iter_effective_routes,
    knowledge_rule_contract_check,
    litellm_client_contract_check,
    lossless_evidence_coverage_check,
    markdown_report,
    ocr_evaluation_contract_check,
    ocr_service_contract_check,
    postgres_index_contract_check,
    release_gate_contract_section,
    response_envelope_contract_check,
    review_orchestration_contract_check,
    role_contract_check,
    storage_contract_check,
    worker_task_contract_check,
    write_outputs,
)
from scripts.security_release_gate import REQUIRED_IMAGE_SERVICES


def write_clean_security_evidence(directory: Path) -> None:
    (directory / "scan-manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": "aicheck-security-scan-manifest-v1",
                "generatedAt": datetime.now(UTC).isoformat(),
                "sourceCommit": "abcdef1234567890",
                "composeSha256": "a" * 64,
                "frontendLockSha256": "b" * 64,
                "services": {
                    service: {
                        "imageId": f"sha256:{index:064x}",
                        "repoDigests": [f"registry.example/{service}@sha256:{index:064x}"],
                    }
                    for index, service in enumerate(REQUIRED_IMAGE_SERVICES, start=1)
                },
            }
        ),
        encoding="utf-8",
    )
    for service in REQUIRED_IMAGE_SERVICES:
        (directory / f"{service}.sbom.cdx.json").write_text(
            json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}), encoding="utf-8"
        )
        (directory / f"{service}.trivy.json").write_text(
            json.dumps({"SchemaVersion": 2, "Results": []}), encoding="utf-8"
        )
    (directory / "pip-audit.json").write_text(json.dumps({"dependencies": []}), encoding="utf-8")
    (directory / "pnpm-audit.json").write_text(
        json.dumps({"metadata": {"vulnerabilities": {"critical": 0, "high": 0, "moderate": 0, "low": 0}}}),
        encoding="utf-8",
    )


def report_args(**overrides):
    values = {
        "strict_production": True,
        "include_live": False,
        "api_base": "https://api",
        "ocr_base": "http://ocr",
        "litellm_base": "http://litellm",
        "litellm_api_key": "sk-test",
        "litellm_api_key_file": None,
        "project_id": "P-2026-HDCP-001",
        "roles": "admin,inspection,contractor",
        "skip_ocr": False,
        "skip_litellm": False,
        "write_probes": False,
        "ocr_object_probe": False,
        "review_run_probe": False,
        "review_run_wait_seconds": 0.0,
        "litellm_management_probes": False,
        "litellm_provider_probes": False,
        "qwen_official_probe": False,
        "release_gate": False,
        "security_scan_dir": None,
        "ocr_98_gate_report": None,
        "release_manifest": None,
        "backup_recoverability_report": None,
        "timeout": 1.0,
        "output_dir": None,
        "json": False,
    }
    values.update(overrides)
    return Namespace(**values)


def _review_registration_request_locked(*_args):
    return None


def _external_idempotent_delegate_for_contract_test(*_args):
    return None


_external_idempotent_delegate_for_contract_test.__module__ = "external.workflow"


def test_deployment_report_static_sections_pass_and_live_is_skipped() -> None:
    repo.reset()
    report = DeploymentReportBuilder(report_args()).build()

    assert report["schemaVersion"] == "aicheck-deployment-report-v1"
    assert report["ok"] is True
    sections = {section["name"]: section for section in report["sections"]}
    assert sections["deployment-config"]["ok"] is True
    assert sections["auth-contract"]["ok"] is True
    assert sections["data-contract"]["ok"] is True
    assert sections["storage-contract"]["ok"] is True
    assert sections["ocr-service-contract"]["ok"] is True
    assert sections["litellm-client-contract"]["ok"] is True
    assert sections["knowledge-rule-contract"]["ok"] is True
    assert sections["review-orchestration-contract"]["ok"] is True
    assert any(
        check["name"] == "review.lossless-evidence-coverage"
        for check in sections["review-orchestration-contract"]["checks"]
    )
    review_check = next(
        check
        for check in sections["review-orchestration-contract"]["checks"]
        if check["name"] == "review-orchestration.contract"
    )
    assert review_check["data"]["frontendArtifactVisualization"] is True
    assert sections["fde-governance-contract"]["ok"] is True
    assert sections["feedback-hr-contract"]["ok"] is True
    feedback_check = next(
        check
        for check in sections["feedback-hr-contract"]["checks"]
        if check["name"] == "feedback.hr-contract"
    )
    assert feedback_check["data"]["frontendFeedbackGovernance"] is True
    assert sections["export-artifact-contract"]["ok"] is True
    assert sections["worker-contract"]["ok"] is True
    assert sections["api-contract"]["ok"] is True
    assert sections["frontend-contract"]["ok"] is True
    assert sections["live-deployment"]["skipped"] is True
    assert any(check["name"] == "dockerfile.build-contract" for check in sections["deployment-config"]["checks"])
    assert any(check["name"] == "dockerfile.ocr-build-contract" for check in sections["deployment-config"]["checks"])
    assert any(check["name"] == "requirements.ocr-baseline" for check in sections["deployment-config"]["checks"])
    assert any(check["name"] == "compose.healthchecks" for check in sections["deployment-config"]["checks"])
    assert any(check["name"] == "compose.ocr-artifacts" for check in sections["deployment-config"]["checks"])
    envelope_check = next(check for check in sections["api-contract"]["checks"] if check["name"] == "api.response-envelope")
    assert envelope_check["status"] == "pass"
    assert envelope_check["data"]["failures"] == []
    role_check = next(check for check in sections["auth-contract"]["checks"] if check["name"] == "auth.role-contract")
    assert role_check["status"] == "pass"
    assert role_check["data"]["missingRoles"] == []
    assert role_check["data"]["ownerWriteLeaks"] == []
    assert role_check["data"]["planFailures"] == []
    security_check = next(
        check for check in sections["auth-contract"]["checks"] if check["name"] == "auth.security-contract"
    )
    assert security_check["status"] == "pass"
    assert security_check["data"]["failures"] == []
    postgres_check = next(check for check in sections["data-contract"]["checks"] if check["name"] == "postgres.index-contract")
    assert postgres_check["status"] == "pass"
    assert postgres_check["data"]["missingTables"] == []
    assert postgres_check["data"]["missingPlanCollections"] == []
    assert postgres_check["data"]["missingCriticalIndexes"] == []
    storage_check = next(
        check for check in sections["storage-contract"]["checks"] if check["name"] == "storage.bucket-contract"
    )
    assert storage_check["status"] == "pass"
    assert storage_check["data"]["missingBuckets"] == []
    assert storage_check["data"]["methodFailures"] == []
    assert storage_check["data"]["repositoryFailures"] == []
    ocr_check = next(
        check for check in sections["ocr-service-contract"]["checks"] if check["name"] == "ocr.service-contract"
    )
    assert ocr_check["status"] == "pass"
    assert ocr_check["data"]["healthFailures"] == []
    assert ocr_check["data"]["parseFailures"] == []
    assert ocr_check["data"]["doctorFailures"] == []
    assert ocr_check["data"]["serviceFailures"] == []
    assert ocr_check["data"]["preprocessFailures"] == []
    assert ocr_check["data"]["qualityGateFailures"] == []
    assert ocr_check["data"]["resultFailures"] == []
    ocr_profile_check = next(
        check for check in sections["ocr-service-contract"]["checks"] if check["name"] == "ocr.profile-contract"
    )
    assert ocr_profile_check["status"] == "pass"
    assert ocr_profile_check["data"]["failures"] == []
    assert "piping_characteristic_list_v1" in ocr_profile_check["data"]["businessProfileIds"]
    ocr_eval_check = next(
        check for check in sections["ocr-service-contract"]["checks"] if check["name"] == "ocr.evaluation-contract"
    )
    assert ocr_eval_check["status"] == "pass"
    assert ocr_eval_check["data"]["metricFailures"] == []
    assert ocr_eval_check["data"]["cliFailures"] == []
    assert ocr_eval_check["data"]["scorecardFailures"] == []
    assert ocr_eval_check["data"]["corpusFailures"] == []
    assert ocr_eval_check["data"]["prefetchFailures"] == []
    assert ocr_eval_check["data"]["strict100Thresholds"]["minCases"] == 100
    assert ocr_eval_check["data"]["strict100Thresholds"]["requiredScenarioCount"] >= 10
    assert ocr_eval_check["data"]["fixtureFailures"] == []
    assert set(ocr_eval_check["data"]["fixtureScenarios"]) == {
        "evidence_profile",
        "field_confidence_profile",
        "field_conflict_profile",
        "fragment_seal_profile",
        "piping_table_profile",
        "quality_gate_profile",
        "seal_text_profile",
    }
    litellm_check = next(
        check for check in sections["litellm-client-contract"]["checks"] if check["name"] == "litellm.client-contract"
    )
    assert litellm_check["status"] == "pass"
    assert litellm_check["data"]["clientFailures"] == []
    assert litellm_check["data"]["workerFailures"] == []
    assert litellm_check["data"]["runtimeFailures"] == []
    review_check = next(
        check for check in sections["review-orchestration-contract"]["checks"] if check["name"] == "review-orchestration.contract"
    )
    assert review_check["status"] == "pass"
    assert review_check["data"]["routeFailures"] == []
    assert review_check["data"]["graphFailures"] == []
    assert review_check["data"]["stateFailures"] == []
    assert review_check["data"]["toolFailures"] == []
    assert review_check["data"]["sourceFailures"] == []
    assert review_check["data"]["stepKeys"][:3] == ["load_context", "load_ocr_result", "run_rule_engine"]
    assert "llm_generate_findings" in review_check["data"]["stepKeys"]
    assert "review.llm" in review_check["data"]["taskQueues"]
    fde_gate_check = next(
        check for check in sections["fde-governance-contract"]["checks"] if check["name"] == "fde.governance-contract"
    )
    assert fde_gate_check["status"] == "pass"
    assert fde_gate_check["data"]["routeFailures"] == []
    assert fde_gate_check["data"]["collectionFailures"] == []
    assert fde_gate_check["data"]["sourceFailures"] == []
    assert fde_gate_check["data"]["businessPackPortabilityScorecard"] is True
    assert fde_gate_check["data"]["frontendBusinessPackScorecard"] is True
    feedback_hr_check = next(
        check for check in sections["feedback-hr-contract"]["checks"] if check["name"] == "feedback.hr-contract"
    )
    assert feedback_hr_check["status"] == "pass"
    assert feedback_hr_check["data"]["routeFailures"] == []
    assert feedback_hr_check["data"]["collectionFailures"] == []
    assert feedback_hr_check["data"]["sourceFailures"] == []
    export_check = next(
        check for check in sections["export-artifact-contract"]["checks"] if check["name"] == "export.artifact-contract"
    )
    assert export_check["status"] == "pass"
    assert export_check["data"]["failures"] == []
    assert export_check["data"]["zip"]["manifestSchema"] == "aicheck-export-v1"
    worker_check = next(check for check in sections["worker-contract"]["checks"] if check["name"] == "worker.task-contract")
    assert worker_check["status"] == "pass"
    assert worker_check["data"]["routeMismatches"] == []
    assert worker_check["data"]["retryMissing"] == []
    assert worker_check["data"]["dispatcherMissing"] == []
    api_check = next(check for check in sections["api-contract"]["checks"] if check["name"] == "api.mutation-idempotency")
    assert api_check["status"] == "pass"
    assert api_check["data"]["missing"] == []
    assert any(
        item["path"] == "/projects/{project_id}/registration-requests/{request_id}/review"
        and item["endpoint"] == "review_registration_request"
        for item in api_check["data"]["delegated"]
    )
    assert any(
        item["path"]
        == "/projects/{project_id}/documents/upload-session/{session_id}/files/{document_version_id}"
        and item["endpoint"] == "upload_session_file"
        for item in api_check["data"]["delegated"]
    )
    action_check = next(check for check in sections["api-contract"]["checks"] if check["name"] == "api.action-coverage")
    assert action_check["status"] == "pass"
    assert action_check["data"]["missing"] == []
    assert any(item["action"] == "review:save" for item in action_check["data"]["covered"])
    assert any(check["name"] == "frontend.contract" for check in sections["frontend-contract"]["checks"])
    mutation_check = next(check for check in sections["frontend-contract"]["checks"] if check["name"] == "frontend.mutation-headers")
    assert mutation_check["status"] == "pass"
    assert mutation_check["data"]["missing"] == []
    helper_check = next(check for check in sections["frontend-contract"]["checks"] if check["name"] == "frontend.mutation-helper")
    assert helper_check["status"] == "pass"
    assert helper_check["data"]["missing"] == []
    assert report["summary"]["fail"] == 0
    assert report["summary"]["skip"] == 2


def test_release_gate_requires_all_live_write_model_and_security_probes(tmp_path: Path) -> None:
    incomplete = release_gate_contract_section(report_args(release_gate=True))
    assert incomplete["ok"] is False
    assert "includeLive" in incomplete["checks"][0]["data"]["missing"]

    write_clean_security_evidence(tmp_path)
    ocr_98_report = tmp_path / "ocr-98-release-gate.json"
    ocr_98_report.write_text(json.dumps({"schemaVersion": "aicheck-ocr-98-release-gate-v1", "ok": True}), encoding="utf-8")
    complete = release_gate_contract_section(
        report_args(
            release_gate=True,
            include_live=True,
            write_probes=True,
            ocr_object_probe=True,
            review_run_probe=True,
            litellm_management_probes=True,
            litellm_provider_probes=True,
            qwen_official_probe=True,
            security_scan_dir=str(tmp_path),
            ocr_98_gate_report=str(ocr_98_report),
        )
    )
    assert complete["ok"] is True
    assert complete["checks"][1]["name"] == "release.security-scans"
    assert complete["checks"][1]["status"] == "pass"
    assert complete["checks"][2]["name"] == "release.ocr-98-gate"
    assert complete["checks"][2]["status"] == "pass"


def test_lossless_evidence_gate_blocks_missing_artifacts() -> None:
    check = lossless_evidence_coverage_check(
        manifests=[
            {
                "evidenceManifestId": "EMAN-1",
                "counts": {"total": 10},
            }
        ],
        coverages=[
            {
                "evidenceManifestId": "EMAN-1",
                "expectedArtifactCount": 10,
                "processedArtifactCount": 9,
                "missingArtifactIds": ["EART-10"],
                "duplicateArtifactIds": [],
                "coveragePassed": False,
            }
        ],
        review_runs=[],
    )

    assert check["status"] == "fail"
    assert check["data"]["gateStatus"] == "blocked"
    assert check["data"]["missingArtifactCount"] == 1


def test_lossless_evidence_gate_passes_complete_manifests_and_runs() -> None:
    check = lossless_evidence_coverage_check(
        manifests=[
            {
                "evidenceManifestId": "EMAN-1",
                "counts": {"total": 10},
            }
        ],
        coverages=[
            {
                "evidenceManifestId": "EMAN-1",
                "expectedArtifactCount": 10,
                "processedArtifactCount": 10,
                "missingArtifactIds": [],
                "duplicateArtifactIds": [],
                "coveragePassed": True,
            }
        ],
        review_runs=[
            {
                "reviewRunId": "RRUN-1",
                "status": "waiting_human_review",
                "evidenceManifestId": "EMAN-1",
                "evidenceCoverage": {"coveragePassed": True},
            }
        ],
    )

    assert check["status"] == "pass"
    assert check["data"]["gateStatus"] == "passed"


def test_backup_recoverability_report_is_integrity_checked(tmp_path: Path) -> None:
    import hashlib

    document = {
        "schemaVersion": "aicheck-backup-recoverability-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "ok": True,
        "checks": [{"name": "restore.drill", "status": "pass", "detail": "verified", "data": None}],
    }
    document["reportHash"] = "sha256:" + hashlib.sha256(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    path = tmp_path / "backup-recoverability.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    section = backup_recoverability_contract_section(report_args(backup_recoverability_report=str(path)))
    assert section["ok"] is True

    document["checks"][0]["status"] = "fail"
    path.write_text(json.dumps(document), encoding="utf-8")
    section = backup_recoverability_contract_section(report_args(backup_recoverability_report=str(path)))
    assert section["ok"] is False


def test_deployment_report_markdown_contains_summary() -> None:
    report = DeploymentReportBuilder(report_args()).build()
    markdown = markdown_report(report)

    assert "# AIcheck Deployment Acceptance Report" in markdown
    assert "| deployment-config | compose.services | PASS |" in markdown
    assert "Summary: total=" in markdown


def test_deployment_report_writes_json_and_markdown(tmp_path) -> None:
    report = DeploymentReportBuilder(report_args()).build()

    write_outputs(report, str(tmp_path))

    report_json = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    report_md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert report_json["ok"] is True
    assert report_json["schemaVersion"] == "aicheck-deployment-report-v1"
    assert "AIcheck Deployment Acceptance Report" in report_md


def test_ocr_evaluation_contract_and_cli_fixture_pass(tmp_path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    markdown_path = tmp_path / "ocr-eval-report.md"
    check = ocr_evaluation_contract_check()

    assert check["status"] == "pass"
    assert check["data"]["fixtureSummary"]["averageScore"] == 1
    assert check["data"]["compactSummary"]["ok"] is True
    assert check["data"]["compactSummary"]["scenarioCount"] >= 1
    assert set(check["data"]["fixtureScenarios"]) == {
        "evidence_profile",
        "field_confidence_profile",
        "field_conflict_profile",
        "fragment_seal_profile",
        "piping_table_profile",
        "quality_gate_profile",
        "seal_text_profile",
    }

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ocr_eval_set.py",
            "ocr_eval/piping_release_set.json",
            "--min-average-score",
            "1",
            "--markdown-output",
            str(markdown_path),
        ],
        cwd=backend_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["averageScore"] == 1
    assert summary["scenarios"]["piping_table_profile"]["averageScore"] == 1
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# OCR Evaluation Report: piping_release_set" in markdown
    assert "| piping_table_profile | 1 | 1 | 0 | 1.0000 |" in markdown
    assert "No failed cases." in markdown


def test_ocr_profile_contract_rejects_missing_critical_conflict_fields() -> None:
    from libs.ocr.profiles import DEFAULT_PROFILE_ID, OCR_PROFILES, validate_profiles

    profiles = {key: json.loads(json.dumps(value, ensure_ascii=False)) for key, value in OCR_PROFILES.items()}
    profiles["broken_profile_v1"] = {
        "profileId": "broken_profile_v1",
        "documentType": "broken",
        "requiredFields": ["report_no"],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": []},
        "qualityRules": {"criticalConflictFields": []},
        "preprocessPolicy": profiles[DEFAULT_PROFILE_ID]["preprocessPolicy"],
    }
    profiles["inherited_profile_v1"] = {
        "profileId": "inherited_profile_v1",
        "documentType": "inherited",
        "requiredFields": ["report_no"],
        "requiredTables": [],
        "sealRules": {"required": False, "expectedSealTypes": []},
    }

    failures = validate_profiles(profiles)

    assert any(
        item["profileId"] == "broken_profile_v1"
        and item["path"] == "qualityRules.criticalConflictFields"
        for item in failures
    )
    assert any(
        item["profileId"] == "inherited_profile_v1"
        and item["path"] == "qualityRules.criticalConflictFields"
        for item in failures
    )
    assert any(
        item["profileId"] == "inherited_profile_v1"
        and item["path"] == "preprocessPolicy"
        for item in failures
    )


def test_ocr_eval_markdown_includes_failed_case_diagnostics() -> None:
    from apps.ocr_service.evaluation import evaluate_cases
    from scripts.ocr_eval_set import markdown_report as ocr_markdown_report

    report = evaluate_cases(
        [
            {
                "caseId": "bad-field-box",
                "scenario": "piping_table_profile",
                "minScore": 0,
                "result": {
                    "parseResultId": "PARSE-BAD",
                    "status": "success",
                    "fields": [{"fieldCode": "pipe_no", "fieldValue": "PL8301", "bbox": [0, 0, 10, 10]}],
                    "tables": [],
                    "seals": [],
                    "quality": {"status": "auto_usable", "reasons": []},
                },
                "expected": {
                    "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [100, 100, 120, 120]}],
                },
            }
        ]
    )

    markdown = ocr_markdown_report(report, eval_set_name="failed_fixture")

    assert "### bad-field-box" in markdown
    assert "OCR_EVAL_FIELD_BBOX_MISMATCH" in markdown
    assert "#### Fields" in markdown
    assert "bestIoU=0.0000" in markdown


def test_frontend_mutation_header_check_fails_non_exempt_mutation_without_headers(tmp_path) -> None:
    api_file = tmp_path / "index.ts"
    api_file.write_text(
        """
        export const safeSave = () => request.post({
          url: '/api/projects/P-1/rectifications',
          data: { nodeId: 16 },
          headers: mutationHeaders(options)
        })
        export const unsafeSave = () => request.post({
          url: '/api/projects/P-1/submissions',
          note: 'headers: mutationHeaders(options)',
          // headers: mutationHeaders(options),
          data: { nodeIds: [16] }
        })
        export const misleadingBlockComment = () => request.post({
          url: '/api/projects/P-1/documents/bindings',
          /*
            headers: mutationHeaders(options)
          */
          data: { bindings: [] }
        })
        export const preview = () => request.post({
          url: '/api/admin/config-diff/preview',
          data: {}
        })
        """,
        encoding="utf-8",
    )

    check = frontend_mutation_header_check(api_file)
    missing_urls = {item["url"] for item in check["data"]["missing"]}

    assert check["status"] == "fail"
    assert missing_urls == {
        "/api/projects/P-1/submissions",
        "/api/projects/P-1/documents/bindings",
    }
    assert check["data"]["exempt"][0]["url"] == "/api/admin/config-diff/preview"


def test_response_envelope_contract_check_fails_legacy_or_incomplete_helpers() -> None:
    def bad_ok(data=None):
        return {"ok": True, "data": data}

    def bad_fail(error):
        return JSONResponse({"ok": False, "code": 0, "message": "", "data": {}}, status_code=409)

    check = response_envelope_contract_check(bad_ok, bad_fail)

    assert check["status"] == "fail"
    detail = check["detail"]
    assert "ok.code must be 0" in detail
    assert "legacy ok field must not be present" in detail
    assert "fail() default HTTP status must be 200" in detail
    assert "fail.data.reason" in detail


def test_role_contract_check_fails_bad_paths_owner_write_and_missing_specs() -> None:
    paths = {
        "admin": "/admin/overview",
        "inspection": "/ai-review-b",
        "contractor": "/wrong",
        "ndt": "/workbench/ndt",
        "owner": "/workbench/owner",
    }
    actions = {
        "admin": ["admin:config", "admin:export", "project:authorize-member", "knowledge:manage"],
        "inspection": ["review:save", "review:return-correction", "ai:recheck", "report:generate"],
        "contractor": ["file:upload", "file:bind", "submission:submit", "rectification:submit"],
        "ndt": ["ndt:film-create", "ndt:record-import", "ndt:report-upload", "ndt:submit"],
        "owner": ["project:view", "file:view", "report:view", "archive:view", "archive:download", "file:upload"],
    }
    specs = {
        role: {
            "username": role,
            "userId": f"USER-{role.upper()}",
            "orgId": f"ORG-{role.upper()}",
            "nodeScope": [1],
            "readonly": role == "owner",
        }
        for role in ["admin", "inspection", "contractor", "owner"]
    }

    check = role_contract_check(role_default_paths=paths, role_actions=actions, role_specs=specs)

    assert check["status"] == "fail"
    assert check["data"]["badPaths"] == [
        {"role": "contractor", "expected": "/workbench/contractor", "actual": "/wrong"}
    ]
    assert check["data"]["ownerWriteLeaks"] == [{"role": "owner", "actions": ["file:upload"]}]
    assert "ndt" in check["data"]["missingSpecs"]


def test_frontend_mutation_helper_check_requires_if_match_and_idempotency(tmp_path) -> None:
    api_file = tmp_path / "index.ts"
    api_file.write_text(
        """
        const mutationHeaders = (options?: MutationHeaderOptions) => {
          const headers: Record<string, string> = {}
          headers['Idempotency-Key'] = options?.idempotencyKey || crypto.randomUUID()
          return headers
        }
        """,
        encoding="utf-8",
    )

    check = frontend_mutation_helper_check(api_file)

    assert check["status"] == "fail"
    assert "If-Match" in check["data"]["missing"]
    assert "etag option" in check["data"]["missing"]


def test_postgres_index_contract_check_fails_missing_tables_and_critical_indexes() -> None:
    check = postgres_index_contract_check(
        {
            "aicheck_state": [{"fields": ["collection"]}],
        }
    )

    assert check["status"] == "fail"
    assert "aicheck_singletons" in check["data"]["missingTables"]
    assert check["data"]["missingPlanCollections"] == []
    assert {
        "table": "aicheck_state",
        "fields": ["tenant_id", "collection", "object_id"],
        "unique": True,
    } in check["data"]["missingCriticalIndexes"]


def test_storage_contract_check_fails_missing_bucket_method_and_repository_usage() -> None:
    class BadStorage:
        def ensure_buckets(self):
            return None

        def presigned_put_url(self, bucket):
            return None

    class BadRepository:
        def signed_get(self):
            return {"url": "mock://download"}

        def signed_put(self):
            return "mock://upload"

    check = storage_contract_check(
        default_buckets=("documents", "exports", "exports", "tmp"),
        storage_class=BadStorage,
        repository_class=BadRepository,
        parse_url_func=lambda _url: ("documents", "raw"),
    )

    assert check["status"] == "fail"
    # 期望值随 REQUIRED_STORAGE_BUCKETS 走：raw vault 功能新增了 agent-raw-vault 桶，
    # 此处曾漏同步。直接由常量推导，避免再次漂移。
    expected_missing = sorted(set(REQUIRED_STORAGE_BUCKETS) - {"documents", "exports"})
    assert check["data"]["missingBuckets"] == expected_missing
    assert check["data"]["unexpectedBuckets"] == ["tmp"]
    assert check["data"]["duplicateBuckets"] == ["exports"]
    assert {"method": "presigned_get_url", "reason": "missing"} in check["data"]["methodFailures"]
    assert any(item.get("method") == "presigned_put_url" for item in check["data"]["methodFailures"])
    assert {"method": "document_storage_url", "reason": "missing"} in check["data"]["repositoryFailures"]
    assert check["data"]["parseFailures"] == ["parse_storage_url must decode minio bucket/object paths"]


def test_ocr_service_contract_check_fails_missing_health_parse_and_result_fields() -> None:
    def bad_healthz():
        return {"service": "ocr-service"}

    def bad_parse_document():
        return {"ok": True}

    def bad_resolve_source_path():
        return None

    bad_healthz.__source__ = "def bad_healthz():\n    return {'service': 'ocr-service'}\n"
    bad_parse_document.__source__ = "def bad_parse_document():\n    return {'ok': True}\n"
    bad_resolve_source_path.__source__ = "def bad_resolve_source_path():\n    return None\n"

    class BadOcrService:
        def parse_document(self):
            return {"status": "success"}

    BadOcrService.parse_document.__source__ = "def parse_document(self):\n    return {'status': 'success'}\n"

    bad_main = SimpleNamespace(healthz=bad_healthz, parse_document=bad_parse_document)
    bad_service = SimpleNamespace(
        OcrService=BadOcrService,
        resolve_source_path=bad_resolve_source_path,
        normalize_ocr_result=lambda _raw, _storage_key, _file_name=None: {"status": "success"},
        failed_result=lambda _storage_key, _file_name, _message: {"status": "failed"},
    )

    check = ocr_service_contract_check(ocr_main_module=bad_main, service_module=bad_service)

    assert check["status"] == "fail"
    assert any("missing health fields" in item for item in check["data"]["healthFailures"])
    assert any("missing parse endpoint terms" in item for item in check["data"]["parseFailures"])
    assert any("runtime doctor endpoint is missing" in item for item in check["data"]["doctorFailures"])
    assert any("missing OcrService.parse_document terms" in item for item in check["data"]["serviceFailures"])
    assert "resolve_source_path must use parse_storage_url" in check["data"]["serviceFailures"]
    assert check["data"]["qualityGateFailures"] == []
    assert any("missing normalized result fields" in item for item in check["data"]["resultFailures"])
    assert any("missing failed result fields" in item for item in check["data"]["resultFailures"])


def test_litellm_client_contract_check_fails_bad_client_and_worker_usage() -> None:
    class BadLiteLLMClient:
        def __init__(self, *args, **kwargs):
            pass

        def chat_sync(self, messages):
            return {"choices": []}

    BadLiteLLMClient.__init__.__source__ = "def __init__(self):\n    pass\n"
    BadLiteLLMClient.chat_sync.__source__ = "def chat_sync(self, messages):\n    return {'choices': []}\n"

    def bad_embed_task():
        return None

    def bad_ai_task():
        return None

    def bad_compare_task():
        return None

    bad_embed_task.__source__ = "def bad_embed_task():\n    return None\n"
    bad_ai_task.__source__ = "def bad_ai_task():\n    return None\n"
    bad_compare_task.__source__ = "def bad_compare_task():\n    return None\n"

    check = litellm_client_contract_check(
        client_class=BadLiteLLMClient,
        worker_tasks_module=SimpleNamespace(
            embed_knowledge=bad_embed_task,
            ai_recheck=bad_ai_task,
            llm_compare=bad_compare_task,
        ),
    )

    assert check["status"] == "fail"
    assert {"method": "chat", "reason": "missing"} in check["data"]["clientFailures"]
    assert any(item.get("method") == "__init__" for item in check["data"]["clientFailures"])
    assert any(item.get("task") == "embed_knowledge" for item in check["data"]["workerFailures"])
    assert any("mocked LiteLLM request failed" in item for item in check["data"]["runtimeFailures"])


def test_knowledge_rule_contract_check_fails_missing_routes_fields_and_validators() -> None:
    class BadExecution:
        pass

    def bad_run_step():
        return {}

    def bad_validator():
        return {"passed": True}

    bad_run_step.__source__ = "def bad_run_step():\n    return {}\n"
    bad_validator.__source__ = "def bad_validator():\n    return {'passed': True}\n"
    BadExecution.run_step = bad_run_step
    BadExecution.validate_review_schema = bad_validator
    BadExecution.validate_review_evidence_refs = bad_validator
    BadExecution.validate_review_references = bad_validator
    BadExecution.review_quality_gate = bad_validator

    check = knowledge_rule_contract_check(
        fastapi_app=SimpleNamespace(routes=[]),
        execution_module=BadExecution,
    )

    assert check["status"] == "fail"
    assert check["data"]["routeFailures"]
    assert any("RuleCheckResult missing fields" in item for item in check["data"]["fieldFailures"])
    assert any("RetrievalTrace missing fields" in item for item in check["data"]["fieldFailures"])
    assert any("validate_review_schema missing source terms" in item for item in check["data"]["validationFailures"])


def test_review_orchestration_contract_check_fails_missing_routes_graph_and_sources() -> None:
    class BadExecution:
        REVIEW_GRAPH_STEPS = [{"key": "load_context", "taskQueue": "review.graph"}]
        REVIEW_GRAPH_EDGES = []
        REVIEW_STATE_COLLECTIONS = ("review_runs",)
        ALLOWED_AGENT_TOOLS = {"approve_review"}
        FORBIDDEN_AGENT_TOOLS = {"approve_review"}

    def bad_create_review_run_from_ai_run():
        return {}

    def bad_generate_finding_drafts():
        return []

    bad_create_review_run_from_ai_run.__source__ = "def bad_create_review_run_from_ai_run():\n    return {}\n"
    bad_generate_finding_drafts.__source__ = "def bad_generate_finding_drafts():\n    return []\n"
    BadExecution.create_review_run_from_ai_run = bad_create_review_run_from_ai_run
    BadExecution.execute_review_run_inline = bad_create_review_run_from_ai_run
    BadExecution.run_step = bad_create_review_run_from_ai_run
    BadExecution.generate_finding_drafts = bad_generate_finding_drafts
    BadExecution.human_decision_for_review_run = bad_create_review_run_from_ai_run
    BadExecution.clone_review_run_for_replay = bad_create_review_run_from_ai_run

    check = review_orchestration_contract_check(
        fastapi_app=SimpleNamespace(routes=[]),
        execution_module=BadExecution,
        dispatcher_module=SimpleNamespace(),
        graph_module=SimpleNamespace(),
        worker_main_module=SimpleNamespace(),
        workflow_module=SimpleNamespace(),
        activities_module=SimpleNamespace(),
    )

    assert check["status"] == "fail"
    assert check["data"]["routeFailures"]
    assert any("missing graph steps" in item for item in check["data"]["graphFailures"])
    assert any("missing review state collections" in item for item in check["data"]["stateFailures"])
    assert any("missing allowed tools" in item for item in check["data"]["toolFailures"])
    assert any("both allowed and forbidden" in item for item in check["data"]["toolFailures"])
    assert any("create_review_run_from_ai_run missing source terms" in item for item in check["data"]["sourceFailures"])


def test_fde_governance_contract_check_fails_missing_routes_and_gate_sources() -> None:
    def bad_gate():
        return []

    bad_gate.__source__ = "def bad_gate():\n    return []\n"
    bad_module = SimpleNamespace(
        fde_release_gate_results=bad_gate,
        fde_create_release_plan=bad_gate,
        fde_submit_release_plan=bad_gate,
        fde_approve_release_plan=bad_gate,
        fde_start_shadow_release=bad_gate,
        fde_request_canary_release=bad_gate,
    )

    check = fde_governance_contract_check(
        fastapi_app=SimpleNamespace(routes=[]),
        api_routes_module=bad_module,
    )

    assert check["status"] == "fail"
    assert check["data"]["routeFailures"]
    assert any("fde_release_gate_results missing source terms" in item for item in check["data"]["sourceFailures"])
    assert any("fde_approve_release_plan missing source terms" in item for item in check["data"]["sourceFailures"])


def test_feedback_hr_contract_check_fails_missing_routes_and_feedback_sources() -> None:
    def bad_handler():
        return {}

    bad_handler.__source__ = "def bad_handler():\n    return {}\n"
    bad_api_module = SimpleNamespace(
        router=SimpleNamespace(routes=[]),
        fde_triage_feedback=bad_handler,
        fde_upsert_evaluation_case_from_feedback=bad_handler,
    )
    bad_execution_module = SimpleNamespace(
        human_decision_for_review_run=bad_handler,
        record_human_feedback_for_review_run=bad_handler,
    )

    check = feedback_hr_contract_check(
        fastapi_app=SimpleNamespace(routes=[]),
        api_routes_module=bad_api_module,
        execution_module=bad_execution_module,
    )

    assert check["status"] == "fail"
    assert check["data"]["routeFailures"]
    assert any("record_human_feedback_for_review_run missing source terms" in item for item in check["data"]["sourceFailures"])
    assert any(
        "fde_upsert_evaluation_case_from_feedback missing source terms" in item
        for item in check["data"]["sourceFailures"]
    )


def test_export_artifact_contract_check_fails_invalid_package_builder() -> None:
    def bad_builder(file_name, task, content_type, repository):
        if content_type == "application/pdf":
            return b"not a pdf"
        return b"not a zip"

    check = export_artifact_contract_check(builder=bad_builder)

    assert check["status"] == "fail"
    assert any("zip artifact is not a valid package" in item for item in check["data"]["failures"])
    assert "pdf artifact must start with %PDF-" in check["data"]["failures"]
    assert "pdf artifact must contain AIcheck Export Report heading" in check["data"]["failures"]


def test_worker_task_contract_check_fails_missing_route_retry_and_dispatcher() -> None:
    class FakeTask:
        name = "apps.worker.tasks.parse_document"
        autoretry_for = ()
        retry_backoff = False
        retry_kwargs = {}

    def bad_dispatcher():
        return None

    bad_dispatcher.__source__ = "def bad_dispatcher():\n    return None\n"
    tasks_module = SimpleNamespace(parse_document=FakeTask())
    dispatcher_module = SimpleNamespace(dispatch_parse_document=bad_dispatcher)

    check = worker_task_contract_check(
        task_routes={"apps.worker.tasks.parse_document": {"queue": "wrong.queue"}},
        tasks_module=tasks_module,
        dispatcher_module=dispatcher_module,
    )

    assert check["status"] == "fail"
    assert "recognize_seals" in check["data"]["missingTasks"]
    assert {
        "task": "parse_document",
        "expectedQueue": "ocr.parse_document",
        "actualQueue": "wrong.queue",
    } in check["data"]["routeMismatches"]
    assert {"task": "parse_document", "reason": "missing Exception autoretry"} in check["data"]["retryMissing"]
    assert "dispatch_slice" in check["data"]["dispatcherMissing"]
    assert check["data"]["dispatcherMismatches"][0]["dispatcher"] == "dispatch_parse_document"


def test_backend_mutation_idempotency_check_fails_unwrapped_business_mutation() -> None:
    def unsafe_endpoint():
        return None

    unsafe_endpoint.__source__ = (
        "def unsafe_endpoint():\n"
        "    marker = 'idempotent('\n"
        "    # create_admin_project(\n"
        "    repo.add_audit('x', 'Y', '1')\n"
        "    return marker\n"
    )
    routes = [
        SimpleNamespace(
            path="/projects/{project_id}/unsafe",
            methods={"POST"},
            endpoint=unsafe_endpoint,
        )
    ]

    check = backend_mutation_idempotency_check(routes)

    assert check["status"] == "fail"
    assert check["data"]["missing"][0]["path"] == "/projects/{project_id}/unsafe"
    assert "idempotent" not in called_function_names(unsafe_endpoint.__source__)


def test_backend_action_coverage_check_fails_unmapped_business_mutation() -> None:
    routes = [
        SimpleNamespace(path="/projects/{project_id}/unmapped-business-action", methods={"POST"}),
        SimpleNamespace(path="/auth/login", methods={"POST"}),
    ]

    check = backend_action_coverage_check(routes)

    assert check["status"] == "fail"
    assert check["data"]["missing"] == [
        {
            "method": "POST",
            "path": "/projects/{project_id}/unmapped-business-action",
            "action": None,
        }
    ]
    assert check["data"]["exempt"] == [
        {"method": "POST", "path": "/auth/login", "category": "public"}
    ]


def test_backend_mutation_idempotency_check_classifies_direct_calls() -> None:
    def direct_endpoint():
        return None

    direct_endpoint.__source__ = (
        "def direct_endpoint():\n"
        "    return idempotent(request, key, produce, fingerprint_source={})\n"
    )
    routes = [
        SimpleNamespace(path="/projects/{project_id}/direct", methods={"POST"}, endpoint=direct_endpoint),
    ]

    check = backend_mutation_idempotency_check(routes)

    assert check["status"] == "pass"
    assert check["data"]["missing"] == []
    assert check["data"]["direct"] == [
        {
            "method": "POST",
            "path": "/projects/{project_id}/direct",
            "endpoint": "direct_endpoint",
            "category": "direct",
        }
    ]
    assert "idempotent" in called_function_names(direct_endpoint.__source__)


def test_backend_mutation_idempotency_check_recognizes_locked_idempotent_registration_review_delegate() -> None:
    routes = [
        route
        for route in iter_effective_routes()
        if getattr(route, "path", "") == "/projects/{project_id}/registration-requests/{request_id}/review"
    ]

    check = backend_mutation_idempotency_check(routes)

    assert check["status"] == "pass"
    assert check["data"]["missing"] == []
    assert check["data"]["delegated"] == [
        {
            "method": "POST",
            "path": "/projects/{project_id}/registration-requests/{request_id}/review",
            "endpoint": "review_registration_request",
            "category": "delegated",
        }
    ]


def test_backend_mutation_idempotency_check_recognizes_trusted_upload_workflow_delegate() -> None:
    routes = [
        route
        for route in iter_effective_routes()
        if getattr(route, "path", "")
        == "/projects/{project_id}/documents/upload-session/{session_id}/files/{document_version_id}"
    ]

    check = backend_mutation_idempotency_check(routes)

    assert check["status"] == "pass"
    assert check["data"]["missing"] == []
    assert check["data"]["delegated"] == [
        {
            "method": "PUT",
            "path": "/projects/{project_id}/documents/upload-session/{session_id}/files/{document_version_id}",
            "endpoint": "upload_session_file",
            "category": "delegated",
        }
    ]

def test_backend_mutation_idempotency_check_rejects_same_named_unapproved_delegate() -> None:
    """A same-spelled local helper is not trusted unless it calls idempotent."""
    def unsafe_same_named_delegate_endpoint():
        return None

    unsafe_same_named_delegate_endpoint.__source__ = (
        "def unsafe_same_named_delegate_endpoint():\n"
        "    return _review_registration_request_locked(request, project_id, request_id, body, key)\n"
    )
    routes = [
        SimpleNamespace(
            path="/projects/{project_id}/unsafe-same-named-delegate",
            methods={"POST"},
            endpoint=unsafe_same_named_delegate_endpoint,
        )
    ]

    check = backend_mutation_idempotency_check(routes)

    assert check["status"] == "fail"
    assert check["data"]["missing"] == [
        {
            "method": "POST",
            "path": "/projects/{project_id}/unsafe-same-named-delegate",
            "endpoint": "unsafe_same_named_delegate_endpoint",
            "category": "missing",
        }
    ]


def test_backend_mutation_idempotency_check_rejects_external_delegate_callable() -> None:
    def unsafe_external_delegate_endpoint():
        return None

    unsafe_external_delegate_endpoint.__source__ = (
        "def unsafe_external_delegate_endpoint():\n"
        "    return _external_idempotent_delegate_for_contract_test(request, key)\n"
    )
    routes = [
        SimpleNamespace(
            path="/projects/{project_id}/unsafe-external-delegate",
            methods={"POST"},
            endpoint=unsafe_external_delegate_endpoint,
        )
    ]

    check = backend_mutation_idempotency_check(routes)

    assert check["status"] == "fail"
    assert check["data"]["missing"] == [
        {
            "method": "POST",
            "path": "/projects/{project_id}/unsafe-external-delegate",
            "endpoint": "unsafe_external_delegate_endpoint",
            "category": "missing",
        }
    ]
