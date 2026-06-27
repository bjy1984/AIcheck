from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import JSONResponse

from libs.contracts import errors
from libs.contracts.responses import fail, ok, page, server_time
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID, ROLE_ACTIONS, ROLE_NODE_MAP
from libs.integrations import task_dispatcher
from libs.security.auth import authenticate, issue_token

router = APIRouter(tags=["AIcheck API"])
mock_router = APIRouter(tags=["Compatibility Mock"])


def role_from_query(role: str | None = None, x_role: str | None = None) -> str:
    return (x_role or role or "inspection").strip() or "inspection"


def mutation_guard(
    request: Request,
    project_id: str | None = None,
    *,
    x_role: str | None = None,
    if_match: str | None = None,
) -> JSONResponse | None:
    effective_role = x_role or request.headers.get("X-Role")
    if project_id:
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        if project.get("status") == "已归档":
            return fail(errors.ARCHIVED_READONLY, request)
        if if_match and if_match not in {"*", str(project.get("revision")), f"W/\"{project.get('revision')}\""}:
            return fail(errors.ETAG_CONFLICT, request)
        node_scope_error = member_node_scope_error(request, project_id, effective_role)
        if node_scope_error:
            return node_scope_error
    action_code = request.headers.get("X-Action-Code")
    if action_code and effective_role and action_code not in repo.role_actions(effective_role):
        return fail(errors.FORBIDDEN, request, message=f"角色 {effective_role} 无权执行 {action_code}。")
    if effective_role in {"owner"}:
        return fail(errors.FORBIDDEN, request)
    if effective_role == "admin" and "/review-opinions" in request.url.path:
        return fail(errors.FORBIDDEN, request, message="管理员不能代替业务角色保存审查意见。")
    return None


def member_node_scope_error(request: Request, project_id: str, role: str | None) -> JSONResponse | None:
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        return None
    member = next(
        (
            item
            for item in repo.state["project_members"]
            if item.get("projectId") == project_id
            and item.get("userId") == user_id
            and (not role or item.get("role") == role)
            and item.get("status") == "启用"
        ),
        None,
    )
    if member is None:
        return fail(errors.FORBIDDEN, request, message="用户未获得该项目授权。")
    match = re.search(r"/nodes/(\d+)", request.url.path)
    if match and int(match.group(1)) not in {int(item) for item in member.get("nodeScope") or []}:
        return fail(errors.FORBIDDEN, request, message="用户不在该节点授权范围内。")
    return None


def idempotent(request: Request, key: str | None, producer):
    if not key:
        return producer()
    scope = f"{request.method}:{request.url.path}:{key}"
    cached = repo.state["idempotency"].get(scope)
    if cached is not None:
        return repo.clone(cached)
    result = producer()
    if not isinstance(result, JSONResponse):
        repo.state["idempotency"][scope] = repo.clone(result)
    return result


def filter_keyword(items: list[dict[str, Any]], keyword: str | None, fields: list[str]) -> list[dict[str, Any]]:
    if not keyword:
        return items
    lowered = keyword.lower()
    return [
        item
        for item in items
        if any(lowered in str(item.get(field, "")).lower() for field in fields)
    ]


def signed_url_for_task(task: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    if task["status"] == "已过期":
        return {"error": errors.EXPORT_TASK_EXPIRED}
    if task["status"] != "可下载":
        return {"error": errors.EXPORT_TASK_NOT_READY}
    return repo.signed_get(
        task["fileName"],
        task.get("downloadUrl") or f"mock://download/exports/{task['id']}",
        file_size=task.get("fileSize"),
    )


def admin_user_snapshot(user_id: str | None, role: str | None = None) -> dict[str, Any]:
    users = repo.state["admin_config"].get("users", [])
    user = next((item for item in users if item.get("id") == user_id), None)
    if user is None and role:
        user = next((item for item in users if item.get("role") == role), None)
    if user is None and role == "admin":
        user = {"id": user_id or "USER-ADMIN-001", "name": "系统管理员", "orgName": "省特检院平台组", "role": "admin"}
    return user or {"id": user_id or "USER-UNKNOWN", "name": "新授权成员", "orgName": "联调组织", "role": role or "inspection"}


def scoped_binding_ids(project_id: str, node_ids: list[int], binding_ids: list[str] | None) -> list[str]:
    if binding_ids:
        return binding_ids
    scoped = [
        item["id"]
        for item in repo.state["bindings"]
        if item["projectId"] == project_id
        and int(item["nodeId"]) in set(node_ids)
        and item.get("bindingStatus") != "已通过"
    ]
    return scoped


def build_config_diff(target: str, object_id: str, values: dict[str, Any], *, object_name: str | None = None) -> dict[str, Any]:
    changed = []
    for field, value in values.items():
        if isinstance(value, dict):
            value = ", ".join(f"{key}: {nested}" for key, nested in value.items())
        changed.append(
            {
                "field": field,
                "label": field,
                "before": None,
                "after": value,
                "severity": "info",
            }
        )
    return {
        "target": target,
        "objectId": object_id,
        "objectName": object_name or values.get("name") or values.get("scene") or target,
        "previewedAt": server_time(),
        "changed": changed,
    }


def project_member_snapshot(project_id: str, role: str, user_id: str | None = None, *, org_name: str | None = None) -> dict[str, Any]:
    user = admin_user_snapshot(user_id, role)
    node_scope = [35, 36, 40, 41, 42] if role == "ndt" else [1, 16, 24, 40, 68]
    return {
        "id": f"PM-{uuid4().hex[:8].upper()}",
        "projectId": project_id,
        "userId": user_id or user["id"],
        "name": user.get("name") or "授权成员",
        "orgName": org_name or user.get("orgName") or "联调组织",
        "role": role,
        "nodeScope": node_scope,
        "actions": repo.role_actions(role),
        "status": "启用",
        "updatedAt": server_time(),
    }


def project_detail_payload(project_id: str) -> dict[str, Any] | None:
    project = repo.require_project(project_id)
    if not project:
        return None
    members = [repo.clone(item) for item in repo.state["project_members"] if item["projectId"] == project_id]
    node_summary = []
    for group in repo.node_groups(PROJECT_ID if project_id != PROJECT_ID else project_id):
        nodes = group["nodes"]
        node_summary.append(
            {
                "groupName": group["groupName"],
                "total": len(nodes),
                "passed": len([item for item in nodes if item.get("status") == "已通过"]),
                "pending": len([item for item in nodes if item.get("status") in {"待提交", "待审查", "待人工确认"}]),
                "correction": len([item for item in nodes if item.get("status") in {"需补正", "补正中"}]),
            }
        )
    return {
        "project": repo.clone(project),
        "members": members,
        "participantUnits": [
            {"unitType": "owner", "unitName": project["ownerOrgName"], "contactName": "赵经理", "contactPhone": "13800000001"},
            {"unitType": "contractor", "unitName": project["contractorOrgName"], "contactName": "李工", "contactPhone": "13800000002"},
            {"unitType": "ndt", "unitName": project["ndtOrgName"], "contactName": "王工", "contactPhone": "13800000003"},
            {"unitType": "inspection", "unitName": project["inspectionOrgName"], "contactName": "张工", "contactPhone": "13800000004"},
        ],
        "nodeSummary": node_summary,
        "recentExportTasks": [repo.clone(item) for item in repo.state["export_tasks"] if item.get("projectId") == project_id],
    }


def simple_routes() -> list[dict[str, Any]]:
    return [
        {
            "path": "/workbench",
            "component": "#",
            "redirect": "/workbench/inspection",
            "name": "Workbench",
            "meta": {"title": "业务工作台", "icon": "vi-ep:monitor", "alwaysShow": True},
            "children": [
                {"path": "inspection", "component": "views/AICheck/Workbench", "name": "InspectionWorkbench", "meta": {"title": "监检工作台"}},
                {"path": "contractor", "component": "views/AICheck/Workbench", "name": "ContractorWorkbench", "meta": {"title": "施工方工作台"}},
                {"path": "ndt", "component": "views/AICheck/Workbench", "name": "NdtWorkbench", "meta": {"title": "无损检测工作台"}},
                {"path": "owner", "component": "views/AICheck/Workbench", "name": "OwnerWorkbench", "meta": {"title": "建设方工作台"}},
            ],
        },
        {
            "path": "/admin",
            "component": "#",
            "redirect": "/admin/overview",
            "name": "AICheckAdmin",
            "meta": {"title": "管理后台", "icon": "vi-ep:setting", "alwaysShow": True},
            "children": [
                {"path": item, "component": "views/AICheck/AdminOverview", "name": f"Admin{item.title().replace('-', '')}", "meta": {"title": "项目与权限配置"}}
                for item in ["overview", "projects", "org", "permission", "rules", "fine-config", "integration", "audit"]
            ],
        },
        {
            "path": "/knowledge",
            "component": "#",
            "redirect": "/knowledge/overview",
            "name": "Knowledge",
            "meta": {"title": "AI 知识库", "icon": "vi-ep:collection", "alwaysShow": True},
            "children": [
                {"path": item, "component": "views/AICheck/KnowledgeOverview", "name": f"Knowledge{item.title().replace('-', '')}", "meta": {"title": "AI 知识库管理"}}
                for item in ["overview", "sources", "files", "tasks", "rules", "retrieval", "reasoning", "compare", "config"]
            ],
        },
    ]


@mock_router.post("/mock/user/login")
def mock_login(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    user = authenticate(str(body.get("username", "")), str(body.get("password", "")))
    if not user:
        return fail(errors.AUTH_REQUIRED, request, message="账号或密码错误")
    return ok(user, request)


@mock_router.get("/mock/user/loginOut")
def mock_logout(request: Request):
    return ok(None, request)


@mock_router.get("/mock/role/list")
def mock_role_list(request: Request):
    return ok(simple_routes(), request)


@mock_router.get("/mock/role/list2")
def mock_role_list2(request: Request):
    return ok(["*.*.*"], request)


@mock_router.get("/mock/user/list")
def mock_user_list(request: Request):
    users = [
        {"username": "admin", "role": "admin", "roleId": "1", "permissions": ["*.*.*"]},
        {"username": "test", "role": "test", "roleId": "2", "permissions": ["example:dialog:create"]},
    ]
    return ok({"list": users, "total": len(users)}, request)


@router.post("/auth/login")
def auth_login(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    user = authenticate(str(body.get("username", "")), str(body.get("password", "")))
    if not user:
        return fail(errors.AUTH_REQUIRED, request, message="账号或密码错误")
    return ok({"token": issue_token(user), "user": user}, request)


@router.get("/auth/me")
def auth_me(request: Request):
    return ok(
        {
            "id": "USER-ADMIN",
            "username": "admin",
            "displayName": "系统管理员",
            "orgUnitName": "省特检院平台组",
            "defaultRole": "admin",
            "projectAuthorizations": repo.clone(repo.state["project_members"]),
        },
        request,
    )


@router.get("/auth/routes")
def auth_routes(request: Request):
    return ok(simple_routes(), request)


@router.get("/auth/actions")
def auth_actions(request: Request, role: str = Query(default="inspection")):
    return ok(repo.role_actions(role), request)


@router.get("/permissions/node-actions")
def node_actions(request: Request, role: str = Query(default="inspection")):
    return ok(repo.role_actions(role), request)


@router.get("/permissions/resources")
def permission_resources(request: Request):
    return ok(repo.state["admin_config"]["permissionMatrix"], request)


@router.post("/auth/logout")
def auth_logout(request: Request):
    return ok(None, request)


@router.get("/workbench/projects")
def list_workbench_projects(
    request: Request,
    role: str = Query(default="inspection"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    resolved_role = role_from_query(role, x_role)
    return ok([repo.project_for_role(item, resolved_role) for item in repo.state["projects"]], request)


@router.get("/projects")
def list_projects(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None):
    items = filter_keyword([repo.clone(item) for item in repo.state["projects"]], keyword, ["name", "code", "region"])
    return ok(page(items, page_no, page_size), request)


@router.post("/projects")
def create_project(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return create_admin_project(request, body, idempotency_key)


@router.get("/projects/{project_id}")
def get_project_detail(request: Request, project_id: str):
    detail = project_detail_payload(project_id)
    if not detail:
        return fail(errors.NOT_FOUND, request)
    return ok(detail, request)


@router.patch("/projects/{project_id}")
def update_project(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role"), if_match: str | None = Header(default=None, alias="If-Match")):
    guard = mutation_guard(request, project_id, x_role=x_role, if_match=if_match)
    if guard:
        return guard
    project = repo.require_project(project_id)
    changed = []
    for field in ["name", "type", "region", "ownerOrgName", "contractorOrgName", "ndtOrgName", "inspectionOrgName"]:
        if field in body:
            changed.append({"field": field, "before": project.get(field), "after": body[field]})
            project[field] = body[field]
    repo.touch_project(project_id)
    return ok({"project": repo.clone(project), **repo.mutation_result("更新项目", "Project", project_id, changed=changed)}, request)


@router.get("/projects/{project_id}/participants")
def list_participants(request: Request, project_id: str):
    detail = get_project_detail(request, project_id)
    if isinstance(detail, JSONResponse):
        return detail
    return ok(detail["data"]["participantUnits"], request)


@router.post("/projects/{project_id}/participants")
def save_participant(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    participant_id = body.get("id") or f"PU-{uuid4().hex[:8].upper()}"
    return ok(repo.mutation_result("保存参建单位", "ProjectUnit", participant_id), request)


@router.patch("/projects/{project_id}/participants/{participant_id}")
def update_participant(request: Request, project_id: str, participant_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    return ok(repo.mutation_result("更新参建单位", "ProjectUnit", participant_id, changed=[{"field": "values", "after": body}]), request)


@router.get("/projects/{project_id}/members")
def list_project_members(request: Request, project_id: str, role: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["project_members"] if item["projectId"] == project_id]
    if role:
        items = [item for item in items if item["role"] == role]
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/members")
def authorize_member(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        role = body.get("role", "inspection")
        user = admin_user_snapshot(body.get("userId"), role)
        member = {
            "id": f"PM-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "userId": body.get("userId") or user["id"],
            "name": body.get("name") or user.get("name") or "新授权成员",
            "orgName": body.get("orgName") or user.get("orgName") or "联调组织",
            "role": role,
            "nodeScope": body.get("nodeScope") or [ROLE_NODE_MAP.get(role, 24)],
            "actions": body.get("actions") or repo.role_actions(role),
            "status": "启用",
            "expiresAt": body.get("expiresAt"),
            "updatedAt": server_time(),
        }
        repo.state["project_members"].insert(0, member)
        audit_id = repo.add_audit("项目成员授权", "ProjectMember", member["id"])
        return ok({"member": member, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce)


@router.put("/projects/{project_id}/members/{member_id}")
def update_member(request: Request, project_id: str, member_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    member = repo.find_one("project_members", member_id)
    if not member:
        return fail(errors.NOT_FOUND, request, message="项目成员不存在。")
    changed = []
    for field in ["role", "nodeScope", "actions", "status", "expiresAt"]:
        if field in body:
            changed.append({"field": field, "before": member.get(field), "after": body[field]})
            member[field] = body[field]
    member["updatedAt"] = server_time()
    audit_id = repo.add_audit("更新项目成员授权", "ProjectMember", member_id)
    return ok({"member": repo.clone(member), "auditLogId": audit_id, "changed": changed}, request)


@router.post("/projects/{project_id}/initialize-workflow")
def initialize_workflow(request: Request, project_id: str, x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    return ok({**repo.mutation_result("初始化 69 节点流程", "Project", project_id), "createdNodeCount": 69}, request)


@router.get("/projects/{project_id}/workbench/context")
def workbench_context(request: Request, project_id: str, role: str = Query(default="inspection"), x_role: str | None = Header(default=None, alias="X-Role")):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    resolved_role = role_from_query(role, x_role)
    current_node_id = ROLE_NODE_MAP.get(resolved_role, project.get("currentNodeId", 24))
    role_project = repo.project_for_role(project, resolved_role)
    return ok(
        {
            "project": role_project,
            "role": resolved_role,
            "currentNodeId": current_node_id,
            "topbar": {
                "todoCount": project.get("todoCount", 0),
                "messageCount": project.get("messageCount", 0),
                "statusText": project.get("status"),
                "projectSwitcherEnabled": True,
            },
            "actions": role_project["actions"],
        },
        request,
    )


@router.get("/projects/{project_id}/workbench/summary")
def workbench_summary(request: Request, project_id: str, role: str = Query(default="inspection")):
    role_todos = [item for item in repo.state["todos"] if item["projectId"] == project_id]
    correction_count = len([item for item in repo.state["tree_nodes"] if item["projectId"] == project_id and item["status"] in {"需补正", "补正中"}])
    metrics = [
        {"key": "todo", "label": "待办", "value": len(role_todos), "tone": "orange"},
        {"key": "correction", "label": "补正", "value": correction_count, "tone": "red"},
        {"key": "document", "label": "资料", "value": len(repo.project_documents(project_id)), "tone": "blue"},
        {"key": "report", "label": "报告", "value": len([item for item in repo.state["reports"] if item["projectId"] == project_id]), "tone": "green"},
    ]
    if role == "owner":
        metrics = [
            {"key": "progress", "label": "总体进度", "value": "42%", "tone": "blue"},
            {"key": "report", "label": "报告版本", "value": len(repo.state["reports"]), "tone": "green"},
            {"key": "archive", "label": "归档资料", "value": len(repo.state["archive_items"]), "tone": "gray"},
        ]
    return ok(
        {
            "metrics": metrics,
            "todos": [repo.clone(item) for item in role_todos[:5]],
            "messages": [repo.clone(item) for item in repo.state["messages"] if item.get("projectId") == project_id][:5],
            "updatedAt": server_time(),
        },
        request,
    )


@router.get("/projects/{project_id}/tree")
def project_tree(request: Request, project_id: str):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    return ok({"project": repo.clone(project), "groups": repo.node_groups(PROJECT_ID if project_id != PROJECT_ID else project_id)}, request)


@router.get("/projects/{project_id}/nodes/{node_id}")
def node_detail(request: Request, project_id: str, node_id: int):
    node = repo.node(PROJECT_ID if project_id != PROJECT_ID else project_id, node_id)
    if not node:
        return fail(errors.NOT_FOUND, request)
    return ok({"node": repo.clone(node)}, request)


@router.get("/projects/{project_id}/nodes/{node_id}/requirements")
def node_requirements(request: Request, project_id: str, node_id: int):
    return ok([repo.clone(item) for item in repo.state["requirements"] if int(item["nodeId"]) == int(node_id)], request)


@router.get("/projects/{project_id}/nodes/{node_id}/package")
def node_package(request: Request, project_id: str, node_id: int):
    effective_project_id = PROJECT_ID if project_id != PROJECT_ID else project_id
    node = repo.node(effective_project_id, node_id)
    if not node:
        return fail(errors.NOT_FOUND, request)
    bindings = repo.bindings_for_node(effective_project_id, node_id)
    version_ids = {item["documentVersionId"] for item in bindings}
    return ok(
        {
            "node": repo.clone(node),
            "requirements": [repo.clone(item) for item in repo.state["requirements"] if int(item["nodeId"]) == int(node_id)],
            "bindings": bindings,
            "projectFiles": repo.project_documents(effective_project_id),
            "availableVersions": [repo.clone(item) for item in repo.state["versions"] if item["id"] in version_ids or True],
            "extractedFields": repo.fields_for_versions(version_ids),
            "reviewOpinions": [repo.clone(item) for item in repo.state["review_opinions"] if item["projectId"] == effective_project_id and int(item["nodeId"]) == int(node_id)],
            "aiRuns": [repo.clone(item) for item in repo.state["ai_runs"] if item["projectId"] == effective_project_id and int(item["nodeId"]) == int(node_id)],
            "actions": repo.clone(node.get("actions", [])),
        },
        request,
    )


@router.get("/projects/{project_id}/documents")
def list_documents(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None):
    items = filter_keyword(repo.project_documents(PROJECT_ID if project_id != PROJECT_ID else project_id), keyword, ["fileName", "sourceOrgName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/projects/{project_id}/documents/bindings")
def list_bindings(request: Request, project_id: str, nodeId: int | None = None):
    items = repo.bindings_for_project(PROJECT_ID if project_id != PROJECT_ID else project_id)
    if nodeId:
        items = [item for item in items if int(item["nodeId"]) == int(nodeId)]
    return ok(items, request)


@router.post("/projects/{project_id}/documents/upload-session")
def create_upload_session(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        files = body.get("files") or []
        if not files:
            return fail(errors.VALIDATION_ERROR, request, message="上传文件不能为空。")
        for file in files:
            if int(file.get("fileSize") or 0) > 50 * 1024 * 1024:
                return fail(errors.FILE_TOO_LARGE, request, message=f"{file.get('fileName', '文件')} 超过 50MB 上传限制。")
        session_id, upload_urls = repo.create_upload_session(project_id, files)
        repo.add_audit("创建上传会话", "UploadSession", session_id)
        return ok({"uploadSessionId": session_id, "expiresAt": upload_urls[0]["expiresAt"], "uploadUrls": upload_urls}, request)

    return idempotent(request, idempotency_key, produce)


@router.post("/projects/{project_id}/documents/upload-session/{session_id}/complete")
def complete_upload_session(request: Request, project_id: str, session_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    files = repo.complete_upload_session(session_id)
    dispatches = []
    for file in files:
        dispatches.append(
            task_dispatcher.dispatch_parse_document(
                file["documentId"],
                file["documentVersionId"],
                file["storageKey"],
                file.get("fileName"),
            )
        )
    result = repo.mutation_result("完成上传会话", "UploadSession", session_id, next_status="排队中")
    return ok({**result, "queuedTasks": dispatches, "fileCount": len(files)}, request)


@router.get("/projects/{project_id}/documents/{document_id}")
def document_detail(request: Request, project_id: str, document_id: str):
    document = repo.find_one("documents", document_id)
    if not document:
        return fail(errors.NOT_FOUND, request)
    versions = repo.versions_for_document(document_id)
    version_ids = {item["id"] for item in versions}
    preview = repo.document_preview(document)
    return ok(
        {
            "document": repo.clone(document),
            "currentVersion": repo.current_version(document_id),
            "versions": versions,
            "bindings": [item for item in repo.bindings_for_project(document["projectId"]) if item["documentId"] == document_id],
            "extractedFields": repo.fields_for_versions(version_ids),
            "evidenceLinks": repo.evidence_for_versions(version_ids),
            "preview": preview,
            "download": repo.signed_get(document["fileName"], f"mock://download/documents/{document_id}?versionId={document['currentVersionId']}", file_size=245760),
        },
        request,
    )


@router.get("/projects/{project_id}/documents/{document_id}/versions")
def document_versions(request: Request, project_id: str, document_id: str):
    return ok(repo.versions_for_document(document_id), request)


@router.get("/projects/{project_id}/documents/{document_id}/preview-url")
def document_preview_url(request: Request, project_id: str, document_id: str):
    document = repo.find_one("documents", document_id)
    if not document:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.document_preview(document), request)


@router.get("/projects/{project_id}/documents/{document_id}/download-url")
def document_download_url(request: Request, project_id: str, document_id: str):
    document = repo.find_one("documents", document_id)
    if not document:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.signed_get(document["fileName"], f"mock://download/documents/{document_id}?versionId={document['currentVersionId']}", file_size=245760), request)


@router.get("/projects/{project_id}/documents/{document_id}/ocr-fields")
def document_ocr_fields(request: Request, project_id: str, document_id: str):
    versions = repo.versions_for_document(document_id)
    return ok(repo.fields_for_versions({item["id"] for item in versions}), request)


@router.get("/projects/{project_id}/documents/{document_id}/review-feedback")
def document_review_feedback(request: Request, project_id: str, document_id: str):
    return ok({"opinions": repo.clone(repo.state["review_opinions"]), "rectifications": repo.clone(repo.state["rectifications"])}, request)


@router.post("/projects/{project_id}/documents/{document_id}/versions")
def append_document_version(request: Request, project_id: str, document_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    document = repo.find_one("documents", document_id)
    if not document:
        return fail(errors.NOT_FOUND, request)
    version_id = f"DV-{uuid4().hex[:8].upper()}-V{len(repo.versions_for_document(document_id)) + 1}"
    for version in repo.state["versions"]:
        if version["documentId"] == document_id:
            version["isCurrent"] = False
    version = {
        "id": version_id,
        "documentId": document_id,
        "versionNo": f"V{len(repo.versions_for_document(document_id)) + 1}",
        "hash": f"mock-sha256-{version_id}",
        "fileSize": int(body.get("fileSize") or 245760),
        "storageKey": f"documents/{project_id}/{version_id}",
        "ocrStatus": "排队中",
        "sliceStatus": "未切片",
        "vectorStatus": "未向量化",
        "uploaderName": "李工",
        "uploadTime": server_time(),
        "isCurrent": True,
    }
    repo.state["versions"].insert(0, version)
    document["currentVersionId"] = version_id
    document["fileStatus"] = "已追加版本" if body.get("mode") == "append" else "已替换"
    document["updatedAt"] = server_time()
    return ok({"version": version, **repo.mutation_result("新增文件版本", "DocumentVersion", version_id, next_status=document["fileStatus"])}, request)


@router.post("/projects/{project_id}/documents/bindings")
def bind_documents(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        binding_inputs = body.get("bindings") or []
        if not binding_inputs:
            return fail(errors.EMPTY_BINDINGS, request)
        node_ids = body.get("nodeIds") or ([body.get("nodeId")] if body.get("nodeId") else [ROLE_NODE_MAP["contractor"]])
        created = []
        changed = []
        for node_id in [int(item) for item in node_ids if item]:
            requirements = [item for item in repo.state["requirements"] if int(item["nodeId"]) == node_id]
            for index, binding_input in enumerate(binding_inputs):
                document = repo.find_one("documents", binding_input.get("documentId"))
                version_id = binding_input.get("documentVersionId") or (document or {}).get("currentVersionId")
                if not document or not version_id:
                    continue
                requirement = requirements[index % len(requirements)] if requirements else None
                binding = {
                    "id": f"BIND-{node_id}-{uuid4().hex[:6].upper()}",
                    "projectId": project_id,
                    "nodeId": node_id,
                    "requirementId": requirement.get("id") if requirement else None,
                    "requirementName": requirement.get("name") if requirement else None,
                    "documentId": document["id"],
                    "documentVersionId": version_id,
                    "fileName": document["fileName"],
                    "versionNo": "V1",
                    "usage": binding_input.get("usage") or body.get("usage") or "原始提交",
                    "sourceOrgName": document["sourceOrgName"],
                    "bindingStatus": "草稿挂载",
                    "boundByName": "李工",
                    "boundAt": server_time(),
                    "actions": ["submission:submit", "submission:withdraw"],
                }
                repo.state["bindings"].insert(0, binding)
                created.append(binding["id"])
            changed.append(repo.set_node_status(project_id, node_id, "部分提交"))
        return ok(repo.mutation_result("保存节点挂载关系", "NodeFileBinding", created[0] if created else "BIND-EMPTY", next_status="部分提交", changed=changed, affected_ids=created), request)

    return idempotent(request, idempotency_key, produce)


@router.patch("/projects/{project_id}/documents/bindings/{binding_id}")
def update_binding(request: Request, project_id: str, binding_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    binding = repo.find_one("bindings", binding_id)
    if not binding:
        return fail(errors.NOT_FOUND, request)
    changed = []
    for field in ["requirementId", "requirementName", "usage", "bindingStatus"]:
        if field in body:
            changed.append({"field": field, "before": binding.get(field), "after": body[field]})
            binding[field] = body[field]
    return ok(repo.mutation_result("更新挂载关系", "NodeFileBinding", binding_id, changed=changed), request)


@router.delete("/projects/{project_id}/documents/bindings/{binding_id}")
def delete_binding(request: Request, project_id: str, binding_id: str, x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    before = len(repo.state["bindings"])
    repo.state["bindings"] = [item for item in repo.state["bindings"] if item["id"] != binding_id]
    if len(repo.state["bindings"]) == before:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.mutation_result("解除草稿挂载", "NodeFileBinding", binding_id, next_status="已解除挂载"), request)


@router.post("/projects/{project_id}/documents/{document_id}/withdraw")
def withdraw_document(request: Request, project_id: str, document_id: str, x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    doc = repo.find_one("documents", document_id)
    if not doc:
        return fail(errors.NOT_FOUND, request)
    doc["fileStatus"] = "已撤回"
    return ok(repo.mutation_result("撤回文件", "Document", document_id, next_status="已撤回"), request)


@router.post("/projects/{project_id}/documents/{document_id}/void")
def void_document(request: Request, project_id: str, document_id: str, x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    doc = repo.find_one("documents", document_id)
    if not doc:
        return fail(errors.NOT_FOUND, request)
    doc["fileStatus"] = "已作废"
    return ok(repo.mutation_result("作废文件", "Document", document_id, next_status="已作废"), request)


@router.post("/projects/{project_id}/documents/batch-classify")
def batch_classify_documents(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    suggestions = [
        {"documentId": doc["id"], "fileName": doc["fileName"], "suggestedNodeIds": [24 if "焊工" in doc["fileName"] else 16], "confidence": 0.82}
        for doc in repo.project_documents(project_id)
    ]
    return ok({"suggestions": suggestions}, request)


@router.post("/projects/{project_id}/submissions/drafts")
def save_submission_draft(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        draft_id = f"DRAFT-{uuid4().hex[:8].upper()}"
        node_ids = body.get("nodeIds") or ([body.get("nodeId")] if body.get("nodeId") else [ROLE_NODE_MAP["contractor"]])
        node_ids = [int(item) for item in node_ids if item]
        binding_ids = scoped_binding_ids(project_id, node_ids, body.get("bindingIds") or [])
        if not binding_ids:
            return fail(errors.EMPTY_NODE_PACKAGE, request)
        draft = {
            "draftId": draft_id,
            "projectId": project_id,
            "nodeIds": node_ids,
            "bindingIds": binding_ids,
            "batchName": body.get("batchName"),
            "remark": body.get("remark"),
            "savedAt": server_time(),
        }
        repo.state["submission_drafts"].insert(0, draft)
        repo.add_audit("保存提交草稿", "SubmissionDraft", draft_id)
        return ok({"draftId": draft_id, "savedAt": draft["savedAt"], "bindingIds": binding_ids}, request)

    return idempotent(request, idempotency_key, produce)


def draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    nodes = [repo.node(draft["projectId"], node_id) for node_id in draft.get("nodeIds", [])]
    return {
        "draftId": draft["draftId"],
        "projectId": draft["projectId"],
        "nodeIds": draft.get("nodeIds", []),
        "nodeNames": [node["name"] for node in nodes if node],
        "bindingCount": len(draft.get("bindingIds", [])),
        "batchName": draft.get("batchName"),
        "remark": draft.get("remark"),
        "savedAt": draft["savedAt"],
    }


def submission_summary(submission: dict[str, Any]) -> dict[str, Any]:
    nodes = [repo.node(submission["projectId"], node_id) for node_id in submission.get("nodeIds", [])]
    return {
        "submissionId": submission["submissionId"],
        "snapshotId": submission["snapshotId"],
        "projectId": submission["projectId"],
        "nodeIds": submission.get("nodeIds", []),
        "nodeNames": [node["name"] for node in nodes if node],
        "bindingCount": len(submission.get("bindingIds", [])),
        "todoCount": len(submission.get("createdTodoIds", [])),
        "batchName": submission.get("batchName"),
        "submitterComment": submission.get("submitterComment"),
        "nextStatus": submission.get("nextStatus"),
        "submittedAt": submission["submittedAt"],
        "withdrawal": submission.get("withdrawal"),
    }


@router.get("/projects/{project_id}/submissions")
def list_submissions(request: Request, project_id: str):
    drafts = [draft_summary(item) for item in repo.state["submission_drafts"] if item["projectId"] == project_id]
    submissions = [submission_summary(item) for item in repo.state["submissions"] if item["projectId"] == project_id]
    return ok({"drafts": drafts, "submissions": submissions}, request)


@router.get("/projects/{project_id}/submissions/drafts/{draft_id}")
def get_submission_draft(request: Request, project_id: str, draft_id: str):
    draft = next((item for item in repo.state["submission_drafts"] if item["projectId"] == project_id and item["draftId"] == draft_id), None)
    if not draft:
        return fail(errors.NOT_FOUND, request)
    bindings = [item for item in repo.bindings_for_project(project_id) if item["id"] in set(draft.get("bindingIds", []))]
    nodes = [repo.node(project_id, node_id) for node_id in draft.get("nodeIds", [])]
    return ok({**draft_summary(draft), "nodes": [repo.clone(item) for item in nodes if item], "bindings": bindings}, request)


@router.post("/projects/{project_id}/submissions")
def submit_node_package(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        submission_id = f"SUB-{uuid4().hex[:8].upper()}"
        snapshot_id = f"SNAP-{uuid4().hex[:8].upper()}"
        node_ids = [int(item) for item in (body.get("nodeIds") or ([body.get("nodeId")] if body.get("nodeId") else [ROLE_NODE_MAP["contractor"]])) if item]
        binding_ids = scoped_binding_ids(project_id, node_ids, body.get("bindingIds") or [])
        if not binding_ids:
            return fail(errors.EMPTY_NODE_PACKAGE, request)
        changed = []
        for binding in repo.state["bindings"]:
            if binding["id"] in binding_ids:
                binding["bindingStatus"] = "已提交"
        for node_id in node_ids:
            changed.append(repo.set_node_status(project_id, node_id, "AI 预审中"))
        todo_id = f"TODO-{uuid4().hex[:8].upper()}"
        repo.state["todos"].insert(
            0,
            {
                "id": todo_id,
                "title": "节点资料已提交，待 AI 预审",
                "projectId": project_id,
                "nodeId": node_ids[0] if node_ids else None,
                "targetType": "submission",
                "targetId": submission_id,
                "status": "待处理",
                "priority": "中",
                "assigneeName": "张工",
                "actions": ["ai:recheck"],
            },
        )
        submission = {
            "submissionId": submission_id,
            "snapshotId": snapshot_id,
            "projectId": project_id,
            "nodeIds": node_ids,
            "bindingIds": binding_ids,
            "batchName": body.get("batchName"),
            "submitterComment": body.get("submitterComment"),
            "nextStatus": "AI 预审中",
            "submittedAt": server_time(),
            "createdTodoIds": [todo_id],
            "changed": changed,
        }
        repo.state["submissions"].insert(0, submission)
        return ok({"submissionId": submission_id, "snapshotId": snapshot_id, "nextStatus": "AI 预审中", "createdTodos": [repo.state["todos"][0]]}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/submissions/{submission_id}")
def get_submission_detail(request: Request, project_id: str, submission_id: str):
    submission = next((item for item in repo.state["submissions"] if item["projectId"] == project_id and item["submissionId"] == submission_id), None)
    if not submission:
        return fail(errors.NOT_FOUND, request)
    bindings = [item for item in repo.bindings_for_project(project_id) if item["id"] in set(submission.get("bindingIds", []))]
    nodes = [repo.node(project_id, node_id) for node_id in submission.get("nodeIds", [])]
    todos = [item for item in repo.state["todos"] if item["id"] in set(submission.get("createdTodoIds", []))]
    return ok({**submission_summary(submission), "nodes": [repo.clone(item) for item in nodes if item], "bindings": bindings, "createdTodos": todos, "changed": submission.get("changed", [])}, request)


@router.post("/projects/{project_id}/submissions/{submission_id}/withdraw-items")
def withdraw_submission_items(
    request: Request,
    project_id: str,
    submission_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        binding_ids = body.get("bindingIds") or []
        if not binding_ids:
            return fail(errors.EMPTY_BINDINGS, request)
        for binding in repo.state["bindings"]:
            if binding["id"] in binding_ids:
                binding["bindingStatus"] = "草稿挂载"
        submission = next((item for item in repo.state["submissions"] if item["submissionId"] == submission_id), None)
        if submission:
            submission["withdrawal"] = {"bindingCount": len(binding_ids), "reason": body.get("reason") or "撤回未提交项", "withdrawnAt": server_time()}
            submission["nextStatus"] = "部分提交"
        node_ids = sorted({int(item["nodeId"]) for item in repo.state["bindings"] if item["id"] in binding_ids})
        changed = [repo.set_node_status(project_id, node_id, "部分提交") for node_id in node_ids]
        return ok(repo.mutation_result("撤回未提交项", "Submission", submission_id, next_status="部分提交", changed=changed, affected_ids=binding_ids), request)

    return idempotent(request, idempotency_key, produce)


@router.post("/projects/{project_id}/rectifications")
def submit_rectification(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        node_id = int(body.get("nodeId") or ROLE_NODE_MAP["contractor"])
        rectification = {
            "id": f"REC-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "status": "已反馈",
            "comment": body.get("comment") or body.get("description"),
            "createdAt": server_time(),
        }
        repo.state["rectifications"].insert(0, rectification)
        changed = [repo.set_node_status(project_id, node_id, "复审中")]
        return ok({"rectification": {"id": rectification["id"], "projectId": project_id, "nodeId": node_id, "status": rectification["status"]}, "nextStatus": "复审中", "createdTodos": [], **repo.mutation_result("提交补正反馈", "Rectification", rectification["id"], changed=changed)}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/rectifications")
def list_rectifications(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return ok(page([repo.clone(item) for item in repo.state["rectifications"] if item["projectId"] == project_id], page_no, page_size), request)


@router.get("/projects/{project_id}/rectifications/{rectification_id}")
def rectification_detail(request: Request, project_id: str, rectification_id: str):
    item = repo.find_one("rectifications", rectification_id)
    if not item:
        return fail(errors.NOT_FOUND, request)
    return ok({"rectification": repo.clone(item), "bindings": repo.bindings_for_node(project_id, item["nodeId"]), "evidenceLinks": repo.clone(repo.state["evidence_links"])}, request)


@router.get("/projects/{project_id}/workflow")
def project_workflow(request: Request, project_id: str):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    return ok({"projectId": project_id, "status": project["status"], "stateMachineVersion": "WF-PIPE-2026"}, request)


@router.get("/projects/{project_id}/workflow/instances/{workflow_id}")
def workflow_instance(request: Request, project_id: str, workflow_id: str):
    return ok({"id": workflow_id, "projectId": project_id, "status": "运行中", "currentNodeId": ROLE_NODE_MAP["inspection"]}, request)


@router.get("/projects/{project_id}/workflow/timeline")
def workflow_timeline(request: Request, project_id: str):
    return ok(
        [
            {"title": "资料提交", "actorName": "李工", "status": "已提交", "createdAt": "2026-06-25 10:45:00"},
            {"title": "AI 预审", "actorName": "系统", "status": "完成", "createdAt": "2026-06-25 15:10:00"},
            {"title": "监检审查", "actorName": "张工", "status": "待人工确认", "createdAt": "2026-06-26 09:12:00"},
        ],
        request,
    )


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/attachments")
def inspection_attachments(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    return create_upload_session(request, project_id, {"files": body.get("files") or [{"fileName": "监检资料.pdf", "fileSize": 245760, "fileType": "application/pdf"}]}, None, x_role)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/file-bindings")
def inspection_file_bindings(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    body = {**body, "nodeId": node_id}
    return bind_documents(request, project_id, body, None, x_role)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/ai-recheck")
def ai_recheck(
    request: Request,
    project_id: str,
    node_id: int,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        run_id = f"AIRUN-{node_id}-{uuid4().hex[:8].upper()}"
        node = repo.node(project_id, node_id)
        run = {
            "id": run_id,
            "projectId": project_id,
            "nodeId": node_id,
            "subject": node["name"] if node else "节点 AI 复核",
            "model": "review-chat",
            "promptVersion": f"node-{node_id}-v1",
            "ruleVersion": "Welder-Qualification-B-v2.1",
            "inputDocumentVersionIds": [item["documentVersionId"] for item in repo.bindings_for_node(project_id, node_id)],
            "status": "推理中",
            "startedAt": server_time(),
            "steps": [],
            "suggestion": {
                "id": f"AIS-{uuid4().hex[:8].upper()}",
                "result": "需人工确认",
                "opinionDraft": "AI 复核任务已进入队列，完成后将更新审查建议。",
                "risks": [],
                "confidence": 0.0,
                "manualConfirmItems": [],
            },
            "evidenceLinks": [],
        }
        repo.state["ai_runs"].insert(0, run)
        repo.set_node_status(project_id, node_id, "业务核验中")
        dispatch = task_dispatcher.dispatch_ai_recheck(project_id, node_id, run_id)
        return ok({"runId": run_id, "status": run["status"], "latestRun": run, "dispatch": dispatch}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/ai-runs")
def list_ai_runs(request: Request, project_id: str, node_id: int):
    return ok([repo.clone(item) for item in repo.state["ai_runs"] if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)], request)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/ai-runs/{run_id}")
def get_ai_run(request: Request, project_id: str, node_id: int, run_id: str):
    run = repo.find_one("ai_runs", run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.clone(run), request)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/review-opinions")
def save_review_opinion(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        opinion = {
            "id": f"OPN-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "result": body.get("result") or "满足要求",
            "opinion": body.get("opinion") or "资料、证据链与规则要求一致，同意通过。",
            "basis": body.get("basis"),
            "riskLevel": body.get("riskLevel", "低"),
            "closeStatus": "未关闭",
            "evidenceLinkIds": body.get("evidenceLinkIds") or [],
            "reviewerName": "张工",
            "createdAt": server_time(),
        }
        repo.state["review_opinions"].insert(0, opinion)
        next_status = "已通过" if opinion["result"] == "满足要求" else "需补正"
        repo.set_node_status(project_id, node_id, next_status)
        return ok({"opinion": opinion, "nextStatus": next_status}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/review-opinions")
def list_review_opinions(request: Request, project_id: str, node_id: int):
    return ok([repo.clone(item) for item in repo.state["review_opinions"] if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)], request)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/ai-suggestions/{suggestion_id}/adopt")
def adopt_ai_suggestion(request: Request, project_id: str, node_id: int, suggestion_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    draft = {
        "id": f"OPN-DRAFT-{uuid4().hex[:8].upper()}",
        "projectId": project_id,
        "nodeId": node_id,
        "result": body.get("result") or "满足要求",
        "opinion": body.get("opinion") or "采纳 AI 建议。",
        "evidenceLinkIds": body.get("evidenceLinkIds") or ["EV-24-001"],
        "reviewerName": "张工",
        "createdAt": server_time(),
    }
    audit_id = repo.add_audit("采纳 AI 建议", "AiSuggestion", suggestion_id)
    return ok({"draftOpinion": draft, "auditLogId": audit_id}, request)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/ai-suggestions/{suggestion_id}/reject")
def reject_ai_suggestion(request: Request, project_id: str, node_id: int, suggestion_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    return ok(repo.mutation_result("驳回 AI 建议", "AiSuggestion", suggestion_id, changed=[{"field": "reason", "after": body.get("reason")}]), request)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/actions/return-correction")
def return_correction(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        rectification = {
            "id": f"REC-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "status": "待反馈",
            "comment": body.get("reason") or body.get("requirement") or "请补充说明。",
            "createdAt": server_time(),
        }
        repo.state["rectifications"].insert(0, rectification)
        changed = [repo.set_node_status(project_id, node_id, "需补正")]
        todo = {
            "id": f"TODO-{uuid4().hex[:8].upper()}",
            "title": f"节点 {node_id} 退回补正",
            "projectId": project_id,
            "nodeId": node_id,
            "targetType": "rectification",
            "targetId": rectification["id"],
            "status": "待处理",
            "priority": "高",
            "assigneeName": "李工",
            "actions": ["rectification:submit"],
        }
        repo.state["todos"].insert(0, todo)
        return ok({"rectification": {"id": rectification["id"], "projectId": project_id, "nodeId": node_id, "status": rectification["status"]}, "nextStatus": "需补正", "createdTodos": [todo], **repo.mutation_result("退回补正", "Rectification", rectification["id"], changed=changed)}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/evidence-chain")
def evidence_chain(request: Request, project_id: str, node_id: int):
    node = repo.node(project_id, node_id)
    if not node:
        return fail(errors.NOT_FOUND, request)
    links = repo.clone(repo.state["evidence_links"])
    grouped = []
    for object_type in sorted({item["objectType"] for item in links}):
        grouped.append({"objectType": object_type, "links": [item for item in links if item["objectType"] == object_type]})
    return ok({"node": repo.clone(node), "links": links, "groupedByObject": grouped}, request)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/standards")
def standards(request: Request, project_id: str, node_id: int):
    return ok(
        [
            {
                "clauseId": "TSG-Z6002-3.2",
                "standardName": "TSG Z6002 焊接人员考核细则",
                "clauseNo": "3.2",
                "title": "焊工资格覆盖要求",
                "summary": "焊工持证项目应覆盖实际焊接方法、材料类别和焊接位置。",
                "effectiveVersion": "2010",
                "evidenceLinkId": "EV-24-002",
            }
        ],
        request,
    )


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/date-compare")
def date_compare(request: Request, project_id: str, node_id: int):
    return ok(
        [
            {
                "fieldName": "证书有效期",
                "leftLabel": "证书有效期",
                "leftValue": "2024-03-15 至 2028-03-14",
                "rightLabel": "施工周期",
                "rightValue": "2026-06-01 至 2026-12-31",
                "result": "覆盖",
                "evidenceLinkIds": ["EV-24-001"],
            }
        ],
        request,
    )


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/rules/current-version")
def current_rule_version(request: Request, project_id: str, node_id: int):
    rule = repo.state["rule_versions"][0]
    return ok({"rule": repo.clone(rule)}, request)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/review-log")
def review_log(request: Request, project_id: str, node_id: int):
    return ok([repo.clone(item) for item in repo.state["review_opinions"] if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)], request)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/report-review")
def generate_report_review(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        report = {
            "id": f"RPT-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "reportNo": f"GDJ-JJ-2026-{len(repo.state['reports']) + 1:03d}",
            "versionNo": "V1",
            "title": f"{repo.require_project(project_id)['name']}监督检验报告",
            "status": "复核中",
            "scope": body.get("reportScope") or "currentNode",
            "nodeIds": [node_id],
            "templateVersion": "TPL-PIPE-2026.06",
            "generatedAt": server_time(),
            "generatedByName": "张工",
            "reviewerName": "张工",
            "dataSnapshotId": f"SNAP-RPT-{uuid4().hex[:8].upper()}",
            "previewUrl": "mock://preview/reports/new",
            "actions": ["report:view", "report:export", "report:archive"],
        }
        repo.state["reports"].insert(0, report)
        repo.touch_project(project_id, "报告生成/复核中", node_id)
        todo = {"id": f"TODO-{uuid4().hex[:8].upper()}", "title": "报告复核", "projectId": project_id, "targetType": "report", "targetId": report["id"], "status": "待处理", "priority": "中", "assigneeName": "张工", "actions": ["report:review"]}
        repo.state["todos"].insert(0, todo)
        return ok({"report": report, "nextStatus": "报告生成/复核中", "createdTodos": [todo]}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/owner/reports")
def owner_reports(request: Request, project_id: str):
    return ok([repo.clone(item) for item in repo.state["reports"] if item["projectId"] == project_id], request)


@router.get("/projects/{project_id}/reports")
def list_reports(request: Request, project_id: str):
    return ok([repo.clone(item) for item in repo.state["reports"] if item["projectId"] == project_id], request)


@router.get("/projects/{project_id}/reports/{report_id}")
def report_detail(request: Request, project_id: str, report_id: str):
    report = repo.find_one("reports", report_id)
    if not report:
        return fail(errors.NOT_FOUND, request)
    return ok(
        {
            "report": repo.clone(report),
            "sections": [
                {"key": "summary", "title": "检验结论", "content": "资料、证据链与规则要求一致，建议复核后签发。", "evidenceLinkIds": ["EV-24-001"]},
                {"key": "node-24", "title": "焊工资格证及持证合格项目", "content": "证书有效期覆盖施工周期，持证项目覆盖焊接方法。", "evidenceLinkIds": ["EV-24-001", "EV-24-002"]},
            ],
            "evidenceLinks": repo.clone(repo.state["evidence_links"]),
            "reviewTrail": [{"title": "生成报告草稿", "actorName": report.get("generatedByName", "张工"), "result": report["status"], "createdAt": report["generatedAt"]}],
            "versionHistory": [{"id": report["id"], "versionNo": report.get("versionNo", "V1"), "status": report["status"], "generatedAt": report["generatedAt"], "summary": "当前版本"}],
        },
        request,
    )


@router.patch("/projects/{project_id}/reports/{report_id}")
def update_report(request: Request, project_id: str, report_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    report = repo.find_one("reports", report_id)
    if not report:
        return fail(errors.NOT_FOUND, request)
    changed = []
    for field in ["title", "status"]:
        if field in body:
            changed.append({"field": field, "before": report.get(field), "after": body[field]})
            report[field] = body[field]
    return ok({"report": repo.clone(report), **repo.mutation_result("保存报告", "Report", report_id, changed=changed)}, request)


@router.get("/projects/{project_id}/reports/{report_id}/versions")
def report_versions(request: Request, project_id: str, report_id: str):
    report = repo.find_one("reports", report_id)
    if not report:
        return fail(errors.NOT_FOUND, request)
    return ok([{"id": report_id, "versionNo": report.get("versionNo", "V1"), "status": report["status"], "generatedAt": report["generatedAt"], "summary": "当前版本"}], request)


@router.post("/projects/{project_id}/reports/{report_id}/export")
def export_report(request: Request, project_id: str, report_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        report = repo.find_one("reports", report_id)
        if not report:
            return fail(errors.NOT_FOUND, request)
        export_id = f"EXP-RPT-{uuid4().hex[:8].upper()}"
        task = {
            "id": export_id,
            "projectId": project_id,
            "exportType": "report",
            "status": "可下载",
            "progress": 100,
            "fileName": f"{report['title']}.{body.get('format') or 'pdf'}",
            "fileSize": 2097152,
            "downloadUrl": f"mock://download/reports/{report_id}.{body.get('format') or 'pdf'}",
            "createdAt": server_time(),
            "finishedAt": server_time(),
            "expiresAt": "2026-06-27 18:00:00",
        }
        repo.attach_export_artifact(task, content_type="application/pdf" if (body.get("format") or "pdf") == "pdf" else None)
        repo.state["export_tasks"].insert(0, task)
        report["status"] = "已签发" if report.get("status") == "待签发" else "复核中"
        return ok({"exportId": export_id, "report": report}, request)

    return idempotent(request, idempotency_key, produce)


@router.post("/projects/{project_id}/reports/{report_id}/archive")
def archive_report(request: Request, project_id: str, report_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        report = repo.find_one("reports", report_id)
        if not report:
            return fail(errors.NOT_FOUND, request)
        report["status"] = "已归档"
        repo.touch_project(project_id, "已归档")
        item = {
            "id": f"ARCH-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "name": f"{report['title']}.pdf",
            "type": "report",
            "nodeId": report.get("nodeIds", [None])[0],
            "sourceOrgName": "省特检院一部",
            "status": "已归档",
            "updatedAt": server_time(),
            "downloadUrl": report.get("exportUrl") or f"mock://download/reports/{report_id}.pdf",
        }
        repo.state["archive_items"].insert(0, item)
        return ok({"report": report, "nextStatus": "已归档"}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/archive")
def list_archive(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, nodeId: int | None = None):
    items = [repo.clone(item) for item in repo.state["archive_items"] if item.get("projectId") == project_id]
    if nodeId:
        items = [item for item in items if int(item.get("nodeId") or 0) == int(nodeId)]
    items = filter_keyword(items, keyword, ["name", "sourceOrgName", "status"])
    return ok(page(items, page_no, page_size), request)


@router.get("/projects/{project_id}/archive/package")
def archive_package(request: Request, project_id: str):
    export_id = "EXP-ARCHIVE-QUEUE-001"
    task = repo.find_one("export_tasks", export_id) or {
        "id": export_id,
        "projectId": project_id,
        "exportType": "archive-package",
        "status": "可下载",
        "progress": 100,
        "fileName": f"{project_id}-归档资料包.zip",
        "fileSize": 4194304,
        "downloadUrl": f"mock://download/archive/{project_id}.zip",
        "createdAt": server_time(),
        "finishedAt": server_time(),
    }
    repo.attach_export_artifact(task, content_type="application/zip")
    return ok({**repo.signed_get(task["fileName"], task["downloadUrl"], "application/zip", task.get("fileSize")), "exportId": export_id, "projectId": project_id, "packageType": "archive", "itemCount": len(repo.state["archive_items"]), "generatedAt": server_time()}, request)


@router.get("/projects/{project_id}/archive/evidence-package")
def evidence_package(request: Request, project_id: str, nodeId: int | None = None):
    export_id = "EXP-EVIDENCE-RUNNING-001"
    file_name = f"{project_id}-节点{nodeId or 24}-证据定位包.zip"
    task = {"id": export_id, "projectId": project_id, "exportType": "evidence-package", "status": "可下载", "progress": 100, "fileName": file_name, "fileSize": 786432, "downloadUrl": f"mock://download/archive/{project_id}-evidence.zip", "createdAt": server_time(), "finishedAt": server_time()}
    repo.attach_export_artifact(task, content_type="application/zip")
    return ok({**repo.signed_get(file_name, task["downloadUrl"], "application/zip", task.get("fileSize")), "exportId": export_id, "projectId": project_id, "packageType": "evidence", "itemCount": len(repo.state["evidence_links"]), "generatedAt": server_time()}, request)


@router.get("/projects/{project_id}/archive/{archive_item_id}")
def archive_item_detail(request: Request, project_id: str, archive_item_id: str):
    item = repo.find_one("archive_items", archive_item_id)
    if not item:
        return fail(errors.NOT_FOUND, request)
    report = repo.state["reports"][0] if item["type"] == "report" else None
    return ok(
        {
            "item": repo.clone(item),
            "preview": {**repo.signed_get(item["name"], item.get("downloadUrl") or f"mock://preview/archive/{item['id']}", "application/pdf"), "previewType": "pdf", "readonly": True, "pageCount": 4},
            "download": repo.signed_get(item["name"], item.get("downloadUrl") or f"mock://download/archive/{item['id']}"),
            "report": repo.clone(report) if report else None,
            "document": None,
            "evidenceLinks": repo.clone(repo.state["evidence_links"]),
            "relatedExportTasks": [repo.clone(task) for task in repo.state["export_tasks"] if task.get("projectId") == project_id],
        },
        request,
    )


@router.get("/projects/{project_id}/export-tasks/{export_id}")
def project_export_task(request: Request, project_id: str, export_id: str):
    task = repo.find_one("export_tasks", export_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    return ok({"task": repo.clone(task)}, request)


@router.get("/exports/{export_id}")
def get_export_task(request: Request, export_id: str):
    task = repo.find_one("export_tasks", export_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    return ok({"task": repo.clone(task)}, request)


@router.get("/exports/{export_id}/download-url")
def export_download_url(request: Request, export_id: str):
    task = repo.find_one("export_tasks", export_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    signed = signed_url_for_task(task)
    if isinstance(signed, dict) and "error" in signed:
        return fail(signed["error"], request)
    return ok(signed, request)


@router.get("/downloads/{file_id}/signed-url")
def file_signed_url(request: Request, file_id: str):
    return ok(repo.signed_get(f"{file_id}.bin", f"mock://download/{file_id}"), request)


@router.post("/exports")
def create_export(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        export_id = f"EXP-{uuid4().hex[:8].upper()}"
        task = {
            "id": export_id,
            "projectId": body.get("projectId"),
            "exportType": body.get("exportType") or "config-package",
            "status": "可下载",
            "progress": 100,
            "fileName": body.get("fileName") or f"{export_id}.zip",
            "fileSize": 1024,
            "downloadUrl": f"mock://download/exports/{export_id}.zip",
            "createdAt": server_time(),
            "finishedAt": server_time(),
            "expiresAt": "2026-06-27 18:00:00",
        }
        repo.attach_export_artifact(task)
        repo.state["export_tasks"].insert(0, task)
        return ok({"exportId": export_id, "task": task}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/ndt/summary")
def ndt_summary(request: Request, project_id: str):
    return ok({"filmCount": len(repo.state["ndt_films"]), "recordCount": len(repo.state["ndt_records"]), "reportCount": len(repo.state["ndt_reports"]), "feedbackCount": len(repo.state["ndt_feedback"])}, request)


@router.get("/projects/{project_id}/ndt/films")
def list_ndt_films(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), status: str | None = None, method: str | None = None, keyword: str | None = None):
    items = [repo.clone(item) for item in repo.state["ndt_films"] if item["projectId"] == project_id]
    if status:
        items = [item for item in items if item["status"] == status]
    if method:
        items = [item for item in items if item["method"] == method]
    items = filter_keyword(items, keyword, ["filmNo", "weldNo", "pipelineNo"])
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/ndt/films")
def create_ndt_film(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        film = {
            "id": f"FILM-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "filmNo": body.get("filmNo") or "RT-NEW",
            "weldNo": body.get("weldNo") or "W-NEW",
            "pipelineNo": body.get("pipelineNo"),
            "method": body.get("method") or "RT",
            "testDate": body.get("testDate"),
            "status": "待提交",
            "actions": ["ndt:submit"],
        }
        repo.state["ndt_films"].insert(0, film)
        return ok({"film": film}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/ndt/films/{film_id}")
def ndt_film_detail(request: Request, project_id: str, film_id: str):
    film = repo.find_one("ndt_films", film_id)
    if not film:
        return fail(errors.NOT_FOUND, request)
    return ok({"film": repo.clone(film)}, request)


@router.patch("/projects/{project_id}/ndt/films/{film_id}")
def update_ndt_film(request: Request, project_id: str, film_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    film = repo.find_one("ndt_films", film_id)
    if not film:
        return fail(errors.NOT_FOUND, request)
    film.update({key: value for key, value in body.items() if value is not None})
    return ok({"film": repo.clone(film), **repo.mutation_result("更新底片", "NdtFilm", film_id)}, request)


@router.post("/projects/{project_id}/ndt/films/import")
def import_ndt_films(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    rows = body.get("rows") or []
    created = []
    for row in rows:
        film = {"id": f"FILM-{uuid4().hex[:8].upper()}", "projectId": project_id, "filmNo": row.get("filmNo") or "RT-IMPORT", "weldNo": row.get("weldNo") or "W-IMPORT", "method": row.get("method") or "RT", "status": "待提交", "actions": ["ndt:submit"]}
        repo.state["ndt_films"].insert(0, film)
        created.append(film)
    return ok({"imported": len(created), "failed": [], "films": created}, request)


@router.get("/projects/{project_id}/ndt/records")
def list_ndt_records(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), filmId: str | None = None, reportId: str | None = None, sampleStatus: str | None = None):
    items = [repo.clone(item) for item in repo.state["ndt_records"] if item["projectId"] == project_id]
    if filmId:
        items = [item for item in items if item.get("filmId") == filmId]
    if reportId:
        items = [item for item in items if item.get("reportId") == reportId]
    if sampleStatus:
        items = [item for item in items if item.get("sampleStatus") == sampleStatus]
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/ndt/records/import")
def import_ndt_records(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard
    created = []
    for row in body.get("rows") or [{"recordNo": "REC-IMPORT-001", "weldNo": "W-IMPORT"}]:
        record = {
            "id": f"NDT-REC-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": int(body.get("nodeId") or 40),
            "recordNo": row.get("recordNo") or "REC-IMPORT",
            "filmId": row.get("filmId"),
            "reportId": row.get("reportId"),
            "weldNo": row.get("weldNo") or "W-IMPORT",
            "pipelineNo": row.get("pipelineNo"),
            "method": row.get("method") or "RT",
            "testDate": row.get("testDate") or "2026-06-26",
            "evaluatorName": row.get("evaluatorName") or "王工",
            "result": row.get("result") or "待复核",
            "sampleStatus": row.get("sampleStatus") or "未抽查",
            "conclusion": row.get("conclusion"),
            "importedAt": server_time(),
            "actions": ["ndt:record-import"],
        }
        repo.state["ndt_records"].insert(0, record)
        created.append(record)
    return ok({"imported": len(created), "failed": [], "records": created}, request)


@router.get("/projects/{project_id}/ndt/reports")
def list_ndt_reports(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), status: str | None = None, method: str | None = None):
    items = [repo.clone(item) for item in repo.state["ndt_reports"] if item["projectId"] == project_id]
    if status:
        items = [item for item in items if item["status"] == status]
    if method:
        items = [item for item in items if item["method"] == method]
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/ndt/reports/upload-session")
def ndt_report_upload_session(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        files = body.get("files") or [{"fileName": "RT检测报告.pdf", "fileSize": 245760, "fileType": "application/pdf"}]
        session_id = f"UPS-NDT-{uuid4().hex[:8].upper()}"
        upload_urls = []
        for file in files:
            doc, version = repo.create_document(project_id, file.get("fileName", "RT检测报告.pdf"), file.get("fileType", "pdf"), source_org_name="华测检测有限公司", uploader_name="王工")
            report = {
                "id": f"NDT-RPT-{uuid4().hex[:8].upper()}",
                "projectId": project_id,
                "reportNo": file.get("fileName", "RT检测报告").split(".")[0],
                "method": "UT" if "UT" in file.get("fileName", "") else "RT",
                "fileId": doc["id"],
                "relatedFilmIds": body.get("relatedFilmIds") or [],
                "status": "待提交",
                "uploadedAt": server_time(),
                "actions": ["ndt:submit"],
            }
            repo.state["ndt_reports"].insert(0, report)
            content_type = file.get("fileType") or "application/pdf"
            upload_urls.append({"fileName": doc["fileName"], "documentId": doc["id"], "documentVersionId": version["id"], "url": repo.signed_put("documents", version["storageKey"], f"mock://upload/ndt/{session_id}/{doc['id']}", content_type=content_type), "method": "PUT", "expiresAt": "2026-06-27 18:00:00", "headers": {"Content-Type": content_type}})
        return ok({"uploadSessionId": session_id, "expiresAt": "2026-06-27 18:00:00", "uploadUrls": upload_urls}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/ndt/reports/{report_id}")
def ndt_report_detail(request: Request, project_id: str, report_id: str):
    report = repo.find_one("ndt_reports", report_id)
    if not report:
        return fail(errors.NOT_FOUND, request)
    films = [repo.clone(item) for item in repo.state["ndt_films"] if item["id"] in set(report.get("relatedFilmIds", []))]
    records = [repo.clone(item) for item in repo.state["ndt_records"] if item.get("reportId") == report_id]
    document = repo.find_one("documents", report.get("fileId"))
    return ok({"report": repo.clone(report), "films": films, "records": records, "document": repo.clone(document) if document else None, "feedback": repo.clone(repo.state["ndt_feedback"])}, request)


@router.post("/projects/{project_id}/ndt/submissions")
def submit_ndt(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        node_id = int(body.get("nodeId") or 40)
        submission_id = f"NDT-SUB-{uuid4().hex[:8].upper()}"
        submitted_report_ids = set(body.get("reportIds") or [])
        for report in repo.state["ndt_reports"]:
            if report["id"] in submitted_report_ids:
                report["status"] = "待审查"
        if not any(report["projectId"] == project_id and report["status"] in {"草稿", "待提交", "需补正"} for report in repo.state["ndt_reports"]):
            seed = uuid4().hex[:8].upper()
            repo.state["ndt_reports"].append(
                {
                    "id": f"NDT-RPT-{seed}",
                    "projectId": project_id,
                    "reportNo": f"RT-FOLLOW-{seed[:4]}",
                    "method": "RT",
                    "fileId": "DOC-20260625-004",
                    "relatedFilmIds": body.get("filmIds") or ["FILM-RT-001"],
                    "status": "待提交",
                    "conclusion": "提交后自动生成的后续底片抽查报告。",
                    "uploadedAt": server_time(),
                    "actions": ["ndt:submit"],
                }
            )
        repo.set_node_status(project_id, node_id, "待审查")
        todo = {"id": f"TODO-{uuid4().hex[:8].upper()}", "title": "无损检测资料待审查", "projectId": project_id, "nodeId": node_id, "targetType": "submission", "targetId": submission_id, "status": "待处理", "priority": "中", "assigneeName": "张工", "actions": ["review:save"]}
        repo.state["todos"].insert(0, todo)
        return ok({"submissionId": submission_id, "nextStatus": "待审查", "createdTodos": [todo]}, request)

    return idempotent(request, idempotency_key, produce)


@router.post("/projects/{project_id}/ndt/rectifications")
def ndt_rectification(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    guard = mutation_guard(request, project_id, x_role=x_role)
    if guard:
        return guard

    def produce():
        rectification_id = body.get("rectificationId") or f"NDT-REC-{uuid4().hex[:8].upper()}"
        feedback = repo.find_one("ndt_feedback", rectification_id)
        if feedback:
            feedback["status"] = "已反馈"
            feedback["feedbackDescription"] = body.get("description")
            feedback["feedbackAt"] = server_time()
        else:
            feedback = {
                "id": rectification_id,
                "projectId": project_id,
                "nodeId": 40,
                "title": "无损检测补正反馈",
                "description": body.get("description") or "已补充无损检测资料。",
                "status": "已反馈",
                "relatedReportIds": body.get("reportIds") or [],
                "relatedFilmIds": body.get("filmIds") or [],
                "createdAt": server_time(),
            }
            repo.state["ndt_feedback"].insert(0, feedback)
        rectification = {"id": feedback["id"], "projectId": project_id, "nodeId": 40, "status": feedback["status"]}
        repo.set_node_status(project_id, 40, "复审中")
        return ok({"rectification": rectification, "nextStatus": "复审中"}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/projects/{project_id}/ndt/inspection-feedback")
def list_ndt_feedback(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), status: str | None = None):
    items = [repo.clone(item) for item in repo.state["ndt_feedback"] if item["projectId"] == project_id]
    if status:
        items = [item for item in items if item["status"] == status]
    return ok(page(items, page_no, page_size), request)


@router.get("/projects/{project_id}/ndt/inspection-feedback/{feedback_id}")
def ndt_feedback_detail(request: Request, project_id: str, feedback_id: str):
    feedback = repo.find_one("ndt_feedback", feedback_id)
    if not feedback:
        return fail(errors.NOT_FOUND, request)
    return ok(
        {
            "feedback": repo.clone(feedback),
            "reports": [repo.clone(item) for item in repo.state["ndt_reports"] if item["id"] in set(feedback.get("relatedReportIds", []))],
            "films": [repo.clone(item) for item in repo.state["ndt_films"] if item["id"] in set(feedback.get("relatedFilmIds", []))],
            "records": repo.clone(repo.state["ndt_records"]),
            "evidenceLinks": repo.clone(repo.state["evidence_links"]),
            "timeline": [{"title": "监检反馈", "actorName": "张工", "status": feedback["status"], "createdAt": feedback["createdAt"], "comment": feedback["description"]}],
        },
        request,
    )


@router.get("/search")
def search(request: Request, keyword: str = Query(default=""), projectId: str | None = None, type: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    results: list[dict[str, Any]] = []
    lowered = keyword.lower()
    for project in repo.state["projects"]:
        if not projectId or project["id"] == projectId:
            results.append({"type": "project", "id": project["id"], "title": project["name"], "description": project["status"], "route": f"/workbench/inspection?projectId={project['id']}", "highlights": [project["code"], project["region"]]})
    for node in repo.state["tree_nodes"]:
        if not projectId or node["projectId"] == projectId:
            results.append({"type": "node", "id": str(node["nodeId"]), "title": f"节点 {node['nodeId']} {node['name']}", "description": node["status"], "route": f"/workbench/inspection?nodeId={node['nodeId']}", "highlights": [node["groupName"], node["inspectionType"]]})
    for doc in repo.state["documents"]:
        if not projectId or doc["projectId"] == projectId:
            results.append({"type": "document", "id": doc["id"], "title": doc["fileName"], "description": doc["sourceOrgName"], "route": f"/workbench/contractor?documentId={doc['id']}", "highlights": [doc["currentOcrStatus"]]})
    for report in repo.state["reports"]:
        if not projectId or report["projectId"] == projectId:
            results.append({"type": "report", "id": report["id"], "title": report["title"], "description": report["status"], "route": f"/workbench/owner?reportId={report['id']}", "highlights": [report["reportNo"]]})
    if type:
        results = [item for item in results if item["type"] == type]
    if keyword:
        results = [item for item in results if lowered in f"{item['title']} {item['description']} {' '.join(item['highlights'])}".lower()]
    return ok(page(results, page_no, page_size), request)


@router.get("/todos")
def list_todos(request: Request, role: str | None = None, projectId: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["todos"]]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if status:
        items = [item for item in items if item.get("status") == status]
    return ok(page(items, page_no, page_size), request)


@router.get("/todos/{todo_id}")
def todo_detail(request: Request, todo_id: str):
    todo = repo.find_one("todos", todo_id)
    if not todo:
        return fail(errors.NOT_FOUND, request)
    return ok({**repo.clone(todo), "relatedObject": None, "evidenceLinks": repo.clone(repo.state["evidence_links"])}, request)


@router.post("/todos/{todo_id}/complete")
def complete_todo(request: Request, todo_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    todo = repo.find_one("todos", todo_id)
    if not todo:
        return fail(errors.NOT_FOUND, request)
    todo["status"] = "已完成"
    return ok(repo.mutation_result("完成待办", "Todo", todo_id, next_status="已完成"), request)


@router.post("/todos/{todo_id}/defer")
def defer_todo(request: Request, todo_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    todo = repo.find_one("todos", todo_id)
    if not todo:
        return fail(errors.NOT_FOUND, request)
    todo["status"] = "已延期"
    return ok(repo.mutation_result("延期待办", "Todo", todo_id, next_status="已延期"), request)


@router.get("/messages")
def list_messages(request: Request, projectId: str | None = None, read: bool | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["messages"]]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if read is not None:
        items = [item for item in items if item.get("read") is read]
    return ok(page(items, page_no, page_size), request)


@router.post("/messages/{message_id}/read")
def mark_message_read(request: Request, message_id: str):
    message = repo.find_one("messages", message_id)
    if not message:
        return fail(errors.NOT_FOUND, request)
    message["read"] = True
    return ok(repo.mutation_result("标记消息已读", "Message", message_id), request)


@router.post("/messages/read-all")
def mark_all_messages_read(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    affected = 0
    for message in repo.state["messages"]:
        if body.get("projectId") and message.get("projectId") != body.get("projectId"):
            continue
        if not message.get("read"):
            message["read"] = True
            affected += 1
    return ok({"affectedCount": affected}, request)


@router.get("/knowledge/overview")
def knowledge_overview(request: Request):
    sources = repo.state["knowledge_sources"]
    files = repo.state["knowledge_files"]
    tasks = repo.state["knowledge_tasks"]
    return ok(
        {
            "metrics": [
                {"key": "source", "label": "知识源", "value": len(sources), "tone": "blue"},
                {"key": "file", "label": "项目文件", "value": len(files), "tone": "green"},
                {"key": "task", "label": "运行任务", "value": len([item for item in tasks if item["status"] in {"排队中", "运行中"}]), "tone": "orange"},
                {"key": "failed", "label": "失败任务", "value": len([item for item in tasks if item["status"] == "失败"]), "tone": "red"},
            ],
            "libraries": [
                {
                    "key": source["id"],
                    "name": source["name"],
                    "fileCount": source["fileCount"],
                    "chunkCount": source["chunkCount"],
                    "vectorCount": source["chunkCount"],
                    "indexVersion": source.get("version") or "v1",
                    "status": source["status"],
                    "updatedAt": source["updatedAt"],
                }
                for source in sources
            ],
        },
        request,
    )


@router.get("/knowledge/sources")
def list_knowledge_sources(request: Request, keyword: str | None = None, sourceType: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["knowledge_sources"]]
    if sourceType:
        items = [item for item in items if item["sourceType"] == sourceType]
    if status:
        items = [item for item in items if item["status"] == status]
    items = filter_keyword(items, keyword, ["name", "version", "status"])
    return ok(page(items, page_no, page_size), request)


@router.post("/knowledge/sources")
def create_knowledge_source(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        source = {
            "id": f"KS-{uuid4().hex[:8].upper()}",
            "name": body.get("name") or "新知识源",
            "sourceType": body.get("sourceType") or "manual",
            "version": body.get("version"),
            "status": body.get("status") or "启用",
            "fileCount": int(body.get("fileCount") or 0),
            "chunkCount": int(body.get("chunkCount") or 0),
            "vectorStatus": body.get("vectorStatus") or "待向量化",
            "updatedAt": server_time(),
            "actions": ["knowledge:view", "knowledge:manage", "knowledge:reindex"],
        }
        repo.state["knowledge_sources"].insert(0, source)
        audit_id = repo.add_audit("新增知识源", "KnowledgeSource", source["id"])
        return ok({"source": source, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/knowledge/sources/{source_id}")
def get_knowledge_source(request: Request, source_id: str):
    source = repo.find_one("knowledge_sources", source_id)
    if not source:
        return fail(errors.NOT_FOUND, request)
    return ok({"source": repo.clone(source)}, request)


@router.put("/knowledge/sources/{source_id}")
@router.patch("/knowledge/sources/{source_id}")
def update_knowledge_source(request: Request, source_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    source = repo.find_one("knowledge_sources", source_id)
    if not source:
        return fail(errors.NOT_FOUND, request)
    for field in ["name", "sourceType", "version", "status", "fileCount", "chunkCount", "vectorStatus"]:
        if field in body:
            source[field] = body[field]
    source["updatedAt"] = server_time()
    audit_id = repo.add_audit("更新知识源", "KnowledgeSource", source_id)
    return ok({"source": repo.clone(source), "auditLogId": audit_id}, request)


@router.post("/knowledge/sources/{source_id}/enable")
def enable_knowledge_source(request: Request, source_id: str):
    return update_knowledge_source(request, source_id, {"status": "启用"})


@router.post("/knowledge/sources/{source_id}/disable")
def disable_knowledge_source(request: Request, source_id: str):
    return update_knowledge_source(request, source_id, {"status": "停用"})


@router.get("/knowledge/project-files")
def list_knowledge_files(request: Request, keyword: str | None = None, projectId: str | None = None, nodeId: int | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["knowledge_files"]]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if nodeId:
        items = [item for item in items if int(item.get("nodeId") or 0) == int(nodeId)]
    if status:
        items = [item for item in items if status in {item.get("ocrStatus"), item.get("sliceStatus"), item.get("vectorStatus")}]
    items = filter_keyword(items, keyword, ["fileName", "sourceName", "nodeName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/knowledge/files/{file_id}")
def knowledge_file_detail(request: Request, file_id: str):
    file = repo.find_one("knowledge_files", file_id)
    if not file:
        return fail(errors.NOT_FOUND, request)
    document = repo.find_one("documents", file.get("documentId"))
    latest_task = next((item for item in repo.state["knowledge_tasks"] if item.get("targetId") == file_id), None)
    return ok(
        {
            "file": repo.clone(file),
            "document": repo.clone(document) if document else None,
            "currentVersion": repo.current_version(document["id"]) if document else None,
            "latestTask": repo.clone(latest_task) if latest_task else None,
            "vectorSummary": {
                "vectorStatus": file.get("vectorStatus"),
                "vectorCount": file.get("vectorCount", 0),
                "indexVersion": "proj-v2026.06.26",
                "dimensions": 3072,
                "updatedAt": file.get("updatedAt"),
            },
        },
        request,
    )


@router.get("/knowledge/files/{file_id}/chunks")
def knowledge_file_chunks(request: Request, file_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    chunks = [repo.clone(item) for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id]
    if not chunks:
        chunks = [
            {"id": f"CHK-{file_id}-{idx}", "chunkNo": idx, "text": f"知识切片 {idx}：压力管道资料审查关键字段与证据定位。", "pageNo": idx, "evidenceLinkId": "EV-24-001", "tokenCount": 128}
            for idx in range(1, 8)
        ]
    return ok(page(chunks, page_no, page_size), request)


@router.get("/knowledge/files/{file_id}/vectors")
def knowledge_file_vectors(request: Request, file_id: str):
    file = repo.find_one("knowledge_files", file_id)
    if not file:
        return fail(errors.NOT_FOUND, request)
    return ok({"vectorStatus": file.get("vectorStatus"), "vectorCount": file.get("vectorCount", 0), "indexVersion": "proj-v2026.06.26", "dimensions": 3072, "updatedAt": file.get("updatedAt")}, request)


@router.get("/knowledge/files/{file_id}/reasoning-references")
def knowledge_file_reasoning_refs(request: Request, file_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    refs = [{"runId": run["id"], "nodeId": run["nodeId"], "subject": run["subject"], "model": run["model"], "quotedText": "证据链引用该文件的 OCR 字段。", "createdAt": run.get("finishedAt") or run.get("startedAt")} for run in repo.state["ai_runs"]]
    return ok(page(refs, page_no, page_size), request)


@router.post("/knowledge/files/{file_id}/reindex")
def reindex_file(request: Request, file_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        file = repo.find_one("knowledge_files", file_id)
        if not file:
            return fail(errors.NOT_FOUND, request)
        task = {"id": f"KT-{uuid4().hex[:8].upper()}", "taskType": "reindex", "targetType": "file", "targetId": file_id, "targetName": file["fileName"], "status": "排队中", "progress": 0, "createdAt": server_time(), "actions": ["knowledge:task-retry"]}
        repo.state["knowledge_tasks"].insert(0, task)
        return ok({"task": task}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/knowledge/tasks")
def list_knowledge_tasks(request: Request, taskType: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["knowledge_tasks"]]
    if taskType:
        items = [item for item in items if item["taskType"] == taskType]
    if status:
        items = [item for item in items if item["status"] == status]
    return ok(page(items, page_no, page_size), request)


@router.get("/knowledge/tasks/{task_id}")
def knowledge_task_detail(request: Request, task_id: str):
    task = repo.find_one("knowledge_tasks", task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    return ok({"task": repo.clone(task)}, request)


@router.get("/knowledge/tasks/{task_id}/logs")
def knowledge_task_logs(request: Request, task_id: str):
    return ok([{"createdAt": server_time(), "level": "info", "message": f"任务 {task_id} 已进入队列。"}], request)


@router.post("/knowledge/tasks/{task_id}/retry")
def retry_knowledge_task(request: Request, task_id: str):
    task = repo.find_one("knowledge_tasks", task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    task["status"] = "排队中"
    task["progress"] = 0
    task.pop("errorMessage", None)
    return ok({"task": repo.clone(task)}, request)


@router.post("/knowledge/tasks/{task_id}/cancel")
def cancel_knowledge_task(request: Request, task_id: str):
    task = repo.find_one("knowledge_tasks", task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    task["status"] = "已取消"
    return ok({"task": repo.clone(task)}, request)


@router.post("/knowledge/reindex")
def batch_reindex(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        ids = []
        targets = repo.state["knowledge_files"] if body.get("scope") != "source" else repo.state["knowledge_sources"]
        for target in targets[:3]:
            task = {"id": f"KT-{uuid4().hex[:8].upper()}", "taskType": "reindex", "targetType": "file" if "fileName" in target else "source", "targetId": target["id"], "targetName": target.get("fileName") or target.get("name"), "status": "排队中", "progress": 0, "createdAt": server_time(), "actions": ["knowledge:task-retry"]}
            repo.state["knowledge_tasks"].insert(0, task)
            ids.append(task["id"])
        return ok({"taskIds": ids}, request)

    return idempotent(request, idempotency_key, produce)


@router.post("/knowledge/retrieval-test")
def retrieval_test(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    question = body.get("question") or "焊工资格证有效期如何校验？"
    return ok({"answerDraft": f"围绕“{question}”，建议核验证书有效期、持证项目、焊接方法覆盖关系，并引用对应证据链。", "hits": repo.clone(repo.state["evidence_links"]), "latencyMs": 186, "usedIndexVersions": ["std-v2026.06", "proj-v2026.06.26"]}, request)


@router.get("/rules/versions")
def list_rule_versions(request: Request, keyword: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["rule_versions"]]
    if status:
        items = [item for item in items if item["status"] == status]
    items = filter_keyword(items, keyword, ["name", "ruleKey", "version"])
    return ok(page(items, page_no, page_size), request)


@router.get("/rules/versions/{version_id}/diff")
def rule_version_diff(request: Request, version_id: str, targetVersionId: str | None = None, targetVersion: str | None = None):
    base = repo.find_one("rule_versions", version_id) or repo.state["rule_versions"][0]
    target = repo.find_one("rule_versions", targetVersionId or "") or repo.state["rule_versions"][-1]
    return ok(
        {
            "base": repo.clone(base),
            "target": repo.clone(target),
            "comparedAt": server_time(),
            "summary": {"added": 1, "changed": 2, "removed": 0, "warning": 1},
            "changes": [
                {"field": "version", "label": "版本号", "before": target.get("version"), "after": base.get("version"), "severity": "info", "changeType": "changed"},
                {"field": "nodes", "label": "适用节点", "before": target.get("nodeIds"), "after": base.get("nodeIds"), "severity": "warning", "changeType": "changed"},
            ],
        },
        request,
    )


@router.post("/rules/versions/{version_id}/publish")
def publish_rule_version(request: Request, version_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    rule = repo.find_one("rule_versions", version_id)
    if not rule:
        return fail(errors.NOT_FOUND, request)
    rule["status"] = "已发布"
    rule["publishedAt"] = server_time()
    result = repo.mutation_result("发布规则版本", "RuleVersion", version_id, next_status="已发布")
    return ok({**result, "rule": repo.clone(rule)}, request)


@router.post("/rules/versions/{version_id}/rollback")
def rollback_rule_version(request: Request, version_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    rule = repo.find_one("rule_versions", version_id)
    if not rule:
        return fail(errors.NOT_FOUND, request)
    target = repo.state["rule_versions"][0]
    rule["status"] = "已回滚"
    result = repo.mutation_result("回滚规则版本", "RuleVersion", version_id, next_status="已回滚")
    return ok({**result, "rule": repo.clone(rule), "target": repo.clone(target)}, request)


@router.get("/knowledge/config")
def get_knowledge_config(request: Request):
    return ok({"config": repo.clone(repo.state["knowledge_config"]), "updatedAt": repo.state["knowledge_config"]["updatedAt"]}, request)


@router.put("/knowledge/config")
@router.patch("/knowledge/config")
def update_knowledge_config(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    repo.state["knowledge_config"].update({key: value for key, value in body.items() if value is not None})
    repo.state["knowledge_config"]["updatedAt"] = server_time()
    audit_id = repo.add_audit("更新知识库配置", "KnowledgeConfig", "default")
    return ok({"config": repo.clone(repo.state["knowledge_config"]), "updatedAt": repo.state["knowledge_config"]["updatedAt"], "auditLogId": audit_id}, request)


@router.get("/knowledge/audit-logs")
def knowledge_audit_logs(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, objectType: str | None = None, result: str | None = None):
    items = [repo.clone(item) for item in repo.state["audit_logs"]]
    if objectType:
        items = [item for item in items if item.get("objectType") == objectType]
    if result:
        items = [item for item in items if item.get("result") == result]
    items = filter_keyword(items, keyword, ["action", "objectType", "objectId", "actorName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/reasoning/logs")
def reasoning_logs(request: Request, projectId: str | None = None, nodeId: int | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["ai_runs"]]
    if projectId:
        items = [item for item in items if item["projectId"] == projectId]
    if nodeId:
        items = [item for item in items if int(item["nodeId"]) == int(nodeId)]
    if status:
        items = [item for item in items if item["status"] == status]
    return ok(page(items, page_no, page_size), request)


@router.get("/reasoning/logs/{log_id}")
def reasoning_log_detail(request: Request, log_id: str):
    run = repo.find_one("ai_runs", log_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok({"log": repo.clone(run), "evidenceLinks": repo.clone(run.get("evidenceLinks") or repo.state["evidence_links"])}, request)


@router.get("/reasoning/logs/{log_id}/evidence")
def reasoning_log_evidence(request: Request, log_id: str):
    run = repo.find_one("ai_runs", log_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.clone(run.get("evidenceLinks") or repo.state["evidence_links"]), request)


@router.post("/llm/compare")
def llm_compare(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        run = {
            "runId": f"CMP-{uuid4().hex[:8].upper()}",
            "question": body.get("question") or "请对比审查意见。",
            "modelCodes": body.get("modelCodes") or ["default-chat", "compare-fast"],
            "createdAt": server_time(),
            "projectId": body.get("projectId"),
            "nodeId": body.get("nodeId"),
            "results": [
                {"modelCode": model, "answer": f"{model} 认为资料基本满足要求，建议保留人工确认项。", "confidence": 0.82, "evidenceLinkIds": body.get("evidenceLinkIds") or ["EV-24-001"], "latencyMs": 900 + idx * 220}
                for idx, model in enumerate(body.get("modelCodes") or ["default-chat", "compare-fast"])
            ],
        }
        repo.state["llm_compare_runs"].insert(0, run)
        return ok(run, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/llm/compare-runs")
def list_compare_runs(request: Request, projectId: str | None = None, nodeId: int | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["llm_compare_runs"]]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if nodeId:
        items = [item for item in items if int(item.get("nodeId") or 0) == int(nodeId)]
    summaries = [{"runId": item["runId"], "question": item["question"], "modelCodes": item["modelCodes"], "createdAt": item["createdAt"], "projectId": item.get("projectId"), "nodeId": item.get("nodeId")} for item in items]
    return ok(page(summaries, page_no, page_size), request)


@router.get("/llm/compare-runs/{run_id}")
def compare_run_detail(request: Request, run_id: str):
    run = repo.find_one("llm_compare_runs", run_id, id_field="runId")
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.clone(run), request)


@router.get("/admin/config-overview")
def admin_config_overview(request: Request):
    return ok(repo.build_admin_overview(), request)


@router.post("/admin/projects")
def create_admin_project(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        project_id = body.get("code") or f"P-2026-{uuid4().hex[:6].upper()}"
        project = {
            "id": project_id,
            "code": project_id,
            "name": body.get("name") or "新建压力管道项目",
            "type": body.get("type") or "工业管道",
            "region": body.get("region") or "华东",
            "ownerOrgName": body.get("ownerOrgName") or "建设单位",
            "contractorOrgName": body.get("contractorOrgName") or "施工单位",
            "ndtOrgName": body.get("ndtOrgName") or "无损检测单位",
            "inspectionOrgName": body.get("inspectionOrgName") or "监检机构",
            "status": "草稿/立项中",
            "todoCount": 0,
            "messageCount": 0,
            "currentNodeId": int(body.get("currentNodeId") or 1),
            "updatedAt": server_time(),
            "actions": ["project:view", "project:authorize-member"],
            "revision": 1,
        }
        repo.state["projects"].insert(0, project)
        member_user_ids = body.get("memberUserIds") or {}
        role_org_names = {
            "owner": project["ownerOrgName"],
            "contractor": project["contractorOrgName"],
            "ndt": project["ndtOrgName"],
            "inspection": project["inspectionOrgName"],
        }
        for role in ["owner", "contractor", "ndt", "inspection"]:
            repo.state["project_members"].insert(
                0,
                project_member_snapshot(
                    project_id,
                    role,
                    member_user_ids.get(role),
                    org_name=role_org_names[role],
                ),
            )
        audit_id = repo.add_audit("项目立项", "Project", project_id)
        detail_data = project_detail_payload(project_id)
        return ok({"project": project, "detail": detail_data, "auditLogId": audit_id, "createdNodeCount": 69}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/admin/integration-contract")
def integration_contract(request: Request, module: str | None = None, status: str | None = None):
    modules = [
        ("workbench", "工作台首屏"),
        ("documents", "资料文件"),
        ("submissions", "提交补正"),
        ("inspection", "监检审查"),
        ("ndt-owner-report", "无损与报告"),
        ("knowledge-admin", "知识库与后台"),
    ]
    fields = [
        {
            "id": "IC-001",
            "module": "workbench",
            "moduleLabel": "工作台首屏",
            "endpoint": "/api/workbench/projects",
            "method": "GET",
            "frontendField": "projects[].riskLevel",
            "backendField": "riskLevel",
            "required": False,
            "status": "待后端确认",
            "severity": "warning",
            "owner": "backend",
            "note": "风险等级字段已纳入首屏合同，后续由真实规则计算。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-002",
            "module": "submissions",
            "moduleLabel": "提交补正",
            "endpoint": "/api/projects/{projectId}/submissions",
            "method": "GET",
            "frontendField": "drafts[].nodeNames",
            "backendField": "",
            "required": True,
            "status": "后端缺失",
            "severity": "danger",
            "owner": "backend",
            "note": "联调清单保留缺口项，用于跟踪真实 Mongo 聚合合同。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-003",
            "module": "inspection",
            "moduleLabel": "监检审查",
            "endpoint": "/api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions",
            "method": "POST",
            "frontendField": "riskLevel",
            "backendField": "riskLevel",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "审查意见保存已返回风险等级。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-004",
            "module": "knowledge-admin",
            "moduleLabel": "知识库与后台",
            "endpoint": "/api/knowledge/tasks",
            "method": "GET",
            "frontendField": "items[].targetName",
            "backendField": "targetName",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "任务中心支持重试和取消。",
            "updatedAt": server_time(),
        },
    ]
    if module and module != "all":
        fields = [item for item in fields if item["module"] == module]
    if status and status != "all":
        fields = [item for item in fields if item["status"] == status]
    module_summaries = []
    all_fields = [
        item
        for item in [
            {
                "module": "workbench",
                "status": "待后端确认",
            },
            {
                "module": "submissions",
                "status": "后端缺失",
            },
            {
                "module": "inspection",
                "status": "已对齐",
            },
            {
                "module": "knowledge-admin",
                "status": "已对齐",
            },
        ]
    ]
    for code, label in modules:
        module_fields = [item for item in all_fields if item["module"] == code]
        total = len(module_fields) or 1
        aligned = len([item for item in module_fields if item["status"] == "已对齐"])
        pending = len([item for item in module_fields if item["status"] in {"待后端确认", "命名不一致"}])
        blockers = len([item for item in module_fields if item["status"] in {"前端缺失", "后端缺失"}])
        module_summaries.append({"module": code, "label": label, "total": total, "aligned": aligned, "pending": pending, "blockers": blockers})
    return ok(
        {
            "summary": {
                "total": len(fields),
                "aligned": len([item for item in fields if item["status"] == "已对齐"]),
                "pending": len([item for item in fields if item["status"] in {"待后端确认", "命名不一致"}]),
                "blockers": len([item for item in fields if item["status"] in {"前端缺失", "后端缺失"}]),
            },
            "modules": module_summaries,
            "fields": fields,
            "generatedAt": server_time(),
        },
        request,
    )


@router.post("/admin/config-diff/preview")
def admin_config_diff_preview(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    values = body.get("values") or {}
    return ok(build_config_diff(body.get("target") or "config", body.get("id") or "new", values), request)


@router.post("/admin/config-items/{target}")
def create_admin_config_item(request: Request, target: str, body: dict[str, Any] = Body(default_factory=dict)):
    values = body.get("values") or {}
    item_id = f"CFG-{uuid4().hex[:8].upper()}"
    item = {"id": item_id, **values, "updatedAt": server_time()}
    repo.state["admin_config"].setdefault(admin_collection_for(target), []).insert(0, item)
    diff = build_config_diff(target, item_id, values, object_name=values.get("name") or values.get("scene") or target)
    audit_id = repo.add_audit("新增配置项", "AdminConfig", diff["objectId"])
    return ok({"overview": repo.build_admin_overview(), "diff": diff, "auditLogId": audit_id, "updatedAt": server_time()}, request)


@router.put("/admin/config-items/{target}/{item_id}")
def save_admin_config_item(request: Request, target: str, item_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    values = body.get("values") or {}
    collection = repo.state["admin_config"].setdefault(admin_collection_for(target), [])
    item = next((entry for entry in collection if entry.get("id") == item_id or entry.get("role") == item_id), None)
    if item:
        item.update(values)
        item["updatedAt"] = server_time()
    diff = build_config_diff(target, item_id, values, object_name=values.get("name") or values.get("scene") or target)
    audit_id = repo.add_audit("保存配置项", "AdminConfig", item_id)
    return ok({"overview": repo.build_admin_overview(), "diff": diff, "auditLogId": audit_id, "updatedAt": server_time()}, request)


def admin_collection_for(kind: str) -> str:
    return {
        "todo-rule": "todoRules",
        "todo-rules": "todoRules",
        "message-template": "messageTemplates",
        "message-templates": "messageTemplates",
        "tool-source": "toolSources",
        "tool-sources": "toolSources",
        "field-mapping": "fieldMappings",
        "field-mappings": "fieldMappings",
        "workflow": "workflowStateMachines",
        "workflow-state-machines": "workflowStateMachines",
        "node-template": "nodeTemplates",
        "tree-nodes": "nodeTemplates",
        "permission": "permissionMatrix",
        "node-role-mappings": "permissionMatrix",
        "roles": "permissionMatrix",
        "rules": "ruleVersions",
    }.get(kind, kind)


@router.post("/admin/config-export")
def admin_config_export(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        export_id = f"EXP-CFG-{uuid4().hex[:8].upper()}"
        scope = body.get("scope") or "all"
        task = {"id": export_id, "exportType": "config-package", "status": "可下载", "progress": 100, "fileName": f"后台配置包-{scope}-20260626.zip", "fileSize": 204800, "downloadUrl": f"mock://download/admin/{export_id}.zip", "createdAt": server_time(), "finishedAt": server_time(), "expiresAt": "2026-06-27 18:00:00"}
        repo.attach_export_artifact(task, content_type="application/zip")
        repo.state["export_tasks"].insert(0, task)
        return ok({"exportId": export_id, "task": task}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/admin/{kind}")
def admin_generic_list(request: Request, kind: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    if kind == "audit-logs":
        return audit_logs(request, page_no, page_size)
    if kind == "config-overview":
        return admin_config_overview(request)
    if kind == "integration-contract":
        return integration_contract(request)
    collection = admin_collection_for(kind)
    items = repo.state["admin_config"].get(collection, [])
    return ok(page(repo.clone(items), page_no, page_size), request)


@router.post("/admin/{kind}")
def admin_generic_create(request: Request, kind: str, body: dict[str, Any] = Body(default_factory=dict)):
    collection = admin_collection_for(kind)
    values = body.get("values") or body
    item = {"id": f"CFG-{uuid4().hex[:8].upper()}", **values, "updatedAt": server_time()}
    repo.state["admin_config"].setdefault(collection, []).insert(0, item)
    return ok({"item": item, "auditLogId": repo.add_audit("新增后台配置", "AdminConfig", item["id"])}, request)


@router.patch("/admin/{kind}/{item_id}")
def admin_generic_update(request: Request, kind: str, item_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    collection = admin_collection_for(kind)
    items = repo.state["admin_config"].setdefault(collection, [])
    item = next((entry for entry in items if entry.get("id") == item_id), None)
    if not item:
        return fail(errors.NOT_FOUND, request)
    item.update(body)
    item["updatedAt"] = server_time()
    return ok({"item": item, "auditLogId": repo.add_audit("更新后台配置", "AdminConfig", item_id)}, request)


@router.get("/admin/workflow-state-machines")
def workflow_state_machines(request: Request):
    return ok(repo.state["admin_config"]["workflowStateMachines"], request)


@router.post("/admin/workflow-state-machines")
def create_workflow_state_machine(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return admin_generic_create(request, "workflowStateMachines", body)


@router.patch("/admin/workflow-state-machines/{state_machine_id}")
def update_workflow_state_machine(request: Request, state_machine_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    return admin_generic_update(request, "workflowStateMachines", state_machine_id, body)


@router.post("/admin/config-overview/publish")
def publish_admin_config(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        publish_id = f"PUB-{uuid4().hex[:8].upper()}"
        audit_id = repo.add_audit("发布后台配置", "AdminConfig", publish_id)
        version = "config-v2026.06.27"
        scope = body.get("scope") or "all"
        message = {
            "id": f"MSG-{uuid4().hex[:8].upper()}",
            "title": f"后台配置已发布：{version}",
            "content": f"发布范围 {scope}，权限、待办和消息模板已完成联动刷新。",
            "projectId": PROJECT_ID,
            "targetType": "admin_config",
            "targetId": publish_id,
            "read": False,
            "createdAt": server_time(),
        }
        todo = {
            "id": f"TODO-{uuid4().hex[:8].upper()}",
            "title": "字段映射配置发布影响",
            "projectId": PROJECT_ID,
            "nodeId": 24,
            "targetType": "admin_config",
            "targetId": publish_id,
            "status": "待处理",
            "priority": "中",
            "assigneeName": "张工",
            "actions": ["admin:config", "knowledge:manage"],
        }
        repo.state["messages"].insert(0, message)
        repo.state["todos"].insert(0, todo)
        impacts = [
            {"domain": "permission", "label": "权限矩阵", "affectedCount": 5, "status": "已同步", "trace": "权限矩阵已同步到工作台动作权限"},
            {"domain": "message-template", "label": "消息模板", "affectedCount": 2, "status": "已同步", "trace": "消息模板已刷新待办通知"},
            {"domain": "field-mapping", "label": "字段映射", "affectedCount": 1, "status": "需复核", "trace": "字段映射阈值变更后需在真实 OCR 样例中复核"},
        ]
        return ok({"publishId": publish_id, "status": "已发布", "version": version, "auditLogId": audit_id, "publishedAt": server_time(), "impactSummary": {"totalAffected": 8, "warningCount": 1, "linkedProjects": len([item for item in repo.state["projects"] if item["status"] != "已归档"]), "pushedMessages": 1, "reviewTodos": 1}, "impacts": impacts}, request)

    return idempotent(request, idempotency_key, produce)


@router.get("/admin/audit-logs")
def audit_logs(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, result: str | None = None, objectType: str | None = None):
    items = [repo.clone(item) for item in repo.state["audit_logs"]]
    if result:
        items = [item for item in items if item.get("result") == result]
    if objectType:
        items = [item for item in items if item.get("objectType") == objectType]
    items = filter_keyword(items, keyword, ["action", "objectType", "objectId", "actorName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/audit-logs")
def global_audit_logs(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return audit_logs(request, page_no, page_size)


@router.get("/projects/{project_id}/audit-logs")
def project_audit_logs(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return audit_logs(request, page_no, page_size)


@router.get("/projects/{project_id}/nodes/{node_id}/audit-logs")
def node_audit_logs(request: Request, project_id: str, node_id: int, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return audit_logs(request, page_no, page_size)


@router.get("/admin/org-units")
def org_units_alias(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return ok(page(repo.clone(repo.state["admin_config"]["orgUnits"]), page_no, page_size), request)


@router.get("/admin/users")
def users_alias(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return ok(page(repo.clone(repo.state["admin_config"]["users"]), page_no, page_size), request)


@router.get("/orgs")
def legacy_orgs(request: Request):
    return ok(repo.clone(repo.state["admin_config"]["orgUnits"]), request)


@router.get("/users")
def legacy_users(request: Request):
    return ok(repo.clone(repo.state["admin_config"]["users"]), request)
