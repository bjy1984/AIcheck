from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo


client = TestClient(app)


def setup_function() -> None:
    repo.reset()
    repo.mongo = None
    repo.sync_mongo = None


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


def test_login_compatibility_paths() -> None:
    mock_user = assert_ok(client.post("/mock/user/login", json={"username": "admin", "password": "admin"}))
    real_login = assert_ok(client.post("/api/auth/login", json={"username": "admin", "password": "admin"}))

    assert mock_user["username"] == "admin"
    assert real_login["token"]
    assert real_login["user"]["role"] == "admin"


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


def test_owner_write_forbidden_and_archived_readonly() -> None:
    project_id = "P-2026-HDCP-001"
    owner_write = client.post(
        f"/projects/{project_id}/inspection/nodes/24/ai-recheck",
        headers={"X-Role": "owner"},
    )
    assert_error(owner_write, "FORBIDDEN")

    archived = client.post(
        "/projects/P-2025-CQARCH-007/documents/upload-session",
        json={"files": [{"fileName": "readonly.pdf", "fileSize": 1, "fileType": "application/pdf"}]},
    )
    assert_error(archived, "ARCHIVED_READONLY")


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


def test_optional_jwt_action_and_node_scope_guards(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    unauthenticated = client.get("/api/auth/me")
    assert_error(unauthenticated, "AUTH_REQUIRED")

    action_forbidden = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
        headers={"Authorization": "Bearer dev-token-admin-admin", "X-Role": "contractor", "X-Action-Code": "review:save"},
    )
    assert_error(action_forbidden, "FORBIDDEN")

    node_forbidden = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/40/ai-recheck",
        headers={
            "Authorization": "Bearer dev-token-admin-admin",
            "X-Role": "contractor",
            "X-User-Id": "USER-CONTRACTOR-001",
        },
    )
    assert_error(node_forbidden, "FORBIDDEN")


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


def test_ndt_submit_preserves_pending_report_and_rectification_updates_feedback() -> None:
    project_id = "P-2026-HDCP-001"
    submit = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/submissions",
            json={"nodeId": 40, "reportIds": ["NDT-RPT-001"], "filmIds": ["FILM-RT-001"]},
        )
    )
    assert submit["nextStatus"] == "待审查"

    reports = assert_ok(client.get(f"/projects/{project_id}/ndt/reports"))
    assert any(report["status"] == "待提交" for report in reports["items"])

    rectification = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/rectifications",
            json={"rectificationId": "NDT-FB-001", "description": "已补充底片索引。"},
        )
    )
    assert rectification["rectification"]["status"] == "已反馈"
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

    member = assert_ok(
        client.post(
            f"/projects/{project_id}/members",
            json={"userId": "USER-ADMIN-001", "role": "admin", "nodeScope": [16, 24, 40, 59]},
        )
    )
    assert member["member"]["name"] == "系统管理员"
    detail = assert_ok(client.get(f"/projects/{project_id}"))
    assert len(detail["members"]) == 5


def test_admin_project_creation_returns_four_initial_members_and_integration_gaps() -> None:
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
        )
    )
    assert len(created["detail"]["members"]) == 4

    gaps = assert_ok(client.get("/admin/integration-contract?status=后端缺失"))
    assert gaps["fields"][0]["frontendField"] == "drafts[].nodeNames"
    assert gaps["fields"][0]["endpoint"] == "/api/projects/{projectId}/submissions"


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


def test_litellm_failure_maps_to_ai_run_failed(monkeypatch) -> None:
    from apps.worker import tasks

    run = assert_ok(client.post("/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck"))

    class FailingLiteLLM:
        def chat_sync(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(tasks, "LiteLLMClient", FailingLiteLLM)
    result = tasks.ai_recheck.run("P-2026-HDCP-001", 24, run["runId"])
    stored = repo.find_one("ai_runs", run["runId"])

    assert result["status"] == "失败"
    assert stored["status"] == "失败"
    assert stored["errorCode"] == "AI_RUN_FAILED"


def test_export_artifact_uses_object_storage_when_available(monkeypatch) -> None:
    stored = {}

    def fake_put(bucket: str, object_name: str, data: bytes, *, content_type: str):
        stored["bucket"] = bucket
        stored["objectName"] = object_name
        stored["contentType"] = content_type
        stored["size"] = len(data)
        return f"minio://{bucket}/{object_name}"

    def fake_get(url: str, *, file_name: str | None = None):
        return f"https://minio.local/{url.removeprefix('minio://')}"

    monkeypatch.setattr("libs.db.repository.object_storage.put_bytes", fake_put)
    monkeypatch.setattr("libs.db.repository.object_storage.presigned_get_url", fake_get)

    export = assert_ok(client.post("/exports", json={"projectId": "P-2026-HDCP-001", "fileName": "contract.zip"}))
    signed = assert_ok(client.get(f"/exports/{export['exportId']}/download-url"))

    assert export["task"]["downloadUrl"].startswith("minio://exports/")
    assert stored["bucket"] == "exports"
    assert stored["contentType"] == "application/zip"
    assert stored["size"] > 0
    assert signed["url"].startswith("https://minio.local/exports/")


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length=None):
        return [dict(item) for item in self.docs]


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def count_documents(self, query):
        return len(self.docs)

    async def delete_many(self, query):
        self.docs.clear()

    async def insert_many(self, docs):
        self.docs.extend([dict(item) for item in docs])

    def find(self, query):
        return FakeCursor(self.docs)

    async def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None

    async def replace_one(self, query, replacement, upsert=False):
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = dict(replacement)
                return
        if upsert:
            self.docs.append(dict(replacement))


class FakeDatabase(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeCollection()
        return dict.__getitem__(self, key)


async def test_mongo_state_round_trip_persists_planned_collections() -> None:
    database = FakeDatabase()
    repo.state["projects"][0]["name"] = "Mongo round trip"
    await repo.flush_to_mongo(database)

    repo.reset()
    await repo.load_from_mongo(database)

    assert repo.require_project("P-2026-HDCP-001")["name"] == "Mongo round trip"
    assert database["project_nodes"].docs
    assert database["document_versions"].docs
    assert database["node_bindings"].docs
    assert database["admin_configs"].docs[0]["_singleton"] == "admin_config"
