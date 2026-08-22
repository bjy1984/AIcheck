"""Project-document reads are isolated by the active member's organization.

The break these tests catch is a route filtering only by project/node scope.  All
three participant organizations deliberately share project P-2026-HDCP-001 and
node 24, so node scope alone cannot make any of these assertions pass.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import apps.api.routes as routes_module
from apps.api import document_access_policy
from apps.api.main import app
from libs.db.repository import repo
from libs.db.seed import ROLE_ACTIONS
from libs.material_auto_classify import known_categories

client = TestClient(app)
PROJECT_ID = "P-2026-HDCP-001"
NODE_ID = 24

ACTORS = {
    "contractor_a": {
        "role": "contractor",
        "user_id": "USER-ORG-ISOLATION-CONTRACTOR-A",
        "org_id": "ORG-ORG-ISOLATION-CONTRACTOR-A",
        "org_name": "同名施工单位",
    },
    "contractor_b": {
        "role": "contractor",
        "user_id": "USER-ORG-ISOLATION-CONTRACTOR-B",
        "org_id": "ORG-ORG-ISOLATION-CONTRACTOR-B",
        "org_name": "同名施工单位",
    },
    "ndt": {
        "role": "ndt",
        "user_id": "USER-ORG-ISOLATION-NDT",
        "org_id": "ORG-ORG-ISOLATION-NDT",
        "org_name": "隔离测试无损检测单位",
    },
    "inspection": {
        "role": "inspection",
        "user_id": "USER-ORG-ISOLATION-INSPECTION",
        "org_id": "ORG-ORG-ISOLATION-INSPECTION",
        "org_name": "隔离测试监检单位",
    },
    "owner": {
        "role": "owner",
        "user_id": "USER-ORG-ISOLATION-OWNER",
        "org_id": "ORG-ORG-ISOLATION-OWNER",
        "org_name": "隔离测试建设单位",
    },
    "admin": {
        "role": "admin",
        "user_id": "USER-ORG-ISOLATION-ADMIN",
        "org_id": "ORG-ORG-ISOLATION-ADMIN",
        "org_name": "隔离测试平台管理单位",
    },
}

DOCUMENTS = {
    "contractor_a": "DOC-CONTRACTOR-A",
    "contractor_b": "DOC-CONTRACTOR-B",
    "ndt": "DOC-NDT-A",
}


def _headers(actor: str) -> dict[str, str]:
    identity = ACTORS[actor]
    return {
        "X-Role": str(identity["role"]),
        "X-User-Id": str(identity["user_id"]),
    }


def _policy_request(actor: str) -> Request:
    headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in _headers(actor).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "path": "/policy-probe",
            "query_string": b"",
            "headers": headers,
        }
    )


def _without_tenant_metadata(value):
    if isinstance(value, dict):
        return {
            key: _without_tenant_metadata(item)
            for key, item in value.items()
            if key != "tenantId"
        }
    if isinstance(value, list):
        return [_without_tenant_metadata(item) for item in value]
    return value


def _document(document_id: str, actor: str, *, submitted: bool) -> dict:
    identity = ACTORS[actor]
    return {
        "id": document_id,
        "projectId": PROJECT_ID,
        "fileName": f"{document_id}.docx",
        "fileType": "docx",
        "sourceOrgId": identity["org_id"],
        "sourceOrgName": identity["org_name"],
        "uploaderName": actor,
        "currentVersionId": f"DV-{document_id}-V1",
        "fileStatus": "已上传",
        "poolSubmissionStatus": "已提交" if submitted else "草稿",
        "currentOcrStatus": "已识别",
        "updatedAt": "2026-08-22 09:00:00",
        "actions": ["file:view", "file:preview", "file:download"],
    }


@pytest.fixture(autouse=True)
def isolated_document_organizations():
    original_state = repo.state
    repo.state = deepcopy(original_state)
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None

    repo.state["project_members"] = [
        item
        for item in repo.state.get("project_members", [])
        if item.get("projectId") != PROJECT_ID
    ]
    for key, identity in ACTORS.items():
        repo.state["project_members"].append(
            {
                "id": f"PM-ORG-ISOLATION-{key.upper()}",
                "projectId": PROJECT_ID,
                "userId": identity["user_id"],
                "name": key,
                "orgId": identity["org_id"],
                "orgName": identity["org_name"],
                "role": identity["role"],
                "nodeScope": [NODE_ID],
                "actions": ROLE_ACTIONS[str(identity["role"])],
                "status": "启用",
            }
        )

    documents = [
        _document(DOCUMENTS["contractor_a"], "contractor_a", submitted=True),
        _document(DOCUMENTS["contractor_b"], "contractor_b", submitted=False),
        _document(DOCUMENTS["ndt"], "ndt", submitted=False),
    ]
    for document in documents:
        document["currentOcrStatus"] = "识别中"
    repo.state["documents"] = documents
    repo.state["versions"] = [
        {
            "id": document["currentVersionId"],
            "documentId": document["id"],
            "versionNo": "V1",
            "hash": f"sha256-{document['id']}",
            "fileSize": 128,
            "storageBucket": "documents",
            "storageKey": f"mock://documents/{document['id']}",
            "ocrStatus": "已识别",
            "sliceStatus": "已切片",
            "vectorStatus": "已向量化",
            "isCurrent": True,
        }
        for document in documents
    ]
    repo.state["knowledge_files"] = [
        {
            "id": f"KF-{document['id']}",
            "fileName": document["fileName"],
            "sourceId": "KS-PROJECT-FILE",
            "projectId": PROJECT_ID,
            "documentId": document["id"],
            "documentVersionId": document["currentVersionId"],
            "sourceOrgId": document["sourceOrgId"],
            "sourceOrgName": document["sourceOrgName"],
            "ocrStatus": "已识别",
            "sliceStatus": "已切片",
            "vectorStatus": "已向量化",
        }
        for document in documents
    ]
    repo.state["bindings"] = [
        {
            "id": f"BIND-{document['id']}",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "documentId": document["id"],
            "documentVersionId": document["currentVersionId"],
            "fileName": document["fileName"],
            "bindingStatus": (
                "已提交" if document["poolSubmissionStatus"] == "已提交" else "草稿挂载"
            ),
        }
        for document in documents
    ]
    repo.state["node_evidence_links"] = [
        {
            "id": "NEL-CONTRACTOR-A",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "reviewPointId": "RP-ORG-ISOLATION",
            "documentId": DOCUMENTS["contractor_a"],
            "documentVersionId": f"DV-{DOCUMENTS['contractor_a']}-V1",
            "fileName": "CONTRACTOR-A.docx",
            "quotedText": "CONTRACTOR A OCR",
            "pageNo": 1,
            "bbox": [0, 0, 100, 20],
            "formalEvidenceEligible": True,
            "manualStatus": "confirmed",
        },
        {
            "id": "NEL-CONTRACTOR-B",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "reviewPointId": "RP-ORG-ISOLATION",
            "documentId": DOCUMENTS["contractor_b"],
            "documentVersionId": f"DV-{DOCUMENTS['contractor_b']}-V1",
            "fileName": "FOREIGN-SECRET.docx",
            "quotedText": "FOREIGN OCR SECRET",
            "pageNo": 1,
            "bbox": [0, 0, 100, 20],
            "formalEvidenceEligible": True,
            "manualStatus": "confirmed",
        },
        {
            "id": "NEL-NDT-ADVISORY",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "reviewPointId": "RP-ORG-ISOLATION",
            "documentId": DOCUMENTS["ndt"],
            "documentVersionId": f"DV-{DOCUMENTS['ndt']}-V1",
            "fileName": "NDT-FOREIGN-SECRET.docx",
            "quotedText": "NDT FOREIGN OCR SECRET",
            "formalEvidenceEligible": False,
            "manualStatus": "pending",
        },
    ]
    repo.state["submission_drafts"] = []
    repo.state["submissions"] = []
    repo.state["ndt_reports"] = []
    repo.state["ndt_feedback"] = []
    repo.state["ndt_films"] = []
    repo.state["ndt_records"] = []
    try:
        yield
    finally:
        repo.state = original_state


@pytest.mark.parametrize(
    ("actor", "expected"),
    [
        ("contractor_a", {"DOC-CONTRACTOR-A"}),
        ("contractor_b", {"DOC-CONTRACTOR-B"}),
        ("ndt", {"DOC-NDT-A"}),
        ("inspection", {"DOC-CONTRACTOR-A", "DOC-CONTRACTOR-B", "DOC-NDT-A"}),
        ("owner", {"DOC-CONTRACTOR-A"}),
    ],
)
def test_project_file_list_is_actor_organization_scoped(actor: str, expected: set[str]) -> None:
    response = client.get(f"/api/projects/{PROJECT_ID}/documents", headers=_headers(actor))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, response.text
    assert {item["id"] for item in payload["data"]["items"]} == expected


@pytest.mark.parametrize(
    ("actor", "expected"),
    [
        ("contractor_a", {"DOC-CONTRACTOR-A"}),
        ("contractor_b", {"DOC-CONTRACTOR-B"}),
        ("ndt", {"DOC-NDT-A"}),
        ("inspection", {"DOC-CONTRACTOR-A", "DOC-CONTRACTOR-B", "DOC-NDT-A"}),
        ("owner", {"DOC-CONTRACTOR-A"}),
    ],
)
def test_node_package_does_not_leak_files_bindings_or_versions(actor: str, expected: set[str]) -> None:
    response = client.get(
        f"/api/projects/{PROJECT_ID}/nodes/{NODE_ID}/package", headers=_headers(actor)
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, response.text
    data = payload["data"]
    assert {item["id"] for item in data["projectFiles"]} == expected
    assert {item["documentId"] for item in data["bindings"]} == expected
    assert {item["documentId"] for item in data["availableVersions"]} == expected


@pytest.mark.parametrize(
    ("actor", "document_id"),
    [
        ("contractor_a", "DOC-CONTRACTOR-B"),
        ("contractor_a", "DOC-NDT-A"),
        ("contractor_b", "DOC-CONTRACTOR-A"),
        ("contractor_b", "DOC-NDT-A"),
        ("ndt", "DOC-CONTRACTOR-A"),
        ("ndt", "DOC-CONTRACTOR-B"),
        ("owner", "DOC-NDT-A"),
    ],
)
@pytest.mark.parametrize(
    "path_suffix",
    [
        "",
        "/preview-url",
        "/download-url",
        "/original",
        "/office-preview",
        "/versions",
    ],
)
def test_guessed_document_ids_are_rejected_on_every_read_path(
    actor: str, document_id: str, path_suffix: str
) -> None:
    response = client.get(
        f"/api/projects/{PROJECT_ID}/documents/{document_id}{path_suffix}",
        headers=_headers(actor),
    )
    payload = response.json()
    assert response.status_code in {200, 403, 404}, response.text
    assert payload["code"] in {403, 40404}, response.text


def test_generic_signed_download_cannot_bypass_document_organization_guard() -> None:
    response = client.get(
        "/api/downloads/DOC-CONTRACTOR-B/signed-url", headers=_headers("contractor_a")
    )
    assert response.json()["code"] in {403, 40404}, response.text


def test_source_org_id_wins_when_two_organizations_have_the_same_display_name() -> None:
    own = client.get(
        f"/api/projects/{PROJECT_ID}/documents/DOC-CONTRACTOR-A",
        headers=_headers("contractor_a"),
    )
    foreign = client.get(
        f"/api/projects/{PROJECT_ID}/documents/DOC-CONTRACTOR-B",
        headers=_headers("contractor_a"),
    )
    assert own.json()["code"] == 0, own.text
    assert foreign.json()["code"] in {403, 40404}, foreign.text


def test_legacy_document_without_source_org_id_uses_normalized_name_fallback() -> None:
    legacy = _document("DOC-LEGACY-CONTRACTOR-A", "contractor_a", submitted=True)
    legacy.pop("sourceOrgId")
    legacy["sourceOrgName"] = "  同名施工单位  "
    repo.state["documents"].append(legacy)
    repo.state["versions"].append(
        {
            "id": legacy["currentVersionId"],
            "documentId": legacy["id"],
            "versionNo": "V1",
            "storageKey": f"mock://documents/{legacy['id']}",
            "isCurrent": True,
        }
    )

    response = client.get(
        f"/api/projects/{PROJECT_ID}/documents/{legacy['id']}",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] == 0, response.text


def test_upload_session_source_org_is_resolved_from_active_member_not_json() -> None:
    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session",
        headers={**_headers("contractor_a"), "Idempotency-Key": "source-org-member-only"},
        json={
            "sourceOrgId": "ORG-CALLER-SPOOFED",
            "sourceOrgName": "伪造单位",
            "files": [
                {
                    "fileName": "member-source-org.pdf",
                    "fileType": "application/pdf",
                    "fileSize": 128,
                    "sourceOrgId": "ORG-FILE-SPOOFED",
                    "sourceOrgName": "文件内伪造单位",
                }
            ],
        },
    )
    assert response.json()["code"] == 0, response.text
    document_id = response.json()["data"]["uploadUrls"][0]["documentId"]
    document = repo.find_one("documents", document_id)
    knowledge_file = next(
        item for item in repo.state["knowledge_files"] if item.get("documentId") == document_id
    )
    assert document["sourceOrgId"] == ACTORS["contractor_a"]["org_id"]
    assert document["sourceOrgName"] == ACTORS["contractor_a"]["org_name"]
    assert knowledge_file["sourceOrgId"] == ACTORS["contractor_a"]["org_id"]
    assert knowledge_file["sourceOrgName"] == ACTORS["contractor_a"]["org_name"]


def test_global_search_does_not_enumerate_foreign_organization_documents() -> None:
    response = client.get(
        f"/api/search?projectId={PROJECT_ID}&type=document",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] == 0, response.text
    assert {item["id"] for item in response.json()["data"]["items"]} == {
        DOCUMENTS["contractor_a"]
    }


def test_node_live_status_only_reports_processing_documents_visible_to_actor() -> None:
    response = client.get(
        f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/live-status",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] == 0, response.text
    data = response.json()["data"]
    assert data["processingDocumentCount"] == 1
    assert {item["documentId"] for item in data["processingDocuments"]} == {
        DOCUMENTS["contractor_a"]
    }


def test_workbench_summary_document_metric_uses_actor_visible_documents() -> None:
    response = client.get(
        f"/api/projects/{PROJECT_ID}/workbench/summary?role=contractor",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] == 0, response.text
    metrics = {item["key"]: item["value"] for item in response.json()["data"]["metrics"]}
    assert metrics["document"] == 1


def test_node_package_evidence_readiness_excludes_foreign_formal_and_advisory_content() -> None:
    response = client.get(
        f"/api/projects/{PROJECT_ID}/nodes/{NODE_ID}/package",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] == 0, response.text
    data = response.json()["data"]
    readiness = data["evidenceReadiness"]
    assert {item["documentId"] for item in data["nodeEvidenceLinks"]} == {
        DOCUMENTS["contractor_a"]
    }
    assert readiness["advisoryEvidenceLinks"] == []
    assert readiness["advisoryEvidenceCount"] == 0
    assert readiness["inputDocumentVersionIds"] == [f"DV-{DOCUMENTS['contractor_a']}-V1"]
    assert readiness["supportingDocumentCount"] == 1
    serialized = response.text
    for secret in (
        DOCUMENTS["contractor_b"],
        DOCUMENTS["ndt"],
        "FOREIGN-SECRET.docx",
        "FOREIGN OCR SECRET",
        "NDT-FOREIGN-SECRET.docx",
        "NDT FOREIGN OCR SECRET",
    ):
        assert secret not in serialized


@pytest.mark.parametrize("duplicate_first", [True, False])
def test_duplicate_active_memberships_fail_closed_independent_of_list_order(
    duplicate_first: bool,
) -> None:
    original_member = next(
        item
        for item in repo.state["project_members"]
        if item.get("userId") == ACTORS["contractor_a"]["user_id"]
        and item.get("projectId") == PROJECT_ID
    )
    duplicate = {
        **original_member,
        "id": "PM-ORG-ISOLATION-AMBIGUOUS",
        "orgId": ACTORS["contractor_b"]["org_id"],
        "orgName": ACTORS["contractor_b"]["org_name"],
    }
    if duplicate_first:
        repo.state["project_members"].insert(0, duplicate)
    else:
        repo.state["project_members"].append(duplicate)

    listed = client.get(f"/api/projects/{PROJECT_ID}/documents", headers=_headers("contractor_a"))
    own = client.get(
        f"/api/projects/{PROJECT_ID}/documents/{DOCUMENTS['contractor_a']}",
        headers=_headers("contractor_a"),
    )
    foreign = client.get(
        f"/api/projects/{PROJECT_ID}/documents/{DOCUMENTS['contractor_b']}",
        headers=_headers("contractor_a"),
    )
    assert listed.json()["data"]["items"] == [], listed.text
    assert own.json()["code"] == 403, own.text
    assert foreign.json()["code"] == 403, foreign.text


def test_same_name_organization_lookup_rejects_ambiguous_stable_id_resolution() -> None:
    org_name = "注册同名组织"
    repo.state["admin_config"]["orgUnits"].extend(
        [
            {"id": "ORG-REGISTER-SAME-A", "name": org_name, "type": "contractor"},
            {"id": "ORG-REGISTER-SAME-B", "name": org_name, "type": "contractor"},
        ]
    )
    assert routes_module.find_org_unit(None, org_name) is None
    assert routes_module.find_org_unit("ORG-REGISTER-SAME-A", org_name)["id"] == "ORG-REGISTER-SAME-A"


def test_cross_organization_replace_is_rejected_before_foreign_version_mutation() -> None:
    foreign = repo.find_one("documents", DOCUMENTS["contractor_b"])
    before_version_id = foreign["currentVersionId"]
    before_version_count = len(repo.versions_for_document(foreign["id"]))

    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session",
        headers={**_headers("contractor_a"), "Idempotency-Key": "foreign-replace-forbidden"},
        json={
            "files": [
                {
                    "fileName": "foreign-replacement.pdf",
                    "fileType": "application/pdf",
                    "fileSize": 128,
                    "replaceDocumentId": foreign["id"],
                }
            ]
        },
    )

    assert response.json()["code"] in {403, 40404}, response.text
    assert foreign["currentVersionId"] == before_version_id
    assert len(repo.versions_for_document(foreign["id"])) == before_version_count


def test_submission_detail_cannot_reverse_lookup_a_foreign_document() -> None:
    submission_id = "SUB-FOREIGN-ORG-ISOLATION"
    foreign_id = DOCUMENTS["contractor_b"]
    repo.state["submissions"].append(
        {
            "submissionId": submission_id,
            "snapshotId": "SNAP-FOREIGN-ORG-ISOLATION",
            "projectId": PROJECT_ID,
            "submissionType": "document",
            "nodeIds": [NODE_ID],
            "bindingIds": [f"BIND-{foreign_id}"],
            "documentIds": [foreign_id],
            "createdTodoIds": [],
            "submittedAt": "2026-08-22 09:30:00",
            "nextStatus": "待审查",
        }
    )

    response = client.get(
        f"/api/projects/{PROJECT_ID}/submissions/{submission_id}",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] in {403, 40404}, response.text


def test_upload_duplicate_projection_does_not_name_foreign_matching_documents() -> None:
    content = b"organization-isolated-duplicate-content"
    digest = hashlib.sha256(content).hexdigest()
    foreign_document = repo.find_one("documents", DOCUMENTS["contractor_b"])
    foreign_version = repo.find_one("versions", foreign_document["currentVersionId"])
    foreign_version["hash"] = f"sha256-{digest}"

    created = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session",
        headers={**_headers("contractor_a"), "Idempotency-Key": "isolated-duplicate-create"},
        json={
            "files": [
                {
                    "fileName": "same-content.pdf",
                    "fileType": "application/pdf",
                    "fileSize": len(content),
                    "contentHash": digest,
                }
            ]
        },
    )
    assert created.json()["code"] == 0, created.text
    session = created.json()["data"]
    target = session["uploadUrls"][0]
    uploaded = client.put(
        target["url"],
        headers={**_headers("contractor_a"), **target["headers"]},
        content=content,
    )
    assert uploaded.json()["code"] == 0, uploaded.text

    completed = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session/{session['uploadSessionId']}/complete",
        headers={**_headers("contractor_a"), "Idempotency-Key": "isolated-duplicate-complete"},
        json={
            "completedFiles": [
                {
                    "documentVersionId": target["documentVersionId"],
                    "fileSize": len(content),
                    "contentHash": digest,
                }
            ]
        },
    )
    assert completed.json()["code"] == 0, completed.text
    assert completed.json()["data"]["duplicates"] == []


def test_submission_list_omits_foreign_submissions_and_drafts_with_derived_ids_counts() -> None:
    repo.state["submission_drafts"].extend(
        [
            {
                "draftId": "DRAFT-OWN-LIST",
                "projectId": PROJECT_ID,
                "nodeIds": [NODE_ID],
                "bindingIds": [f"BIND-{DOCUMENTS['contractor_a']}"],
                "savedAt": "2026-08-22 10:00:00",
            },
            {
                "draftId": "DRAFT-FOREIGN-LIST",
                "projectId": PROJECT_ID,
                "nodeIds": [NODE_ID],
                "bindingIds": [f"BIND-{DOCUMENTS['ndt']}"],
                "savedAt": "2026-08-22 10:01:00",
            },
        ]
    )
    repo.state["submissions"].extend(
        [
            {
                "submissionId": "SUB-OWN-LIST",
                "snapshotId": "SNAP-OWN-LIST",
                "projectId": PROJECT_ID,
                "submissionType": "document",
                "nodeIds": [NODE_ID],
                "bindingIds": [f"BIND-{DOCUMENTS['contractor_a']}"],
                "documentIds": [DOCUMENTS["contractor_a"]],
                "createdTodoIds": [],
                "submittedAt": "2026-08-22 10:02:00",
            },
            {
                "submissionId": "SUB-FOREIGN-LIST",
                "snapshotId": "SNAP-FOREIGN-LIST",
                "projectId": PROJECT_ID,
                "submissionType": "document",
                "nodeIds": [NODE_ID],
                "bindingIds": [f"BIND-{DOCUMENTS['ndt']}"],
                "documentIds": [DOCUMENTS["ndt"]],
                "createdTodoIds": [],
                "submittedAt": "2026-08-22 10:03:00",
            },
        ]
    )

    response = client.get(
        f"/api/projects/{PROJECT_ID}/submissions",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] == 0, response.text
    data = response.json()["data"]
    assert {item["draftId"] for item in data["drafts"]} == {"DRAFT-OWN-LIST"}
    assert data["drafts"][0]["bindingCount"] == 1
    assert {item["submissionId"] for item in data["submissions"]} == {"SUB-OWN-LIST"}
    assert data["submissions"][0]["documentIds"] == [DOCUMENTS["contractor_a"]]
    assert data["submissions"][0]["documentCount"] == 1
    assert data["submissions"][0]["bindingCount"] == 1


def test_direct_foreign_submission_draft_is_non_enumerating_and_leaks_no_binding_ids() -> None:
    draft_id = "DRAFT-FOREIGN-DIRECT"
    repo.state["submission_drafts"].append(
        {
            "draftId": draft_id,
            "projectId": PROJECT_ID,
            "nodeIds": [NODE_ID],
            "bindingIds": [f"BIND-{DOCUMENTS['contractor_b']}"],
            "savedAt": "2026-08-22 10:04:00",
        }
    )
    response = client.get(
        f"/api/projects/{PROJECT_ID}/submissions/drafts/{draft_id}",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert DOCUMENTS["contractor_b"] not in response.text


def _add_ndt_projection_fixtures() -> None:
    repo.state["ndt_reports"].extend(
        [
            {
                "id": "NDT-RPT-OWN",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "fileId": DOCUMENTS["contractor_a"],
                "reportNo": "OWN-REPORT",
                "conclusion": "OWN REPORT CONCLUSION",
                "status": "待提交",
            },
            {
                "id": "NDT-RPT-FOREIGN",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "fileId": DOCUMENTS["contractor_b"],
                "reportNo": "FOREIGN-REPORT",
                "conclusion": "FOREIGN REPORT SECRET",
                "status": "待提交",
            },
        ]
    )
    repo.state["ndt_films"].extend(
        [
            {"id": "FILM-OWN", "projectId": PROJECT_ID, "nodeId": NODE_ID, "filmNo": "OWN"},
            {"id": "FILM-FOREIGN", "projectId": PROJECT_ID, "nodeId": NODE_ID, "filmNo": "FOREIGN"},
        ]
    )
    repo.state["ndt_records"].extend(
        [
            {"id": "NDT-REC-OWN", "projectId": PROJECT_ID, "nodeId": NODE_ID, "reportId": "NDT-RPT-OWN", "filmId": "FILM-OWN"},
            {"id": "NDT-REC-FOREIGN", "projectId": PROJECT_ID, "nodeId": NODE_ID, "reportId": "NDT-RPT-FOREIGN", "filmId": "FILM-FOREIGN"},
        ]
    )
    repo.state["ndt_feedback"].extend(
        [
            {
                "id": "NDT-FB-OWN",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "status": "待反馈",
                "description": "OWN FEEDBACK",
                "relatedReportIds": ["NDT-RPT-OWN"],
                "relatedFilmIds": ["FILM-OWN"],
                "createdAt": "2026-08-22 10:05:00",
            },
            {
                "id": "NDT-FB-FOREIGN",
                "projectId": PROJECT_ID,
                "nodeId": NODE_ID,
                "status": "待反馈",
                "description": "FOREIGN FEEDBACK SECRET",
                "relatedReportIds": ["NDT-RPT-FOREIGN"],
                "relatedFilmIds": ["FILM-FOREIGN"],
                "createdAt": "2026-08-22 10:06:00",
            },
        ]
    )


def test_ndt_report_and_feedback_lists_and_summary_derive_only_visible_records() -> None:
    _add_ndt_projection_fixtures()
    reports = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/reports",
        headers=_headers("contractor_a"),
    )
    feedback = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/inspection-feedback",
        headers=_headers("contractor_a"),
    )
    summary = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/summary",
        headers=_headers("contractor_a"),
    )
    assert {item["id"] for item in reports.json()["data"]["items"]} == {"NDT-RPT-OWN"}
    assert {item["id"] for item in feedback.json()["data"]["items"]} == {"NDT-FB-OWN"}
    assert summary.json()["data"] == {
        "filmCount": 1,
        "recordCount": 1,
        "reportCount": 1,
        "feedbackCount": 1,
    }
    combined = reports.text + feedback.text + summary.text
    for secret in ("FOREIGN-REPORT", "FOREIGN REPORT SECRET", "FOREIGN FEEDBACK SECRET"):
        assert secret not in combined


def test_ndt_feedback_detail_filters_nested_reports_records_films_and_evidence() -> None:
    _add_ndt_projection_fixtures()
    own = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/inspection-feedback/NDT-FB-OWN",
        headers=_headers("contractor_a"),
    )
    foreign = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/inspection-feedback/NDT-FB-FOREIGN",
        headers=_headers("contractor_a"),
    )
    assert own.json()["code"] == 0, own.text
    data = own.json()["data"]
    assert {item["id"] for item in data["reports"]} == {"NDT-RPT-OWN"}
    assert {item["id"] for item in data["films"]} == {"FILM-OWN"}
    assert {item["id"] for item in data["records"]} == {"NDT-REC-OWN"}
    assert {item["documentId"] for item in data["evidenceLinks"]} == {
        DOCUMENTS["contractor_a"]
    }
    assert foreign.json()["code"] in {403, 40404}, foreign.text
    for secret in ("FOREIGN REPORT SECRET", "FOREIGN FEEDBACK SECRET", "FOREIGN OCR SECRET"):
        assert secret not in own.text


def test_ndt_report_detail_matches_list_visibility_and_filters_feedback_expansion() -> None:
    _add_ndt_projection_fixtures()
    own = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/reports/NDT-RPT-OWN",
        headers=_headers("contractor_a"),
    )
    foreign = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/reports/NDT-RPT-FOREIGN",
        headers=_headers("contractor_a"),
    )
    assert own.json()["code"] == 0, own.text
    assert {item["id"] for item in own.json()["data"]["feedback"]} == {"NDT-FB-OWN"}
    assert foreign.json()["code"] in {403, 40404}, foreign.text
    assert "FOREIGN FEEDBACK SECRET" not in own.text


def test_batch_classify_only_returns_actor_readable_document_suggestions() -> None:
    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/batch-classify",
        headers={**_headers("contractor_a"), "Idempotency-Key": "isolated-batch-classify"},
        json={},
    )
    assert response.json()["code"] == 0, response.text
    assert {item["documentId"] for item in response.json()["data"]["suggestions"]} == {
        DOCUMENTS["contractor_a"]
    }


def test_duplicate_inspection_membership_denies_unbound_documents_in_list_and_search() -> None:
    inspection_member = next(
        item
        for item in repo.state["project_members"]
        if item.get("userId") == ACTORS["inspection"]["user_id"]
        and item.get("projectId") == PROJECT_ID
    )
    repo.state["project_members"].append(
        {**inspection_member, "id": "PM-INSPECTION-AMBIGUOUS", "orgId": "ORG-OTHER-INSPECTION"}
    )
    repo.state["bindings"] = [
        item
        for item in repo.state["bindings"]
        if item.get("documentId") != DOCUMENTS["contractor_b"]
    ]

    listed = client.get(f"/api/projects/{PROJECT_ID}/documents", headers=_headers("inspection"))
    searched = client.get(
        f"/api/search?projectId={PROJECT_ID}&type=document",
        headers=_headers("inspection"),
    )
    assert listed.json()["data"]["items"] == [], listed.text
    assert searched.json()["data"]["items"] == [], searched.text


def test_valid_nonempty_scope_can_still_see_own_unbound_upload() -> None:
    repo.state["bindings"] = [
        item
        for item in repo.state["bindings"]
        if item.get("documentId") != DOCUMENTS["contractor_a"]
    ]
    response = client.get(f"/api/projects/{PROJECT_ID}/documents", headers=_headers("contractor_a"))
    assert {item["id"] for item in response.json()["data"]["items"]} == {
        DOCUMENTS["contractor_a"]
    }


def test_submission_policy_rejects_same_org_document_from_another_project() -> None:
    foreign = _document("DOC-CROSS-PROJECT-SUBMISSION", "contractor_a", submitted=True)
    foreign["projectId"] = "P-CROSS-PROJECT-FOREIGN"
    foreign["nodeId"] = NODE_ID
    repo.state["documents"].append(foreign)
    submission = {
        "submissionId": "SUB-CROSS-PROJECT-LINK",
        "projectId": PROJECT_ID,
        "submissionType": "document",
        "nodeIds": [NODE_ID],
        "bindingIds": [],
        "documentIds": [foreign["id"]],
    }

    assert not routes_module.submission_record_visible_for_request(
        _policy_request("contractor_a"),
        submission,
    )


def test_ndt_report_policy_rejects_same_org_document_from_another_project() -> None:
    foreign = _document("DOC-CROSS-PROJECT-NDT", "ndt", submitted=True)
    foreign["projectId"] = "P-CROSS-PROJECT-FOREIGN"
    foreign["nodeId"] = NODE_ID
    repo.state["documents"].append(foreign)
    report = {
        "id": "NDT-RPT-CROSS-PROJECT-LINK",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "fileId": foreign["id"],
        "relatedFilmIds": [],
    }

    assert not routes_module.ndt_report_document_visible_for_request(
        _policy_request("ndt"),
        PROJECT_ID,
        report,
    )


def test_standalone_ndt_film_and_record_routes_follow_backing_document_visibility() -> None:
    _add_ndt_projection_fixtures()
    films = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/films",
        headers=_headers("contractor_a"),
    )
    records = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/records",
        headers=_headers("contractor_a"),
    )
    foreign_detail = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/films/FILM-FOREIGN",
        headers=_headers("contractor_a"),
    )
    assert {item["id"] for item in films.json()["data"]["items"]} == {"FILM-OWN"}
    assert {item["id"] for item in records.json()["data"]["items"]} == {"NDT-REC-OWN"}
    assert foreign_detail.json()["code"] in {403, 40404}, foreign_detail.text
    assert "FOREIGN" not in films.text + records.text + foreign_detail.text


def test_unbacked_ndt_rows_require_stable_org_provenance_for_participants() -> None:
    _add_ndt_projection_fixtures()
    repo.state["ndt_films"].extend(
        [
            {"id": "FILM-UNBACKED-OWN", "projectId": PROJECT_ID, "nodeId": NODE_ID, "filmNo": "OWN-UNBACKED", "sourceOrgId": ACTORS["contractor_a"]["org_id"], "sourceOrgName": ACTORS["contractor_a"]["org_name"]},
            {"id": "FILM-UNBACKED-UNKNOWN", "projectId": PROJECT_ID, "nodeId": NODE_ID, "filmNo": "UNKNOWN-SECRET"},
        ]
    )
    repo.state["ndt_records"].extend(
        [
            {"id": "REC-UNBACKED-OWN", "projectId": PROJECT_ID, "nodeId": NODE_ID, "sourceOrgId": ACTORS["contractor_a"]["org_id"], "sourceOrgName": ACTORS["contractor_a"]["org_name"]},
            {"id": "REC-UNBACKED-UNKNOWN", "projectId": PROJECT_ID, "nodeId": NODE_ID, "conclusion": "UNKNOWN RECORD SECRET"},
        ]
    )
    films = client.get(f"/api/projects/{PROJECT_ID}/ndt/films", headers=_headers("contractor_a"))
    records = client.get(f"/api/projects/{PROJECT_ID}/ndt/records", headers=_headers("contractor_a"))
    assert {item["id"] for item in films.json()["data"]["items"]} == {
        "FILM-OWN",
        "FILM-UNBACKED-OWN",
    }
    assert {item["id"] for item in records.json()["data"]["items"]} == {
        "NDT-REC-OWN",
        "REC-UNBACKED-OWN",
    }
    assert "UNKNOWN-SECRET" not in films.text
    assert "UNKNOWN RECORD SECRET" not in records.text


def test_new_unbacked_ndt_rows_take_source_org_from_active_member_not_json() -> None:
    film_response = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/films",
        headers={**_headers("ndt"), "Idempotency-Key": "ndt-film-source-org"},
        json={
            "nodeId": NODE_ID,
            "filmNo": "FILM-SOURCE-ORG",
            "weldNo": "W-SOURCE-ORG",
            "method": "RT",
            "sourceOrgId": "ORG-SPOOFED",
            "sourceOrgName": "伪造组织",
        },
    )
    record_response = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/records/import",
        headers={**_headers("ndt"), "Idempotency-Key": "ndt-record-source-org"},
        json={
            "nodeId": NODE_ID,
            "rows": [
                {
                    "recordNo": "REC-SOURCE-ORG",
                    "weldNo": "W-SOURCE-ORG",
                    "method": "RT",
                    "sourceOrgId": "ORG-SPOOFED",
                    "sourceOrgName": "伪造组织",
                }
            ],
        },
    )
    assert film_response.json()["code"] == 0, film_response.text
    assert record_response.json()["code"] == 0, record_response.text
    film = film_response.json()["data"]["film"]
    record = record_response.json()["data"]["records"][0]
    for item in (film, record):
        assert item["sourceOrgId"] == ACTORS["ndt"]["org_id"]
        assert item["sourceOrgName"] == ACTORS["ndt"]["org_name"]


def test_mixed_ndt_relations_require_every_report_and_film_to_be_visible() -> None:
    _add_ndt_projection_fixtures()
    own_report = repo.find_one("ndt_reports", "NDT-RPT-OWN")
    own_report["relatedFilmIds"] = ["FILM-FOREIGN"]
    repo.state["ndt_records"].append(
        {
            "id": "NDT-REC-MIXED",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "reportId": "NDT-RPT-OWN",
            "filmId": "FILM-FOREIGN",
            "conclusion": "MIXED FOREIGN RECORD SECRET",
        }
    )
    repo.state["ndt_feedback"].append(
        {
            "id": "NDT-FB-MIXED",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "status": "待反馈",
            "description": "MIXED FOREIGN FILM SECRET",
            "relatedReportIds": ["NDT-RPT-OWN"],
            "relatedFilmIds": ["FILM-FOREIGN"],
            "createdAt": "2026-08-22 11:00:00",
        }
    )

    reports = client.get(f"/api/projects/{PROJECT_ID}/ndt/reports", headers=_headers("contractor_a"))
    records = client.get(f"/api/projects/{PROJECT_ID}/ndt/records", headers=_headers("contractor_a"))
    feedback = client.get(f"/api/projects/{PROJECT_ID}/ndt/inspection-feedback", headers=_headers("contractor_a"))
    mixed_detail = client.get(
        f"/api/projects/{PROJECT_ID}/ndt/inspection-feedback/NDT-FB-MIXED",
        headers=_headers("contractor_a"),
    )
    assert "NDT-RPT-OWN" not in {item["id"] for item in reports.json()["data"]["items"]}
    assert "NDT-REC-MIXED" not in {item["id"] for item in records.json()["data"]["items"]}
    assert "NDT-FB-MIXED" not in {item["id"] for item in feedback.json()["data"]["items"]}
    assert mixed_detail.json()["code"] in {403, 40404}, mixed_detail.text
    combined = reports.text + records.text + feedback.text + mixed_detail.text
    assert "MIXED FOREIGN RECORD SECRET" not in combined
    assert "MIXED FOREIGN FILM SECRET" not in combined


@pytest.mark.parametrize(
    "submission",
    [
        {
            "submissionId": "NDT-SUB-FOREIGN-REPORT",
            "reportIds": ["NDT-RPT-FOREIGN"],
            "filmIds": ["FILM-FOREIGN"],
        },
        {
            "submissionId": "NDT-SUB-MIXED-REFERENCES",
            "reportIds": ["NDT-RPT-OWN"],
            "filmIds": ["FILM-FOREIGN"],
        },
    ],
)
def test_direct_ndt_submission_validates_report_and_film_ids_and_never_returns_raw_snapshot(
    submission: dict,
) -> None:
    _add_ndt_projection_fixtures()
    submission_id = submission["submissionId"]
    repo.state["submissions"].append(
        {
            **submission,
            "snapshotId": f"SNAP-{submission_id}",
            "projectId": PROJECT_ID,
            "submissionType": "ndt",
            "nodeIds": [NODE_ID],
            "bindingIds": [],
            "documentIds": [],
            "createdTodoIds": [],
            "submittedAt": "2026-08-22 11:05:00",
            "snapshot": {
                "reports": [{"id": "RAW-FOREIGN", "conclusion": "RAW FOREIGN SNAPSHOT SECRET"}],
                "films": [{"id": "FILM-FOREIGN", "filmNo": "RAW FOREIGN FILM"}],
                "records": [{"id": "RAW-REC", "conclusion": "RAW FOREIGN RECORD"}],
            },
        }
    )
    response = client.get(
        f"/api/projects/{PROJECT_ID}/submissions/{submission_id}",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert "RAW FOREIGN" not in response.text


def test_visible_ndt_submission_snapshot_is_rebuilt_from_authorized_current_records() -> None:
    _add_ndt_projection_fixtures()
    submission_id = "NDT-SUB-OWN-SANITIZED"
    repo.state["submissions"].append(
        {
            "submissionId": submission_id,
            "snapshotId": f"SNAP-{submission_id}",
            "projectId": PROJECT_ID,
            "submissionType": "ndt",
            "nodeIds": [NODE_ID],
            "bindingIds": [],
            "documentIds": [],
            "reportIds": ["NDT-RPT-OWN"],
            "filmIds": ["FILM-OWN"],
            "createdTodoIds": [],
            "submittedAt": "2026-08-22 11:06:00",
            "snapshot": {
                "reports": [{"id": "RAW-FOREIGN", "conclusion": "RAW FOREIGN SNAPSHOT SECRET"}],
                "films": [{"id": "RAW-FILM", "filmNo": "RAW FOREIGN FILM"}],
                "records": [{"id": "RAW-REC", "conclusion": "RAW FOREIGN RECORD"}],
            },
        }
    )
    response = client.get(
        f"/api/projects/{PROJECT_ID}/submissions/{submission_id}",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] == 0, response.text
    snapshot = response.json()["data"]["snapshot"]
    assert {item["id"] for item in snapshot["reports"]} == {"NDT-RPT-OWN"}
    assert {item["id"] for item in snapshot["films"]} == {"FILM-OWN"}
    assert {item["id"] for item in snapshot["records"]} == {"NDT-REC-OWN"}
    assert "RAW FOREIGN" not in response.text


def test_foreign_ndt_film_patch_is_denied_before_any_field_or_provenance_mutation() -> None:
    _add_ndt_projection_fixtures()
    film = repo.find_one("ndt_films", "FILM-FOREIGN")
    before = deepcopy(film)
    response = client.patch(
        f"/api/projects/{PROJECT_ID}/ndt/films/{film['id']}",
        headers={**_headers("ndt"), "Idempotency-Key": "foreign-film-patch"},
        json={
            "filmNo": "MUTATED-BY-FOREIGN",
            "sourceOrgId": ACTORS["ndt"]["org_id"],
            "sourceOrgName": ACTORS["ndt"]["org_name"],
        },
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _without_tenant_metadata(film) == _without_tenant_metadata(before)


def test_own_ndt_film_patch_allowlists_fields_and_never_overwrites_source_org() -> None:
    film = {
        "id": "FILM-NDT-OWN-PATCH",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "filmNo": "BEFORE",
        "weldNo": "W-OWN",
        "method": "RT",
        "sourceOrgId": ACTORS["ndt"]["org_id"],
        "sourceOrgName": ACTORS["ndt"]["org_name"],
        "status": "待提交",
    }
    repo.state["ndt_films"].append(film)
    response = client.patch(
        f"/api/projects/{PROJECT_ID}/ndt/films/{film['id']}",
        headers={**_headers("ndt"), "Idempotency-Key": "own-film-patch"},
        json={
            "filmNo": "AFTER",
            "sourceOrgId": "ORG-SPOOFED",
            "sourceOrgName": "伪造组织",
            "projectId": "P-SPOOFED",
            "nodeId": 999,
            "status": "已通过",
        },
    )
    assert response.json()["code"] == 0, response.text
    assert film["filmNo"] == "AFTER"
    assert film["sourceOrgId"] == ACTORS["ndt"]["org_id"]
    assert film["sourceOrgName"] == ACTORS["ndt"]["org_name"]
    assert film["projectId"] == PROJECT_ID
    assert film["nodeId"] == NODE_ID
    assert film["status"] == "待提交"


def _add_ndt_owned_report_and_film() -> tuple[dict, dict]:
    report = {
        "id": "NDT-RPT-NDT-OWN",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "fileId": DOCUMENTS["ndt"],
        "reportNo": "NDT-OWN",
        "status": "待提交",
    }
    film = {
        "id": "FILM-NDT-OWN",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "filmNo": "NDT-OWN",
        "sourceOrgId": ACTORS["ndt"]["org_id"],
        "sourceOrgName": ACTORS["ndt"]["org_name"],
        "status": "待提交",
    }
    repo.state["ndt_reports"].append(report)
    repo.state["ndt_films"].append(film)
    repo.state["ndt_records"].append(
        {
            "id": "NDT-REC-NDT-OWN",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "reportId": report["id"],
            "filmId": film["id"],
        }
    )
    return report, film


def test_ndt_rectification_rejects_foreign_existing_new_and_mixed_relations_atomically() -> None:
    _add_ndt_projection_fixtures()
    own_report, _ = _add_ndt_owned_report_and_film()
    foreign_feedback = repo.find_one("ndt_feedback", "NDT-FB-FOREIGN")
    foreign_before = deepcopy(foreign_feedback)
    feedback_count = len(repo.state["ndt_feedback"])

    existing = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/rectifications",
        headers={**_headers("ndt"), "Idempotency-Key": "foreign-feedback-update"},
        json={"nodeId": NODE_ID, "rectificationId": foreign_feedback["id"], "description": "MUTATED"},
    )
    new_foreign = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/rectifications",
        headers={**_headers("ndt"), "Idempotency-Key": "foreign-feedback-create"},
        json={
            "nodeId": NODE_ID,
            "rectificationId": "NDT-FB-NEW-FOREIGN",
            "description": "FOREIGN CREATE",
            "reportIds": ["NDT-RPT-FOREIGN"],
            "filmIds": ["FILM-FOREIGN"],
        },
    )
    mixed = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/rectifications",
        headers={**_headers("ndt"), "Idempotency-Key": "mixed-feedback-create"},
        json={
            "nodeId": NODE_ID,
            "rectificationId": "NDT-FB-NEW-MIXED",
            "description": "MIXED CREATE",
            "reportIds": [own_report["id"]],
            "filmIds": ["FILM-FOREIGN"],
        },
    )
    for response in (existing, new_foreign, mixed):
        assert response.json()["code"] in {403, 40404}, response.text
    assert _without_tenant_metadata(foreign_feedback) == _without_tenant_metadata(foreign_before)
    assert len(repo.state["ndt_feedback"]) == feedback_count


def test_new_ndt_rectification_derives_provenance_from_active_member() -> None:
    own_report, own_film = _add_ndt_owned_report_and_film()
    feedback_id = "NDT-FB-NDT-OWN-CREATE"
    response = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/rectifications",
        headers={**_headers("ndt"), "Idempotency-Key": "own-feedback-create"},
        json={
            "nodeId": NODE_ID,
            "rectificationId": feedback_id,
            "description": "OWN CREATE",
            "reportIds": [own_report["id"]],
            "filmIds": [own_film["id"]],
            "sourceOrgId": "ORG-SPOOFED",
            "sourceOrgName": "伪造组织",
        },
    )
    assert response.json()["code"] == 0, response.text
    feedback = repo.find_one("ndt_feedback", feedback_id)
    assert feedback["sourceOrgId"] == ACTORS["ndt"]["org_id"]
    assert feedback["sourceOrgName"] == ACTORS["ndt"]["org_name"]


def _prepare_foreign_atomic_document() -> tuple[dict, dict]:
    member = next(
        item
        for item in repo.state["project_members"]
        if item.get("userId") == ACTORS["ndt"]["user_id"]
        and item.get("projectId") == PROJECT_ID
    )
    member["nodeScope"] = sorted({*member.get("nodeScope", []), 35, 36})
    document = repo.find_one("documents", DOCUMENTS["contractor_b"])
    document.update(
        {
            "materialCategory": routes_module.NDT_ATOMIC_MATERIAL_CATEGORY,
            "materialTypeCode": "ndt_quality_assurance_manual",
            "fileStatus": "已上传",
            "currentOcrStatus": "已识别",
        }
    )
    version = repo.find_one("versions", document["currentVersionId"])
    version.update({"ocrStatus": "已识别", "sliceStatus": "已切片", "vectorStatus": "已向量化"})
    knowledge_file = next(item for item in repo.state["knowledge_files"] if item.get("documentId") == document["id"])
    knowledge_file.update({"ocrStatus": "已识别", "sliceStatus": "已切片", "vectorStatus": "已向量化"})
    repo.state["bindings"] = [item for item in repo.state["bindings"] if item.get("documentId") != document["id"]]
    binding = {
        "id": "BIND-FOREIGN-ATOMIC-35",
        "projectId": PROJECT_ID,
        "nodeId": 35,
        "documentId": document["id"],
        "documentVersionId": document["currentVersionId"],
        "fileName": document["fileName"],
        "bindingStatus": "草稿挂载",
    }
    repo.state["bindings"].append(binding)
    return document, binding


def test_foreign_atomic_binding_replacement_is_denied_before_binding_mutation() -> None:
    document, _ = _prepare_foreign_atomic_document()
    bindings_before = deepcopy(repo.state["bindings"])
    response = client.put(
        f"/api/projects/{PROJECT_ID}/ndt/documents/{document['id']}/bindings",
        headers={**_headers("ndt"), "Idempotency-Key": "foreign-atomic-rebind"},
        json={"nodeIds": [36]},
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _without_tenant_metadata(repo.state["bindings"]) == _without_tenant_metadata(bindings_before)


def test_foreign_atomic_submission_is_denied_before_document_binding_or_workflow_mutation() -> None:
    document, binding = _prepare_foreign_atomic_document()
    document_before = deepcopy(document)
    bindings_before = deepcopy(repo.state["bindings"])
    todos_before = deepcopy(repo.state["todos"])
    submissions_before = deepcopy(repo.state["submissions"])
    node_before = deepcopy(repo.node(PROJECT_ID, 35))
    response = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/material-submissions",
        headers={**_headers("ndt"), "Idempotency-Key": "foreign-atomic-submit"},
        json={"documentId": document["id"], "bindingIds": [binding["id"]]},
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _without_tenant_metadata(document) == _without_tenant_metadata(document_before)
    assert _without_tenant_metadata(repo.state["bindings"]) == _without_tenant_metadata(bindings_before)
    assert _without_tenant_metadata(repo.state["todos"]) == _without_tenant_metadata(todos_before)
    assert _without_tenant_metadata(repo.state["submissions"]) == _without_tenant_metadata(submissions_before)
    assert _without_tenant_metadata(repo.node(PROJECT_ID, 35)) == _without_tenant_metadata(node_before)


def test_ndt_record_import_rejects_foreign_and_mixed_relationships_before_insert() -> None:
    _add_ndt_projection_fixtures()
    own_report, _ = _add_ndt_owned_report_and_film()
    before = deepcopy(repo.state["ndt_records"])
    foreign = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/records/import",
        headers={**_headers("ndt"), "Idempotency-Key": "foreign-record-import"},
        json={
            "nodeId": NODE_ID,
            "rows": [
                {
                    "recordNo": "REC-FOREIGN-IMPORT",
                    "weldNo": "W-FOREIGN",
                    "method": "RT",
                    "reportId": "NDT-RPT-FOREIGN",
                    "filmId": "FILM-FOREIGN",
                }
            ],
        },
    )
    mixed = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/records/import",
        headers={**_headers("ndt"), "Idempotency-Key": "mixed-record-import"},
        json={
            "nodeId": NODE_ID,
            "rows": [
                {
                    "recordNo": "REC-MIXED-IMPORT",
                    "weldNo": "W-MIXED",
                    "method": "RT",
                    "reportId": own_report["id"],
                    "filmId": "FILM-FOREIGN",
                }
            ],
        },
    )
    for response in (foreign, mixed):
        assert response.json()["code"] in {403, 40404}, response.text
    assert _without_tenant_metadata(repo.state["ndt_records"]) == _without_tenant_metadata(before)


def _create_uploaded_session(actor: str, key: str, *, ndt: bool = False):
    content = f"session-owner-{actor}-{key}".encode()
    if ndt:
        member = next(
            item
            for item in repo.state["project_members"]
            if item.get("userId") == ACTORS[actor]["user_id"]
            and item.get("projectId") == PROJECT_ID
        )
        member["nodeScope"] = sorted({*member.get("nodeScope", []), 40, 41, 42})
    endpoint = (
        f"/api/projects/{PROJECT_ID}/ndt/reports/upload-session"
        if ndt
        else f"/api/projects/{PROJECT_ID}/documents/upload-session"
    )
    created = client.post(
        endpoint,
        headers={**_headers(actor), "Idempotency-Key": f"{key}-create"},
        json={
            "requireSignedUrls": False,
            "files": [
                {
                    "fileName": f"{key}.pdf",
                    "fileType": "application/pdf",
                    "fileSize": len(content),
                }
            ],
        },
    )
    assert created.json()["code"] == 0, created.text
    session = created.json()["data"]
    target = session["uploadUrls"][0]
    uploaded = client.put(
        target["url"],
        headers={**_headers(actor), **target["headers"]},
        content=content,
    )
    assert uploaded.json()["code"] == 0, uploaded.text
    completion_body = {
        "completedFiles": [
            {
                "documentVersionId": target["documentVersionId"],
                "fileSize": len(content),
                "contentHash": hashlib.sha256(content).hexdigest(),
            }
        ]
    }
    return session, target, completion_body


def _session_business_state(session_id: str):
    session = repo.find_one("upload_sessions", session_id)
    document_ids = {
        str(item.get("documentId"))
        for item in (session or {}).get("files") or []
        if item.get("documentId")
    }
    version_ids = {
        str(item.get("documentVersionId"))
        for item in (session or {}).get("files") or []
        if item.get("documentVersionId")
    }
    return _without_tenant_metadata(
        {
            "session": deepcopy(session),
            "documents": [deepcopy(item) for item in repo.state["documents"] if item.get("id") in document_ids],
            "versions": [deepcopy(item) for item in repo.state["versions"] if item.get("id") in version_ids or item.get("documentId") in document_ids],
            "reports": [deepcopy(item) for item in repo.state["ndt_reports"] if item.get("fileId") in document_ids],
            "bindings": [deepcopy(item) for item in repo.state["bindings"] if item.get("documentId") in document_ids],
            "tasks": [deepcopy(item) for item in repo.state["knowledge_tasks"] if item.get("documentId") in document_ids or item.get("documentVersionId") in version_ids],
            "submissions": [deepcopy(item) for item in repo.state["submissions"] if bool(document_ids & set(item.get("documentIds") or []))],
        }
    )


def _second_ndt_headers() -> dict[str, str]:
    user_id = "USER-ORG-ISOLATION-NDT-B"
    repo.state["project_members"].append(
        {
            "id": "PM-ORG-ISOLATION-NDT-B",
            "projectId": PROJECT_ID,
            "userId": user_id,
            "name": "ndt_b",
            "orgId": "ORG-ORG-ISOLATION-NDT-B",
            "orgName": "第二无损检测单位",
            "role": "ndt",
            "nodeScope": [NODE_ID, 40, 41, 42],
            "actions": ROLE_ACTIONS["ndt"],
            "status": "启用",
        }
    )
    return {"X-Role": "ndt", "X-User-Id": user_id}


def test_foreign_org_cannot_complete_generic_upload_session_and_creator_identity_is_immutable() -> None:
    session_payload, _, completion_body = _create_uploaded_session(
        "contractor_a", "generic-foreign-completion"
    )
    session_id = session_payload["uploadSessionId"]
    session = repo.find_one("upload_sessions", session_id)
    assert session["creatorOrgId"] == ACTORS["contractor_a"]["org_id"]
    assert session["creatorUserId"] == ACTORS["contractor_a"]["user_id"]
    before = _session_business_state(session_id)
    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session/{session_id}/complete",
        headers={**_headers("contractor_b"), "Idempotency-Key": "generic-foreign-complete"},
        json=completion_body,
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _session_business_state(session_id) == before


def test_foreign_org_cannot_complete_ndt_upload_session_before_reports_bindings_or_dispatch() -> None:
    session_payload, _, completion_body = _create_uploaded_session(
        "ndt", "ndt-foreign-completion", ndt=True
    )
    session_id = session_payload["uploadSessionId"]
    session = repo.find_one("upload_sessions", session_id)
    assert session["creatorOrgId"] == ACTORS["ndt"]["org_id"]
    assert session["creatorUserId"] == ACTORS["ndt"]["user_id"]
    before = _session_business_state(session_id)
    response = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/reports/upload-session/{session_id}/complete",
        headers={**_second_ndt_headers(), "Idempotency-Key": "ndt-foreign-complete"},
        json=completion_body,
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _session_business_state(session_id) == before


def test_mixed_session_documents_are_all_authorized_before_generic_completion() -> None:
    session_payload, _, completion_body = _create_uploaded_session(
        "contractor_a", "generic-mixed-completion"
    )
    session_id = session_payload["uploadSessionId"]
    session = repo.find_one("upload_sessions", session_id)
    foreign_document = repo.find_one("documents", DOCUMENTS["contractor_b"])
    session["files"].append(
        {
            "documentId": foreign_document["id"],
            "documentVersionId": foreign_document["currentVersionId"],
            "fileName": foreign_document["fileName"],
            "status": "已上传",
            "fileSize": 128,
        }
    )
    completion_body["completedFiles"].append(
        {
            "documentVersionId": foreign_document["currentVersionId"],
            "fileSize": 128,
            "contentHash": f"sha256-{foreign_document['id']}",
        }
    )
    before = _session_business_state(session_id)
    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session/{session_id}/complete",
        headers={**_headers("contractor_a"), "Idempotency-Key": "generic-mixed-complete"},
        json=completion_body,
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _session_business_state(session_id) == before


@pytest.mark.parametrize(
    ("actor", "allowed"),
    [("owner", False), ("inspection", True), ("admin", False)],
)
def test_upload_completion_role_matrix_preserves_owner_inspection_admin_behavior(
    actor: str,
    allowed: bool,
) -> None:
    session_payload, _, completion_body = _create_uploaded_session(
        "contractor_a", f"generic-role-{actor}"
    )
    session_id = session_payload["uploadSessionId"]
    before = _session_business_state(session_id)
    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session/{session_id}/complete",
        headers={**_headers(actor), "Idempotency-Key": f"generic-complete-{actor}"},
        json=completion_body,
    )
    if allowed:
        assert response.json()["code"] == 0, response.text
        assert repo.find_one("upload_sessions", session_id)["status"] == "已完成"
    else:
        assert response.json()["code"] in {403, 40404}, response.text
        assert _session_business_state(session_id) == before


def _generic_document_write_state():
    return _without_tenant_metadata(
        {
            "documents": deepcopy(repo.state["documents"]),
            "versions": deepcopy(repo.state["versions"]),
            "bindings": deepcopy(repo.state["bindings"]),
            "nodeEvidenceLinks": deepcopy(repo.state["node_evidence_links"]),
            "targetingRuns": deepcopy(repo.state.get("material_targeting_runs", [])),
            "drafts": deepcopy(repo.state["submission_drafts"]),
            "submissions": deepcopy(repo.state["submissions"]),
            "todos": deepcopy(repo.state["todos"]),
            "treeNodes": deepcopy(repo.state["tree_nodes"]),
            "rectifications": deepcopy(repo.state["rectifications"]),
        }
    )


def _mark_document_pipeline_ready(document_id: str) -> None:
    document = repo.find_one("documents", document_id)
    document["currentOcrStatus"] = "已识别"
    version = repo.find_one("versions", document["currentVersionId"])
    version.update({"ocrStatus": "已识别", "sliceStatus": "已切片", "vectorStatus": "已向量化"})
    knowledge_file = next(item for item in repo.state["knowledge_files"] if item.get("documentId") == document_id)
    knowledge_file.update({"ocrStatus": "已识别", "sliceStatus": "已切片", "vectorStatus": "已向量化"})


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("POST", "/targeting/recompute", {}),
        ("POST", "/versions", {"mode": "append", "fileSize": 42, "hash": "foreign-version"}),
        ("DELETE", "", None),
        ("POST", "/withdraw", {}),
        ("POST", "/void", {}),
    ],
)
def test_foreign_document_id_generic_mutations_fail_before_state_change(
    method: str,
    suffix: str,
    body,
) -> None:
    document_id = DOCUMENTS["contractor_b"]
    before = _generic_document_write_state()
    response = client.request(
        method,
        f"/api/projects/{PROJECT_ID}/documents/{document_id}{suffix}",
        headers={**_headers("contractor_a"), "Idempotency-Key": f"foreign-generic-{method}-{suffix}"},
        json=body,
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before


def test_split_material_category_route_cannot_recategorize_foreign_document() -> None:
    category = sorted(known_categories())[0]
    document = repo.find_one("documents", DOCUMENTS["contractor_b"])
    before = deepcopy(document)
    response = client.patch(
        f"/api/projects/{PROJECT_ID}/documents/{document['id']}/material-category",
        headers={**_headers("contractor_a"), "Idempotency-Key": "foreign-material-category"},
        json={"materialCategory": category},
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _without_tenant_metadata(document) == _without_tenant_metadata(before)


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_foreign_binding_update_and_delete_fail_before_state_change(method: str) -> None:
    binding_id = f"BIND-{DOCUMENTS['contractor_b']}"
    before = _generic_document_write_state()
    response = client.request(
        method,
        f"/api/projects/{PROJECT_ID}/documents/bindings/{binding_id}",
        headers={**_headers("contractor_a"), "Idempotency-Key": f"foreign-binding-{method}"},
        json={"usage": "MUTATED"} if method == "PATCH" else None,
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before


def test_mixed_document_binding_create_fails_atomically() -> None:
    before = _generic_document_write_state()
    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/bindings",
        headers={**_headers("contractor_a"), "Idempotency-Key": "mixed-binding-create"},
        json={
            "bindings": [
                {"documentId": DOCUMENTS["contractor_a"], "nodeId": NODE_ID},
                {"documentId": DOCUMENTS["contractor_b"], "nodeId": NODE_ID},
            ]
        },
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before


def test_binding_create_rejects_foreign_version_reverse_lookup_for_own_document() -> None:
    before = _generic_document_write_state()
    foreign = repo.find_one("documents", DOCUMENTS["contractor_b"])
    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/bindings",
        headers={**_headers("contractor_a"), "Idempotency-Key": "foreign-version-binding"},
        json={
            "bindings": [
                {
                    "documentId": DOCUMENTS["contractor_a"],
                    "documentVersionId": foreign["currentVersionId"],
                    "nodeId": NODE_ID,
                }
            ]
        },
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before


@pytest.mark.parametrize(
    "body",
    [
        {"nodeIds": [NODE_ID], "bindingIds": [f"BIND-{DOCUMENTS['contractor_b']}"]},
        {"nodeIds": [NODE_ID], "documentIds": [DOCUMENTS["contractor_a"], DOCUMENTS["contractor_b"]]},
    ],
)
def test_submission_draft_foreign_and_mixed_references_fail_before_binding_creation(body: dict) -> None:
    before = _generic_document_write_state()
    response = client.post(
        f"/api/projects/{PROJECT_ID}/submissions/drafts",
        headers={**_headers("contractor_a"), "Idempotency-Key": f"foreign-draft-{len(body)}"},
        json=body,
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before


@pytest.mark.parametrize(
    "body",
    [
        {"nodeIds": [NODE_ID], "bindingIds": [f"BIND-{DOCUMENTS['contractor_b']}"]},
        {"nodeIds": [NODE_ID]},
        {"submissionType": "project", "documentIds": [DOCUMENTS["contractor_a"], DOCUMENTS["contractor_b"]]},
    ],
)
def test_submission_foreign_scoped_and_mixed_references_fail_atomically(body: dict) -> None:
    for document_id in DOCUMENTS.values():
        _mark_document_pipeline_ready(document_id)
    before = _generic_document_write_state()
    response = client.post(
        f"/api/projects/{PROJECT_ID}/submissions",
        headers={**_headers("contractor_a"), "Idempotency-Key": f"foreign-submit-{len(body)}-{body.get('submissionType')}"},
        json=body,
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before


def test_generic_rectification_cannot_submit_foreign_binding() -> None:
    rectification = {
        "id": "RECT-FOREIGN-BINDING-ATTACK",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "status": "待反馈",
        "bindingIds": [f"BIND-{DOCUMENTS['contractor_b']}"],
        "createdAt": "2026-08-22 12:00:00",
    }
    repo.state["rectifications"].append(rectification)
    before = _generic_document_write_state()
    response = client.post(
        f"/api/projects/{PROJECT_ID}/rectifications",
        headers={**_headers("contractor_a"), "Idempotency-Key": "foreign-generic-rectification"},
        json={
            "nodeIds": [NODE_ID],
            "rectificationId": rectification["id"],
            "bindingIds": [f"BIND-{DOCUMENTS['contractor_b']}"],
            "description": "MUTATED",
        },
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before


def test_direct_evidence_readiness_matches_actor_filtered_node_package() -> None:
    response = client.get(
        f"/api/projects/{PROJECT_ID}/nodes/{NODE_ID}/evidence-readiness",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] == 0, response.text
    readiness = response.json()["data"]
    assert {item["documentId"] for item in readiness["nodeEvidenceLinks"]} == {
        DOCUMENTS["contractor_a"]
    }
    assert readiness["advisoryEvidenceLinks"] == []
    assert readiness["inputDocumentVersionIds"] == [f"DV-{DOCUMENTS['contractor_a']}-V1"]
    assert readiness["supportingDocumentCount"] == 1
    for secret in (
        DOCUMENTS["contractor_b"],
        DOCUMENTS["ndt"],
        "FOREIGN-SECRET.docx",
        "FOREIGN OCR SECRET",
        "NDT FOREIGN OCR SECRET",
    ):
        assert secret not in response.text


def test_project_targeting_recompute_only_mutates_actor_visible_documents() -> None:
    foreign_ids = {DOCUMENTS["contractor_b"], DOCUMENTS["ndt"]}
    before_foreign_links = deepcopy(
        [item for item in repo.state["node_evidence_links"] if item.get("documentId") in foreign_ids]
    )
    before_foreign_runs = deepcopy(
        [item for item in repo.state.get("material_targeting_runs", []) if item.get("documentId") in foreign_ids]
    )
    response = client.post(
        f"/api/projects/{PROJECT_ID}/material-targeting/recompute",
        headers={**_headers("contractor_a"), "Idempotency-Key": "visible-project-targeting"},
    )
    assert response.json()["code"] == 0, response.text
    assert response.json()["data"]["documentCount"] == 1
    assert _without_tenant_metadata(
        [item for item in repo.state["node_evidence_links"] if item.get("documentId") in foreign_ids]
    ) == _without_tenant_metadata(before_foreign_links)
    assert _without_tenant_metadata(
        [item for item in repo.state.get("material_targeting_runs", []) if item.get("documentId") in foreign_ids]
    ) == _without_tenant_metadata(before_foreign_runs)


def test_project_tree_file_and_requirement_counts_use_actor_visible_bindings() -> None:
    response = client.get(
        f"/api/projects/{PROJECT_ID}/tree",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] == 0, response.text
    nodes = [
        node
        for group in response.json()["data"]["groups"]
        for node in group["nodes"]
    ]
    node = next(item for item in nodes if int(item["nodeId"]) == NODE_ID)
    assert node["fileCount"] == 1
    assert node["requirementsSummary"]["satisfiedCount"] <= 1


@pytest.mark.parametrize("related_film_ids", [["FILM-FOREIGN"], ["FILM-NDT-OWN", "FILM-FOREIGN"]])
def test_ndt_report_session_creation_rejects_foreign_and_mixed_related_films_atomically(
    related_film_ids: list[str],
) -> None:
    _add_ndt_projection_fixtures()
    _add_ndt_owned_report_and_film()
    member = next(
        item
        for item in repo.state["project_members"]
        if item.get("userId") == ACTORS["ndt"]["user_id"]
        and item.get("projectId") == PROJECT_ID
    )
    member["nodeScope"] = sorted({*member.get("nodeScope", []), 40, 41, 42})
    before = _generic_document_write_state()
    sessions_before = deepcopy(repo.state["upload_sessions"])
    response = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/reports/upload-session",
        headers={**_headers("ndt"), "Idempotency-Key": f"foreign-related-film-{len(related_film_ids)}"},
        json={
            "requireSignedUrls": False,
            "relatedFilmIds": related_film_ids,
            "files": [{"fileName": "foreign-related-film.pdf", "fileType": "application/pdf", "fileSize": 16}],
        },
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before
    assert _without_tenant_metadata(repo.state["upload_sessions"]) == _without_tenant_metadata(sessions_before)


def test_ndt_completion_revalidates_tampered_related_films_inside_locked_aggregate() -> None:
    _add_ndt_projection_fixtures()
    session_payload, _, completion_body = _create_uploaded_session(
        "ndt", "ndt-tampered-related-film", ndt=True
    )
    session_id = session_payload["uploadSessionId"]
    session = repo.find_one("upload_sessions", session_id)
    session["ndtReportContext"]["relatedFilmIds"] = ["FILM-FOREIGN"]
    before = _session_business_state(session_id)
    response = client.post(
        f"/api/projects/{PROJECT_ID}/ndt/reports/upload-session/{session_id}/complete",
        headers={**_headers("ndt"), "Idempotency-Key": "tampered-related-film-complete"},
        json=completion_body,
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _session_business_state(session_id) == before


@pytest.mark.parametrize("mode", ["declared-node", "replacement-node"])
def test_upload_session_creation_authorizes_declared_and_replacement_target_nodes_before_records(
    mode: str,
) -> None:
    member = next(
        item
        for item in repo.state["project_members"]
        if item.get("userId") == ACTORS["contractor_a"]["user_id"]
        and item.get("projectId") == PROJECT_ID
    )
    member["nodeScope"] = [NODE_ID]
    file = {"fileName": f"{mode}.pdf", "fileType": "application/pdf", "fileSize": 16}
    if mode == "declared-node":
        file["nodeIds"] = [35]
    else:
        own_binding = repo.find_one("bindings", f"BIND-{DOCUMENTS['contractor_a']}")
        own_binding["nodeId"] = 35
        file["replaceDocumentId"] = DOCUMENTS["contractor_a"]
    before = _generic_document_write_state()
    sessions_before = deepcopy(repo.state["upload_sessions"])
    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/upload-session",
        headers={**_headers("contractor_a"), "Idempotency-Key": f"unauthorized-{mode}"},
        json={"files": [file]},
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before
    assert _without_tenant_metadata(repo.state["upload_sessions"]) == _without_tenant_metadata(sessions_before)


def test_targeting_recompute_rejects_foreign_version_for_visible_path_document_unchanged() -> None:
    own_id = DOCUMENTS["contractor_a"]
    foreign = repo.find_one("documents", DOCUMENTS["contractor_b"])
    foreign_link = {
        "id": "NEL-FOREIGN-VERSION-TARGETING",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "documentId": foreign["id"],
        "documentVersionId": foreign["currentVersionId"],
        "source": "material_targeting",
        "quotedText": "FOREIGN VERSION TARGETING SECRET",
    }
    repo.state["node_evidence_links"].append(foreign_link)
    before = _generic_document_write_state()
    response = client.post(
        f"/api/projects/{PROJECT_ID}/documents/{own_id}/targeting/recompute",
        headers={**_headers("contractor_a"), "Idempotency-Key": "foreign-version-targeting"},
        json={"documentVersionId": foreign["currentVersionId"]},
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before


def test_evidence_readiness_rejects_inconsistent_document_version_and_binding_pairs() -> None:
    foreign = repo.find_one("documents", DOCUMENTS["contractor_b"])
    repo.state["node_evidence_links"].append(
        {
            "id": "NEL-INCONSISTENT-PAIR",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "reviewPointId": "RP-ORG-ISOLATION",
            "documentId": DOCUMENTS["contractor_a"],
            "documentVersionId": foreign["currentVersionId"],
            "fileName": "INCONSISTENT-FOREIGN-NAME.pdf",
            "quotedText": "INCONSISTENT FOREIGN OCR SECRET",
            "formalEvidenceEligible": True,
            "manualStatus": "confirmed",
            "pageNo": 1,
            "bbox": [0, 0, 20, 20],
        }
    )
    repo.state["bindings"].append(
        {
            "id": "BIND-INCONSISTENT-PAIR",
            "projectId": PROJECT_ID,
            "nodeId": NODE_ID,
            "documentId": DOCUMENTS["contractor_a"],
            "documentVersionId": foreign["currentVersionId"],
            "fileName": "INCONSISTENT-BINDING-NAME.pdf",
            "bindingStatus": "已提交",
        }
    )
    response = client.get(
        f"/api/projects/{PROJECT_ID}/nodes/{NODE_ID}/evidence-readiness",
        headers=_headers("contractor_a"),
    )
    assert response.json()["code"] == 0, response.text
    for secret in (
        "NEL-INCONSISTENT-PAIR",
        "BIND-INCONSISTENT-PAIR",
        foreign["currentVersionId"],
        "INCONSISTENT-FOREIGN-NAME.pdf",
        "INCONSISTENT FOREIGN OCR SECRET",
        "INCONSISTENT-BINDING-NAME.pdf",
    ):
        assert secret not in response.text
    package = client.get(
        f"/api/projects/{PROJECT_ID}/nodes/{NODE_ID}/package",
        headers=_headers("contractor_a"),
    )
    assert package.json()["code"] == 0, package.text
    for secret in (
        "BIND-INCONSISTENT-PAIR",
        foreign["currentVersionId"],
        "INCONSISTENT-BINDING-NAME.pdf",
    ):
        assert secret not in package.text
    assert {item["documentId"] for item in package.json()["data"]["bindings"]} == {
        DOCUMENTS["contractor_a"]
    }


@pytest.mark.parametrize("explicit", [True, False])
def test_generic_rectification_cannot_take_over_foreign_target_with_own_binding(explicit: bool) -> None:
    rectification = {
        "id": "RECT-FOREIGN-TARGET-TAKEOVER",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "status": "待反馈",
        "bindingIds": [f"BIND-{DOCUMENTS['contractor_b']}"],
        "createdAt": "2026-08-22 12:10:00",
    }
    repo.state["rectifications"].append(rectification)
    before = _generic_document_write_state()
    body = {
        "nodeIds": [NODE_ID],
        "bindingIds": [f"BIND-{DOCUMENTS['contractor_a']}"],
        "description": "OWN BINDING TAKEOVER",
    }
    if explicit:
        body["rectificationId"] = rectification["id"]
    response = client.post(
        f"/api/projects/{PROJECT_ID}/rectifications",
        headers={**_headers("contractor_a"), "Idempotency-Key": f"rectification-takeover-{explicit}"},
        json=body,
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before


def test_normal_submission_cannot_relink_mixed_existing_rectification() -> None:
    for document_id in (DOCUMENTS["contractor_a"], DOCUMENTS["contractor_b"]):
        _mark_document_pipeline_ready(document_id)
    rectification = {
        "id": "RECT-MIXED-SUBMISSION-RELINK",
        "projectId": PROJECT_ID,
        "nodeId": NODE_ID,
        "status": "待反馈",
        "bindingIds": [
            f"BIND-{DOCUMENTS['contractor_a']}",
            f"BIND-{DOCUMENTS['contractor_b']}",
        ],
        "createdAt": "2026-08-22 12:11:00",
    }
    repo.state["rectifications"].append(rectification)
    before = _generic_document_write_state()
    response = client.post(
        f"/api/projects/{PROJECT_ID}/submissions",
        headers={**_headers("contractor_a"), "Idempotency-Key": "mixed-rectification-relink"},
        json={"nodeIds": [NODE_ID], "bindingIds": [f"BIND-{DOCUMENTS['contractor_a']}"]},
    )
    assert response.json()["code"] in {403, 40404}, response.text
    assert _generic_document_write_state() == before


def test_project_tree_requirements_summary_exactly_matches_actor_readiness() -> None:
    global_readiness = routes_module.build_node_evidence_readiness(repo, PROJECT_ID, NODE_ID)
    if not global_readiness.get("requirements"):
        pytest.skip("node has no configured review points")
    point_id = str(global_readiness["requirements"][0]["id"])
    own_link = repo.find_one("node_evidence_links", "NEL-CONTRACTOR-A")
    foreign_link = repo.find_one("node_evidence_links", "NEL-CONTRACTOR-B")
    own_link.update({"reviewPointId": point_id, "manualStatus": "pending"})
    foreign_link.update({"reviewPointId": point_id, "manualStatus": "confirmed"})

    direct = client.get(
        f"/api/projects/{PROJECT_ID}/nodes/{NODE_ID}/evidence-readiness",
        headers=_headers("contractor_a"),
    ).json()["data"]
    tree = client.get(f"/api/projects/{PROJECT_ID}/tree", headers=_headers("contractor_a")).json()["data"]
    tree_node = next(
        node
        for group in tree["groups"]
        for node in group["nodes"]
        if int(node["nodeId"]) == NODE_ID
    )
    summary = tree_node["requirementsSummary"]
    for key in ("requiredCount", "satisfiedCount", "missingCount", "progressPercent", "supportingDocumentCount"):
        assert summary.get(key) == direct.get(key), (key, summary, direct)
    assert {item["id"] for item in summary["missingRequirements"]} == {
        item["id"] for item in direct["missingRequirements"]
    }


def test_node_package_rectifications_and_hidden_timeline_are_actor_filtered() -> None:
    repo.state["rectifications"].extend(
        [
            {"id": "RECT-OWN-TIMELINE", "projectId": PROJECT_ID, "nodeId": NODE_ID, "status": "待反馈", "bindingIds": [f"BIND-{DOCUMENTS['contractor_a']}"], "description": "OWN RECTIFICATION EVENT", "createdAt": "2026-08-22 12:20:00"},
            {"id": "RECT-FOREIGN-TIMELINE", "projectId": PROJECT_ID, "nodeId": NODE_ID, "status": "待反馈", "bindingIds": [f"BIND-{DOCUMENTS['contractor_b']}"], "description": "FOREIGN RECTIFICATION SECRET", "createdAt": "2026-08-22 12:21:00"},
            {"id": "RECT-MIXED-TIMELINE", "projectId": PROJECT_ID, "nodeId": NODE_ID, "status": "待反馈", "bindingIds": [f"BIND-{DOCUMENTS['contractor_a']}", f"BIND-{DOCUMENTS['contractor_b']}"], "description": "MIXED RECTIFICATION SECRET", "createdAt": "2026-08-22 12:22:00"},
        ]
    )
    repo.state["ai_runs"].insert(0, {"id": "AI-RUN-HIDDEN-TIMELINE", "projectId": PROJECT_ID, "nodeId": NODE_ID, "status": "完成", "suggestion": {"result": "HIDDEN AI TIMELINE SECRET"}, "createdAt": "2026-08-22 12:23:00"})
    repo.state["review_opinions"].insert(0, {"id": "OPINION-HIDDEN-TIMELINE", "projectId": PROJECT_ID, "nodeId": NODE_ID, "result": "HIDDEN HUMAN TIMELINE SECRET", "createdAt": "2026-08-22 12:24:00"})

    contractor = client.get(
        f"/api/projects/{PROJECT_ID}/nodes/{NODE_ID}/package",
        headers=_headers("contractor_a"),
    )
    owner = client.get(
        f"/api/projects/{PROJECT_ID}/nodes/{NODE_ID}/package",
        headers=_headers("owner"),
    )
    assert contractor.json()["code"] == 0, contractor.text
    contractor_data = contractor.json()["data"]
    assert {item["id"] for item in contractor_data["rectifications"]} == {"RECT-OWN-TIMELINE"}
    assert contractor_data["autoReviewStatus"] is None
    assert contractor_data["node"]["requirementsSummary"]["satisfiedCount"] == contractor_data["evidenceReadiness"]["satisfiedCount"]
    assert contractor_data["node"]["requirementsSummary"]["supportingDocumentCount"] == contractor_data["evidenceReadiness"]["supportingDocumentCount"]
    assert "OWN RECTIFICATION EVENT" in contractor.text
    for secret in (
        "FOREIGN RECTIFICATION SECRET",
        "MIXED RECTIFICATION SECRET",
        "HIDDEN AI TIMELINE SECRET",
        "HIDDEN HUMAN TIMELINE SECRET",
        "AI-RUN-HIDDEN-TIMELINE",
        "OPINION-HIDDEN-TIMELINE",
    ):
        assert secret not in contractor.text
    assert owner.json()["code"] == 0, owner.text
    assert owner.json()["data"]["rectifications"] == []
    assert owner.json()["data"]["reviewTimeline"] == []
    assert owner.json()["data"]["autoReviewStatus"] is None
    inspection = client.get(
        f"/api/projects/{PROJECT_ID}/nodes/{NODE_ID}/package",
        headers=_headers("inspection"),
    )
    assert inspection.json()["code"] == 0, inspection.text
    assert inspection.json()["data"]["autoReviewStatus"] is not None


def test_project_tree_builds_actor_visible_evidence_repository_once(monkeypatch) -> None:
    original_repository = document_access_policy.InMemoryRepository
    calls = 0

    class CountingRepository(original_repository):
        def __init__(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(document_access_policy, "InMemoryRepository", CountingRepository)
    response = client.get(f"/api/projects/{PROJECT_ID}/tree", headers=_headers("admin"))
    assert response.json()["code"] == 0, response.text
    assert calls == 1, "actor-visible detached evidence state must be built once per tree request"


def test_standalone_rectification_list_and_detail_are_actor_document_filtered() -> None:
    repo.state["rectifications"].extend(
        [
            {"id": "RECT-OWN-STANDALONE", "projectId": PROJECT_ID, "nodeId": NODE_ID, "status": "待反馈", "bindingIds": [f"BIND-{DOCUMENTS['contractor_a']}"], "comment": "OWN RECTIFICATION REASON", "createdAt": "2026-08-22 12:30:00"},
            {"id": "RECT-FOREIGN-STANDALONE", "projectId": PROJECT_ID, "nodeId": NODE_ID, "status": "待反馈", "bindingIds": [f"BIND-{DOCUMENTS['contractor_b']}"], "comment": "FOREIGN RECTIFICATION REASON", "createdAt": "2026-08-22 12:31:00"},
            {"id": "RECT-MIXED-STANDALONE", "projectId": PROJECT_ID, "nodeId": NODE_ID, "status": "待反馈", "bindingIds": [f"BIND-{DOCUMENTS['contractor_a']}", f"BIND-{DOCUMENTS['contractor_b']}"], "comment": "MIXED RECTIFICATION REASON", "createdAt": "2026-08-22 12:32:00"},
        ]
    )
    listed = client.get(f"/api/projects/{PROJECT_ID}/rectifications", headers=_headers("contractor_a"))
    own = client.get(f"/api/projects/{PROJECT_ID}/rectifications/RECT-OWN-STANDALONE", headers=_headers("contractor_a"))
    foreign = client.get(f"/api/projects/{PROJECT_ID}/rectifications/RECT-FOREIGN-STANDALONE", headers=_headers("contractor_a"))
    mixed = client.get(f"/api/projects/{PROJECT_ID}/rectifications/RECT-MIXED-STANDALONE", headers=_headers("contractor_a"))
    assert {item["id"] for item in listed.json()["data"]["items"]} == {"RECT-OWN-STANDALONE"}
    assert own.json()["code"] == 0, own.text
    assert {item["documentId"] for item in own.json()["data"]["bindings"]} == {
        DOCUMENTS["contractor_a"]
    }
    for response in (foreign, mixed):
        assert response.json()["code"] in {403, 40404}, response.text
    combined = listed.text + own.text
    assert "OWN RECTIFICATION REASON" in combined
    assert "FOREIGN RECTIFICATION REASON" not in combined
    assert "MIXED RECTIFICATION REASON" not in combined
