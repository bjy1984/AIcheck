from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

from fastapi.responses import JSONResponse

from scripts.deployment_report import (
    DeploymentReportBuilder,
    backend_action_coverage_check,
    backend_mutation_idempotency_check,
    called_function_names,
    export_artifact_contract_check,
    frontend_mutation_header_check,
    frontend_mutation_helper_check,
    litellm_client_contract_check,
    markdown_report,
    mongo_index_contract_check,
    ocr_service_contract_check,
    response_envelope_contract_check,
    role_contract_check,
    storage_contract_check,
    worker_task_contract_check,
    write_outputs,
)


def report_args(**overrides):
    values = {
        "strict_production": True,
        "include_live": False,
        "api_base": "http://api",
        "ocr_base": "http://ocr",
        "litellm_base": "http://litellm",
        "litellm_api_key": "sk-test",
        "project_id": "P-2026-HDCP-001",
        "roles": "admin,inspection,contractor",
        "skip_ocr": False,
        "skip_litellm": False,
        "write_probes": False,
        "ocr_object_probe": False,
        "litellm_provider_probes": False,
        "timeout": 1.0,
        "output_dir": None,
        "json": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_deployment_report_static_sections_pass_and_live_is_skipped() -> None:
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
    mongo_check = next(check for check in sections["data-contract"]["checks"] if check["name"] == "mongo.index-contract")
    assert mongo_check["status"] == "pass"
    assert mongo_check["data"]["missingPersisted"] == []
    assert mongo_check["data"]["missingPlanCollections"] == []
    assert mongo_check["data"]["missingCriticalIndexes"] == []
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
    assert ocr_check["data"]["serviceFailures"] == []
    assert ocr_check["data"]["resultFailures"] == []
    litellm_check = next(
        check for check in sections["litellm-client-contract"]["checks"] if check["name"] == "litellm.client-contract"
    )
    assert litellm_check["status"] == "pass"
    assert litellm_check["data"]["clientFailures"] == []
    assert litellm_check["data"]["workerFailures"] == []
    assert litellm_check["data"]["runtimeFailures"] == []
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
    assert report["summary"]["skip"] == 1


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
        "inspection": "/workbench/inspection",
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


def test_mongo_index_contract_check_fails_missing_persisted_and_critical_indexes() -> None:
    check = mongo_index_contract_check(
        {
            "projects": [[("code", 1)]],
            "project_nodes": [[("projectId", 1), ("nodeId", 1)]],
            "documents": [[("projectId", 1), ("currentVersionId", 1)]],
        }
    )

    assert check["status"] == "fail"
    assert "audit_logs" in check["data"]["missingPersisted"]
    assert "knowledge_tasks" in check["data"]["missingPlanCollections"]
    assert {
        "collection": "project_nodes",
        "fields": ["projectId", "nodeId", "status"],
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
    assert check["data"]["missingBuckets"] == ["ocr-artifacts", "previews"]
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
    assert any("missing OcrService.parse_document terms" in item for item in check["data"]["serviceFailures"])
    assert "resolve_source_path must use parse_storage_url" in check["data"]["serviceFailures"]
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


def test_backend_mutation_idempotency_check_classifies_direct_and_delegated_calls() -> None:
    def direct_endpoint():
        return None

    def delegated_endpoint():
        return None

    direct_endpoint.__source__ = (
        "def direct_endpoint():\n"
        "    return idempotent(request, key, produce, fingerprint_source={})\n"
    )
    delegated_endpoint.__source__ = (
        "def delegated_endpoint():\n"
        "    return create_admin_project(request, body, idempotency_key)\n"
    )
    routes = [
        SimpleNamespace(path="/projects/{project_id}/direct", methods={"POST"}, endpoint=direct_endpoint),
        SimpleNamespace(path="/projects/{project_id}/delegated", methods={"POST"}, endpoint=delegated_endpoint),
    ]

    check = backend_mutation_idempotency_check(routes)
    categories = {item["path"]: item["category"] for item in [*check["data"]["direct"], *check["data"]["delegated"]]}

    assert check["status"] == "pass"
    assert check["data"]["missing"] == []
    assert categories["/projects/{project_id}/direct"] == "direct"
    assert categories["/projects/{project_id}/delegated"] == "delegated"
    assert "idempotent" in called_function_names(direct_endpoint.__source__)
