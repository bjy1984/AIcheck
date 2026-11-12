"""按项目生成注册链接 → 自选角色注册 → 项目负责人后台审核。

    「根据项目生成注册链接 - 用户通过链接进去选择角色注册 -
      项目负责人在后台审核通过」

## 和上一版组织邀请的三处差别

| | 上一版（组织邀请） | 这一版（项目注册） |
|---|---|---|
| 链接绑什么 | 组织 + 角色 | **项目**，不绑角色 |
| 角色谁定 | 邀请人写死 | **注册者自选** |
| 生效时机 | 提交即建账号 | **审核通过才建账号** |

上一版把角色写死，理由是「自选角色的链接等于公开提权入口」。
**加了审核这一关之后这个理由不成立了**：审核才是闸门，自选只是填表。

## 但这带来一条新的硬要求

**待审期间绝不能存在可用账号。**

所以这里不走「先建用户再标 pending」——那种做法一旦哪个查询忘了过滤
pending，人就登进来了，而且不会报错。这里根本不建 user 记录：
申请只是一条 registration_requests，批准的那一刻才创建用户。
没有账号，就没有「忘了过滤」的可能。

## 链接是多次可用的

一个项目发一个链接给一群人，这是这个流程的意义。所以不能沿用
「单次有效」——但也不能就此无限制：

- 有效期照旧（过期即废）
- 有使用次数上限（防止链接外流后被灌注册）
- 可以随时停用

真正的闸门是审核，链接只是入口。

## 单位由申请人自己填（2026-11-11 客户反馈）

原来批准时要求「项目已配置该角色的参建单位，且这个单位已在组织用户里建档」，
而申请表不收单位——项目没填施工单位、或组织没建，审核就一直卡死。
客户的话：「不用管理员去创建组织和人员，只需要创建一个施工项目就行了」。

现在：
- 申请时必填所属单位；项目已有该角色单位时注册页预填。
- 批准时按单位名找组织，没有就按角色类型自动建一个；项目该角色单位还空着就回填。
- 申请单位和项目已有单位名字不同（「珠海安粤」对「珠海安粤工程有限公司」）**不自动合并**：
  资料访问按单位隔离，合错了两家会互相看到资料。退回 `orgMismatch`，
  由审核人选「并入已有单位」（传 orgName=已有单位）或「算作新单位」（传 confirmNewOrg）。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from fastapi import APIRouter, Body, Header, Request

from libs import institutes
from libs.contracts import errors
from libs.contracts.responses import fail, ok, server_time
from libs.db.repository import repo
from libs.security.tenant import configured_tenant_id as platform_tenant_id
from libs.security.tenant import current_tenant_id

project_registration_router = APIRouter()

# 注册者能自选的角色。admin / fde 不在里面——审核人也无权在这里造管理员。
SELECTABLE_ROLES = ("inspection", "contractor", "ndt", "owner")

INVITE_TTL_HOURS = 168  # 7 天：项目级链接要发给一群人，比组织邀请长一些
MAX_USES = 200  # 链接外流后被灌注册的上限

INVITES = "project_invitations"
REQUESTS = "registration_requests"
ROLE_ORG_FIELDS = {
    "inspection": "inspectionOrgName",
    "contractor": "contractorOrgName",
    "ndt": "ndtOrgName",
    "owner": "ownerOrgName",
}
_REGISTRATION_IDENTITY_LOCK = Lock()
ORG_NAME_MAX = 80
REVIEW_TODO_KIND = "registration_review"
# 查审核结果要验口令：按用户名记失败次数，防止拿链接撞口令
STATUS_FAILURE_LIMIT = 10
STATUS_FAILURE_WINDOW = timedelta(minutes=15)
_STATUS_FAILURES: dict[str, list[datetime]] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _actor(request: Request) -> dict[str, Any] | None:
    auth = getattr(request.state, "auth", None) or {}
    username = auth.get("sub") or auth.get("username")
    if not username:
        return None
    return next(
        (u for u in repo.state.get("users", []) if str(u.get("username")) == str(username)), None
    )


def can_manage_project_registration(user: dict[str, Any] | None, project_id: str) -> bool:
    """谁能发链接、谁能审核。

    admin，或者这个项目的成员里被标了负责人的人。
    **不看全局的 isOrgLeader**：那是组织层的身份，和「这个项目的负责人」
    不是一回事——甲公司的负责人不该能审乙项目的注册。
    """
    if not user:
        return False
    if str(user.get("role")) == "admin":
        return True
    return any(
        str(member.get("projectId")) == str(project_id)
        and str(member.get("userId")) == str(user.get("id"))
        and bool(member.get("isProjectLeader"))
        for member in repo.state.get("project_members", [])
    )


def _guard(request: Request, project_id: str):
    actor = _actor(request)
    if not actor:
        return None, fail(errors.AUTH_REQUIRED, request, http_status=401)
    if not can_manage_project_registration(actor, project_id):
        return None, fail(
            errors.FORBIDDEN, request, http_status=403, message="只有项目负责人可以操作。"
        )
    return actor, None


def _registration_flush_records(
    *,
    invite: dict[str, Any] | None = None,
    registration_request: dict[str, Any] | None = None,
    user: dict[str, Any] | None = None,
    member: dict[str, Any] | None = None,
    admin_config: dict[str, Any] | None = None,
    project: dict[str, Any] | None = None,
    todo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for state_key, item in (
        (INVITES, invite),
        (REQUESTS, registration_request),
        ("users", user),
        ("project_members", member),
        ("projects", project),
        ("todos", todo),
    ):
        if item is not None:
            records[state_key] = [item]
    if admin_config is not None:
        records["admin_config"] = admin_config
    return records


# --------------------------------------------------------------------------
# 一、项目负责人生成注册链接
# --------------------------------------------------------------------------


@project_registration_router.post("/projects/{project_id}/registration-links")
def create_registration_link(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from apps.api.routes import idempotent

    actor, error = _guard(request, project_id)
    if error:
        return error
    if not repo.require_project(project_id):
        return fail(errors.NOT_FOUND, request)

    def produce():
        if body.get("reuse"):
            # 面板一打开就给链接：还有一天以上有效期的就沿用，不是每开一次都发新链接
            reusable = next(
                (
                    item
                    for item in repo.state.get(INVITES, [])
                    if str(item.get("projectId")) == str(project_id)
                    and _invite_usable(item)
                    and _expires_after(item, _now() + timedelta(days=1))
                ),
                None,
            )
            if reusable:
                return ok(
                    {
                        "token": reusable["token"],
                        "projectId": project_id,
                        "expiresAt": reusable["expiresAt"],
                        "maxUses": reusable["maxUses"],
                        "selectableRoles": list(SELECTABLE_ROLES),
                        "reused": True,
                    },
                    request,
                )
        token = secrets.token_urlsafe(24)
        if current_tenant_id() != platform_tenant_id():
            # 公开链接不带登录，靠前缀知道是哪个院的（main.py 按它切院）
            token = f"{current_tenant_id()}.{token}"
        invite = {
            "id": f"PINV-{secrets.token_hex(8).upper()}",
            "token": token,
            "projectId": project_id,
            "createdBy": actor.get("id"),
            "createdAt": server_time(),
            "expiresAt": (_now() + timedelta(hours=INVITE_TTL_HOURS)).isoformat(),
            "maxUses": int(body.get("maxUses") or MAX_USES),
            "useCount": 0,
            "disabled": False,
        }
        repo.state.setdefault(INVITES, []).insert(0, invite)
        repo.add_audit("创建项目注册链接", "ProjectInvitation", token[:8], result="成功")
        request.state.scoped_flush_records = lambda: _registration_flush_records(invite=invite)
        return ok(
            {
                "token": token,
                "projectId": project_id,
                "expiresAt": invite["expiresAt"],
                "maxUses": invite["maxUses"],
                "selectableRoles": list(SELECTABLE_ROLES),
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@project_registration_router.post("/projects/{project_id}/registration-links/{token}/disable")
def disable_registration_link(
    request: Request,
    project_id: str,
    token: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """停用链接。发出去的东西必须能收回来。"""
    from apps.api.routes import idempotent

    _, error = _guard(request, project_id)
    if error:
        return error
    invite = next(
        (
            i
            for i in repo.state.get(INVITES, [])
            if str(i.get("token")) == token and str(i.get("projectId")) == project_id
        ),
        None,
    )
    if not invite:
        return fail(errors.NOT_FOUND, request, message="链接不存在。")

    def produce():
        invite["disabled"] = True
        repo.add_audit("停用项目注册链接", "ProjectInvitation", token[:8], result="成功")
        request.state.scoped_flush_records = lambda: _registration_flush_records(invite=invite)
        return ok({"token": token, "disabled": True}, request)

    return idempotent(request, idempotency_key, produce)


# --------------------------------------------------------------------------
# 二、注册者：看链接、选角色、提交申请
# --------------------------------------------------------------------------


def _invite_usable(invite: dict[str, Any] | None) -> bool:
    """能不能用。**对外只回一句笼统的话**——区分「不存在」「已停用」「已过期」
    「用完了」等于给撞令牌的人送反馈。"""
    if not invite or invite.get("disabled"):
        return False
    if int(invite.get("useCount") or 0) >= int(invite.get("maxUses") or MAX_USES):
        return False
    try:
        return datetime.fromisoformat(str(invite.get("expiresAt"))) > _now()
    except ValueError:
        return False


def _expires_after(invite: dict[str, Any], moment: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(invite.get("expiresAt"))) > moment
    except ValueError:
        return False


def _find_invite(token: str) -> dict[str, Any] | None:
    # 公开接口按链接前缀切到了某个院，那个院在本进程可能还没加载过
    institutes.ensure_tenant_loaded(current_tenant_id())
    return next(
        (i for i in repo.state.get(INVITES, []) if str(i.get("token")) == str(token)), None
    )


@project_registration_router.get("/registration-links/{token}")
def inspect_registration_link(request: Request, token: str):
    """注册页用它显示「你要加入哪个项目」和可选角色。不需要登录。"""
    invite = _find_invite(token)
    if not _invite_usable(invite):
        return fail(errors.NOT_FOUND, request, message="注册链接无效或已过期。")
    project = repo.require_project(str(invite["projectId"]))
    return ok(
        {
            "projectId": invite["projectId"],
            "projectName": (project or {}).get("name") or "",
            # 角色由注册者自选——审核才是闸门
            "selectableRoles": list(SELECTABLE_ROLES),
            # 项目已登记的各角色单位，注册页选了角色就预填（申请人可改）
            "roleOrgNames": _project_role_org_names(project),
            "expiresAt": invite["expiresAt"],
        },
        request,
    )


def _project_role_org_names(project: dict[str, Any] | None) -> dict[str, str]:
    return {
        role: str((project or {}).get(field) or "").strip()
        for role, field in ROLE_ORG_FIELDS.items()
    }


def _same_org_name(left: str, right: str) -> bool:
    from apps.api import document_access_policy

    return document_access_policy.normalized_organization_name(
        left
    ) == document_access_policy.normalized_organization_name(right)


def _pending_count(project_id: str) -> int:
    return sum(
        1
        for item in repo.state.get(REQUESTS, [])
        if str(item.get("projectId")) == str(project_id) and str(item.get("status")) == "待审核"
    )


def _sync_review_todo(project_id: str) -> dict[str, Any] | None:
    """项目一条「加入申请待审核」待办：有待审就开着并更新数字，审完自动关。"""
    from libs import notifications

    dedupe_key = f"registration-review:{project_id}"
    count = _pending_count(project_id)
    if count:
        return notifications.open_todo(
            repo.state,
            kind=REVIEW_TODO_KIND,
            project_id=str(project_id),
            title=f"有 {count} 条加入项目申请待审核",
            target_type="registration",
            target_id=str(project_id),
            assignee_role="inspection",
            priority="高",
            dedupe_key=dedupe_key,
        )
    closed = notifications.close_todos(
        repo.state,
        project_id=str(project_id),
        kinds=[REVIEW_TODO_KIND],
        dedupe_key=dedupe_key,
        reason="加入申请已全部审核",
    )
    if not closed:
        return None
    return next((t for t in repo.state.get("todos", []) if str(t.get("id")) == closed[0]), None)


@project_registration_router.post("/registration-links/{token}/apply")
def submit_registration(request: Request, token: str, body: dict[str, Any] = Body(default_factory=dict)):
    with _REGISTRATION_IDENTITY_LOCK:
        return _submit_registration_locked(request, token, body)


def _submit_registration_locked(request: Request, token: str, body: dict[str, Any]):
    """提交注册申请。**不建用户**——批准的那一刻才建。

    先建用户再标 pending 的话，只要哪个查询忘了过滤 pending，人就登进来了，
    而且不会报错。没有账号，就没有「忘了过滤」的可能。
    """
    from apps.api.routes import password_strength_errors

    invite = _find_invite(token)
    if not _invite_usable(invite):
        return fail(errors.NOT_FOUND, request, message="注册链接无效或已过期。")

    username = str(body.get("username") or "").strip()
    role = str(body.get("role") or "").strip()
    password = str(body.get("password") or "")

    if not username:
        return fail(errors.VALIDATION_ERROR, request, message="用户名不能为空。")
    if role not in SELECTABLE_ROLES:
        # 不在可选名单里的一律拒——包括 admin/fde
        return fail(errors.VALIDATION_ERROR, request, message="所选角色不可用。")
    org_name = str(body.get("orgName") or "").strip()
    if not org_name:
        return fail(
            errors.VALIDATION_ERROR,
            request,
            message="请填写所属单位。",
            data={"field": "orgName"},
        )
    if len(org_name) > ORG_NAME_MAX:
        return fail(
            errors.VALIDATION_ERROR,
            request,
            message=f"单位名称不能超过 {ORG_NAME_MAX} 个字。",
            data={"field": "orgName"},
        )
    problems = password_strength_errors(username, password)
    if problems:
        return fail(
            errors.VALIDATION_ERROR,
            request,
            message="口令不符合安全要求。",
            data={"field": "password", "problems": problems},
        )
    if any(str(u.get("username")) == username for u in repo.state.get("users", [])):
        return fail(errors.CONFLICT, request, http_status=409, message="该用户名已存在。")
    # 用户名全平台唯一：提交申请时就查，不要等审核通过才告诉人家名字被别的单位用了
    if conflict := institutes.username_conflict_message(username):
        return fail(errors.CONFLICT, request, http_status=409, message=conflict)
    if any(
        str(r.get("username")) == username and str(r.get("status")) == "待审核"
        for r in repo.state.get(REQUESTS, [])
    ):
        return fail(errors.CONFLICT, request, http_status=409, message="该用户名已有待审核的申请。")

    from libs.security.auth import hash_password

    record = {
        "id": f"REG-{secrets.token_hex(4).upper()}",
        "projectId": invite["projectId"],
        "username": username,
        "displayName": str(body.get("displayName") or username),
        "mobile": str(body.get("mobile") or ""),
        "role": role,
        "orgName": org_name,
        # 口令在申请阶段就定好并**只存哈希**：批准时直接建账号，
        # 不用再让申请人设一次，也不用由审核人代设——
        # 代设意味着审核人知道别人的口令。
        "passwordHash": hash_password(password),
        "status": "待审核",
        "createdAt": server_time(),
        "reviewedAt": None,
        "reviewedBy": None,
        "rejectReason": "",
    }
    repo.state.setdefault(REQUESTS, []).insert(0, record)
    invite["useCount"] = int(invite.get("useCount") or 0) + 1
    repo.add_audit("提交项目注册申请", "RegistrationRequest", record["id"], result="成功")
    # 给项目负责人一条待办，不然没人知道有人在等审核
    todo = _sync_review_todo(str(invite["projectId"]))
    request.state.scoped_flush_records = lambda: _registration_flush_records(
        invite=invite, registration_request=record, todo=todo
    )
    # 不回任何令牌：账号还不存在，现在还不能登录
    return ok(
        {"requestId": record["id"], "status": record["status"], "message": "已提交，等待项目负责人审核。"},
        request,
    )


@project_registration_router.post("/registration-links/{token}/status")
def registration_status(request: Request, token: str, body: dict[str, Any] = Body(default_factory=dict)):
    """申请人凭用户名＋申请时设的口令查审核结果。

    审核通过前没有账号、登录不了，原来申请人只能干等，被拒了也看不到理由。
    要验口令：不然拿着链接就能挨个试用户名，看到别人的拒绝理由。
    用户名不存在和口令不对回同一句话。
    """
    from libs.security.auth import verify_password

    invite = _find_invite(token)
    if not invite:
        return fail(errors.NOT_FOUND, request, message="注册链接无效或已过期。")
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not username or not password:
        return fail(errors.VALIDATION_ERROR, request, message="请填写用户名和口令。")

    now = _now()
    failures = [
        at for at in _STATUS_FAILURES.get(username, []) if now - at < STATUS_FAILURE_WINDOW
    ]
    _STATUS_FAILURES[username] = failures
    if len(failures) >= STATUS_FAILURE_LIMIT:
        return fail(
            errors.VALIDATION_ERROR,
            request,
            http_status=429,
            message="尝试次数过多，请 15 分钟后再试。",
        )

    record = next(
        (
            item
            for item in repo.state.get(REQUESTS, [])
            if str(item.get("projectId")) == str(invite["projectId"])
            and str(item.get("username")) == username
        ),
        None,
    )  # 列表新的在前：同一用户名被拒后重提，看最新那条
    if not record or not verify_password(password, record.get("passwordHash")):
        failures.append(now)
        return fail(errors.NOT_FOUND, request, message="没有找到这个用户名和口令对应的申请。")
    _STATUS_FAILURES.pop(username, None)
    return ok(
        {
            "requestId": record["id"],
            "status": record.get("status"),
            "role": record.get("role"),
            "orgName": record.get("approvedOrgName") or record.get("orgName") or "",
            "displayName": record.get("displayName") or "",
            "mobile": record.get("mobile") or "",
            "createdAt": record.get("createdAt"),
            "reviewedAt": record.get("reviewedAt"),
            "rejectReason": record.get("rejectReason") or "",
        },
        request,
    )


# --------------------------------------------------------------------------
# 三、项目负责人审核
# --------------------------------------------------------------------------


@project_registration_router.get("/projects/{project_id}/registration-requests")
def list_registration_requests(request: Request, project_id: str, status: str | None = None):
    _, error = _guard(request, project_id)
    if error:
        return error
    role_orgs = _project_role_org_names(repo.require_project(project_id))
    items = [
        {
            **{k: v for k, v in item.items() if k != "passwordHash"},  # 哈希不出接口
            # 审核人一眼看出申请单位和项目已有单位是否一致
            "projectOrgName": role_orgs.get(str(item.get("role")), ""),
        }
        for item in repo.state.get(REQUESTS, [])
        if str(item.get("projectId")) == str(project_id)
        and (not status or str(item.get("status")) == status)
    ]
    return ok(
        {
            "items": items,
            "total": len(items),
            "pendingCount": _pending_count(project_id),
            "roleOrgNames": role_orgs,
        },
        request,
    )


@project_registration_router.post(
    "/projects/{project_id}/registration-requests/{request_id}/review"
)
def review_registration_request(
    request: Request,
    project_id: str,
    request_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    with _REGISTRATION_IDENTITY_LOCK:
        return _review_registration_request_locked(
            request,
            project_id,
            request_id,
            body,
            idempotency_key,
        )


def _review_registration_request_locked(
    request: Request,
    project_id: str,
    request_id: str,
    body: dict[str, Any],
    idempotency_key: str | None,
):
    """通过或拒绝。通过时才真正创建账号。"""
    from apps.api.routes import (
        admin_org_units,
        build_admin_user_record,
        bump_record_revision,
        bump_singleton_revision,
        idempotent,
        org_type_matches_role,
        resolve_project_member_grant,
        upsert_admin_config_user,
    )

    actor, error = _guard(request, project_id)
    if error:
        return error

    record = next(
        (
            item
            for item in repo.state.get(REQUESTS, [])
            if str(item.get("id")) == request_id and str(item.get("projectId")) == str(project_id)
        ),
        None,
    )
    if not record:
        return fail(errors.NOT_FOUND, request, message="申请不存在。")
    if str(record.get("status")) != "待审核":
        # 已经处理过的不许再处理一次：重复审批会重复建账号
        return fail(
            errors.CONFLICT, request, http_status=409, message=f"该申请已{record.get('status')}。"
        )

    approved = bool(body.get("approved"))
    reason = str(body.get("reason") or "").strip()
    if not approved and not reason:
        # 拒绝必须写理由。不写的话申请人只看到「被拒了」，不知道要改什么
        return fail(errors.VALIDATION_ERROR, request, message="拒绝时必须填写理由。")

    project = repo.require_project(project_id) or {}
    role_field = ROLE_ORG_FIELDS[record["role"]]
    project_org_name = str(project.get(role_field) or "").strip()
    # 单位的先后：审核人改过的 > 申请人填的 > 项目上已登记的（老申请没有单位）
    org_name = (
        str(body.get("orgName") or "").strip()
        or str(record.get("orgName") or "").strip()
        or project_org_name
    )
    org: dict[str, Any] | None = None
    if approved:
        if not org_name:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="这条申请没有填单位，请填写申请人所属单位后再通过。",
                data={"field": "orgName"},
            )
        if len(org_name) > ORG_NAME_MAX:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message=f"单位名称不能超过 {ORG_NAME_MAX} 个字。",
            )
        if (
            project_org_name
            and not _same_org_name(org_name, project_org_name)
            and not bool(body.get("confirmNewOrg"))
        ):
            # 不自动合并：资料访问按单位隔离，合错了两家单位会互相看到资料
            return fail(
                errors.CONFLICT,
                request,
                http_status=409,
                message=f"申请单位「{org_name}」与项目已有单位「{project_org_name}」不同。",
                data={
                    "reason": "orgMismatch",
                    "requestedOrgName": org_name,
                    "projectOrgName": project_org_name,
                },
            )
        same_name = [
            item for item in admin_org_units() if _same_org_name(item.get("name"), org_name)
        ]
        if len(same_name) > 1:
            return fail(
                errors.CONFLICT,
                request,
                http_status=409,
                message=f"「{org_name}」对应多个同名组织，请先在组织用户里合并或改名。",
            )
        org = same_name[0] if same_name else None
        if org and org.get("status") == "停用":
            return fail(
                errors.CONFLICT,
                request,
                http_status=409,
                message=f"组织「{org.get('name')}」已停用，请先启用或换一个单位。",
            )
        if org and not org_type_matches_role(record["role"], org.get("type")):
            return fail(
                errors.CONFLICT,
                request,
                http_status=409,
                message=f"组织「{org.get('name')}」的类型与申请角色不符，请换一个单位名。",
            )
    if approved and any(
        str(item.get("username")) == str(record["username"])
        for item in repo.state.get("users", [])
    ):
        return fail(
            errors.CONFLICT,
            request,
            http_status=409,
            message="该用户名已创建账号。",
        )

    def produce():
        if not approved:
            record.update(
                {
                    "status": "已拒绝",
                    "reviewedAt": server_time(),
                    "reviewedBy": actor.get("id"),
                    "rejectReason": reason,
                }
            )
            repo.add_audit("拒绝注册申请", "RegistrationRequest", request_id, result="成功")
            todo = _sync_review_todo(project_id)
            request.state.scoped_flush_records = lambda: _registration_flush_records(
                registration_request=record, todo=todo
            )
            return ok({"requestId": request_id, "status": "已拒绝"}, request)

        if conflict := institutes.username_conflict_message(record["username"]):
            return fail(errors.CONFLICT, request, http_status=409, message=conflict)
        nonlocal org
        org_created = False
        if org is None:
            # 不用管理员先去「组织用户」建档：按申请人的单位自动建一个
            org = {
                "id": f"ORG-{secrets.token_hex(4).upper()}",
                "name": org_name,
                "type": record["role"],
                "contactName": record.get("displayName") or "",
                "contactPhone": record.get("mobile") or "",
                "status": "启用",
                "projectCount": 0,
                "source": "registration",
                "updatedAt": server_time(),
                "revision": 1,
            }
            admin_org_units().insert(0, org)
            org_created = True
            repo.add_audit("注册审核自动建组织", "OrgUnit", org["id"], result="成功")
        project_touched = None
        if not project_org_name and project:
            # 项目该角色单位还空着：用第一个通过的申请回填，之后的申请就能预填、比对
            project[role_field] = org["name"]
            bump_record_revision(project)
            project_touched = project
        user = build_admin_user_record(
            {
                "username": record["username"],
                "role": record["role"],
                "name": record["displayName"],
                "mobile": record.get("mobile") or "",
                "orgName": org["name"],
            },
            org=org,
        )
        # 口令沿用申请时定的那个：审核人不该知道、也不该代设别人的口令
        user["passwordHash"] = record["passwordHash"]
        user["authVersion"] = 1
        user["mustChangePassword"] = False
        if any(
            str(item.get("projectId")) == str(project_id)
            and str(item.get("userId")) == str(user["id"])
            for item in repo.state.get("project_members", [])
        ):
            return fail(
                errors.CONFLICT,
                request,
                http_status=409,
                message="该用户已是项目成员。",
            )
        repo.state["users"].insert(0, user)
        institutes.register_username(user["username"], current_tenant_id())
        upsert_admin_config_user(user)
        # 建账号的同时把他加进项目成员，否则批准了却进不了这个项目
        grant = resolve_project_member_grant(project_id, record["role"])
        member = {
            "id": f"PM-{secrets.token_hex(4).upper()}",
            "projectId": project_id,
            "userId": user["id"],
            "name": record["displayName"],
            "orgId": org["id"],
            "orgName": org["name"],
            "role": record["role"],
            "nodeScope": grant["nodeScope"],
            "actions": grant["actions"],
            "status": "启用",
            "isProjectLeader": False,
            "updatedAt": server_time(),
            "revision": 1,
        }
        repo.state.setdefault("project_members", []).insert(0, member)
        record.update(
            {
                "status": "已通过",
                "reviewedAt": server_time(),
                "reviewedBy": actor.get("id"),
                "approvedOrgName": org["name"],
            }
        )
        if org_created:
            bump_singleton_revision(repo.state["admin_config"])
        repo.add_audit("通过注册申请", "RegistrationRequest", request_id, result="成功")
        todo = _sync_review_todo(project_id)
        request.state.scoped_flush_records = lambda: _registration_flush_records(
            registration_request=record,
            user=user,
            member=member,
            admin_config=repo.state["admin_config"],
            project=project_touched,
            todo=todo,
        )
        return ok(
            {
                "requestId": request_id,
                "status": "已通过",
                "userId": user["id"],
                "orgName": org["name"],
                "orgCreated": org_created,
                "projectOrgFilled": project_touched is not None,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


# --------------------------------------------------------------------------
# 四、项目负责人替成员重置密码（2026-11-12）
#
# 施工方、无损检测、建设方的人忘了密码，原来只能找特检院系统管理员；客户反馈
# 「电脑能力差」的人根本不知道管理员是谁。邀请他们进项目的负责人最近，就让
# 负责人在「邀请成员」里重置：系统生成一个临时密码，负责人当面或电话告诉对方，
# 对方下次登录必须先改成自己的密码，旧的登录立即失效。
#
# 范围收得很窄，防止拿这个功能接管别人的账号：
#   - 只能重置本项目的施工方、无损检测、建设方成员（监检人员和管理员走系统管理员）；
#   - 不能重置自己、不能重置任何项目的负责人；
#   - 对方还在别的项目里、而那个项目不归你管，就不能重置（找管理员）。
# 临时密码只在这一次响应里出现：不走 idempotent（它会把响应原样存进库里重放）。
# --------------------------------------------------------------------------

RESETTABLE_ROLES = ("contractor", "ndt", "owner")
_TEMP_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # 去掉 0/o、1/l/i，电话里好念


def _temporary_password() -> str:
    return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(8))


def _active_project_members(project_id: str) -> list[dict[str, Any]]:
    return [
        member
        for member in repo.state.get("project_members", [])
        if str(member.get("projectId")) == str(project_id)
        and str(member.get("status") or "启用") == "启用"
    ]


def _password_reset_block_reason(
    actor: dict[str, Any], project_id: str, target: dict[str, Any] | None
) -> str | None:
    """能重置就返回 None，不能就返回给人看的原因。"""
    if target is None:
        return "该成员没有账号。"
    if str(target.get("id")) == str(actor.get("id")):
        return "不能重置自己的密码，请在右上角「修改密码」里改。"
    if str(target.get("role")) not in RESETTABLE_ROLES:
        return "监检人员和管理员的密码请找系统管理员重置。"
    if str(target.get("status") or "启用") != "启用":
        return "该账号已停用。"
    memberships = [
        member
        for member in repo.state.get("project_members", [])
        if str(member.get("userId")) == str(target.get("id"))
    ]
    if any(bool(member.get("isProjectLeader")) for member in memberships):
        return "对方是项目负责人，请找系统管理员重置。"
    if str(actor.get("role")) != "admin":
        other_projects = {
            str(member.get("projectId"))
            for member in memberships
            if str(member.get("projectId")) != str(project_id)
        }
        if any(not can_manage_project_registration(actor, other) for other in other_projects):
            return "对方还在你不负责的其他项目里，请找系统管理员重置。"
    return None


@project_registration_router.get("/projects/{project_id}/member-accounts")
def list_project_member_accounts(request: Request, project_id: str):
    """「邀请成员」里列出本项目的施工方、无损检测、建设方成员，标出能不能重置密码。"""
    actor, error = _guard(request, project_id)
    if error:
        return error
    users = {str(user.get("id")): user for user in repo.state.get("users", [])}
    items = []
    for member in _active_project_members(project_id):
        if str(member.get("role")) not in RESETTABLE_ROLES:
            continue
        user = users.get(str(member.get("userId")))
        reason = _password_reset_block_reason(actor, project_id, user)
        items.append(
            {
                "userId": member.get("userId"),
                "username": (user or {}).get("username") or "",
                "name": member.get("name") or (user or {}).get("name") or "",
                "role": member.get("role"),
                "orgName": member.get("orgName") or (user or {}).get("orgName") or "",
                "mustChangePassword": bool((user or {}).get("mustChangePassword")),
                "canResetPassword": reason is None,
                "resetBlockedReason": reason or "",
            }
        )
    return ok({"items": items, "total": len(items)}, request)


@project_registration_router.post("/projects/{project_id}/member-accounts/{user_id}/reset-password")
def reset_project_member_password(request: Request, project_id: str, user_id: str):
    from apps.api.routes import bump_singleton_revision, upsert_admin_config_user
    from libs.security.auth import hash_password

    with _REGISTRATION_IDENTITY_LOCK:
        actor, error = _guard(request, project_id)
        if error:
            return error
        member = next(
            (
                item
                for item in _active_project_members(project_id)
                if str(item.get("userId")) == str(user_id)
            ),
            None,
        )
        if member is None:
            return fail(errors.NOT_FOUND, request, http_status=404, message="该用户不是本项目成员。")
        target = next(
            (user for user in repo.state.get("users", []) if str(user.get("id")) == str(user_id)),
            None,
        )
        reason = _password_reset_block_reason(actor, project_id, target)
        if reason:
            return fail(errors.FORBIDDEN, request, http_status=403, message=reason)
        assert target is not None
        temporary = _temporary_password()
        target["passwordHash"] = hash_password(temporary)
        target.pop("password", None)
        target["mustChangePassword"] = True
        # 版本号加一：对方（或捡到旧会话的人）已登录的会话立即失效
        target["authVersion"] = int(target.get("authVersion") or 0) + 1
        target["updatedAt"] = server_time()
        upsert_admin_config_user(target)
        bump_singleton_revision(repo.state["admin_config"])
        repo.add_audit(
            "项目负责人重置成员密码",
            "User",
            str(user_id),
            result="成功",
            project_id=project_id,
            after={"resetBy": actor.get("id"), "mustChangePassword": True},
        )
        request.state.scoped_flush_records = lambda: _registration_flush_records(
            user=target, admin_config=repo.state["admin_config"]
        )
        return ok(
            {
                "userId": user_id,
                "username": target.get("username"),
                "name": member.get("name") or target.get("name") or "",
                "temporaryPassword": temporary,
                "mustChangePassword": True,
            },
            request,
        )
