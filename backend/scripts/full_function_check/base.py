"""全功能验收的骨架：用例登记、角色会话、断言工具。

用例只写「这个功能用户怎么用、应该得到什么」，不碰实现细节：一律按前端的方式发 HTTP
请求（登录拿令牌、带 Idempotency-Key、高风险写带 If-Match），看业务码和返回数据。
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

ROLE_LABELS = {
    "inspection": "监检",
    "contractor": "施工方",
    "ndt": "无损检测",
    "owner": "建设方",
    "admin": "管理员",
    "fde": "FDE",
    "public": "未登录",
    "all": "全部角色",
    "outside": "施工方/无损/建设方",
}

# 用例编号前缀 → 模块名，顺序即用例文档里的章节顺序。
MODULES: dict[str, str] = {
    "SYS": "系统与运行状态",
    "AUTH": "登录与账号",
    "PERM": "权限与数据隔离",
    "INSP": "监检工作台",
    "CONT": "施工方工作台",
    "NDT": "无损检测工作台",
    "OWN": "建设方工作台",
    "FLOW": "主业务链路（跨角色）",
    "AUTO": "自动审查与批量复核",
    "MSG": "消息与待办",
    "FB": "意见反馈与改进",
    "RULE": "规则升级与审查口径",
    "ADM": "管理后台",
    "PLAT": "平台（多院）",
    "KNOW": "知识库",
    "FDE": "FDE 治理台",
    "SKILL": "节点审计 skill 与 OCR 复用",
    "ARCH": "报告归档（项目收尾，最后跑）",
    "UI": "页面与交互（浏览器）",
}

# 后端强制 If-Match 的四类高风险写（apps/api/routes.py IF_MATCH_REQUIRED_PATH_PATTERNS）。
IF_MATCH_PATHS = (
    re.compile(r"/inspection/nodes/[^/]+/review-opinions$"),
    re.compile(r"/inspection/nodes/[^/]+/actions/return-correction$"),
    re.compile(r"/projects/[^/]+/submissions$"),
    re.compile(r"/projects/[^/]+/reports/[^/]+/archive$"),
)

DENIED_CODES = {401, 403, 40301}


class CaseFailed(AssertionError):
    """预期没达到。"""


class CaseSkipped(Exception):
    """前置条件不满足（环境不支持、前面的用例没产出所需数据）。"""


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    role: str
    steps: tuple[str, ...]
    expected: str
    priority: str = "P1"
    # api：本脚本自动跑；ui：浏览器脚本（frontend/e2e/full-function.spec.ts）跑；manual：人工
    mode: str = "api"
    writes: bool = False
    in_process_only: bool = False
    fn: Callable[[Context], None] | None = None

    @property
    def prefix(self) -> str:
        return self.id.split("-", 1)[0]

    @property
    def module(self) -> str:
        return MODULES[self.prefix]


REGISTRY: list[Case] = []


def _register(item: Case) -> None:
    if item.prefix not in MODULES:
        raise ValueError(f"{item.id}: 未登记的模块前缀 {item.prefix}")
    if any(existing.id == item.id for existing in REGISTRY):
        raise ValueError(f"用例编号重复：{item.id}")
    REGISTRY.append(item)


def api_case(
    case_id: str,
    title: str,
    *,
    role: str,
    steps: tuple[str, ...] | list[str],
    expected: str,
    priority: str = "P1",
    writes: bool = False,
    in_process_only: bool = False,
) -> Callable[[Callable[[Context], None]], Callable[[Context], None]]:
    def wrap(fn: Callable[[Context], None]) -> Callable[[Context], None]:
        _register(
            Case(
                case_id,
                title,
                role,
                tuple(steps),
                expected,
                priority=priority,
                writes=writes,
                in_process_only=in_process_only,
                fn=fn,
            )
        )
        return fn

    return wrap


def ui_case(
    case_id: str,
    title: str,
    *,
    role: str,
    steps: tuple[str, ...] | list[str],
    expected: str,
    priority: str = "P1",
    mode: str = "ui",
) -> None:
    _register(Case(case_id, title, role, tuple(steps), expected, priority=priority, mode=mode))


def check(condition: object, message: str) -> None:
    if not condition:
        raise CaseFailed(message)


def skip(reason: str) -> None:
    raise CaseSkipped(reason)


@dataclass
class Reply:
    http: int
    body: Any
    content: bytes
    headers: dict[str, str]

    @property
    def code(self) -> Any:
        return self.body.get("code") if isinstance(self.body, dict) else None

    @property
    def data(self) -> Any:
        return self.body.get("data") if isinstance(self.body, dict) else None

    @property
    def message(self) -> str:
        return str(self.body.get("message") or "") if isinstance(self.body, dict) else ""

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def brief(self) -> str:
        if isinstance(self.body, dict):
            text = f"HTTP {self.http} code={self.code} {self.message[:160]}"
            if self.code not in (0, None) and self.data:
                text += f" data={json.dumps(self.data, ensure_ascii=False, default=str)[:300]}"
            return text
        return f"HTTP {self.http} {self.text[:160]}"


def items_of(data: Any) -> list[Any]:
    """列表接口有的直接回数组，有的回 {items: [...]}，统一取出来。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "list", "records", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


class RoleSession:
    """一个已登录（或未登录）的身份，按前端的方式发请求。"""

    def __init__(
        self, ctx: Context, role: str, token: str = "", user: dict[str, Any] | None = None
    ):
        self.ctx = ctx
        self.role = role
        self.token = token
        self.user = user or {}

    @property
    def user_id(self) -> str:
        return str(self.user.get("id") or "")

    def headers(
        self, extra: dict[str, str] | None = None, *, method: str = "GET", path: str = ""
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.role != "public":
            headers["X-Role"] = self.role
            if self.user_id:
                headers["X-User-Id"] = self.user_id
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            headers["Idempotency-Key"] = f"ff-{uuid.uuid4()}"
            bare = path.split("?", 1)[0]
            if any(pattern.search(bare) for pattern in IF_MATCH_PATHS):
                headers["If-Match"] = "*"
        headers.update(extra or {})
        return headers

    def call(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> Reply:
        method = method.upper()
        return self.ctx.send(
            method,
            path,
            json=json,
            params=params,
            headers=self.headers(headers, method=method, path=path),
            content=content,
        )

    def get(self, path: str, **params: Any) -> Reply:
        return self.call("GET", path, params=params or None)

    def ok(self, method: str, path: str, **kwargs: Any) -> Any:
        """断言成功（HTTP 200 且业务码 0），回 data。"""
        reply = self.call(method, path, **kwargs)
        check(
            reply.http == 200 and reply.code == 0, f"{method} {path} 应成功，实际 {reply.brief()}"
        )
        return reply.data

    def ok_get(self, path: str, **params: Any) -> Any:
        return self.ok("GET", path, params=params or None)

    def denied(
        self, method: str, path: str, *, codes: set[int] | None = None, **kwargs: Any
    ) -> Reply:
        """断言被拒绝：HTTP 401/403，或业务码属于拒绝类。"""
        reply = self.call(method, path, **kwargs)
        allowed = codes or DENIED_CODES
        refused = reply.http in {401, 403} or reply.code in allowed
        check(refused, f"{self.role} 调 {method} {path} 应被拒绝，实际 {reply.brief()}")
        return reply


@dataclass
class Context:
    """一次运行的共享状态。transport 是 httpx.Client 或 FastAPI TestClient。"""

    transport: Any
    in_process: bool
    allow_writes: bool
    password: str
    usernames: dict[str, str]
    store: dict[str, Any] = field(default_factory=dict)
    sessions: dict[str, RoleSession] = field(default_factory=dict)
    _patches: list[tuple[Any, str, Any]] = field(default_factory=list)

    def send(self, method: str, path: str, **kwargs: Any) -> Reply:
        response = self.transport.request(
            method, path, **{k: v for k, v in kwargs.items() if v is not None}
        )
        try:
            body: Any = response.json()
        except ValueError:
            body = None
        return Reply(response.status_code, body, response.content, dict(response.headers))

    def login(self, role: str, *, password: str | None = None) -> Reply:
        username = self.usernames.get(role, role)
        return self.send(
            "POST",
            "/api/auth/login",
            json={
                "username": username,
                "password": self.password if password is None else password,
            },
            headers={"Idempotency-Key": f"ff-login-{uuid.uuid4()}"},
        )

    def session(self, role: str) -> RoleSession:
        if role == "public":
            return RoleSession(self, "public")
        if role not in self.sessions:
            reply = self.login(role)
            data = reply.data if isinstance(reply.data, dict) else {}
            token = str(data.get("token") or "")
            if not token:
                raise CaseSkipped(f"{ROLE_LABELS.get(role, role)}账号登录失败：{reply.brief()}")
            self.sessions[role] = RoleSession(self, role, token, data.get("user") or {})
        return self.sessions[role]

    def need(self, key: str) -> Any:
        if self.store.get(key) in (None, "", [], {}):
            skip(f"缺少前置数据 {key}（产出它的用例没通过或被跳过）")
        return self.store[key]

    def require_in_process(self, why: str) -> None:
        if not self.in_process:
            skip(f"只在进程内模式跑：{why}")

    def patch(self, target: Any, name: str, value: Any) -> None:
        """进程内替身（例如不派发真实的 AI 复核），用例结束自动还原。"""
        self.require_in_process("需要替换后台任务")
        self._patches.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def restore_patches(self) -> None:
        while self._patches:
            target, name, original = self._patches.pop()
            setattr(target, name, original)

    @contextmanager
    def patched(self, target: Any, name: str, value: Any) -> Iterator[None]:
        self.patch(target, name, value)
        try:
            yield
        finally:
            target_, name_, original = self._patches.pop()
            setattr(target_, name_, original)
