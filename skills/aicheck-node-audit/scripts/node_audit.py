#!/usr/bin/env python3
"""AIcheck node audit helper for AI coding assistants. Python 3.10+, standard library (PyYAML only for local rules).

Pulls one project node from the AIcheck server into a local bundle, exposes the server's
certificate/standard tools, and checks the assistant's audit.json before rendering audit.md.
Only an explicitly confirmed sync writes draft AI findings back to the server.
"""
from __future__ import annotations

import argparse
import base64
import functools
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib import error, parse, request

SKILL_DIR = Path(__file__).resolve().parents[1]
BUNDLE_SCHEMA = "aicheck-node-audit-bundle@1"
REPORT_SCHEMA = "aicheck-node-audit-report@1"
VERDICTS = {
    "passed": "符合",
    "failed": "不符合",
    "evidence_insufficient": "证据不足",
    "human_review_required": "需人工确认",
    "not_applicable": "不适用",
    "not_executed": "未执行",
}
NEEDS_SOURCE = {"passed", "failed"}
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 每页
MAX_IMAGE_PAGES = 16
TEXT_WHOLE_FILE_PAGES = 20  # text 整份转出超过这么多页就提示改用 --pages 按命中页读
GATEWAY_ERRORS = {"http502", "http503", "http504"}
GATEWAY_RETRY_SECONDS = 5
# 这个服务器的业务错误是 HTTP 200 加 JSON，code 是数字（contracts/errors.py）：翻成和 HTTP 错误一样的错误码，助手才认得。
BUSINESS_CODES = {"401": "loginRequired", "403": "forbidden", "40404": "notFound"}
LOGIN_HINT = "（令牌缺失或过期：重新 login --web 让用户在浏览器里授权，或让用户在自己的终端口令登录）"
SERVER_RAW_DIR = "ocr/server"  # 服务器返回的 JSON 原文（含完整证号），只给脚本回查；包根目录那份已脱敏
RULE_FIELDS = ("id", "sourceRuleId", "name", "nodeIds", "version", "status", "inspectionClass",
               "businessModule", "inspectionItem", "criteria", "checkMethod", "referencedStandards",
               "agentThinking", "toolchainThinking", "materialTypeCodes")


class ClientError(Exception):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def archive_stamp() -> str:
    """存档文件名：精确到微秒。按秒命名时同一秒查两次，后一次会盖掉前一次，报告里的出处就指错了。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def audit_home() -> Path:
    return Path(os.getenv("AICHECK_AUDIT_HOME") or Path.home() / ".aicheck-node-audit").expanduser()


def session_path() -> Path:
    return Path(os.getenv("AICHECK_SESSION_FILE") or Path.home() / ".config/aicheck-node-audit/session.json").expanduser()


def repo_root() -> Path:
    return Path(os.getenv("AICHECK_REPO") or SKILL_DIR.parents[1]).expanduser()


def private_dir(path: Path) -> Path:
    """mkdir -p；这次新建的各级目录和审计目录里的各级目录设 0700。
    审计目录外本来就有的目录（--out 指到的 /tmp、共享目录）不动：改不了会报错，改了会把别人锁在外面。"""
    resolved = path.resolve()
    created = {p for p in (resolved, *resolved.parents) if not p.exists()}
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    home = audit_home().resolve()
    for current in (resolved, *resolved.parents):
        if current not in created and home not in (current, *current.parents):
            break
        os.chmod(current, 0o700)
    return path


def write_private(path: Path, text: str) -> None:
    private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- connection

def normalize_base(url: str) -> str:
    url = url.strip().rstrip("/")
    url = url[:-4] if url.endswith("/api") else url
    parts = parse.urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password \
            or parts.query or parts.fragment:
        raise ClientError("invalidUrl", "服务器地址须为不带账号、查询串或片段的 http(s) origin。")
    try:
        loopback = ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        loopback = parts.hostname.lower() == "localhost"
    if parts.scheme == "http" and not loopback and os.getenv("AICHECK_ALLOW_HTTP", "").lower() not in {"1", "true", "yes"}:
        raise ClientError("insecureTransport", "远程地址是明文 HTTP，口令和令牌会明文传输；确认可接受后设置 AICHECK_ALLOW_HTTP=1。")
    return url


def load_session() -> dict[str, Any]:
    try:
        return json.loads(session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Api:
    def __init__(self, base_url: str | None = None):
        session = load_session()
        base = base_url or os.getenv("AICHECK_BASE_URL") or session.get("baseUrl")
        if not base:
            raise ClientError("baseUrlMissing", "未配置服务器地址：设置 AICHECK_BASE_URL 或先执行 login --base-url。")
        self.base = normalize_base(base)
        # 会话令牌只发给签发它的服务器；换地址必须重新登录。
        self.token = os.getenv("AICHECK_TOKEN") or (session.get("token") if session.get("baseUrl") == self.base else None)

    def _request(self, method: str, path: str, *, body: Any = None, auth: bool = False,
                 query: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
                 content: bytes | None = None) -> request.Request:
        url = f"{self.base}/api{path}"
        if query:
            url += "?" + parse.urlencode({k: v for k, v in query.items() if v is not None})
        data = content if content is not None else json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None and content is None:
            req.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            req.add_header(name, value)
        if auth:
            if not self.token:
                raise ClientError("loginRequired", f"该接口需要监检账号令牌{LOGIN_HINT}。")
            # unredirected：跳转到对象存储时不带令牌。
            req.add_unredirected_header("Authorization", f"Bearer {self.token}")
        return req

    def call(self, method: str, path: str, *, body: Any = None, auth: bool = False,
             query: dict[str, Any] | None = None, timeout: float = 90, headers: dict[str, str] | None = None,
             content: bytes | None = None) -> Any:
        try:
            return self._call(method, path, body=body, auth=auth, query=query, timeout=timeout, headers=headers, content=content)
        except ClientError as exc:
            # 网关 502/504 多是服务器一时不可用（部署、重启），公示平台暂不可查询回 503，过几秒常常就好；只重试一次，登录不重试。
            if exc.code not in GATEWAY_ERRORS or path.startswith("/auth/"):
                raise
            time.sleep(GATEWAY_RETRY_SECONDS)
            return self._call(method, path, body=body, auth=auth, query=query, timeout=timeout, headers=headers, content=content)

    def upload(self, path: str, content: bytes, *, headers: dict[str, str], timeout: float = 300) -> Any:
        """原始字节上传（服务器 OCR）。网关重试靠调用方给的 Idempotency-Key 去重。"""
        return self.call("POST", path, auth=True, headers=headers, content=content, timeout=timeout)

    def _call(self, method: str, path: str, *, body: Any, auth: bool, query: dict[str, Any] | None, timeout: float,
              headers: dict[str, str] | None = None, content: bytes | None = None) -> Any:
        req = self._request(method, path, body=body, auth=auth, query=query, headers=headers, content=content)
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read() or b"{}")
        except error.HTTPError as exc:
            raise http_error(exc, path) from None
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ClientError("unreachable", f"服务器不可达：{getattr(exc, 'reason', exc)}", path=path) from None
        except ValueError:
            raise ClientError("badResponse", "服务器返回的不是 JSON。", path=path) from None
        if isinstance(payload, dict) and "code" in payload:
            if payload.get("code") not in (0, "0", "OK"):
                raise business_error(payload, path)
            return payload.get("data")
        return payload

    def download(self, path: str, target: Path, *, query: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return self._download(path, target, query=query)
        except ClientError as exc:
            # 同 call：服务器重启时的 502/503/504 隔几秒重试一次，不然这份原件就被记成没下载到。
            if exc.code not in GATEWAY_ERRORS:
                raise
            time.sleep(GATEWAY_RETRY_SECONDS)
            return self._download(path, target, query=query)

    def _download(self, path: str, target: Path, *, query: dict[str, Any] | None = None) -> dict[str, Any]:
        req = self._request("GET", path, auth=True, query=query)
        digest, size = hashlib.sha256(), 0
        private_dir(target.parent)
        try:
            with request.urlopen(req, timeout=300) as resp, \
                    os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as handle:
                while chunk := resp.read(1 << 16):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise ClientError("fileTooLarge", "原件超过 300MB，未下载。", path=path)
                    digest.update(chunk)
                    handle.write(chunk)
                content_type = resp.headers.get("Content-Type", "")
        except error.HTTPError as exc:
            target.unlink(missing_ok=True)
            raise http_error(exc, path) from None
        except ClientError:
            target.unlink(missing_ok=True)
            raise
        except (error.URLError, TimeoutError, OSError) as exc:
            target.unlink(missing_ok=True)
            raise ClientError("unreachable", f"下载失败：{getattr(exc, 'reason', exc)}", path=path) from None
        return {"sha256": digest.hexdigest(), "bytes": size, "contentType": content_type}


def http_error(exc: error.HTTPError, path: str) -> ClientError:
    try:
        payload = json.loads(exc.read() or b"{}")
    except ValueError:
        payload = {}
    finally:
        exc.close()
    payload = payload if isinstance(payload, dict) else {}
    message = str(payload.get("message") or exc.reason or "请求失败")
    code = {401: "loginRequired", 403: "forbidden", 404: "notFound", 429: "rateLimited"}.get(exc.code, f"http{exc.code}")
    details: dict[str, Any] = {"status": exc.code, "path": path}
    if isinstance(payload.get("data"), dict) and "retryAfter" in payload["data"]:
        details["retryAfter"] = payload["data"]["retryAfter"]
    if exc.code == 401:
        message += LOGIN_HINT
    return ClientError(code, message, **details)


def business_error(payload: dict[str, Any], path: str) -> ClientError:
    """HTTP 200 里的业务错误：401 没登录、403 无权、40404 对象不存在，其余保留服务器的数字码。"""
    raw = str(payload.get("code"))
    code = BUSINESS_CODES.get(raw, raw)
    message = str(payload.get("message") or "服务器拒绝请求。")
    if code == "loginRequired":
        message += LOGIN_HINT
    return ClientError(code, message, path=path, serverCode=raw)


# ---------------------------------------------------------------- auth

def login_base(args: argparse.Namespace) -> str:
    base = args.base_url or os.getenv("AICHECK_BASE_URL") or load_session().get("baseUrl")
    if not base:
        raise ClientError("baseUrlMissing", "未配置服务器地址：加 --base-url 或设置 AICHECK_BASE_URL。")
    return normalize_base(base)


def save_login(base: str, token: str, user: dict[str, Any], *, method: str) -> dict[str, Any]:
    write_private(session_path(), dump({"baseUrl": base, "token": token, "username": user.get("username"),
                                        "role": user.get("role"), "savedAt": now(), "method": method}))
    role = user.get("role")
    result = {"baseUrl": base, "username": user.get("username"), "role": role, "sessionFile": str(session_path())}
    if role not in {"inspection", "admin"}:
        result["warning"] = "节点审计工作区只对监检（inspection）或管理员开放，当前角色可能取不到节点资料。"
    return result


def cmd_login(args: argparse.Namespace) -> Any:
    if args.web:
        return cmd_login_web(args)
    if not args.username:
        raise ClientError("usernameRequired", "口令登录要加 --username；或改用 login --web 在浏览器里授权。")
    if not sys.stdin.isatty():
        raise ClientError("ttyRequired", "口令登录只能在用户自己的终端里运行（getpass 读口令，不经过对话）；助手可以改用 login --web。")
    base = login_base(args)
    api = Api(base)
    password = getpass.getpass(f"{args.username} @ {base} 口令（不回显）: ")
    body: dict[str, Any] = {"username": args.username, "password": password}
    if args.tenant_id:
        body["tenantId"] = args.tenant_id
    data = api.call("POST", "/auth/login", body=body)
    user = {"username": args.username, **((data or {}).get("user") or {})}
    return save_login(base, data["token"], user, method="password")


WEB_LOGIN_TIMEOUT_SECONDS = 300
CALLBACK_PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>AIcheck 节点审计</title>
<body style="font-family:system-ui,sans-serif;max-width:32em;margin:15vh auto;padding:0 1em;color:#24364f">
<h2>{title}</h2><p>{detail}</p></body></html>"""


def pkce_pair() -> tuple[str, str]:
    """RFC 7636：校验码随机 32 字节，challenge = base64url(sha256(校验码))，都去掉末尾的 =。"""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def web_authorize_url(base: str, redirect_uri: str, state: str, challenge: str) -> str:
    """授权请求整体编码进路径（/#/skill-authorize/<base64url(JSON)>）：平台未登录时守卫只把路径带进登录页，查询串会丢。"""
    raw = json.dumps({"r": redirect_uri, "s": state, "c": challenge}, separators=(",", ":")).encode("ascii")
    return f"{base}/#/skill-authorize/{base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')}"


def callback_handler(state: str, outcome: dict[str, str]) -> type:
    """本机回调处理器。state 对不上的请求回 400 并继续等（可能是别的程序在敲这个端口）。"""
    from http.server import BaseHTTPRequestHandler

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # 不往 stderr 打访问日志
            return

        def reply(self, status: int, title: str, detail: str) -> None:
            body = CALLBACK_PAGE.format(title=title, detail=detail).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            url = parse.urlsplit(self.path)
            query = dict(parse.parse_qsl(url.query))
            if url.path != "/callback" or not hmac.compare_digest(query.get("state", "").encode(), state.encode()):
                self.reply(400, "这不是本次授权的回调", "请回到助手重新运行 login --web。")
            elif query.get("error"):
                outcome["error"] = query["error"]
                self.reply(200, "已拒绝授权", "skill 没有拿到任何权限，可以关闭这个页面。")
            elif query.get("code"):
                outcome["code"] = query["code"]
                self.reply(200, "授权成功", "可以关闭这个页面，回到助手继续。")
            else:
                self.reply(400, "回调缺少授权码", "请回到助手重新运行 login --web。")

    return Callback


def wait_for_web_callback(server: Any, outcome: dict[str, str], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not outcome and time.monotonic() < deadline:
        server.timeout = max(0.1, min(1.0, deadline - time.monotonic()))
        server.handle_request()


def cmd_login_web(args: argparse.Namespace) -> Any:
    """浏览器授权：平台上已登录的监检或管理员点「授权」，一次性授权码回调到本机端口，再凭 PKCE 校验码换令牌。
    口令只在浏览器里输入，不经过 skill 和助手，所以这个命令助手可以自己运行。"""
    from http.server import HTTPServer

    base = login_base(args)
    verifier, challenge = pkce_pair()
    state = base64.urlsafe_b64encode(os.urandom(24)).rstrip(b"=").decode("ascii")
    outcome: dict[str, str] = {}
    server = HTTPServer(("127.0.0.1", 0), callback_handler(state, outcome))
    try:
        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}/callback"
        url = web_authorize_url(base, redirect_uri, state, challenge)
        print(f"在浏览器里打开下面的链接，用监检或管理员账号登录平台后点「授权」（{args.timeout} 秒内有效）：\n{url}",
              file=sys.stderr, flush=True)
        opened = False
        if not args.no_browser:
            import webbrowser

            opened = bool(webbrowser.open(url))
        wait_for_web_callback(server, outcome, args.timeout)
    finally:
        server.server_close()
    if outcome.get("error"):
        raise ClientError("webLoginDenied", "在浏览器里点了拒绝，没有登录。要登录就重新运行 login --web。")
    if not outcome.get("code"):
        hint = "" if opened or args.no_browser else "浏览器没能自动打开：把上面的链接发给用户，让他自己打开。"
        raise ClientError("webLoginTimeout", f"{args.timeout} 秒内没收到浏览器授权。{hint}重新运行 login --web 会生成新链接。",
                          authorizeUrl=url)
    data = Api(base).call("POST", "/auth/skill/token", body={"code": outcome["code"], "codeVerifier": verifier,
                                                               "redirectUri": redirect_uri})
    return save_login(base, data["token"], (data or {}).get("user") or {}, method="web")


def cmd_logout(args: argparse.Namespace) -> Any:
    session = load_session()
    if session.get("token"):
        try:
            Api(session.get("baseUrl")).call("POST", "/auth/logout", auth=True, body={})
        except ClientError:
            pass
    session_path().unlink(missing_ok=True)
    return {"loggedOut": True}


def cmd_connection(args: argparse.Namespace) -> Any:
    api = Api(args.base_url)
    result: dict[str, Any] = {"baseUrl": api.base, "tokenPresent": bool(api.token)}
    for key, path in (("ready", "/readyz"), ("inspectionServices", "/inspection-services/capabilities")):
        try:
            result[key] = api.call("GET", path, timeout=30)
        except ClientError as exc:
            result[key] = {"error": exc.code, "message": exc.message}
    if api.token:
        try:
            me = api.call("GET", "/auth/me", auth=True, timeout=30) or {}
            user = me.get("user", me)
            result["user"] = {k: user.get(k) for k in ("username", "role", "displayName") if k in user}
        except ClientError as exc:
            result["user"] = {"error": exc.code, "message": exc.message}
    return result


# ---------------------------------------------------------------- rules (local business pack)

@functools.lru_cache(maxsize=None)
def load_yaml(path: Path) -> Any:
    try:
        import yaml  # type: ignore
    except ImportError:
        raise ClientError("pyyamlMissing", "读取业务包需要 PyYAML：python3 -m pip install pyyaml，或用 backend/.venv/bin/python 运行。") from None
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


PER_ITEM = re.compile(r"逐(焊口|焊缝|件|张|根|个|条|项|台|批|道|管线|份|人|名)")


# instruction 没写“逐”字、但实际要逐件核对的检查。
PER_ITEM_OVERRIDES = {"AC-R24-04": "逐焊口"}  # 厚度、外径、填充金属要按每道焊口的实际规格核


def check_role(instruction: str, check_id: str = "") -> dict[str, Any]:
    """Every rule has one traceability check; 14 checks (plus overrides) demand item-by-item coverage."""
    role: dict[str, Any] = {}
    if check_id in PER_ITEM_OVERRIDES:
        role["perItem"] = PER_ITEM_OVERRIDES[check_id]
    if "可追溯" in instruction and "不得判定为符合" in instruction:
        role["role"] = "traceability"
    match = PER_ITEM.search(instruction)
    if match and "perItem" not in role:
        role["perItem"] = match.group(0)
    return role


def rule_catalog(node_id: int) -> dict[str, Any]:
    pack = Path(os.getenv("AICHECK_BUSINESS_PACK") or repo_root() / "backend/business_packs/engineering_inspection_v1")
    if not (pack / "rules.yaml").exists():
        raise ClientError("businessPackMissing", f"找不到业务包：{pack}（可设置 AICHECK_REPO 或 AICHECK_BUSINESS_PACK）。")
    rule_id = f"R{node_id:02d}"
    rules = [r for r in load_yaml(pack / "rules.yaml")["ruleSets"]
             if node_id in (r.get("nodeIds") or []) and r.get("sourceRuleId") == rule_id]
    if not rules:
        raise ClientError("ruleNotFound", f"业务包里没有节点 {node_id} 的规则 {rule_id}。")
    node = next((n for n in load_yaml(pack / "nodes.yaml")["nodeTemplates"] if n.get("nodeId") == node_id), {})
    checks = [c for c in load_yaml(pack / "atomic_checks.yaml")["atomicChecks"] if c.get("sourceRuleId") == rule_id]
    bindings = {b["atomicCheckId"]: b for b in load_yaml(pack / "atomic_check_tool_bindings.yaml")["atomicCheckToolBindings"]
                if b.get("sourceRuleId") == rule_id}
    clauses = [c for c in load_yaml(pack / "standard_clause_bindings.yaml")["standardClauseBindings"]
               if c.get("sourceRuleId") == rule_id]
    return {
        "source": "local_business_pack",
        "businessPack": str(pack),
        "ruleId": rule_id,
        "node": {k: node.get(k) for k in ("nodeId", "name", "groupName", "inspectionType", "requiredMaterials")},
        "rule": {k: rules[0].get(k) for k in RULE_FIELDS},
        "atomicChecks": [
            {**{k: c.get(k) for k in ("id", "name", "checkType", "instruction", "evidenceRequired")},
             **check_role(str(c.get("instruction") or ""), c["id"]),
             "serverTools": (bindings.get(c["id"]) or {}).get("tools") or [],
             "requiredFacts": (bindings.get(c["id"]) or {}).get("requiredFacts") or [],
             "toolImplementationStatus": (bindings.get(c["id"]) or {}).get("implementationStatus")}
            for c in checks
        ],
        "standardClauses": [{k: c.get(k) for k in ("standardRef", "clauseNo", "bindingRole", "applicability",
                                                   "verificationStatus", "sourcePage", "knowledgeFileId")}
                            for c in clauses],
    }


def cmd_rules(args: argparse.Namespace) -> Any:
    return rule_catalog(args.node)


# ---------------------------------------------------------------- bundle helpers

def safe_name(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" .") or "file"
    return name[:120]


def bundle_dir(project: str, node: int, out: str | None) -> Path:
    if out:
        return Path(out).expanduser().resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return audit_home() / safe_name(project) / f"node-{node:02d}" / stamp


def latest(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    key = lambda r: str(r.get("updatedAt") or r.get("completedAt") or r.get("createdAt") or "")
    return max(records, key=key) if records else None


def server_outcomes(review_run: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    run = (review_run or {}).get("run", review_run) or {}
    run_id = run.get("reviewRunId") or run.get("id")
    outcomes = {}
    for item in run.get("atomicCheckOutcomes") or []:
        if isinstance(item, dict) and item.get("atomicCheckId"):
            outcomes[item["atomicCheckId"]] = {"result": item.get("result") or item.get("status"),
                                               "decisionSource": item.get("decisionSource"),
                                               "reviewRunId": run_id}
    return outcomes


def field_value(field: dict[str, Any]) -> str:
    value = field.get("fieldValue", field.get("value"))
    return "" if value is None else str(value)


def cell(value: Any) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ")


def flatten_workspace(payload: Any) -> dict[str, Any]:
    """服务器 audit-workspace 把 submission / ocr / evidence / aiReview 等放在 `content` 下；
    包里和后面各处都按顶层键读，所以这里摊平。已经是平铺的（本地 --workspace 模拟文件）原样返回。"""
    if not isinstance(payload, dict):
        return {}
    content = payload.get("content")
    if not isinstance(content, dict):
        return payload
    return {**{k: v for k, v in payload.items() if k != "content"}, **content}


DIGEST_FIELD_ROWS = 60  # 摘要里服务器抽取字段只列这么多行：它只是 OCR 线索，全表在 workspace.json


def clause_line(clause: dict[str, Any]) -> str:
    """固定主条款：总适用的只写页码和核验状态；有条件的把条件也写出来，免得为一句适用条件去读 rules.json。"""
    extra = [f"第{clause.get('sourcePage')}页", str(clause.get("verificationStatus"))]
    if clause.get("applicability") not in (None, "always"):
        note = clause.get("condition") or clause.get("applicabilityNote")
        extra.append(f"适用：{clause.get('applicability')}" + (f"——{note}" if note else ""))
    return f"{clause.get('standardRef')} {clause.get('clauseNo')}（{'，'.join(extra)}）"


def write_digest(root: Path, manifest: dict[str, Any], rules: dict[str, Any], workspace: dict[str, Any]) -> None:
    """A compact first read for the assistant; full JSON stays alongside."""
    rule = rules["rule"]
    outcomes = manifest.get("serverOutcomes") or {}
    lines = [f"# {manifest.get('projectId')} · 节点 {manifest['nodeId']:02d} · {rules['ruleId']} {rule.get('name')}", "",
             f"- 来源：{manifest['source']}；取数时间：{manifest['fetchedAt']}；服务器：{manifest.get('baseUrl') or '—'}"]
    lines += [f"- ⚠ {w}" for w in manifest.get("warnings") or []]
    lines += ["", "## 规则", "", f"**依据（criteria）**：{rule.get('criteria')}", "",
              f"**审查方法（checkMethod）**：{rule.get('checkMethod')}", "",
              "**参考标准**：" + "、".join(str(s.get("reference") or s) for s in rule.get("referencedStandards") or []), "",
              "**固定主条款**：" + ("；".join(clause_line(c) for c in rules.get("standardClauses") or []) or "—"), "",
              "## 原子检查（每项都要出结论；audit.json 骨架已按这个顺序列好）", ""]
    for check in rules["atomicChecks"]:
        server = outcomes.get(check["id"], {})
        marks = [m for m in ("**证据追溯项**：节点内任一项证据不足/未执行就判证据不足，有冲突就判需人工确认" if check.get("role") == "traceability" else "",
                             f"**逐件核对项（{check['perItem']}）**：判符合要 coverage 且全部覆盖，没有逐件记录就判证据不足" if check.get("perItem") else "") if m]
        lines += [f"### {check['id']} {check['name']}", "", f"- 要做的事：{check.get('instruction')}"]
        lines += [f"- {m}" for m in marks]
        if manifest.get("source") == "server":
            lines.append(f"- 服务器结果：{server.get('result') or '—'}；服务器工具：{', '.join(check['serverTools']) or '—'}")
        lines.append("")
    lines += ["## 资料要求", ""]
    for req in (rules["node"].get("requiredMaterials") or []):
        lines.append(f"- `{req.get('id')}` {req.get('name')}（{req.get('requiredType')}）— {req.get('note') or ''}")
    lines += ["", "## 文件（files/ 下为原件，可直接读取）", "",
              "| 文件 | 资料名 | 挂载状态 | OCR | sha256 前 12 位 |", "|---|---|---|---|---|"]
    for item in manifest["files"]:
        lines.append(f"| `{item['path']}` | {item.get('requirementName') or item.get('fileName')} | "
                     f"{item.get('bindingStatus') or '—'} | {item.get('ocrStatus') or '—'} | {str(item.get('sha256') or '')[:12]} |")
    for item in manifest.get("skippedFiles") or []:
        lines.append(f"| （未收入）{item.get('fileName') or item.get('projectPath')} | — | — | — | {item.get('reason')} |")
    fields = ((workspace.get("ocr") or {}).get("extractedFields") or [])
    if fields:
        by_version = {f.get("documentVersionId"): f.get("path") for f in manifest["files"]}
        lines += ["", "## 服务器抽取字段（OCR 线索，关键值须对照原页）", "",
                  "| 文件 | 页 | 字段 | 值 | 置信度 | 状态 |", "|---|---|---|---|---|---|"]
        for field in fields[:DIGEST_FIELD_ROWS]:
            value = cell(field_value(field)[:120])
            lines.append(f"| {by_version.get(field.get('documentVersionId')) or field.get('documentVersionId')} | "
                         f"{field.get('pageNo') or '—'} | {field.get('fieldName')} | {value} | "
                         f"{field.get('confidence') if field.get('confidence') is not None else '—'} | {field.get('reviewStatus') or '—'} |")
        if len(fields) > DIGEST_FIELD_ROWS:
            lines.append(f"\n（共 {len(fields)} 条，只列前 {DIGEST_FIELD_ROWS} 条；全部在 workspace.json（已脱敏）→ ocr.extractedFields，"
                         "按字段名 grep，别整份读）")
    readiness = (workspace.get("evidence") or {}).get("readiness") or {}
    if readiness:
        lines += ["", "## 服务器证据就绪度", "",
                  f"readyForAiFormal={readiness.get('readyForAiFormal')}，missing={readiness.get('missingCount')}，pending={readiness.get('pendingCount')}"]
        lines += [f"- {r.get('code')}: {r.get('message')}" for r in readiness.get("blockingReasons") or []]
    write_private(root / "digest.md", mask_ids("\n".join(lines) + "\n"))


def write_server_json(root: Path, filename: str, value: Any) -> None:
    """服务器返回的 JSON 落两份：包根目录的脱敏版给助手读；ocr/server/ 下的原文只给脚本回查完整证号（resolve_masked_id）。"""
    write_private(root / filename, dump_masked(value))
    write_private(root / SERVER_RAW_DIR / filename, dump(value))


def finish_bundle(root: Path, manifest: dict[str, Any], rules: dict[str, Any], workspace: dict[str, Any]) -> dict[str, Any]:
    manifest["atomicChecks"] = [c["id"] for c in rules["atomicChecks"]]
    write_private(root / "rules.json", dump(rules))
    write_private(root / "bundle.json", dump(manifest))
    write_digest(root, manifest, rules, workspace)
    return {"bundle": str(root), "digest": str(root / "digest.md"), "files": len(manifest["files"]),
            "skippedFiles": manifest.get("skippedFiles") or [], "atomicChecks": manifest["atomicChecks"],
            "serverOutcomes": len(manifest.get("serverOutcomes") or {}), "warnings": manifest.get("warnings") or []}


# ---------------------------------------------------------------- fetch from server

def cmd_fetch(args: argparse.Namespace) -> Any:
    api = Api(args.base_url)
    project, node = args.project, args.node
    node_path = f"/projects/{parse.quote(project, safe='')}/inspection/nodes/{node}"
    workspace = flatten_workspace(api.call("GET", f"{node_path}/audit-workspace", auth=True))
    root = bundle_dir(project, node, args.out)
    private_dir(root)
    write_server_json(root, "workspace.json", workspace)
    warnings: list[str] = []
    if not any(key in workspace for key in ("submission", "ocr", "aiReview")):
        warnings.append("服务器 audit-workspace 的返回里没有 submission / ocr / aiReview（也不在 content 下），"
                        "接口结构可能变了：下面“没有挂载资料”“没有审查运行”可能是读不到而不是真没有，先看 workspace.json 再信。")
    parts = {"workspace": "workspace.json"}
    optional = (("serverRule", "rules/current-version", "server-rule.json"),
                ("standards", "standards", "standards.json"),
                ("evidenceChain", "evidence-chain", "evidence-chain.json"))
    fetched: dict[str, Any] = {}
    for key, path, filename in optional:
        try:
            fetched[key] = api.call("GET", f"{node_path}/{path}", auth=True)
            parts[key] = filename
            write_server_json(root, filename, fetched[key])
        except ClientError as exc:
            warnings.append(f"{key} 未取到：{exc.code} {exc.message}")

    rules = rule_catalog(node)
    server_rule = (fetched.get("serverRule") or {}).get("rule") or {}
    if server_rule and (node not in (server_rule.get("nodeIds") or []) or server_rule.get("sourceRuleId") != rules["ruleId"]):
        warnings.append(f"服务器规则与节点不一致：节点 {node} 拿到 {server_rule.get('sourceRuleId')}/{server_rule.get('nodeIds')}，"
                        f"审计以本地业务包 {rules['ruleId']} 为准，并在报告里写明。")

    review_run = None
    run_ref = latest(((workspace.get("aiReview") or {}).get("reviewRuns")) or [])
    if run_ref:
        run_id = run_ref.get("reviewRunId") or run_ref.get("id")
        try:
            review_run = api.call("GET", f"/review-runs/{parse.quote(str(run_id), safe='')}", auth=True)
            parts["reviewRun"] = "review-run.json"
            write_server_json(root, "review-run.json", review_run)
        except ClientError as exc:
            warnings.append(f"最近一次审查运行 {run_id} 未取到：{exc.code} {exc.message}")
    else:
        warnings.append("该节点在服务器上没有审查运行，没有服务器结论可对照。")

    files, skipped = [], []
    documents = ((workspace.get("submission") or {}).get("documents")) or ((workspace.get("ocr") or {}).get("documents")) or []
    for index, doc in enumerate(documents, start=1):
        bindings = doc.get("bindings") or []
        binding = doc.get("primaryBinding") or (bindings[0] if bindings else {})
        version_id = binding.get("documentVersionId") or doc.get("currentVersionId")
        entry = {"documentId": doc.get("id"), "documentVersionId": version_id, "fileName": doc.get("fileName"),
                 "requirementName": binding.get("requirementName"), "bindingStatus": binding.get("bindingStatus"),
                 "materialTypeCode": doc.get("materialTypeCode"),
                 "ocrStatus": (doc.get("ocrReadiness") or {}).get("status")}
        if args.no_files:
            skipped.append({**entry, "reason": "--no-files"})
            continue
        relative = f"files/{index:02d}-{safe_name(str(doc.get('fileName') or doc.get('id')))}"
        try:
            meta = api.download(f"/projects/{parse.quote(project, safe='')}/documents/{parse.quote(str(doc.get('id')), safe='')}/original",
                                root / relative, query={"disposition": "attachment", "versionId": version_id})
            files.append({**entry, "path": relative, **meta})
        except ClientError as exc:
            if exc.code == "loginRequired":
                raise  # 令牌中途过期：别建一个缺原件的包，重新授权后重跑 fetch
            skipped.append({**entry, "reason": f"{exc.code} {exc.message}", "downloadFailed": True})
    if not documents:
        warnings.append("该节点没有已提交的挂载资料（工作区只给已提交的挂载）。")
    failed_downloads = [s for s in skipped if s.get("downloadFailed")]
    if failed_downloads:
        warnings.append(f"{len(failed_downloads)} 份挂载资料没下载到（见 skippedFiles）：资料包不完整。先隔一两分钟重跑 fetch；"
                        "仍拿不到就在报告 limitations 写明缺哪份、影响哪些检查，report 会核对。")

    manifest = {"schemaVersion": BUNDLE_SCHEMA, "source": "server", "baseUrl": api.base, "projectId": project,
                "nodeId": node, "ruleId": rules["ruleId"], "fetchedAt": now(), "parts": parts,
                "files": files, "skippedFiles": skipped, "serverOutcomes": server_outcomes(review_run),
                "warnings": warnings}
    return finish_bundle(root, manifest, rules, workspace)


# ---------------------------------------------------------------- local test bundle

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 16):
            digest.update(chunk)
    return digest.hexdigest()


def skip_file(path: Path) -> bool:
    """Office lock files (~$x.docx), macOS metadata and hidden files are not project material."""
    return path.name.startswith(("~$", ".", "._")) or path.name in {"Thumbs.db", "desktop.ini"}


def cmd_local_init(args: argparse.Namespace) -> Any:
    project = args.project or "LOCAL-TEST"
    root = bundle_dir(project, args.node, args.out)
    if (root / "bundle.json").exists():
        raise ClientError("bundleExists", f"{root} 已有 bundle.json，换一个 --out。")
    sources = [Path(p).expanduser().resolve() for p in args.files or []]
    skipped: list[dict[str, Any]] = []
    project_dir = Path(args.project_dir).expanduser().resolve() if args.project_dir else None
    if project_dir:
        if not project_dir.is_dir():
            raise ClientError("fileNotFound", f"找不到项目目录：{project_dir}")
        found = sorted(p for p in project_dir.rglob("*") if p.is_file())
        hidden = lambda p: skip_file(p) or any(part.startswith(".") or part == "__MACOSX" for part in p.relative_to(project_dir).parts)
        sources += [p for p in found if not hidden(p)]
        skipped = [{"projectPath": str(p.relative_to(project_dir)), "reason": "锁文件、隐藏文件或系统元数据"} for p in found if hidden(p)]
    if not sources:
        raise ClientError("invalidArguments", "用 --project-dir 给整个项目目录（推荐），或用 --files 列文件。")
    missing = [str(p) for p in sources if not p.is_file()]
    if missing:
        raise ClientError("fileNotFound", "找不到文件：" + "、".join(missing))
    workspace: dict[str, Any] = {}
    if args.workspace:
        workspace = json.loads(Path(args.workspace).expanduser().read_text(encoding="utf-8"))
        workspace = flatten_workspace(workspace.get("data", workspace))
    private_dir(root)
    write_server_json(root, "workspace.json", workspace)
    files = []
    for index, source in enumerate(sources, start=1):
        relative = f"files/{index:02d}-{safe_name(source.name)}"
        private_dir(root / "files")
        shutil.copyfile(source, root / relative)
        os.chmod(root / relative, 0o600)
        entry = {"path": relative, "fileName": source.name, "sha256": sha256_file(source),
                 "bytes": source.stat().st_size, "localSource": str(source)}
        if project_dir and project_dir in source.parents:
            entry["projectPath"] = str(source.relative_to(project_dir))
        files.append(entry)
    review_run = None
    if args.review_run:
        review_run = json.loads(Path(args.review_run).expanduser().read_text(encoding="utf-8"))
        review_run = review_run.get("data", review_run)
    rules = rule_catalog(args.node)
    manifest = {"schemaVersion": BUNDLE_SCHEMA, "source": "local", "baseUrl": None, "projectId": project,
                "nodeId": args.node, "ruleId": rules["ruleId"], "fetchedAt": now(),
                "parts": {"workspace": "workspace.json"}, "files": files, "skippedFiles": skipped,
                "serverOutcomes": server_outcomes(review_run),
                "warnings": ["本地测试资料：没有服务器挂载、OCR 与证据确认状态，资料是否齐备只能按文件本身判断。"]}
    return finish_bundle(root, manifest, rules, workspace)


# ---------------------------------------------------------------- page rendering (PDF too large to open whole)

def parse_pages(spec: str | None, count: int, limit: int = 20) -> list[int]:
    if not spec:
        pages = list(range(1, count + 1))
    else:
        pages = []
        for part in spec.split(","):
            start, _, end = part.strip().partition("-")
            try:
                first, last = int(start), int(end or start)
            except ValueError:
                raise ClientError("invalidArguments", f"页码 {part!r} 看不懂：写成 4-6,9 这样的数字和范围。") from None
            if not 1 <= first <= last <= count:
                raise ClientError("pageOutOfRange", f"页码 {part} 超出 1–{count}。")
            pages.extend(range(first, last + 1))
    if len(pages) > limit:
        raise ClientError("tooManyPages", f"一次最多 {limit} 页。")
    return pages


def quiet_fitz() -> Any:
    """PyMuPDF prints xref repair messages to stdout, which would corrupt the JSON this CLI prints."""
    import fitz  # type: ignore  # PyMuPDF
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)
    return fitz


def find_bundle(path: Path) -> Path | None:
    for parent in list(path.parents)[:4]:
        if (parent / "bundle.json").exists():
            return parent
    return None


def pages_out_dir(args: argparse.Namespace, path: Path) -> Path:
    """页图只进资料包：渲染仓库里的标准原件时不加 --bundle 会写进 rules/，那是要提交的目录。"""
    if args.out:
        return Path(args.out).expanduser().resolve()
    if args.bundle:
        bundle = Path(args.bundle).expanduser().resolve()
        if not (bundle / "bundle.json").exists():
            raise ClientError("bundleMissing", f"{bundle} 不是资料包（没有 bundle.json）。")
        return bundle / "pages"
    bundle = find_bundle(path)
    if bundle is None:
        raise ClientError("outputMissing", f"{path.name} 不在资料包里：加 --bundle <资料包>（页图存进它的 pages/），或 --out <目录>。")
    return bundle / "pages"


def parse_clip(value: str | None) -> list[float] | None:
    if not value:
        return None
    try:
        box = [float(v) for v in value.split(",")]
    except ValueError:
        box = []
    if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
        raise ClientError("invalidArguments", "--clip 须为 x0,y0,x1,y1，取值 0–1 的页面比例。")
    return box


def render_png(fitz: Any, page: Any, target: Path, *, dpi: int, rotate: int = 0, clip: Any = None) -> Path:
    private_dir(target.parent)
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72).prerotate(rotate), clip=clip)
    pix.set_dpi(dpi, dpi)  # 用 matrix 渲染时 PNG 不记分辨率，补上，和 dpi= 渲染的一样
    pix.save(target)
    os.chmod(target, 0o600)
    return target


def clip_rect(fitz: Any, page: Any, box: list[float]) -> Any:
    r = page.rect
    return fitz.Rect(r.x0 + r.width * box[0], r.y0 + r.height * box[1], r.x0 + r.width * box[2], r.y0 + r.height * box[3])


def unrotate_box(box: list[float], rotate: int) -> list[float]:
    """--clip 按转正后的样子给比例坐标；换回未旋转页面上的比例（顺时针转 90/180/270）。"""
    u0, v0, u1, v1 = box
    if rotate == 90:
        return [v0, 1 - u1, v1, 1 - u0]
    if rotate == 180:
        return [1 - u1, 1 - v1, 1 - u0, 1 - v0]
    if rotate == 270:
        return [1 - v1, u0, 1 - v0, u1]
    return box


def resolve_input(args: argparse.Namespace) -> Path:
    """--file 可写资料包里的相对路径（如 files/13-焊工证.pdf），配 --bundle 时按资料包解析。"""
    path = Path(args.file).expanduser()
    if not path.is_absolute() and not path.exists() and getattr(args, "bundle", None):
        candidate = Path(args.bundle).expanduser() / path
        if candidate.exists():
            path = candidate
    return path.resolve()


def form_fields(page: Any) -> int:
    """图纸上的电子章、签名多是表单域，不在页面内容里；有几个就报几个，给“页面上有章”一个工具依据。"""
    try:
        return sum(1 for _ in page.widgets())
    except Exception:  # noqa: BLE001 -- 图片文档没有表单域
        return 0


def contact_sheets(fitz: Any, doc: Any, numbers: list[int], out_dir: Path, stem: str, cols: int, dpi: int) -> list[str]:
    """缩略拼图：每格一页、左上角标页码，每张最多 30 格；用来过目扫描件、找某张表在哪页。
    每格用 get_pixmap 连注释和表单域一起渲染再贴图：show_pdf_page 会漏掉表单域里的电子章。"""
    cell_w, cell_h, label_h, per_sheet = 200, 260, 14, 30
    scale = dpi / 72
    sheets = []
    for k in range(0, len(numbers), per_sheet):
        chunk = numbers[k:k + per_sheet]
        rows = -(-len(chunk) // cols)
        with fitz.open() as canvas:
            sheet = canvas.new_page(width=cols * cell_w, height=rows * (cell_h + label_h))
            for i, number in enumerate(chunk):
                x, y = (i % cols) * cell_w, (i // cols) * (cell_h + label_h)
                page = doc[number - 1]
                fields = form_fields(page)
                sheet.insert_text((x + 4, y + 11), f"p{number}" + (f" 表单域{fields}" if fields else ""), fontsize=9,
                                  fontname="china-s")
                zoom = min((cell_w - 4) / page.rect.width, (cell_h - 4) / page.rect.height) * scale
                thumb = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), annots=True)
                sheet.insert_image(fitz.Rect(x + 2, y + label_h, x + cell_w - 2, y + label_h + cell_h - 2), pixmap=thumb)
                sheet.draw_rect(fitz.Rect(x + 1, y + label_h - 1, x + cell_w - 1, y + label_h + cell_h - 1), color=(0.75, 0.75, 0.75), width=0.5)
            target = out_dir / f"{stem}-sheet-p{chunk[0]:03d}-{chunk[-1]:03d}.png"
            private_dir(target.parent)
            sheet.get_pixmap(dpi=dpi).save(target)
            os.chmod(target, 0o600)
            sheets.append(str(target))
    return sheets


def all_visual_sheets(fitz: Any, args: argparse.Namespace) -> Any:
    """一次给最近一次 search 标出的全部无文字层文件（和文字 PDF 里的扫描页）出缩略拼图。"""
    if not args.bundle:
        raise ClientError("invalidArguments", "--all-visual 要配 --bundle <资料包>。")
    bundle = Path(args.bundle).expanduser().resolve()
    search = latest_search(bundle)
    if not search:
        raise ClientError("searchMissing", "先跑 search，再用 --all-visual。")
    out_dir = Path(args.out).expanduser().resolve() if args.out else bundle / "pages"
    targets = [(path, None) for path in search.get("needsOcr", search.get("needsVisualReview")) or []]
    targets += [(path, pages) for path, pages in (search.get("needsOcrPages", search.get("needsVisualPages")) or {}).items()]
    results, skipped = [], []
    for relative, pages in targets:
        try:
            doc = fitz.open(bundle / relative)
        except Exception:  # noqa: BLE001 -- e.g. a .doc fitz cannot open
            skipped.append({"file": relative, "reason": "不是 PDF 或图片，用 text 转文字，或请用户给 PDF"})
            continue
        with doc:
            numbers = pages if pages and not isinstance(pages, str) else list(range(1, doc.page_count + 1))
            numbers = numbers[:300]
            results.append({"file": relative, "pageCount": doc.page_count,
                            "sheets": contact_sheets(fitz, doc, numbers, out_dir, safe_name(Path(relative).stem), args.cols, args.dpi or 72),
                            "formFieldPages": {n: c for n in numbers if (c := form_fields(doc[n - 1]))}})
    return {"bundle": str(bundle), "files": results, "skipped": skipped}


def cmd_pages(args: argparse.Namespace) -> Any:
    try:
        fitz = quiet_fitz()
    except ImportError:
        raise ClientError("pymupdfMissing", "需要 PyMuPDF：用 backend/.venv/bin/python 运行本命令，或 pip install pymupdf。") from None
    if args.all_visual:
        return all_visual_sheets(fitz, args)
    if not args.file:
        raise ClientError("invalidArguments", "给 --file，或用 --all-visual --bundle 一次过目全部无文字层文件。")
    path = resolve_input(args)
    if not path.is_file():
        raise ClientError("fileNotFound", f"找不到文件：{path}")
    out_dir = pages_out_dir(args, path)
    rotate = args.rotate or 0
    clip_box = parse_clip(args.clip)
    try:
        doc = fitz.open(path)  # PDF，或 png/jpg/tif 等图片（当作单页文档）
    except Exception:  # noqa: BLE001 -- unreadable or unsupported file
        raise ClientError("unsupportedFile", f"{path.name} 不是 PDF 或可识别的图片。") from None
    with doc:
        if not args.pages and not args.sheet:
            if doc.page_count != 1:
                raise ClientError("invalidArguments", f"{path.name} 有 {doc.page_count} 页：给 --pages（如 1-3,7），或用 --sheet 出缩略拼图。")
            args.pages = "1"  # 图片和单页 PDF 不必写 --pages
        stem = safe_name(path.stem)
        result: dict[str, Any] = {"file": str(path), "pageCount": doc.page_count, "outDir": str(out_dir)}
        if args.sheet:
            numbers = parse_pages(args.pages, doc.page_count, limit=300)
            result["sheets"] = contact_sheets(fitz, doc, numbers, out_dir, stem, args.cols, args.dpi or 72)
            result["formFieldPages"] = {n: c for n in numbers if (c := form_fields(doc[n - 1]))}
            return result
        result["pages"] = []
        for number in parse_pages(args.pages, doc.page_count):
            page = doc[number - 1]
            item: dict[str, Any] = {"page": number}
            if not args.text_only:
                clip = clip_rect(fitz, page, unrotate_box(clip_box, rotate)) if clip_box else None
                suffix = ("-clip" + "_".join(f"{v:g}" for v in clip_box)) if clip_box else ""
                suffix += f"-r{rotate}" if rotate else ""
                if clip_box:
                    item["clip"] = clip_box
                if rotate:
                    item["rotate"] = rotate
                target = render_png(fitz, page, out_dir / f"{stem}-p{number:03d}{suffix}.png",
                                    dpi=args.dpi or 150, rotate=rotate, clip=clip)
                item["image"] = str(target)
            text = page.get_text().strip()
            item["text"] = text[:6000]
            item["textLayer"] = bool(text)
            item["formFields"] = form_fields(page)
            result["pages"].append(item)
    return result


# ---------------------------------------------------------------- whole-bundle search

# 全项目资料里最容易漏的事实：工期、证书有效期、材质、人员、管道级别。
COMMON_TERMS = ("计划施工时间", "施工时间", "工期", "开工", "竣工", "有效期", "许可证")
# 原子检查 requiredFacts 里的字段名 → 原件里会写的词；字段缺了就要靠这些词去找。
REQUIRED_FACT_TERMS = {
    "changeClarification": ("设计变更", "变更单", "澄清"), "actualConstructionEnd": ("竣工",),
    "pipelineGrades": ("管道级别", "管道等级", "GC1", "GC2", "GCD"), "scopeCodes": ("许可项目", "许可范围"),
    "titleBlockOrganization": ("标题栏",), "designSealOrganization": ("出图专用章", "设计专用章", "许可印章"),
    "workDate": ("施焊日期", "焊接日期"), "workItems": ("焊口", "焊缝编号"), "qualificationCodes": ("合格项目", "项目代号"),
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp"}


# 拉丁补充、希腊字母、数学符号、带圈数字、罗马数字、几何形状：工程文本里的 Φ × ° ≤ Ⅱ ① 都在这里。
READABLE_RANGES = ((0x4E00, 0x9FFF), (0x3000, 0x303F), (0xFF00, 0xFFEF), (0x00A0, 0x03FF),
                   (0x2000, 0x22FF), (0x2150, 0x218F), (0x2460, 0x24FF), (0x25A0, 0x25FF))


def readable_ratio(text: str) -> float:
    if not text:
        return 0.0
    # \x07 是 Word 表格的单元格结束符，\x0b/\x0c 是换行换页。
    good = sum(1 for ch in text if ch.isspace() or ch in "\x07\x0b\x0c" or (ch.isascii() and ch.isprintable())
               or any(low <= ord(ch) <= high for low, high in READABLE_RANGES))
    return good / len(text)


def looks_like_text(text: str) -> bool:
    sample = text[:200000]
    return bool(sample.strip()) and sample.count("\x00") < len(sample) * 0.005 and readable_ratio(sample) >= 0.85


# GB 标准 PDF 的斜体拉丁字母（公式、符号里的 D、S、W、Rm）字体映射错：文字层里成了 GBK 0xA0A1–0xA0FE 这段罕用字，
# 正好是 ASCII 码加 0x80（犇=D、犛=S、犠=W、犪=a）。逐字换回；这段字在正常文本里几乎不出现。仓库标准里有 71 页这样。
ITALIC_LATIN = str.maketrans({bytes([0xA0, t]).decode("gbk"): chr(t - 0x80) for t in range(0xA1, 0xFF)})
# GB2312 一级字（3755 个常用字）。扫描件自带的识别文字认错时满页是罕用字（鸥、罾、邳），常用字占比掉到 0.7 以下；
# 正常页在 0.9 以上（2026-10-28 量过仓库 59 份标准 1350 页、评测工程 38 份资料 158 页：正常页最低 0.94）。
COMMON_HANZI = frozenset(bytes([hi, lo]).decode("gb2312") for hi in range(0xB0, 0xD8) for lo in range(0xA1, 0xFF)
                         if not (hi == 0xD7 and lo > 0xF9))
GARBLED_COMMON_BELOW = 0.8
GARBLED_MIN_HANZI = 50
TABLE_MIN_LINES = 80  # 一页至少这么多行、六成以上是一两个字的短行：表格被文字层拆成了一格一行
TABLE_SHORT_SHARE = 0.6


def garbled_layer(text: str) -> bool:
    """文字层是认错了的识别文字（满页罕用字，常见于倒放、旋转的扫描页），不能当原文读。"""
    hanzi = [ch for ch in text if "一" <= ch <= "鿿"]
    return len(hanzi) >= GARBLED_MIN_HANZI and sum(ch in COMMON_HANZI for ch in hanzi) < GARBLED_COMMON_BELOW * len(hanzi)


def table_layout_lost(text: str) -> bool:
    """表格被文字层拆成一格一行（评定因素矩阵、尺寸表）：字都对，但哪个值属于哪一行哪一列读不出来。"""
    lines = [line for line in text.splitlines() if line.strip()]
    return len(lines) >= TABLE_MIN_LINES and sum(len(line.strip()) <= 2 for line in lines) >= TABLE_SHORT_SHARE * len(lines)


def word97_text(path: Path) -> str:
    """Word 97-2003 .doc text: OLE compound file → WordDocument/Table streams → piece table. Data only, nothing executed."""
    data = path.read_bytes()
    if data[:8] != bytes.fromhex("D0CF11E0A1B11AE1"):
        raise ValueError("not an OLE compound file")
    import struct
    sector_size, mini_size = 1 << struct.unpack_from("<H", data, 0x1E)[0], 1 << struct.unpack_from("<H", data, 0x20)[0]
    first_dir, mini_cutoff, first_minifat, first_difat, n_difat = (struct.unpack_from("<I", data, off)[0]
                                                                   for off in (0x30, 0x38, 0x3C, 0x44, 0x48))
    end = 0xFFFFFFFA
    sector = lambda i: data[(i + 1) * sector_size:(i + 2) * sector_size]
    difat = list(struct.unpack_from("<109I", data, 0x4C))
    nxt = first_difat
    for _ in range(n_difat):
        if nxt >= end:
            break
        values = struct.unpack(f"<{sector_size // 4}I", sector(nxt))
        difat.extend(values[:-1])
        nxt = values[-1]
    fat = [v for s in difat if s < end for v in struct.unpack(f"<{sector_size // 4}I", sector(s))]

    def chain(start: int, table: list[int], read) -> bytes:
        out, seen = [], set()
        while start < end and start not in seen and start < len(table):
            seen.add(start)
            out.append(read(start))
            start = table[start]
        return b"".join(out)

    directory = chain(first_dir, fat, sector)
    entries = []
    for off in range(0, len(directory) - 127, 128):
        entry = directory[off:off + 128]
        name_len = struct.unpack_from("<H", entry, 64)[0]
        entries.append((entry[:max(name_len - 2, 0)].decode("utf-16-le", "replace"), entry[66],
                        struct.unpack_from("<I", entry, 116)[0], struct.unpack_from("<I", entry, 120)[0]))
    ministream = chain(entries[0][2], fat, sector)
    minifat = list(struct.unpack(f"<{len(m) // 4}I", m)) if (m := chain(first_minifat, fat, sector)) else []

    def stream(name: str) -> bytes:
        for entry_name, kind, start, size in entries:
            if entry_name == name and kind == 2:
                if size < mini_cutoff:
                    return chain(start, minifat, lambda i: ministream[i * mini_size:(i + 1) * mini_size])[:size]
                return chain(start, fat, sector)[:size]
        raise ValueError(f"stream {name} missing")

    word = stream("WordDocument")
    table = stream("1Table" if struct.unpack_from("<H", word, 0x0A)[0] & 0x0200 else "0Table")
    fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x1A2)  # FibRgFcLcb97.fcClx
    clx = table[fc_clx:fc_clx + lcb_clx]
    i = 0
    while i < len(clx) and clx[i] == 0x01:  # Prc 块跳过
        i += 3 + struct.unpack_from("<h", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise ValueError("piece table missing")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    count = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{count + 1}I", plc, 0)
    parts = []
    for k in range(count):
        fc = struct.unpack_from("<I", plc, (count + 1) * 4 + k * 8 + 2)[0]
        chars = cps[k + 1] - cps[k]
        if fc & 0x40000000:
            start = (fc & ~0x40000000) // 2
            parts.append(word[start:start + chars].decode("cp1252", "replace"))
        else:
            parts.append(word[fc:fc + chars * 2].decode("utf-16-le", "replace"))
    text = "".join(parts)
    text = re.sub(r"\x13[^\x13\x14\x15]*\x14", "", text)  # 域代码只留结果
    text = re.sub(r"\x13[^\x13\x14\x15]*\x15", "", text)
    for old, new in (("\r", "\n"), ("\x07", "\t"), ("\x0b", "\n"), ("\x0c", "\n")):
        text = text.replace(old, new)
    return "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)


def office_xml_text(path: Path) -> str:
    import zipfile
    parts = {".docx": ("word/document.xml",), ".xlsx": ("xl/sharedStrings.xml",)}[path.suffix.lower()]
    with zipfile.ZipFile(path) as archive:
        xml = "\n".join(archive.read(name).decode("utf-8", "replace") for name in parts if name in archive.namelist())
    xml = re.sub(r"</w:p>|</si>|</w:tc>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def file_text(path: Path) -> tuple[str, list[str]]:
    """(status, page texts). status: text | image | pdf_unreadable | office_unreadable | unsupported | pymupdf_missing."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image", []
    if suffix == ".pdf":
        try:
            fitz = quiet_fitz()
        except ImportError:
            return "pymupdf_missing", []
        try:
            with fitz.open(path) as doc:
                return "text", [page.get_text().translate(ITALIC_LATIN) for page in doc]
        except Exception:  # noqa: BLE001 -- 一份坏 PDF 不能让整包检索崩掉：记成打不开，报告里标 skipped 写原因
            return "pdf_unreadable", []
    if suffix in {".txt", ".md", ".csv", ".json"}:
        return "text", [path.read_text(encoding="utf-8", errors="replace")]
    if suffix in {".docx", ".xlsx"}:
        try:
            return "text", [office_xml_text(path)]
        except Exception:  # noqa: BLE001 -- a damaged archive is reported, not fatal
            return "office_unreadable", []
    if suffix in {".doc", ".wps"}:
        try:
            text = word97_text(path)
            if looks_like_text(text):
                return "text", [text]
        except Exception:  # noqa: BLE001 -- not Word 97 (RTF/HTML saved as .doc, Word 6): try textutil
            pass
    if suffix in {".doc", ".xls", ".rtf", ".wps"} and shutil.which("textutil"):
        import subprocess
        try:
            out = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)], capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            return "office_unreadable", []
        text = out.stdout.decode("utf-8", "replace")
        # WPS 存的 .doc 经 textutil 常吐出整份二进制：可读字符太少或夹着大量 NUL 就当没读到。
        if out.returncode or not looks_like_text(text):
            return "office_unreadable", []
        return "text", [text]
    return "unsupported", []


# 按节点所属专业补的默认检索词；材质牌号决定焊工、焊材、元件能否覆盖，焊接和材料类节点必查。
MATERIAL_GRADES = ("材质", "牌号", "不锈钢", "碳钢", "合金钢", "异种钢", "S30408", "S31603", "Q235", "Q245R", "Q345R",
                   "20#", "15CrMo", "12Cr1MoV")
GROUP_TERMS = {
    "焊接": ("焊工", "钢印", "焊工号", "焊口", "施焊", "焊接记录", "焊材", "母材", "规格", *MATERIAL_GRADES),
    "热处理": ("热处理", "硬度", "曲线", "测温", "恒温"),
    "材料": ("质量证明", "炉批号", "复验", "规格", "数量", *MATERIAL_GRADES),
    "阀门": ("阀门", "壳体试验", "密封试验", "试压"),
    "无损检测": ("检测比例", "合格级别", "底片", "RT", "UT", "PT", "MT"),
    "设计": ("设计压力", "设计温度", "管道级别", "设计变更", "审批", "会审"),
    "资质": ("许可证", "许可项目", "许可范围", "有效期"),
    "耐压": ("试验压力", "保压", "压力表", "试验介质"),
    "泄漏": ("泄漏试验", "试验压力", "压力表"),
}


def text_out_path(args: argparse.Namespace, path: Path, part: str | None = None) -> Path:
    """转出的文字只进资料包：仓库里的标准原件不带 --bundle/--out 会写进 rules/ 旁边。
    只转部分页时文件名带页码（如 x.p4-6_9.txt），不覆盖整份转出的那一份。"""
    name = f"{safe_name(path.stem)}{'.p' + part.replace(',', '_') if part else ''}.txt"
    if args.out:
        out = Path(args.out).expanduser().resolve()
        return out / name if out.is_dir() or args.out.endswith(("/", os.sep)) else out
    if args.bundle:
        bundle = Path(args.bundle).expanduser().resolve()
        if not (bundle / "bundle.json").exists():
            raise ClientError("bundleMissing", f"{bundle} 不是资料包（没有 bundle.json）。")
        return bundle / "text" / name
    bundle = find_bundle(path)
    if bundle is None:
        raise ClientError("outputMissing", f"{path.name} 不在资料包里：加 --bundle <资料包>（存进它的 text/），或 --out <文件或目录>。")
    return bundle / "text" / name


def cmd_text(args: argparse.Namespace) -> Any:
    path = resolve_input(args)
    if not path.is_file():
        raise ClientError("fileNotFound", f"找不到文件：{path}")
    bundle = Path(args.bundle).expanduser().resolve() if args.bundle else find_bundle(path)
    relative = bundle_relative(bundle, path) if bundle else None
    status, layer, pages, used = page_texts(bundle, relative, path)
    ocr_hint = f"先跑 ocr --bundle <资料包>{'' if not relative or relative.startswith('files/') else ' --files ' + relative}（服务器 OCR），再用 text 读 OCR 文字。"
    if status not in {"text", "ocr"}:
        raise ClientError("noTextLayer", f"{path.name}：{status}，没有可取的文字——{ocr_hint}")
    empty = [n for n, text in enumerate(pages, start=1) if len(text.strip()) < 20]
    if pages and len(empty) == len(pages):
        raise ClientError("noTextLayer", f"{path.name} 没有文字层（扫描件）——{ocr_hint}")
    # --pages 只转这几页：大文件、标准原文按 search 命中页读，不用整份读进对话
    selected = parse_pages(args.pages, len(pages), limit=max(len(pages), 1)) if args.pages else list(range(1, len(pages) + 1))
    out = text_out_path(args, path, page_ranges(selected) if args.pages else None)
    # 文字层齐、只在页末补了 OCR 多读出的字（印章、签字栏、图片上的字）的页
    supplemented = {n for n in selected if status == "text" and n not in used and n <= len(layer) and pages[n - 1] != layer[n - 1]}
    label = lambda n: f"--- 第 {n} 页{'（OCR）' if status == 'ocr' or n in used else '（文字层＋OCR 补充）' if n in supplemented else ''} ---"
    body = "\n\n".join(f"{label(n)}\n{pages[n - 1]}" if len(pages) > 1 or status == "ocr" else pages[n - 1] for n in selected)
    write_private(out, mask_ids(body))
    result = {"file": str(path), "status": status, "pages": len(pages), "chars": sum(len(pages[n - 1]) for n in selected), "saved": str(out)}
    if args.pages:
        result["readPages"] = page_ranges(selected)
    elif len(pages) > TEXT_WHOLE_FILE_PAGES:
        result["readHint"] = (f"共 {len(pages)} 页：不要整份读进对话。按 search 的 termPages 用 --pages 只转要看的页；"
                              "逐件核对要看全部页时分段转、边读边记 notes.md。")
    record = load_ocr(bundle, relative, path)
    if status == "ocr" or used or supplemented:
        ocr_selected = selected if status == "ocr" else sorted(used & set(selected))
        if ocr_selected:
            result["ocrPages"] = page_ranges(ocr_selected)
        if supplemented:
            result["ocrSupplementPages"] = page_ranges(sorted(supplemented))
        result["ocrNote"] = ("标（OCR）的页是服务器识别的文字；标（文字层＋OCR 补充）的页，页末“以下是服务器 OCR 读出、文字层里没有的字”后面"
                             "是 OCR 多读出的格（印章、签字栏人名、图片上的字），引用照抄那一行；"
                             "[印章：…]、[签名：…] 是服务器识别的印章、签名，“服务器未读出章上的字”表示有章但没读出字，该事实交人工确认。"
                             f"{CODE_MISREAD_NOTE}。")
        if (record or {}).get("renderVersion") != OCR_RENDER_VERSION:
            result["ocrOutdated"] = "这份 OCR 是旧排版（横跨多列的格子逐格重复）：再跑一次 ocr 会按新排版重排，不重新上传、不重新识别；重排后摘录照新转出的文字抄。"
    quality = ocr_quality(bundle, relative, path, selected) if record else {}
    if quality:
        result["ocrQuality"] = (problem_summary(quality, OCR_QUALITY_LABELS) + "。这些页上找不到的事实不能写“原件没有”：先到材料表、"
                                "管道特性表、设计说明等别的资料里找，仍找不到就判证据不足或需人工确认，limitations 写明哪页 OCR 读不全")
    # 文字层靠不住、又还没用上 OCR 的页：text 给的是文字层原样，读数会错。
    shaky = layer_problems(path, layer, [n for n in selected if n not in used]) if status == "text" else {}
    if shaky:
        result["layerWarnings"] = problem_summary(shaky, LAYER_PROBLEMS) + "。" + (
            "这些页服务器 OCR 也没读出字：相关事实交人工确认" if record else
            f"要用这些页的数值、表格：{ocr_hint}有 OCR 后 text 对这些页只给 OCR 文字")
    if status == "text" and not used and (images := office_image_count(path)):
        result["embeddedImages"] = f"文档里嵌了 {images} 张图片，图片里的字这里读不到（如证件照片）：{ocr_hint}"
    empty_selected = [n for n in empty if n in selected]
    if empty_selected and len(pages) > 1:
        result["pagesWithoutText"] = page_ranges(empty_selected)  # 这些页文字层和 OCR 里都没有字：跑 ocr；跑过仍是空白的页，相关事实交人工确认
    return result


def scan_pages(path: Path, layer: list[str]) -> set[int]:
    """要靠 OCR 才读得到内容的页（按原件文字层算）：几乎没字（<20）；文字层是认错了的识别文字（满页罕用字）；
    字很少（<50）又嵌着图片（整页证书配一行说明）；字不多（<200）而一张图片占了大半页（扫描仪自带的页眉页脚、
    垃圾文字层盖不住图里的内容）；字不多（<200）的大幅面页（CAD 出的图纸把标注转成了线条，文字层只剩图框编号，
    评测里储罐施工图第 23–30 页就是这样）。"""
    pages = {n for n, text in enumerate(layer, start=1) if len(text.strip()) < 20 or garbled_layer(text)}
    candidates = [n for n, text in enumerate(layer, start=1) if 20 <= len(text.strip()) < SCAN_TEXT_BELOW and n not in pages]
    if not candidates or path.suffix.lower() != ".pdf":
        return pages
    fitz = quiet_fitz()
    with fitz.open(path) as doc:
        for n in candidates:
            page = doc[n - 1]
            if max(page.rect.width, page.rect.height) >= DRAWING_LONG_SIDE:
                pages.add(n)
            elif len(layer[n - 1].strip()) < OCR_FILL_BELOW:
                if page.get_images():
                    pages.add(n)
                continue
            if image_covers_page(fitz, page):
                pages.add(n)
    return pages


def image_covers_page(fitz: Any, page: Any) -> bool:
    area = abs(page.rect) or 1.0
    return any(abs(fitz.Rect(info["bbox"]) & page.rect) / area >= SCAN_IMAGE_SHARE for info in page.get_image_info())


def embedded_ocr_page(fitz: Any, page: Any) -> bool:
    """整页是图片，文字是扫描时自带的隐形识别文字（渲染模式 3）：字多半对，数值、牌号常有认错的（GB/T 8163
    表 7 的 Q420 成了“Q衽20”、-40 成了“一返0”）。"""
    if not image_covers_page(fitz, page):
        return False
    shown = hidden = 0
    for span in page.get_texttrace():
        count = len(span.get("chars") or ())
        hidden, shown = (hidden + count, shown) if span.get("type") == 3 else (hidden, shown + count)
    return hidden > 0 and hidden >= 0.8 * (hidden + shown)


LAYER_PROBLEMS = {"garbled": "文字层是认错了的识别文字（满页罕用字）",
                  "embedded": "是扫描件自带的识别文字（数值、牌号可能认错）",
                  "table": "表格被文字层拆成一格一行（行列对不上）"}


def layer_problems(path: Path, layer: list[str], numbers: Any = None) -> dict[int, str]:
    """有文字层、但文字层靠不住的页 → LAYER_PROBLEMS 的键。几乎没字的页不算（那是扫描页，见 scan_pages）。
    有这一页的服务器 OCR 时，text、检索和摘录核对都改用 OCR 文字（摘录核对仍认文字层）。"""
    wanted = sorted({n for n in (numbers if numbers is not None else range(1, len(layer) + 1))
                     if 1 <= n <= len(layer) and len(layer[n - 1].strip()) >= 20})
    problems: dict[int, str] = {}
    image_pages = []
    for n in wanted:
        if garbled_layer(layer[n - 1]):
            problems[n] = "garbled"
        elif table_layout_lost(layer[n - 1]):
            problems[n] = "table"
        elif len(layer[n - 1].strip()) >= SCAN_TEXT_BELOW:
            image_pages.append(n)  # 字更少又有大图的页已按扫描页算
    if image_pages and path.suffix.lower() == ".pdf":
        try:
            fitz = quiet_fitz()
            with fitz.open(path) as doc:
                problems.update({n: "embedded" for n in image_pages if embedded_ocr_page(fitz, doc[n - 1])})
        except Exception:  # noqa: BLE001 -- 打不开就当文字层可用：只是少一条提示
            return problems
    return problems


def problem_summary(problems: dict[int, str], labels: dict[str, str] | None = None) -> str:
    """{页: 原因} → “第 2-3,5 页文字层是…；第 12 页…”。"""
    groups: dict[str, list[int]] = {}
    for page, reason in sorted(problems.items()):
        groups.setdefault(labels.get(reason, reason) if labels else reason, []).append(page)
    return "；".join(f"第 {page_ranges(pages)} 页{reason}" for reason, pages in groups.items())


def default_terms(bundle: Path) -> list[str]:
    rules = json.loads((bundle / "rules.json").read_text(encoding="utf-8"))
    terms = list(COMMON_TERMS)
    group = f"{rules['node'].get('groupName') or ''}{rules['rule'].get('businessModule') or ''}"
    for key, extra in GROUP_TERMS.items():
        if key in group:
            terms += [t for t in extra if t not in terms]
    facts = " ".join(f for check in rules["atomicChecks"] for f in check.get("requiredFacts") or [])
    for key, extra in REQUIRED_FACT_TERMS.items():
        if key in facts:
            terms += [t for t in extra if t not in terms]
    for requirement in rules["node"].get("requiredMaterials") or []:
        for part in re.split(r"[、及和与/（）()\s]+", str(requirement.get("name") or "")):
            if len(part) >= 2 and part not in terms:
                terms.append(part)
    return terms


def cmd_search(args: argparse.Namespace) -> Any:
    bundle = Path(args.bundle).expanduser().resolve()
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    terms = list(args.terms or []) if args.only else [*default_terms(bundle), *(args.terms or [])]
    terms = list(dict.fromkeys(t for t in terms if t.strip()))
    files, visual, visual_pages, id_files = [], [], {}, {}
    scanned_files, scanned_pages, weak, embedded = [], {}, {}, {}
    for item in manifest.get("files") or []:
        path = bundle / item["path"]
        status, layer, pages, used = page_texts(bundle, item["path"], path)
        for text in pages:
            for match in ID_CANDIDATE.finditer(text):
                if looks_like_id(match.group(1)):
                    id_files.setdefault(mask_ids(match.group(1)), set()).add(item["path"])
        record: dict[str, Any] = {"path": item["path"], "status": status, "pages": len(pages),
                                  "textChars": sum(len(t.strip()) for t in pages), "hits": []}
        # 扫描页按原件文字层算（报告据此要求这一页有 OCR 文字）；还缺字的页按补过 OCR 的文字算（要先跑 ocr）。
        raw_empty = sorted(scan_pages(path, layer)) if status == "text" else []
        if status not in {"text"} or (layer and len(raw_empty) == len(layer)):
            scanned_files.append(item["path"])
        elif raw_empty:
            scanned_pages[item["path"]] = raw_empty
        empty = [n for n, text in enumerate(pages, start=1) if len(text.strip()) < 20 and n not in used]
        if status == "text":
            empty = sorted(set(empty) | (set(raw_empty) - used))
        if used:
            record["ocrPages"] = page_ranges(used)
        elif status == "text" and (images := office_image_count(path)):
            embedded[item["path"]] = images  # 嵌着的图片里的字检索不到
        quality = ocr_quality(bundle, item["path"], path) if status in {"text", "ocr"} and (used or status == "ocr") else {}
        if quality:
            weak[item["path"]] = problem_summary(quality, OCR_QUALITY_LABELS)
            record["ocrQuality"] = weak[item["path"]]
        if empty and len(pages) > 1:
            record["pagesWithoutText"] = empty if len(empty) <= 30 else f"{len(empty)} 页"
        if status not in {"text", "ocr"} or (pages and len(empty) == len(pages)):
            visual.append(item["path"])
        elif empty and len(pages) > 1:
            visual_pages[item["path"]] = empty  # 部分页是扫描件、也还没 OCR：检索看不到这些页
        per_term: dict[str, int] = {}
        for page_no, text in enumerate(pages, start=1):
            flat = re.sub(r"\s+", " ", text)
            for term in terms:
                for match in re.finditer(re.escape(term), flat):
                    if per_term.get(term, 0) >= args.max_per_term:
                        break
                    per_term[term] = per_term.get(term, 0) + 1
                    record["hits"].append({"page": page_no, "term": term,
                                           "snippet": flat[max(0, match.start() - 40): match.end() + 60]})
        files.append(record)
    # 文字层里有的身份证号可直接用脱敏号查 cert-registry；不在这里的只在图片上，要照原件读。
    id_numbers = {masked: sorted(paths) for masked, paths in sorted(id_files.items())}
    target = bundle / "search" / f"{archive_stamp()}.json"
    write_private(target, dump_masked({"at": now(), "bundle": str(bundle), "terms": terms, "files": files,
                                        "needsOcr": visual, "needsOcrPages": visual_pages,
                                        "scannedFiles": scanned_files, "scannedPages": scanned_pages,
                                        "ocrQuality": weak, "idNumbersInText": id_numbers}))
    files.sort(key=lambda f: -len(f["hits"]))
    term_files = {t: sorted({f["path"] for f in files for h in f["hits"] if h["term"] == t}) for t in terms}
    zero_hit = [t for t, paths in term_files.items() if not paths]
    # 输出只给摘要，一行一份文件、按词列命中页；逐条命中和片段在 saved 的 JSON 里。
    return {
        "bundle": str(bundle),
        "saved": str(target),
        "termHitFiles": "、".join(f"{t} {len(paths)}" for t, paths in term_files.items() if paths),
        "zeroHitTerms": "、".join(zero_hit),
        **({"zeroHitNote": zero_hit_note(len(visual), len(visual_pages), len(weak))} if zero_hit and (visual or visual_pages or weak) else {}),
        "filesWithHits": [{"path": f["path"], "hitCount": len(f["hits"]),
                           "termPages": "、".join(f"{t} p{page_ranges(p)}" for t, p in term_pages(f["hits"]).items()),
                           **({"ocrPages": f["ocrPages"]} if f.get("ocrPages") else {}),
                           "sample": [f"p{h['page']} [{h['term']}] {h['snippet']}" for h in f["hits"][:args.sample]]}
                          for f in files if f["hits"]],
        "filesWithoutHits": [f["path"] for f in files if not f["hits"] and f["path"] not in visual],
        "needsOcr": visual,
        "needsOcrPages": {path: page_ranges(pages) for path, pages in visual_pages.items()},
        **({"ocrQuality": dict(list(weak.items())[:20])} if weak else {}),
        **({"embeddedImages": {path: f"嵌了 {n} 张图片，图片里的字检索不到：跑 ocr 会把这份交服务器识别" for path, n in embedded.items()}}
           if embedded else {}),
        "idNumbersInText": {masked: "、".join(paths) for masked, paths in list(id_numbers.items())[:30]},
    }


def zero_hit_note(scanned_files: int, partly_scanned: int, weak_ocr: int = 0) -> str:
    """零命中只对有文字（文字层或 OCR）的文件成立；还没 OCR 的扫描件没被检索到，OCR 读不全的页也可能漏了，
    不能凭零命中说“没有”。"""
    parts = [f"{scanned_files} 份图片或扫描件（needsOcr）" if scanned_files else "",
             f"{partly_scanned} 份文件的部分扫描页（needsOcrPages）" if partly_scanned else ""]
    note = "零命中只对有文字的文件有效；"
    if scanned_files or partly_scanned:
        note += "、".join(p for p in parts if p) + "还没 OCR，没有被检索到，这些词可能在那里。要说“没有”，先跑 ocr 再检索。"
    if weak_ocr:
        note += (f"另有 {weak_ocr} 份文件的部分页 OCR 读得不全（ocrQuality：图纸、空白页、识别跑飞），那几页上的词可能没读出来，"
                 "零命中不能当原件没有。")
    return note


def term_pages(hits: list[dict[str, Any]]) -> dict[str, set[int]]:
    pages: dict[str, set[int]] = {}
    for hit in hits:
        pages.setdefault(hit["term"], set()).add(hit["page"])
    return dict(sorted(pages.items()))


def page_ranges(numbers: Any) -> str:
    """[1, 2, 3, 7] → "1-3,7"。"""
    ordered, parts = sorted(numbers), []
    for n in ordered:
        if parts and n == parts[-1][1] + 1:
            parts[-1][1] = n
        else:
            parts.append([n, n])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in parts)


# ---------------------------------------------------------------- OCR（经服务器：MinerU，排队超时自动改 qwen）
#
# 扫描件、图片不让助手自己看图：交给 AIcheck 服务器做 OCR。服务器用它自己配的 MinerU，MinerU 连续排队
# 超时会自动改用千问识别（qwen 兜底），本机不需要任何 OCR 密钥，用监检登录令牌即可。结果按页给出文字、
# 表格、印章、签名，助手读文字。2026-10-27 用 TSG Z6002 两页实测：MinerU 项目代号逐字全对、合并单元格
# 表格全对。服务器没有“对某一页问一个问题”的接口：OCR 后仍缺的事实交人工确认。

OCR_UPLOAD_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".ppt", ".pptx"}
OCR_MAX_BYTES = 100 * 1024 * 1024
OCR_ACTIVE = {"queued", "running"}
OCR_FAILED = {"failed", "canceled"}
OCR_POLL_SECONDS = 30  # 服务器查状态、取结果每次都整表加载 OCR 记录，别查太勤；它建议更久就听它的
OCR_FILL_BELOW = 50  # 文字层不到这么多字的页（扫描页、整页证书配一行说明）用 OCR 文字补
SCAN_TEXT_BELOW = 200  # 文字层不到这么多字、又有一张图占了大半页的，也按扫描页算（见 scan_pages）
SCAN_IMAGE_SHARE = 0.5
# OCR 记录里存的是排好版的逐页文字（表格怎么展开）；改了排版就加一，旧记录在下次 ocr 时按新排版重排。
# 2：横跨多列的格子每行只写一次、标（跨N列）。
OCR_RENDER_VERSION = 2
LATEX_SYMBOLS = {r"\geqslant": "≥", r"\leqslant": "≤", r"\geq": "≥", r"\leq": "≤", r"\ge": "≥", r"\le": "≤",
                 r"\sim": "~", r"\times": "×", r"\pm": "±", r"\varphi": "φ", r"\phi": "φ", r"\Phi": "Φ",
                 r"\circ": "°", r"\%": "%", r"\mu": "μ", r"\alpha": "α", r"\beta": "β", r"\delta": "δ",
                 r"\Delta": "Δ", r"\sigma": "σ", r"\cdot": "·", r"\approx": "≈", r"\neq": "≠", r"\infty": "∞"}
INLINE_MATH = re.compile(r"\$\$?([^$]{1,300}?)\$\$?")


def latex_plain(expr: str) -> str:
    """MinerU 把 14mm 写成 $14\\mathrm{mm}$、≥300 写成 $\\geqslant 300$：转回原件上的写法，检索才对得上。"""
    text = expr.replace("~", " ")  # LaTeX 里 ~ 是空格；\sim 才是波浪号，下面再换
    for _ in range(3):  # \mathrm{\mathbf{x}} 这类嵌套
        text = re.sub(r"\\(?:mathrm|text|textrm|mathbf|mathit|operatorname|rm|bf|it)\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\^\s*\{?\s*\\circ\s*\}?", "°", text)
    for command in sorted(LATEX_SYMBOLS, key=len, reverse=True):
        text = re.sub(re.escape(command) + r"(?![A-Za-z])", LATEX_SYMBOLS[command], text)
    text = re.sub(r"[_^]\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"[_^]\s*(\w)", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+", "", text).replace("{", "").replace("}", "").replace("\\", "")
    text = re.sub(r"\s*([≥≤<>±~×=·])\s*", r"\1", text)
    text = re.sub(r"(?<=\d)\s+(?=[A-Za-z°%μ])", "", text)  # 14 mm → 14mm，和原件一致
    text = re.sub(r"([φΦ])\s+(?=\d)", r"\1", text)  # φ 89 → φ89
    return re.sub(r"\s+", " ", text).strip()


def plain_latex(text: str) -> str:
    return INLINE_MATH.sub(lambda m: latex_plain(m.group(1)), text)


class TableGrid(HTMLParser):
    """MinerU 的表格是带 rowspan/colspan 的 HTML。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, int, int]]] = []
        self.row: list[tuple[str, int, int]] | None = None
        self.cell: list[str] | None = None
        self.span = (1, 1)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.flush_row()  # 上一行没写 </tr>：先收下，不丢
            self.row = []
        elif tag in ("td", "th"):
            self.flush_cell()  # 上一格没写 </td>
            values = dict(attrs)
            span = []
            for name in ("rowspan", "colspan"):
                try:
                    span.append(min(max(int(values.get(name) or 1), 1), 100))
                except ValueError:
                    span.append(1)
            self.cell, self.span = [], (span[0], span[1])
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self.flush_cell()
        elif tag in ("tr", "table"):
            self.flush_row()

    def close(self) -> None:
        super().close()
        self.flush_row()  # MinerU 偶尔给的 HTML 末行没有 </tr>

    def flush_cell(self) -> None:
        if self.cell is None:
            return
        if self.row is None:
            self.row = []
        self.row.append((re.sub(r"\s+", " ", "".join(self.cell)).strip(), *self.span))
        self.cell = None

    def flush_row(self) -> None:
        self.flush_cell()
        if self.row is not None:
            self.rows.append(self.row)
            self.row = None


def table_text(html: str) -> str:
    """合并单元格按格展开：值在所跨的每一行都重复，逐行读就知道每一行的完整取值。
    横跨多列的格子每行只写一次、标「（跨N列）」：原先每列都重复一遍，节点 16 的 OCR 文字里
    这类重复占了 68%（一行里同一个标准号连写 15 遍），白白占掉上下文。"""
    grid = TableGrid()
    grid.feed(html)
    grid.close()
    cells: dict[tuple[int, int], str | None] = {}  # None：被左边横跨的格子占住，输出时跳过
    for r, row in enumerate(grid.rows):
        c = 0
        for text, rowspan, colspan in row:
            while (r, c) in cells:
                c += 1
            shown = f"{text}（跨{colspan}列）" if colspan > 1 and text else text
            for dr in range(min(rowspan, len(grid.rows) - r)):  # rowspan 写多了不凭空多出几行
                for dc in range(colspan):
                    cells[(r + dr, c + dc)] = shown if dc == 0 else None
            c += colspan
    if not cells:
        return plain_latex(re.sub(r"<[^>]+>", " ", html))
    width = max(c for _, c in cells) + 1
    lines = []
    for r in range(max(r for r, _ in cells) + 1):
        values = [plain_latex(value) for c in range(width) if (value := cells.get((r, c), "")) is not None]
        while values and not values[-1]:
            values.pop()
        lines.append(" | ".join(values))
    return "\n".join(lines)


def first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def page_of(row: dict[str, Any]) -> int | None:
    try:
        number = int(row.get("pageNo"))
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


# 二维码、国徽这类没有字的图块，服务器偶尔把识别模型的英文说明当成文字返回（c 轮评测：“The image provided is a
# QR code. It does not contain any text…”，储罐、华润的证书页都有）。整行换成一个标记，别当成原件文字。
# 要同时像说明文字：英文标准里也有以 The image 开头的正文（The image quality indicator…），不能误伤。
MODEL_REPLY_LINE = re.compile(
    r"^[ \t]*(?:The (?:provided |given |uploaded )?(?:image|picture|figure)|This (?:image|picture|figure)|"
    r"I(?:'m| am) (?:sorry|unable)|Sorry,)\b"
    r"(?=[^\n]*(?:\bOCR\b|no (?:visible |readable )?text|not contain any text|empty string|guidelines|instructions|"
    r"cannot be extracted|no textual))[^\n]*$", re.MULTILINE)
MODEL_REPLY_MARK = "[图块：识别模型没读出字（二维码、国徽、图案等）]"


def strip_model_replies(text: str) -> str:
    return MODEL_REPLY_LINE.sub(MODEL_REPLY_MARK, text)


def server_ocr_pages(result: dict[str, Any]) -> dict[int, str]:
    """服务器 OCR 结果 → {物理页: 文字}：文字块按阅读顺序排；表格用原 HTML 展开合并单元格；印章、签名各记一行。"""
    pages: dict[int, list[tuple[int, str]]] = {}
    for fragment in result.get("fragments") or []:
        if not isinstance(fragment, dict) or page_of(fragment) is None:
            continue
        html = fragment.get("tableHtml")
        text = table_text(html) if isinstance(html, str) and "<t" in html else plain_latex(first_text(fragment, ("text",)))
        if text:
            order = fragment.get("readingOrder") if isinstance(fragment.get("readingOrder"), int) else 10 ** 6
            pages.setdefault(page_of(fragment), []).append((order, text))
    tail = 10 ** 7  # 印章、签名排在本页文字后面
    for seal in result.get("seals") or []:
        if isinstance(seal, dict) and page_of(seal):
            text = first_text(seal, ("text", "sealText", "recognizedText", "ocrText", "content"))
            pages.setdefault(page_of(seal), []).append((tail, f"[印章：{text or '服务器未读出章上的字'}]"))
    for signature in result.get("signatures") or []:
        if isinstance(signature, dict) and page_of(signature):
            text = first_text(signature, ("text", "name", "recognizedText", "content"))
            pages.setdefault(page_of(signature), []).append((tail + 1, f"[签名：{text or '有手写签名'}]"))
    count = result.get("pageCount") if isinstance(result.get("pageCount"), int) else 0
    count = max([count, *pages]) if pages else count
    return {n: strip_model_replies("\n".join(text for _, text in sorted(pages.get(n, []), key=lambda item: item[0])))
            for n in range(1, count + 1)}


def server_ocr_fields(result: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    for row in [*(result.get("fields") or []), *(result.get("documentFields") or [])]:
        if isinstance(row, dict):
            name = first_text(row, ("fieldName", "name", "label", "key"))
            value = row.get("fieldValue", row.get("value", row.get("normalizedValue")))
            if name and value not in (None, ""):
                fields.append({"name": name, "value": str(value), "pageNo": page_of(row)})
    return fields


SHA_CACHE: dict[tuple[str, int, int], str] = {}


def cached_sha(path: Path) -> str:
    info = path.stat()
    key = (str(path), info.st_size, info.st_mtime_ns)
    if key not in SHA_CACHE:
        SHA_CACHE[key] = sha256_file(path)
    return SHA_CACHE[key]


def ocr_key(relative: str) -> str:
    return safe_name(relative.replace("/", "__").replace(":", "_"))


def ocr_record_path(bundle: Path, relative: str) -> Path:
    return bundle / "ocr" / f"{ocr_key(relative)}.json"


def ocr_text_path(bundle: Path, relative: str) -> Path:
    return bundle / "text" / f"{safe_name(Path(relative).stem)}.ocr.txt"


def load_ocr(bundle: Path | None, relative: str | None, path: Path) -> dict[str, Any] | None:
    """本包里这份原件的 OCR 记录；原件改过（sha256 不同）就当没有。"""
    if bundle is None or relative is None:
        return None
    try:
        record = json.loads(ocr_record_path(bundle, relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("sha256") != cached_sha(path):
        return None
    return record


def ocr_page_map(record: dict[str, Any]) -> dict[int, str]:
    pages = {}
    for item in record.get("pages") or []:
        try:
            pages[int(item["page"])] = strip_model_replies(str(item.get("text") or ""))  # 旧记录里还留着模型的说明文字
        except (KeyError, TypeError, ValueError):
            continue
    return pages


OFFICE_MEDIA_DIRS = ("word/media/", "ppt/media/", "xl/media/")


def office_image_count(path: Path) -> int:
    """docx、pptx 里嵌的图片张数（c 轮评测：储罐焊工清单 docx 文末嵌着焊工证照片，文字层里看不到）。"""
    if path.suffix.lower() not in {".docx", ".pptx"}:  # 服务器 OCR 收这两种（xlsx 不收）
        return 0
    import zipfile
    try:
        with zipfile.ZipFile(path) as archive:
            return sum(1 for name in archive.namelist() if name.startswith(OFFICE_MEDIA_DIRS)
                       and Path(name).suffix.lower() in IMAGE_SUFFIXES | {".emf", ".wmf"})
    except (OSError, zipfile.BadZipFile):
        return 0


def ocr_has_table(text: str) -> bool:
    """OCR 文字里有一张展开了的表格（table_text 用“ | ”分格）：至少三行、每行至少三格。"""
    return sum(1 for line in text.splitlines() if line.count(" | ") >= 2) >= 3


def page_texts(bundle: Path | None, relative: str | None, path: Path) -> tuple[str, list[str], list[str], set[int]]:
    """(状态, 文字层每页, 用 OCR 补过的每页, 用了 OCR 的页)。没有 OCR 记录时后两份同文字层。
    状态 ocr 表示原件本身没有可取的文字，整份文字来自 OCR。"""
    status, layer = file_text(path)
    record = load_ocr(bundle, relative, path)
    if not record:
        return status, layer, layer, set()
    ocr = ocr_page_map(record)
    if status != "text" or not layer or all(len(t.strip()) < 20 for t in layer):
        count = max([*ocr, len(layer)]) if ocr else len(layer)
        return "ocr", layer, [ocr.get(n, "") for n in range(1, count + 1)], {n for n, t in ocr.items() if t.strip()}
    if path.suffix.lower() != ".pdf":
        # Office 文件（嵌了图片）：文字层只有一“页”，服务器转成 PDF 后按页识别。OCR 文字整份接在文字层后面。
        extra = "\n\n".join(text for _, text in sorted(ocr.items()) if text.strip())
        if not extra:
            return status, layer, layer, set()
        return status, layer, [f"{layer[0].strip()}\n\n（以下是服务器 OCR 文字，含文档里嵌的图片）\n{extra}"], {1}
    merged, used = list(layer), set()
    # 字不少但被大图占满的页也要 OCR 文字；只有 OCR 补到了这种页才去开 PDF 数图片。
    wide = any(1 <= n <= len(layer) and OCR_FILL_BELOW <= len(layer[n - 1].strip()) < SCAN_TEXT_BELOW for n in ocr)
    scanned = scan_pages(path, layer) if wide else set()
    # 文字层靠不住的页（认错的识别文字、扫描件自带的隐形识别文字、拆散的表格）只给 OCR 文字：两份并排只会读乱。
    shaky = layer_problems(path, layer, [n for n, text in ocr.items() if text.strip()])
    if relative and relative.startswith("standard:"):
        # 标准的表格页以 OCR 版为准：文字层常丢列（c 轮评测：NB/T 47014-2023 第 41 页表 6 文字层缺了最大值一列），
        # 又看不出来。只对标准这么做：工程资料的数字文字层比 OCR 准。
        shaky.update({n: "table" for n, text in ocr.items() if n not in shaky and ocr_has_table(text)})
    extras: dict[int, list[list[str]]] = {}
    whole = norm_cell("".join(layer))
    for number, text in sorted(ocr.items()):
        if not (1 <= number <= len(layer)) or not text.strip():
            continue
        if number in shaky:
            merged[number - 1] = text
            used.add(number)
        elif len(layer[number - 1].strip()) < OCR_FILL_BELOW or number in scanned:
            merged[number - 1] = f"{layer[number - 1].strip()}\n{text}".strip()
            used.add(number)
        elif not (relative or "").startswith("standard:"):
            extras[number] = ocr_only_cells(layer[number - 1], text, whole)
    # 文字层齐的页只补文字层没有的格（10-29 服务器节点评测：储罐施工图是带文字层的 PDF，设计许可章、出图专用章、
    # 签字栏人名都是图片，只在 OCR 里，text、search 读不到）。很多页都补出的中英双语栏名（“版次REV.”）只在第一页给；
    # 章上的字、签字栏人名每页照给，逐页核盖章、签字要用。
    seen = Counter(cell for lines in extras.values() for cell in {norm_cell(c) for line in lines for c in line})
    boiler = {cell for cell, pages in seen.items() if pages >= max(OCR_BOILERPLATE_PAGES, len(extras) / 3)
              and re.search(r"[A-Za-z]", cell) and not re.search(r"\d", cell)}
    shown: set[str] = set()
    for number, lines in extras.items():
        kept = []
        for line in lines:
            cells = [c for c in line if norm_cell(c) not in boiler or norm_cell(c) not in shown]
            shown.update(norm_cell(c) for c in cells)
            if cells:
                kept.append(" | ".join(cells))
        if kept:
            merged[number - 1] = f"{layer[number - 1].strip()}\n\n{OCR_SUPPLEMENT_MARK}\n" + "\n".join(kept)
    return status, layer, merged, used


OCR_SUPPLEMENT_MARK = "（以下是服务器 OCR 读出、文字层里没有的字：印章、签名、图签和图片上的字；可能有误读，数字和文字层不同时以文字层为准）"
OCR_SPAN_TAG = re.compile(r"（跨\d+[列行]）")
OCR_BOILERPLATE_PAGES = 5  # 同一份文件至少这么多页（且三分之一以上）都补出的同一个双语栏名，只在第一页给
OCR_CELL_SHINGLE = 6  # 长格按 6 字一段、隔 3 字取段，六成段落在文字层里就算文字层有（OCR 认错几个字、断句不同）


def norm_cell(cell: str) -> str:
    return re.sub(r"[\W_]+", "", cell)


def ocr_only_cells(layer: str, text: str, whole: str = "") -> list[list[str]]:
    """OCR 文字里文字层没有的格，按 OCR 的行分组。比较时去掉空白、标点和“（跨N列）”：表格在 OCR 里按格展开，
    和文字层的写法不同，逐行比几乎每行都算多出来的。长格还和整份文件的文字层（whole，已 norm_cell）比：
    服务器 OCR 会把后面几页的字记到前一页（10-29 储罐施工图第 4 页的 OCR 含第 4–11 页的设计说明，第 5–11 页是空的）。"""
    flat = norm_cell(layer)

    def in_layer(cell: str) -> bool:
        if len(cell) < 2:
            return True  # 单字、勾选符号：补了也看不出是哪一格
        if len(cell) < 2 * OCR_CELL_SHINGLE:
            return cell in flat  # 短格（签字栏人名）只和本页比：别页文字层有同一个名字不等于本页签了
        parts = [cell[i:i + OCR_CELL_SHINGLE] for i in range(0, len(cell) - OCR_CELL_SHINGLE + 1, OCR_CELL_SHINGLE // 2)]
        return any(sum(part in source for part in parts) >= 0.6 * len(parts) for source in (flat, whole) if source)

    lines, seen = [], set()
    for line in OCR_SPAN_TAG.sub("", text).splitlines():
        cells = []
        for cell in line.split(" | "):
            key = norm_cell(cell)
            if key not in seen and not in_layer(key):  # 同一页里重复的格（表格一列的“III级”、两枚章读出同一行）只给一次
                seen.add(key)
                cells.append(cell.strip())
        if cells:
            lines.append(cells)
    return lines


OCR_SPARSE_BELOW = 40  # OCR 只读出这么几个字的页
DRAWING_LONG_SIDE = 1150  # PDF 页长边（点）：A4 是 842、A3 是 1191；比 A4 大得多的多是图纸
OCR_REPEAT_RUN = re.compile(r"([一-鿿A-Za-z0-9])\1{29,}")
OCR_REPEAT_RATIO = 0.07  # 压缩后不到原长的 7%：同一段字反复出现（评测里一张配管平面图把一句法院名重复了 200 次）
OCR_QUALITY_LABELS = {"blank": "没读出字", "repeat": "识别跑飞（同一段字反复出现，内容不可信）", "sparse": "只读出几个字",
                      "drawing": "是大幅面图纸（图签、表格读得出，图上分散的标注常读不全）"}


OCR_REPEAT_LINE_CHARS = 40  # 这么长的一整行
OCR_REPEAT_LINE_TIMES = 5  # 在同一页出现这么多次：c 轮评测里贵州强度计算书一行 405 字重复 10 次、储罐图纸图签重复 8 次；
# 68 份 OCR 记录里正常的表格行（“检查结果 合格”之类）最多是 14 字重复 13 次，长行最多重复 3 次


def ocr_degenerate(flat: str, text: str = "") -> bool:
    import zlib
    if OCR_REPEAT_RUN.search(flat):
        return True
    lines = Counter("".join(line.split()) for line in text.splitlines())
    if any(len(line) >= OCR_REPEAT_LINE_CHARS and times >= OCR_REPEAT_LINE_TIMES for line, times in lines.items()):
        return True
    raw = flat.encode("utf-8")
    return len(raw) >= 3000 and len(zlib.compress(raw, 9)) < OCR_REPEAT_RATIO * len(raw)


def ocr_quality(bundle: Path | None, relative: str | None, path: Path, numbers: Any = None) -> dict[int, str]:
    """要靠 OCR 才有字的页里，OCR 读得不全或读坏的页 → OCR_QUALITY_LABELS 的键。有文字层的正常页 OCR 是空的不算。
    “没读出字”“只读出几个字”“图纸”的页上找不到某个事实，不等于原件上没有。"""
    record = load_ocr(bundle, relative, path)
    if not record:
        return {}
    ocr = ocr_page_map(record)
    status, layer = file_text(path)
    if status != "text" or not layer or all(len(t.strip()) < 20 for t in layer):
        needed = set(ocr) | set(range(1, len(layer) + 1))
    else:
        thin = {n for n, text in enumerate(layer, start=1) if len(text.strip()) < OCR_FILL_BELOW}  # 合并时也用 OCR 补的页
        needed = scan_pages(path, layer) | set(layer_problems(path, layer)) | thin
    if numbers is not None:
        needed &= set(numbers)
    sides: dict[int, float] = {}
    if path.suffix.lower() == ".pdf" and needed:
        try:
            with quiet_fitz().open(path) as doc:
                sides = {n: max(doc[n - 1].rect.width, doc[n - 1].rect.height) for n in needed if 1 <= n <= doc.page_count}
        except Exception:  # noqa: BLE001 -- 打不开就不判图纸
            sides = {}
    problems: dict[int, str] = {}
    for n in sorted(needed):
        flat = "".join(ocr.get(n, "").split())
        if not flat:
            problems[n] = "blank"
        elif ocr_degenerate(flat, ocr.get(n, "")):
            problems[n] = "repeat"
        elif len(flat) < OCR_SPARSE_BELOW:
            problems[n] = "sparse"
        elif sides.get(n, 0) >= DRAWING_LONG_SIDE:
            problems[n] = "drawing"
    return problems


def bundle_relative(bundle: Path, path: Path) -> str | None:
    """资料包里的原件写 files/…；仓库里的标准原件写 standard:rules/…，和报告出处的写法一致。"""
    resolved = path.resolve()
    if resolved.is_relative_to(bundle.resolve()):
        return str(resolved.relative_to(bundle.resolve()))
    root = repo_root().resolve()
    if resolved.is_relative_to(root):
        return "standard:" + str(resolved.relative_to(root))
    return None


def ocr_reason(path: Path) -> str | None:
    """这份原件为什么要 OCR；不需要（文字层齐）或服务器收不了时返回 None。"""
    status, layer = file_text(path)
    if status == "pymupdf_missing":
        raise ClientError("pymupdfMissing", "需要 PyMuPDF：用 backend/.venv/bin/python 运行本命令，或 pip install pymupdf。")
    if status == "image":
        return "图片"
    if status == "office_unreadable" and path.suffix.lower() in OCR_UPLOAD_SUFFIXES:
        return "转不出文字的 Office 文件"
    if status == "text" and path.suffix.lower() in OCR_UPLOAD_SUFFIXES and (images := office_image_count(path)):
        return f"Office 文件里嵌了 {images} 张图片（图片里的字文字层读不到）"
    if status == "text" and path.suffix.lower() == ".pdf":
        empty = sorted(scan_pages(path, layer))
        if empty:
            return "扫描件" if len(empty) == len(layer) else f"第 {page_ranges(empty)} 页是扫描页"
    return None


# MinerU 收不了太大的照片：2026-10-29 生产实测，GDLNG-002 的 5712×3213 手机照片（15–20MB）13 张全部
# MINERU_JOB_FAILED，同一批 4032×2268 的都识别成功。长边超过这个值的图片先等比缩小再上传，拍一页 A4 仍有约 340 dpi。
OCR_MAX_IMAGE_SIDE = 4000


def upload_payload(path: Path, sha: str) -> tuple[str, bytes]:
    """上传名只用哈希：文件名里常有人名，没必要给出去。服务器不收的图片格式先转 PNG；太大的照片先缩小（存 JPEG）。"""
    suffix = path.suffix.lower()
    if suffix in OCR_UPLOAD_SUFFIXES and suffix not in IMAGE_SUFFIXES:
        return f"{sha[:16]}{suffix}", path.read_bytes()
    if suffix not in IMAGE_SUFFIXES:
        raise ClientError("unsupportedFile", f"{path.name}：服务器 OCR 不收这种格式，请用户转成 PDF。")
    try:
        fitz = quiet_fitz()
        pix = fitz.Pixmap(str(path))
    except Exception:  # noqa: BLE001 -- 读不出尺寸：服务器收的格式照原样传，让服务器判断
        if suffix in OCR_UPLOAD_SUFFIXES:
            return f"{sha[:16]}{suffix}", path.read_bytes()
        raise ClientError("unsupportedFile", f"{path.name}：服务器 OCR 不收这种图片格式，也转不成 PNG。") from None
    try:
        side = max(pix.width, pix.height)
        if side <= OCR_MAX_IMAGE_SIDE and suffix in OCR_UPLOAD_SUFFIXES:
            return f"{sha[:16]}{suffix}", path.read_bytes()
        if pix.alpha or pix.n > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if side > OCR_MAX_IMAGE_SIDE:
            scale = OCR_MAX_IMAGE_SIDE / side
            pix = fitz.Pixmap(pix, max(1, round(pix.width * scale)), max(1, round(pix.height * scale)), None)
            return f"{sha[:16]}.jpg", pix.tobytes("jpg", jpg_quality=92)
        return f"{sha[:16]}.png", pix.tobytes("png")
    except Exception:  # noqa: BLE001 -- 转不了就跳过这份，不让整批失败
        raise ClientError("unsupportedFile", f"{path.name}：服务器 OCR 不收这种图片格式，也转不成 PNG。") from None


def check_egress(bundle: Path, manifest: dict[str, Any], allowed: bool) -> None:
    """服务器节点的资料本来就在服务器上、服务器自己做过 OCR；本地资料第一次上传要用户点头。"""
    marker = bundle / "ocr" / "egress-approved.json"
    if manifest.get("source") == "server" or marker.exists():
        return
    if not allowed:
        raise ClientError("egressNotApproved", "本地资料包：ocr 会把原件上传到 AIcheck 服务器（服务器会留存原件，并交 MinerU、千问识别），"
                                               "里面可能有身份证号等个人信息。先问用户是否同意；同意后加 --allow-egress（每个资料包只需一次）。")
    write_private(marker, dump({"approvedAt": now(), "note": "用户同意把本资料包的原件上传到 AIcheck 服务器做 OCR"}))


CODE_MISREAD_NOTE = ("焊工证上的项目代号 OCR 常认错字母（实测 MinerU 把 GTAW 读成 CTAF、Fe 读成 Pe、6G 读成 60，"
                     "千问会改大小写），代号以 cert-registry 查到的登记项目（czxm）为准")


def ocr_text(record: dict[str, Any], problems: dict[int, str] | None = None) -> str:
    provider = "千问（MinerU 排队超时后服务器改用）" if record.get("provider") == "qwen" else "MinerU"
    head = (f"（服务器 OCR 文字，识别：{provider}；不是原件文字层。表格已按格展开：合并单元格的值在所跨的每一行重复，"
            "横跨多列的每行只写一次并标（跨N列）；"
            f"[印章：…]、[签名：…] 是服务器识别的印章、签名。{CODE_MISREAD_NOTE}。"
            "页头标了“OCR 读得不全”的页，找不到某个事实不等于原件上没有。）")
    marks = {n: f"（OCR 读得不全：{OCR_QUALITY_LABELS[kind]}）" for n, kind in (problems or {}).items()}
    body = "\n\n".join(f"--- 第 {p['page']} 页{marks.get(p['page'], '')} ---\n{strip_model_replies(str(p.get('text') or ''))}"
                       for p in record.get("pages") or [])
    fields = record.get("fields") or []
    if fields:
        body += "\n\n--- 服务器抽取的字段（只作线索，以上面的页文字为准） ---\n" + "\n".join(
            f"{f['name']}：{f['value']}" + (f"（第 {f['pageNo']} 页）" if f.get("pageNo") else "") for f in fields)
    return f"{head}\n\n{body}\n"


def store_ocr(bundle: Path, item: dict[str, Any], status: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    pages = server_ocr_pages(result)
    processing = result.get("processing") if isinstance(result.get("processing"), dict) else {}
    provider = str(processing.get("provider") or status.get("provider") or "mineru")
    record = {"file": item["file"], "sha256": item["sha256"], "engine": "aicheck-server", "provider": provider,
              "renderVersion": OCR_RENDER_VERSION,
              "fallback": processing.get("fallback") or status.get("fallback"), "jobId": item["jobId"],
              "quality": result.get("quality"), "documentType": result.get("documentType"), "at": now(),
              "pages": [{"page": n, "text": t} for n, t in sorted(pages.items())], "fields": server_ocr_fields(result)}
    write_private(ocr_record_path(bundle, item["file"]), dump(record))  # 原文（含完整证号），只给脚本回查用
    target = ocr_text_path(bundle, item["file"])
    source = target_path(bundle, item["file"])
    problems = ocr_quality(bundle, item["file"], source) if source.is_file() else {}
    write_private(target, mask_ids(ocr_text(record, problems)))
    # 只算要靠 OCR 的页里没读出字的：有文字层的页 OCR 是空的不要紧（c 轮评测里把有文字层的页也算进来，agent 读成整份没字）
    blank = sorted(n for n, kind in problems.items() if kind == "blank")
    return {"file": item["file"], "pages": len(pages), "chars": sum(len(t) for t in pages.values()), "provider": provider,
            "saved": str(target), **({"blankPages": page_ranges(blank)} if blank else {})}


def target_path(bundle: Path, relative: str) -> Path:
    """OCR 记录里的 file → 原件：资料包里的写 files/…，仓库里的标准原件写 standard:rules/…。"""
    return repo_root() / relative.removeprefix("standard:") if relative.startswith("standard:") else bundle / relative


def mark_rerender_failed(bundle: Path, relative: str) -> None:
    target = ocr_record_path(bundle, relative)
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    write_private(target, dump({**record, "rerenderFailed": now()}))


def ocr_targets(bundle: Path, manifest: dict[str, Any], files: list[str] | None) -> tuple[list[tuple[str, Path]], list[dict[str, Any]]]:
    skipped: list[dict[str, Any]] = []
    if not files:
        return [(item["path"], bundle / item["path"]) for item in manifest.get("files") or []
                if ocr_reason(bundle / item["path"])], skipped
    targets = []
    for name in files:
        path = repo_root() / name.removeprefix("standard:") if name.startswith("standard:") else bundle / name
        if not path.exists() and Path(name).expanduser().exists():
            path = Path(name).expanduser()
        relative = bundle_relative(bundle, path) if path.is_file() else None
        if relative is None:
            skipped.append({"file": name, "reason": "找不到，或不在资料包、仓库里"})
        else:
            targets.append((relative, path.resolve()))
    return targets, skipped


# 服务器暂时不可用：API 每约半小时被内存守卫重启一次（502/503/504 或连不上，约一分钟），不能因此中止整个 OCR。
OCR_TRANSIENT = GATEWAY_ERRORS | {"unreachable"}
OCR_RETRY_PAUSES = (10, 20, 30)  # 上传遇到上面的错误时的等待；轮询不重试，下一轮再查就是退避


def is_transient(exc: ClientError) -> bool:
    return exc.code in OCR_TRANSIENT


def with_server_retry(call: Any, deadline: float | None = None) -> Any:
    """服务器暂时不可用时按 OCR_RETRY_PAUSES 重试几次；仍不行（或等下去就过了 deadline）就把最后一次的错误抛出去，
    由调用方决定怎么办。"""
    for pause in (*OCR_RETRY_PAUSES, None):
        try:
            return call()
        except ClientError as exc:
            if not is_transient(exc) or pause is None or (deadline is not None and time.monotonic() + pause > deadline):
                raise
            time.sleep(pause)


def ocr_attempts_path(bundle: Path) -> Path:
    return bundle / "ocr" / "attempts.json"


def load_attempts(bundle: Path) -> dict[str, int]:
    """{原件哈希: 已经用掉的重试次数}。服务器的幂等记录不过期：同一个键永远拿回第一次建的任务，
    任务失败了也一样，所以重试必须换键。"""
    try:
        data = json.loads(ocr_attempts_path(bundle).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, int) and v > 0} if isinstance(data, dict) else {}


def save_attempts(bundle: Path, attempts: dict[str, int]) -> None:
    write_private(ocr_attempts_path(bundle), dump(attempts))


def idempotency_key(sha: str, attempt: int) -> str:
    base = f"aicheck-node-audit-{sha[:48]}"
    return base if attempt <= 0 else f"{base}-r{attempt}"


def record_failed_attempt(bundle: Path, attempts: dict[str, int], item: dict[str, Any]) -> None:
    """任务失败、取消或完成了却没有结果：下次上传换新键，才会建新任务，而不是拿回这个失败的。"""
    sha = item["sha256"]
    attempts[sha] = max(attempts.get(sha, 0), int(item.get("attempt") or 0) + 1)
    save_attempts(bundle, attempts)


# 整条 ocr 命令（上传＋查状态）的时长上限：agent 跑一条命令最长 10 分钟，超了被杀掉就白等了（评测里整包 ocr
# 一次要 10–24 分钟）。到点就停，没传完、没查完的下次接着来：pending.json 记着任务号，不重传。
# 每个请求的超时都按剩余时间截断（c 轮评测里 --timeout 480 的一条实际跑了 10.2 分钟：大文件上传一次最多等 5 分钟，
# 服务器重启时还要退避重试）；只有保证进展的第一份上传、第一次查状态给到 OCR_FIRST_REQUEST 秒。
OCR_BUDGET_CAP = 420
OCR_FIRST_REQUEST = 60
OCR_MIN_REQUEST = 20  # 剩这么点时间就不再开始新的上传
OCR_STALE_SKEW = 120  # 秒：任务建立时间早于本次命令开始这么久以上，才算上次留下的（容忍本机和服务器的钟差）
OCR_SERVER_TZ = timezone(timedelta(hours=8))  # 服务器的 createdAt 是北京时间、不带时区（libs/contracts/responses.server_time）
# 服务器调 MinerU 被拒或没配好：是服务器那边的令牌、配置问题，不是本机的登录令牌。2026-10-28 服务器的 MinerU 令牌过期，
# 31 个任务全是 HTTP_401，子代理当成自己的令牌失效。
ENGINE_AUTH_CODES = {"HTTP_401", "HTTP_403", "MINERU_NOT_CONFIGURED", "MINERU_CONFIG_INVALID", "MINERU_MODEL_INVALID"}
ENGINE_BUSY_CODES = {"HTTP_429"}


def failure_reason(state: str, status: dict[str, Any]) -> tuple[str, str | None]:
    """(给助手看的原因, 类别)。类别 engineAuth：服务器的 MinerU 令牌或配置坏了；engineBusy：MinerU 限流或额度用完。"""
    codes = [str(d.get("code")) for d in status.get("diagnostics") or [] if isinstance(d, dict) and d.get("code")]
    reason = f"服务器 OCR {state}" + (f"：{'、'.join(codes)}" if codes else "")
    if ENGINE_AUTH_CODES & set(codes):
        return (reason + "（这次新建的任务服务器调 MinerU 也被拒或没配好：是服务器那边 MinerU 的令牌或配置问题，不是你的登录令牌，"
                         "重新 login 没用）", "engineAuth")
    if ENGINE_BUSY_CODES & set(codes):
        return reason + "（MinerU 限流或额度用完）", "engineBusy"
    return reason, None


def job_created_before(status: dict[str, Any], moment: float) -> bool | None:
    """服务器上这个任务是不是在 moment（本机时间戳）之前就建好的（上次留下的）；看不出来返回 None。"""
    raw = status.get("createdAt")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        created = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=OCR_SERVER_TZ)
    return created.timestamp() < moment - OCR_STALE_SKEW


def cmd_ocr(args: argparse.Namespace) -> Any:
    started_at = time.time()
    # --timeout 是整条命令的时长（上传＋查状态）。每次至少传一份、查一份，保证重跑总有进展。
    clock = {"end": time.monotonic() + min(max(args.timeout, 0), OCR_BUDGET_CAP)}

    def time_left() -> float:
        return clock["end"] - time.monotonic()

    def request_timeout(normal: float, first: bool = False) -> float:
        """这个请求最多等多久：不超过剩余时间；保证进展的第一个请求至少给 OCR_FIRST_REQUEST 秒。"""
        return min(normal, max(time_left(), OCR_FIRST_REQUEST if first else 5.0))

    bundle = Path(args.bundle).expanduser().resolve()
    if not (bundle / "bundle.json").exists():
        raise ClientError("bundleMissing", f"{bundle} 不是资料包（没有 bundle.json）。")
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    api = Api(args.base_url)
    if not api.token:
        raise ClientError("loginRequired", f"OCR 由服务器做，要监检账号令牌{LOGIN_HINT}。")
    targets, skipped = ocr_targets(bundle, manifest, args.files)
    if any(not relative.startswith("standard:") for relative, _ in targets):
        check_egress(bundle, manifest, args.allow_egress)
    state_path = bundle / "ocr" / "pending.json"
    try:
        pending = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pending = []
    waiting = {item["sha256"] for item in pending}
    attempts = load_attempts(bundle)
    cached, failed, rerendered, deferred, retried = [], [], [], [], []
    not_uploaded: list[str] = []  # 服务器暂时不可用、没传上去的：不是识别失败，稍后重跑接着传
    server_down = ""  # 上传时服务器一直不可用：后面的文件不再试，别一份份耗时间

    def submit(relative: str, sha: str, attempt: int, payload: tuple[str, bytes], first: bool = False,
               **extra: Any) -> dict[str, Any] | None:
        """上传一份，返回待查的任务；服务器一直不可用或到点没传完返回 None（已记进 not_uploaded 或 deferred）。"""
        nonlocal server_down
        name, content = payload
        # 同一份原件同一个键：网关重试、重跑都拿回原来的任务，不会重复识别。要重做已完成的文件（--force）
        # 或上次失败了，就换键（r1、r2…）：服务器的幂等记录不过期，同键永远是第一次的那个任务。
        # 键按实际上传的字节算：原样传的就是原件哈希；缩小、转 PNG 的换了内容，用原件哈希的键会被拒（40905，
        # 2026-10-29 评测：早上原尺寸传过的照片，缩小后再传永远拿不到 OCR）。
        metadata = base64.urlsafe_b64encode(json.dumps({"fileName": name, "options": {"language": "ch"}}).encode()).decode()
        key = idempotency_key(hashlib.sha256(content).hexdigest(), attempt)
        headers = {"Content-Type": "application/octet-stream", "Idempotency-Key": key,
                   "X-AICheck-Ocr-Metadata-B64": metadata}
        try:
            data = with_server_retry(lambda: api.upload("/internal/ocr/mineru/tasks/upload", content, headers=headers,
                                                        timeout=request_timeout(300.0, first)), clock["end"])
        except ClientError as exc:
            if not is_transient(exc):
                raise
            # 请求可能已经在服务器上建了任务：键没变，稍后重跑会拿回它，不会重复建，所以这里不动重试计数。
            if time_left() <= 1 and not first:
                deferred.append(relative)  # 是到点了、请求被截断，不是服务器坏了
                return None
            server_down = f"服务器暂时不可用（{exc.code}），没有上传：等一两分钟重跑同一条 ocr 命令，键不变，不会重复建任务。"
            not_uploaded.append(relative)
            return None
        job_id = str((data or {}).get("jobId") or "")
        if not job_id:
            raise ClientError("badResponse", "服务器没有返回 OCR 任务号。")
        if attempt != attempts.get(sha, 0):
            attempts[sha] = attempt
            save_attempts(bundle, attempts)
        return {"file": relative, "sha256": sha, "jobId": job_id, "attempt": attempt, "submittedAt": now(), **extra}

    uploaded = 0
    for relative, path in targets:
        finished = load_ocr(bundle, relative, path)
        if finished and not args.force:
            if (finished.get("renderVersion") != OCR_RENDER_VERSION and finished.get("jobId")
                    and not finished.get("rerenderFailed") and finished["sha256"] not in waiting):
                # 旧排版：服务器上那个任务已经识别完，只取一次结果重排，不重新上传、不重新识别。
                pending.append({"file": relative, "sha256": finished["sha256"], "jobId": finished["jobId"],
                                "attempt": attempts.get(finished["sha256"], 0), "submittedAt": now(), "rerender": True})
                rerendered.append(relative)
            else:
                cached.append(relative)
            continue
        sha = cached_sha(path)
        if sha in waiting:
            continue  # 上次交了还没出结果：接着等，不重传
        if server_down:
            not_uploaded.append(relative)
            continue
        if path.stat().st_size > OCR_MAX_BYTES:
            skipped.append({"file": relative, "reason": "超过 100MB，服务器 OCR 不收"})
            continue
        if (uploaded or deferred) and time_left() < OCR_MIN_REQUEST:
            deferred.append(relative)  # 到点了：下次再传
            continue
        try:
            payload = upload_payload(path, sha)
        except ClientError as exc:
            skipped.append({"file": relative, "reason": exc.message})
            continue
        item = submit(relative, sha, attempts.get(sha, 0) + (1 if finished else 0), payload, first=not (uploaded or deferred))
        if item:
            pending.append(item)
            uploaded += 1
            write_private(state_path, dump(pending))
    if server_down:
        clock["end"] = min(clock["end"], time.monotonic())  # 服务器不可用：查一下就走，不干等
    done, kinds = [], set()

    def give_up(item: dict[str, Any], reason: str, kind: str | None = None) -> None:
        if item.get("rerender"):
            # 只是重排没成：旧排版的文字照样能用，记下别每次重试；不动重试计数。
            mark_rerender_failed(bundle, item["file"])
            failed.append({"file": item["file"], "reason": f"{reason}；旧排版没能重排，旧的 OCR 文字照样能用，要新排版就加 --force 重新识别",
                           "rerender": True})
            return
        entry: dict[str, Any] = {"file": item["file"], "reason": reason}
        if item.get("retried"):
            entry["autoRetried"] = True  # 这次已当场换新任务重试过一次
        if kind:
            entry["kind"] = kind
            kinds.add(kind)
        failed.append(entry)
        record_failed_attempt(bundle, attempts, item)

    def retry_now(item: dict[str, Any]) -> dict[str, Any] | str | None:
        """失败的任务当场换新键重传一次（常见的是上次留下的失败任务：同一个键永远拿回它）。
        返回新任务；这次来不及重传（到点了、服务器暂时不可用）返回 "later"：重试计数已加，下次重跑用新键传，
        不算失败；不该或不能重试返回 None。"""
        path = target_path(bundle, item["file"])
        if (item.get("rerender") or item.get("retried")
                or not path.is_file() or cached_sha(path) != item["sha256"]):
            return None
        try:
            payload = upload_payload(path, item["sha256"])
        except ClientError:
            return None
        record_failed_attempt(bundle, attempts, item)
        if server_down:
            not_uploaded.append(item["file"])
            return "later"
        if time_left() < OCR_MIN_REQUEST:
            deferred.append(item["file"])
            return "later"
        return submit(item["file"], item["sha256"], attempts[item["sha256"]], payload, retried=True) or "later"

    first_round, unpolled = True, []
    while pending:
        left, waits, unpolled = [], [], []
        for index, item in enumerate(pending):
            if time_left() <= 0 and not (first_round and index == 0):
                unpolled = pending[index:]  # 到点了：这些这次没查，排到前面，下次先查
                break
            path = f"/internal/ocr/mineru/tasks/{parse.quote(item['jobId'], safe='')}"
            first_poll = first_round and index == 0
            try:
                status = api.call("GET", path, auth=True, timeout=request_timeout(90.0, first_poll)) or {}
                state = str(status.get("status") or "")
                result = (api.call("GET", f"{path}/result", auth=True, timeout=request_timeout(120.0, first_poll)) or {}
                          if state == "success" else {})
            except ClientError as exc:
                if exc.code in {"loginRequired", "forbidden"}:
                    # 令牌过期或无权：任务都还在服务器上，先记下没查完的，重新授权后重跑同一条 ocr 接着等。
                    write_private(state_path, dump([*left, *pending[index:]]))
                    raise
                if not is_transient(exc):
                    # 任务被服务器清理（notFound）或别的错误：这一份算失败，下次重跑换新键重新上传，不再卡在这个任务上。
                    give_up(item, f"查 OCR 任务出错（{exc.code} {exc.message}）")
                    continue
                if time_left() <= 1 and not first_poll:
                    unpolled = [item, *pending[index + 1:]]  # 是到点了、请求被截断：这些这次没查完，下次先查
                    break
                # 服务器重启中：不是识别失败。任务还在，记着，下一轮（或下次重跑）再查。
                left.append({**item, "state": "unreachable", "message": f"服务器暂时不可用（{exc.code}），稍后接着等"})
                continue
            if state == "success":
                if result.get("resultAvailable") is False:
                    give_up(item, "服务器说识别完成，但没有结果")
                else:
                    done.append(store_ocr(bundle, item, status, result))
            elif state in OCR_FAILED:
                reason, kind = failure_reason(state, status)
                # 服务器的 MinerU 令牌坏了、任务又是这次刚建的：当场重传还是一样失败，不浪费上传。
                # 上次留下的失败任务（c 轮评测 3 个 agent 碰到 10-28 事故遗留的 401 任务）不算：换新键重传，
                # 这次来不及就留到下次，不报成令牌坏了。
                again = None if kind == "engineAuth" and job_created_before(status, started_at) is False else retry_now(item)
                if isinstance(again, dict):
                    retried.append(item["file"])
                    left.append(again)
                elif again is None:
                    give_up(item, reason, kind)
            else:
                left.append({**item, "state": state or "unknown", "provider": status.get("provider"),
                             "message": status.get("statusMessage")})
                if isinstance(status.get("recommendedPollSeconds"), int):
                    waits.append(status["recommendedPollSeconds"])
        pending = unpolled + left
        if pending:
            write_private(state_path, dump(pending))
        else:
            state_path.unlink(missing_ok=True)
        first_round = False
        pause = max([OCR_POLL_SECONDS, *waits])
        if not pending or unpolled or time_left() < pause:
            break
        time.sleep(pause)
    result: dict[str, Any] = {"bundle": str(bundle), "done": done, "cached": cached, "skipped": skipped, "failed": failed}
    if rerendered:
        result["rerendered"] = rerendered  # 旧排版的 OCR 记录，按新排版重排（没有重新识别）
    if retried:
        result["retried"] = retried  # 任务失败，这次已当场换新任务重传（新任务在 pending 里，标 retried）；不是失败
    deferred = list(dict.fromkeys(f for f in deferred if f not in not_uploaded))
    if deferred:
        result["notSubmitted"] = deferred
    if not_uploaded:
        result["notUploaded"] = list(dict.fromkeys(not_uploaded))
    quality, unreadable = {}, []
    for relative in [*(d["file"] for d in done), *cached]:
        source = target_path(bundle, relative)
        problems = ocr_quality(bundle, relative, source) if source.is_file() else {}
        if problems:
            quality[relative] = problem_summary(problems, OCR_QUALITY_LABELS)
            record = load_ocr(bundle, relative, source)
            status, layer = file_text(source)
            no_layer = status != "text" or all(len(t.strip()) < 20 for t in layer)
            if record and no_layer and not any(str(p.get("text") or "").strip() for p in record.get("pages") or []):
                unreadable.append(relative)  # 原件没有文字层、OCR 也一个字没读出
    if quality:
        result["qualityWarnings"] = quality
    total = len(targets) - len([s for s in skipped if s.get("file") in {r for r, _ in targets}])
    result["progress"] = f"{len(cached) + len(done)}/{total} 份已有 OCR 文字"
    steps = []
    if deferred:
        steps.append(f"到点了（--timeout 是整条命令的时长，最多 {OCR_BUDGET_CAP} 秒），还有 {len(deferred)} 份没上传（notSubmitted）："
                     "再跑同一条 ocr 命令接着传、接着等，已传的不重传。")
    if pending:
        # 同一份文件只列一次：换新任务重传的那份标 retried（只有一个任务在等）。
        rows: dict[str, dict[str, Any]] = {}
        for i in pending:
            rows[str(i.get("file"))] = {"file": i.get("file"), "state": i.get("state") or "submitted", "provider": i.get("provider"),
                                        "message": i.get("message"), **({"retried": True} if i.get("retried") else {})}
        result["pending"] = list(rows.values())
        if any(i.get("state") == "unreachable" for i in pending):
            steps.append("服务器暂时不可用（API 每约半小时重启一次，约一分钟）：等一两分钟再跑同一条 ocr 命令接着等，任务还在，不会重新上传。")
        else:
            steps.append("服务器还在识别" + (f"（{len(unpolled)} 份这次没来得及查状态）" if unpolled else "")
                         + "：不用另外等，直接再跑同一条 ocr 命令接着等（命令里会按服务器建议的间隔查），不会重新上传。")
    hard = [f for f in failed if not f.get("rerender")]
    if "engineAuth" in kinds:
        steps.append("这次新建的 OCR 任务服务器调 MinerU 也被拒（HTTP_401 等）：可以再原样跑一次同一条 ocr 确认；仍是 engineAuth，"
                     "就是服务器那边 MinerU 的令牌失效或没配好，不是你的登录过期，重新 login 没用。"
                     "告诉用户请管理员检查服务器的 MinerU 令牌，修好后再跑同一条 ocr（会换新任务）；在此之前这些文件相关的事实交人工确认，写进 limitations。")
    if "engineBusy" in kinds:
        steps.append("MinerU 限流或额度用完：过半小时再跑同一条 ocr（会换新任务）；仍不行就写进 limitations，相关事实交人工确认。")
    others = [f for f in hard if not f.get("kind")]
    if others and all(f.get("autoRetried") for f in others):
        steps.append("失败的文件这次已当场换新任务重试过一次，仍失败：写进 limitations，相关事实交人工确认，不要反复重跑。")
    elif others:
        steps.append("失败的文件：再跑一次同一条 ocr 命令会换新任务重试一次（已记下重试次数）；仍失败就写进 limitations，相关事实交人工确认。")
    if not_uploaded:
        steps.append((server_down or "服务器暂时不可用，没有上传：等一两分钟重跑同一条 ocr 命令，不会重复建任务。")
                     + f"（notUploaded 里 {len(result['notUploaded'])} 份，不是识别失败）")
    if not steps and (done or cached):
        steps.append("重跑 search，检索就带上 OCR 文字；读某份文件用 text --file（扫描页给的是 OCR 文字）。")
    if quality:
        steps.append("qualityWarnings 里的页 OCR 读得不全（图纸、空白页、识别跑飞）：那几页上找不到的事实不能写“原件没有”，"
                     "先到材料表、管道特性表、设计说明等别的资料里找，仍找不到就判证据不足或需人工确认，limitations 写明哪份哪页。")
    if unreadable:
        steps.append(f"{len(unreadable)} 份整份 OCR 都没读出字（{'、'.join(unreadable[:5])}{'等' if len(unreadable) > 5 else ''}）："
                     "--force 重做也一样（多是大幅面图纸，OCR 的限制），不要重跑；reviewedFiles 标 skipped，note 写“服务器 OCR 读不出字”，"
                     "相关事实交人工确认")
    if steps:
        result["nextStep"] = "；".join(step.rstrip("。") for step in steps)
    if not targets:
        result["note"] = "没有需要 OCR 的文件：包里的原件都有文字层。"
    return result


def ocr_coverage(bundle: Path, known: list[str]) -> dict[str, set[int]]:
    """每份原件哪些页有 OCR 文字；报告里确定结论引用的扫描页必须落在这里。"""
    pages: dict[str, set[int]] = {}
    for relative in known:
        path = bundle / relative
        record = load_ocr(bundle, relative, path) if path.is_file() else None
        if record:
            pages[relative] = {n for n, t in ocr_page_map(record).items() if t.strip()}
    return pages


# ---------------------------------------------------------------- server tools

def cmd_cert_registry(args: argparse.Namespace) -> Any:
    identifier = args.identifier.strip().upper()
    if args.kind == "person" and MASKED_ID.fullmatch(identifier):
        identifier = resolve_masked_id(identifier, args.bundle)
    pattern = r"\d{17}[\dX]" if args.kind == "person" else r"TS\d{7}-\d{4}"
    if args.kind != "person" and re.fullmatch(r"TS[0-9A-Z]{7}-\d{4}", identifier) and not re.fullmatch(pattern, identifier):
        # 有些许可证号中间带字母（如 TS2710A12-2030），服务器登记接口目前只收纯数字格式，发过去也会被拒。
        raise ClientError("unsupportedLicenceFormat",
                          "这个许可证号带字母，服务器的登记查询接口目前只支持 TS+7 位数字-4 位。登记核验这一维记为未完成："
                          "请监检人员在全国特种设备公示信息查询平台手工核验，并在报告 limitations 写明。")
    if not re.fullmatch(pattern, identifier):
        raise ClientError("invalidArguments", "person 需 18 位身份证号；organization_license 需 TS+7 位-4 位的许可证编号。")
    if args.kind == "person" and not is_id_number(identifier):
        # OCR 读出的号码最容易错一位：出生日期或校验位对不上就不去平台查，也不自己看图重读。
        raise ClientError("idChecksumFailed", "身份证号的出生日期或校验位对不上，多半是 OCR 读错了一位：不要自己看图重读；"
                                              "search 的 idNumbersInText 里没有另一个号时，这张证的登记查询交人工，写进 limitations。")
    return Api(args.base_url).call("POST", "/inspection-services/certificate-registry", timeout=120,
                                   body={"kind": args.kind, "identifier": identifier, "allowExternalQuery": True})


VALIDITY_FIELDS = ("certificates", "expectedHolder", "requiredScopes", "periodStart", "periodEnd", "referenceDate")
CERTIFICATE_FIELDS = ("certificateNo", "holder", "validFrom", "validUntil", "scopes")


def cmd_cert_validity(args: argparse.Namespace) -> Any:
    try:
        payload = json.loads(args.json)
    except ValueError as exc:
        raise ClientError("invalidArguments", f"--json 不是合法 JSON：{exc}") from None
    if not isinstance(payload, dict) or not payload.get("certificates"):
        raise ClientError("invalidArguments", "--json 须为含 certificates 的对象。")
    # 服务器只说“存在不支持的字段”，不说是哪个；在本地先点名。
    unknown = [k for k in payload if k not in VALIDITY_FIELDS]
    unknown += [f"certificates[].{k}" for c in payload["certificates"] if isinstance(c, dict) for k in c if k not in CERTIFICATE_FIELDS]
    if unknown:
        raise ClientError("invalidArguments", f"cert-validity 不接受这些字段：{'、'.join(dict.fromkeys(unknown))}。"
                                              f"顶层只收 {'、'.join(VALIDITY_FIELDS)}；certificates 里只收 {'、'.join(CERTIFICATE_FIELDS)}。")
    return Api(args.base_url).call("POST", "/inspection-services/certificate-validity", body=payload)


def cmd_cnse_org_search(args: argparse.Namespace) -> Any:
    return Api(args.base_url).call("POST", "/cnse/organizations/search", auth=True, body={"keyword": args.keyword}, timeout=120)


def trim_text(value: Any, limit: int = 300) -> Any:
    """检索命中里会夹整张表的 OCR 文字（实测一次 600 多 KB）：只留开头，原文用 standard-content 读。"""
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:limit]}…（共 {len(value)} 字，原文用 standard-content 读）"
    if isinstance(value, list):
        return [trim_text(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: trim_text(item, limit) for key, item in value.items()}
    return value


def cmd_standards(args: argparse.Namespace) -> Any:
    return trim_text(Api(args.base_url).call("GET", "/inspection-services/standards",
                                             query={"keyword": args.query, "page": args.page, "pageSize": args.page_size}))


def cmd_standard_content(args: argparse.Namespace) -> Any:
    return Api(args.base_url).call("GET", f"/inspection-services/standards/{parse.quote(args.file_id, safe='')}/canonical",
                                   query={"pageNo": args.page_no, "section": args.section})


def status_on_date(result: Any, day: str) -> dict[str, Any]:
    """服务器的 verdict 按今天算；给了 --date 就按实施日、废止日算出那一天的状态。"""
    result = result if isinstance(result, dict) else {}
    ref = next(iter(result.get("standardReferences") or []), {})
    detail = result.get("detail") or {}
    start = ref.get("effectiveFrom") or detail.get("effectiveDate")
    end = ref.get("withdrawnOn") or detail.get("withdrawnOn")
    out: dict[str, Any] = {"date": day, "effectiveFrom": start, "withdrawnOn": end}
    if not start:
        out.update(status="unknown", note="没有实施日期，判断不了那一天是否有效。")
    elif day < start:
        out.update(status="not_yet_effective", note=f"{day} 时还没实施（{start} 起实施）。")
    elif end and day >= end:
        out.update(status="withdrawn", note=f"{day} 时已废止（{end} 起）。")
    else:
        out.update(status="in_force", note=f"{day} 时有效（{start} 起实施" + (f"，{end} 废止）。" if end else "，未废止）。"))
    return out


def cmd_standard_status(args: argparse.Namespace) -> Any:
    if args.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        raise ClientError("invalidArguments", "--date 写成 YYYY-MM-DD，如 2021-03-24。")
    body = {"standardRef": args.ref, **({"reviewDate": args.date} if args.date else {})}
    result = Api(args.base_url).call("POST", "/inspection-services/standard-status", body=body, timeout=120)
    if args.date and isinstance(result, dict) and result.get("status") == "COMPLETED":
        result["onDate"] = status_on_date(result, args.date)
    return result


def cmd_node_standards(args: argparse.Namespace) -> Any:
    return Api(args.base_url).call("GET", f"/projects/{parse.quote(args.project, safe='')}/inspection/nodes/{args.node}/standards", auth=True)


# ---------------------------------------------------------------- report

# 资料包里的派生文件不是出处：事实要指回原件或工具。
SOURCE_HINTS = (("text/", "转出的文字（含 OCR 文字）：file 写 files/ 下的原件，page 写页码，text/… 写进 locator"),
                ("ocr/", "OCR 存档：file 写 files/ 下的原件，page 写页码"),
                ("search/", "检索结果：file 写 tool:search，search/<时间>.json 和检索词写进 locator"),
                ("tool-results/", "工具结果：file 写 tool:<命令名>，存档路径写进 locator"),
                ("pages/", "页图：file 写 files/ 下的原件，page 写页码"))


def has_value(value: Any) -> bool:
    """Zero and False are facts, not missing values."""
    return value is not None and (bool(value.strip()) if isinstance(value, str)
                                  else bool(value) if isinstance(value, (list, dict)) else True)


def lexical_path(root: Path, relative: str) -> Path:
    """按字面路径（去掉 ..）判断在不在允许目录里，不跟符号链接：仓库里的 rules/、资料包里的原件都可能是链接。"""
    return Path(os.path.normpath(os.path.join(os.path.abspath(root), relative)))


def source_problem(bundle: Path, source: dict[str, Any], known_files: set[str], page_counts: dict[str, int]) -> str | None:
    """Check existing source fields and files, not whether the model read them correctly."""
    file, page, locator = source.get("file"), source.get("page"), str(source.get("locator") or "").strip()
    if not isinstance(file, str) or not file.strip() or (page is None and not locator):
        return "出处须有 file 及 page/locator"
    if page is not None and (type(page) is not int or page < 1):
        return "page 须为正整数物理页"
    base = bundle.resolve()
    if file.startswith("tool:"):
        command = file.removeprefix("tool:")
        matches = re.findall(r"(?<![\w./-])((?:tool-results|search)/[\w.-]+\.json)(?![\w./-])", locator)
        for relative in matches:
            archive = (base / relative).resolve()
            if not archive.is_relative_to(base) or not archive.is_file():
                continue
            try:
                record = json.loads(archive.read_text(encoding="utf-8"))
                if isinstance(record, dict) and (record.get("tool") == command or
                        (command == "search" and relative.startswith("search/") and "files" in record and "terms" in record)):
                    return None
            except (OSError, ValueError):
                pass
        return "工具出处的 locator 须指向本包内对应命令的实际 JSON 存档"
    if file.startswith("standard:"):
        base = Path(os.path.abspath(repo_root()))
        target = lexical_path(base, file.removeprefix("standard:"))
    elif file.startswith("server:"):
        target = lexical_path(base, file.removeprefix("server:"))
        if target.suffix != ".json":
            return "服务器出处须指向本包内已保存的 JSON"
    else:
        if file not in known_files:
            hint = next((h for prefix, h in SOURCE_HINTS if file.startswith(prefix)), "")
            return f"引用的 {file} 不在本资料包清单中" + (f"——{hint}" if hint else "")
        target = lexical_path(base, file)
    if not target.is_relative_to(base) or not target.is_file():
        return "引用来源不存在或越出允许目录"
    if target.suffix.lower() == ".pdf":
        if page is None:
            return "PDF 出处须写物理页 page"
        key = str(target)
        if key not in page_counts:
            try:
                with quiet_fitz().open(target) as document:
                    page_counts[key] = document.page_count
            except Exception:  # noqa: BLE001 -- 原件损坏或没装 PyMuPDF：数不了页，check_report 统一给警告
                page_counts[key] = 0
        if page_counts[key] and page > page_counts[key]:
            return "引用页超过原件页数"
    elif target.suffix.lower() in IMAGE_SUFFIXES and page not in (None, 1):
        return "单页图片的物理页只能为 1"
    return None


def match_text(text: str) -> str:
    """摘录比对用：按助手看到的脱敏文本比，去空白、表格竖线和“（跨N列）”标记，全角转半角。"""
    text = re.sub(r"（跨\d+列）", "", mask_ids(text)).translate(ITALIC_LATIN)  # 旧摘录可能照抄了没还原的斜体字母
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", text))


def excerpt_problem(bundle: Path, source: dict[str, Any], known_files: set[str],
                    texts: dict[str, list[str] | None]) -> str | None:
    """写了 excerpt 就要真的出现在所引那一页的文字里（text 给的文字，或原件文字层：文字层靠不住的页 text 改给 OCR，
    之前照文字层抄的摘录照样算数）；省略号隔开的几段各自要在。
    页文字取不到（原件打不开、扫描页没 OCR）这里不报：前者 source_problem 已警告，后者 check_reading_coverage 报错。"""
    excerpt, file, page = source.get("excerpt"), source.get("file"), source.get("page")
    if not isinstance(excerpt, str) or not excerpt.strip() or not isinstance(file, str) or type(page) is not int:
        return None
    if file in known_files:
        path = bundle / file
    elif file.startswith("standard:"):
        path = lexical_path(Path(os.path.abspath(repo_root())), file.removeprefix("standard:"))
    else:
        return None
    key = str(path)
    if key not in texts:
        try:
            _, layer, merged, _ = page_texts(bundle, file, path)
            # 每页：text 给的文字 + 原件文字层（两份不同时），用 \0 隔开，摘录不会跨两份拼出来
            texts[key] = [m if n > len(layer) or layer[n - 1] == m else f"{m}\0{layer[n - 1]}"
                          for n, m in enumerate(merged, start=1)]
        except Exception:  # noqa: BLE001 -- 原件打不开或没装 PyMuPDF：source_problem 已给过警告
            texts[key] = None
    pages = texts[key]
    if not pages or not 1 <= page <= len(pages) or not match_text(pages[page - 1]):
        return None
    haystack = match_text(pages[page - 1])
    pieces = [p for p in re.split(r"…+|\.{3,}|⋯+", match_text(excerpt)) if p]
    if pieces and all(p in haystack for p in pieces):
        return None
    shown = excerpt if len(excerpt) <= 40 else excerpt[:40] + "…"
    return f"摘录「{shown}」不在 {file} 第 {page} 页的文字里：excerpt 要照抄 text 转出的那一句，不能改写；文字里没有就别写 excerpt，按证据不足或需人工确认处理"


def check_report(bundle: Path) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    report_path = bundle / "audit.json"
    if not report_path.exists():
        raise ClientError("reportMissing", f"{report_path} 不存在：先按 references/report-format.md 写 audit.json。")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    errors_, warnings = [], []
    if report.get("schemaVersion") != REPORT_SCHEMA:
        errors_.append(f"schemaVersion 应为 {REPORT_SCHEMA}")
    expected = list(manifest.get("atomicChecks") or [])
    seen: dict[str, int] = {}
    known_files = {f["path"] for f in manifest.get("files") or []}
    outcomes = manifest.get("serverOutcomes") or {}
    page_counts: dict[str, int] = {}
    page_text_cache: dict[str, list[str] | None] = {}
    for check in report.get("checks") or []:
        cid = check.get("atomicCheckId")
        seen[cid] = seen.get(cid, 0) + 1
        verdict = check.get("verdict")
        if verdict not in VERDICTS:
            errors_.append(f"{cid}: 还没下结论" if not verdict else f"{cid}: verdict 必须是 {sorted(VERDICTS)} 之一")
            continue
        sourced = []
        for fact in check.get("facts") or []:
            if not isinstance(fact, dict) or not str(fact.get("name") or "").strip() or not has_value(fact.get("value")):
                errors_.append(f"{cid}: 每条已列事实须有非空 name 和 value；未知事实写入 reason/limitations")
                continue
            source = fact.get("source")
            problem = source_problem(bundle, source, known_files, page_counts) if isinstance(source, dict) else "事实缺 source"
            if problem:
                errors_.append(f"{cid}: {problem}")
                continue
            # 摘录对不上所引页：符合／不符合靠它下结论，算错误；其他结论只提醒。
            mismatch = excerpt_problem(bundle, source, known_files, page_text_cache)
            if mismatch and verdict in NEEDS_SOURCE:
                errors_.append(f"{cid}: {mismatch}")
            elif mismatch:
                warnings.append(f"{cid}: {mismatch}")
            else:
                sourced.append(fact)
        if verdict in NEEDS_SOURCE and not sourced:
            errors_.append(f"{cid}: {VERDICTS[verdict]} 至少要一条带 file+page/locator 的事实")
        if verdict in NEEDS_SOURCE and not str(check.get("reasoning") or check.get("reason") or "").strip():
            errors_.append(f"{cid}: {VERDICTS[verdict]} 必须写 reasoning 或 reason 说明比较与判断")
        if verdict not in NEEDS_SOURCE and not str(check.get("reason") or "").strip():
            errors_.append(f"{cid}: {VERDICTS[verdict]} 必须写 reason")
        if verdict == "passed" and any(str(step).strip() for step in check.get("nextSteps") or []):
            warnings.append(f"{cid}: 符合项带着 nextSteps。这些若是本项结论依赖的待补材料或待人工核对的事项，改判证据不足或需人工确认"
                            "（audit-method「判符合前自检」）；与结论无关的跟进事项可保留，并在 reasoning 说明为什么不影响结论")
        for fact in check.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            file = (fact.get("source") if isinstance(fact.get("source"), dict) else {}).get("file")
            if file and file not in known_files and not str(file).startswith(("server:", "tool:", "standard:")):
                hint = next((h for prefix, h in SOURCE_HINTS if str(file).startswith(prefix)), "")
                warnings.append(f"{cid}: 引用的 {file} 不在 bundle files 里" + (f"——{hint}" if hint else ""))
        if not outcomes:
            continue  # 本地资料没有服务器结论，不往 audit.json 里加空的对照字段
        server = (outcomes.get(cid) or {}).get("result")
        check["serverResult"] = server
        check["agreesWithServer"] = None if not server else server == verdict
        if server and server != verdict and not str(check.get("differenceNote") or "").strip():
            warnings.append(f"{cid}: 与服务器结论（{server}）不同，补 differenceNote 说明原因")
    missing = [cid for cid in expected if cid not in seen]
    extra = [cid for cid in seen if cid not in expected]
    dupes = [cid for cid, count in seen.items() if count > 1]
    if missing:
        errors_.append("缺少原子检查：" + "、".join(missing))
    if extra:
        errors_.append("不属于本节点的检查：" + "、".join(map(str, extra)))
    if dupes:
        errors_.append("重复的检查：" + "、".join(dupes))
    unreadable = sorted(Path(key).name for key, count in page_counts.items() if not count)
    if unreadable:
        warnings.append("这些 PDF 打不开（原件损坏，或没用装了 PyMuPDF 的 backend/.venv/bin/python 跑），没核对引用页是否超出页数："
                        + "、".join(unreadable))
    if mask_value(report) != report:  # 按解析后的字符串查：JSON 里换行写成 \n，紧跟的号码在原文上扫会漏
        errors_.append("audit.json 里有完整的 18 位身份证号：一律写成前 4 位 + **** + 后 4 位")
    for flag in report.get("riskFlags") or []:
        if not isinstance(flag, dict) or flag.get("level") not in RISK_LEVELS or not str(flag.get("flag") or "").strip():
            errors_.append(f"riskFlags 每条须有 level（{'/'.join(RISK_LEVELS)}）和 flag：{flag}")
    # 没下载到的挂载资料：包不完整，报告必须说出来，不能当它不存在。
    limitations = clause_text(report.get("limitations") or [])
    for item in manifest.get("skippedFiles") or []:
        if not item.get("downloadFailed"):
            continue
        file_name = str(item.get("fileName") or "")
        names = {file_name, Path(file_name).name, Path(file_name).stem, str(item.get("requirementName") or "")}
        if not any(name and clause_text(name) in limitations for name in names):
            errors_.append(f"资料包缺原件 {file_name or item.get('documentId')}（没下载到：{item.get('reason')}）："
                           "先重跑 fetch 补齐；仍拿不到就在 limitations 写明缺这份（写出文件名或资料名）、影响哪些检查")
    rules = json.loads((bundle / "rules.json").read_text(encoding="utf-8"))
    roles = {c["id"]: c for c in rules["atomicChecks"]}
    check_strict_rules(report.get("checks") or [], roles, errors_)
    check_reading_coverage(bundle, manifest, report, errors_, warnings)
    check_primary_clauses(rules, report, warnings)
    return manifest, report, errors_, warnings


def clause_text(value: Any) -> str:
    """条款号比对用：全角括号变半角、去空白，D2.4.1（5）和 D2.4.1 (5) 都算 D2.4.1(5)。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)))


def check_primary_clauses(rules: dict[str, Any], report: dict[str, Any], warnings: list[str]) -> None:
    """总适用的固定主条款要么在某条事实里引用（excerpt 或 locator 写出条款号），要么在 limitations 里写明没取到。"""
    cited = clause_text([f.get("source") for c in report.get("checks") or [] for f in c.get("facts") or [] if isinstance(f, dict)])
    noted = clause_text(report.get("limitations") or [])
    for clause in rules.get("standardClauses") or []:
        number = clause_text(str(clause.get("clauseNo") or ""))
        if clause.get("bindingRole") != "primary" or clause.get("applicability") != "always" or not number:
            continue
        if number not in cited and number not in noted:
            ref = str(clause.get("standardRef") or "").removeprefix("STD-")
            warnings.append(f"固定主条款 {ref} {clause.get('clauseNo')}（物理页 {clause.get('sourcePage')}）没有在任何检查的 facts 里引用"
                            "（source 的 excerpt 或 locator 要写出条款号），也没有在 limitations 里写明没取到")


def check_strict_rules(checks: list[dict[str, Any]], roles: dict[str, dict[str, Any]], errors_: list[str]) -> None:
    valid = [c for c in checks if c.get("verdict") in VERDICTS]
    conflicted = [c["atomicCheckId"] for c in valid if c.get("conflicts")]
    for check in valid:
        cid, verdict = check["atomicCheckId"], check["verdict"]
        role = roles.get(cid) or {}
        if check.get("conflicts") and verdict == "passed":
            errors_.append(f"{cid}: 列了 conflicts 就不能判符合")
        if role.get("perItem") and verdict == "passed":
            coverage = check.get("coverage") or {}
            items, done = coverage.get("items"), coverage.get("checked")
            if not (isinstance(items, int) and items > 0 and done == items and str(coverage.get("source") or "").strip()):
                errors_.append(f"{cid}: 规则要求{role['perItem']}核对，判符合须给 coverage{{items, checked, source}} 且 checked = items；"
                               "没有逐件记录就判证据不足")
        if role.get("role") == "traceability" and verdict == "passed":
            short = [c["atomicCheckId"] for c in valid if c is not check and c["verdict"] in {"evidence_insufficient", "not_executed"}]
            if short or conflicted:
                expected = "需人工确认" if conflicted else "证据不足"
                errors_.append(f"{cid}: 证据追溯项不得判符合——"
                               + "；".join(x for x in (f"证据缺失：{'、'.join(short)}" if short else "",
                                                     f"存在冲突：{'、'.join(conflicted)}" if conflicted else "") if x)
                               + f"。应判{expected}")


# ocr：读了服务器 OCR 的文字。read/pages/thumbs 是助手自己看图的旧写法：旧报告（评测包）还要能复核，所以仍收、只警告；
# 扫描页上的确定结论只认 OCR 文字（见 check_reading_coverage）。
LEGACY_METHODS = {"read", "pages", "thumbs"}
REVIEW_METHODS = {"ocr", "search", "text", "textutil", "skipped", *LEGACY_METHODS}
# 6+8+4 位之间容一个空格：OCR 常把证件上的号码拆开。前后不能紧挨字母数字，免得把哈希、更长的编号切一段出来。
ID_CANDIDATE = re.compile(r"(?<![0-9A-Za-z])(\d{6}[ 　]?\d{8}[ 　]?\d{3}[\dXx])(?![0-9A-Za-z])")
ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)


def id_digits(value: str) -> str:
    return re.sub(r"[ 　]", "", value)


def plausible_birth_date(value: str) -> bool:
    try:
        return 1900 <= datetime.strptime(value[6:14], "%Y%m%d").year <= 2099
    except ValueError:
        return False


def is_id_number(value: str) -> bool:
    """居民身份证号：出生日期合法且校验位正确（GB 11643）。查登记前用它把关。"""
    value = id_digits(value)
    if len(value) != 18 or not plausible_birth_date(value):
        return False
    return value[17].upper() == "10X98765432"[sum(int(d) * w for d, w in zip(value[:17], ID_WEIGHTS)) % 11]


def looks_like_id(value: str) -> bool:
    """脱敏用的宽口径：出生日期合法、首位是省级代码（1–8）就遮，不要求校验位对——OCR 读错一位的号码也不能带进对话。
    以 9 开头的全数字统一社会信用代码不遮；偶有编号被误遮，前 4 位 + 后 4 位仍在。"""
    value = id_digits(value)
    return len(value) == 18 and value[0] in "12345678" and plausible_birth_date(value)


def contains_id_number(text: str) -> bool:
    return any(looks_like_id(match.group(1)) for match in ID_CANDIDATE.finditer(text))


def mask_ids(text: str) -> str:
    """命令输出、检索结果、转出的文字、工具存档里的身份证号一律写成前 4 位 + ********** + 后 4 位。"""
    def mask(m: re.Match[str]) -> str:
        digits = id_digits(m.group(1))
        return f"{digits[:4]}**********{digits[-4:]}" if looks_like_id(digits) else m.group(0)
    return ID_CANDIDATE.sub(mask, text)


def mask_value(value: Any) -> Any:
    """递归遮蔽字符串值。必须在转 JSON 之前做：JSON 里换行写成 \\n，后面紧跟的号码前一个字符是字母 n，在转义后的文本上扫会漏掉。"""
    if isinstance(value, str):
        return mask_ids(value)
    if isinstance(value, dict):
        return {mask_value(k): mask_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(v) for v in value]
    return value


def dump_masked(value: Any) -> str:
    return dump(mask_value(value))


MASKED_ID = re.compile(r"\d{4}\*{4,}\d{3}[\dX]")


def resolve_masked_id(masked: str, bundle_arg: str | None) -> str:
    """模型手里只有脱敏号：回资料包原件的文字层、OCR 原文（和服务器抽取字段）里找前后 4 位都对上的那一个完整号码。"""
    if not bundle_arg:
        raise ClientError("invalidArguments", "脱敏号码要配 --bundle <资料包>，从包里原件找回完整号码再查。")
    bundle = Path(bundle_arg).expanduser().resolve()
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    texts: list[str] = []
    for item in manifest.get("files") or []:
        try:
            texts += page_texts(bundle, item["path"], bundle / item["path"])[2]
        except Exception:  # noqa: BLE001 -- 原件打不开就跳过这份，号码可能在别处（OCR 原文、服务器 JSON）
            texts.append("")
    # 服务器 JSON 的原文在 ocr/server/ 下（包根目录那份已脱敏）；旧资料包只有根目录那份未脱敏的。
    for filename in ("workspace.json", "evidence-chain.json"):
        for candidate in (bundle / SERVER_RAW_DIR / filename, bundle / filename):
            if candidate.exists():
                texts.append(candidate.read_text(encoding="utf-8"))
                break
    head, tail = masked[:4], masked[-4:]
    found = {id_digits(m.group(1)).upper() for text in texts for m in ID_CANDIDATE.finditer(text)
             if looks_like_id(m.group(1)) and id_digits(m.group(1)).startswith(head) and id_digits(m.group(1)).upper().endswith(tail)}
    if len(found) == 1:
        return found.pop()
    if not found:
        raise ClientError("identifierNotFound", f"资料包的文字层和 OCR 文字里都没有与 {masked} 前后 4 位都对上的身份证号；"
                                                 "还没跑 ocr 就先跑；OCR 也没读出时，这张证的登记查询交人工，写进 limitations。")
    raise ClientError("identifierAmbiguous", f"资料包里有 {len(found)} 个身份证号与 {masked} 前后 4 位相同，分不出是哪个；这张证的登记查询交人工，写进 limitations。")


RISK_LEVELS = ("high", "medium")


def latest_search(bundle: Path) -> dict[str, Any] | None:
    runs = sorted((bundle / "search").glob("*.json")) if (bundle / "search").is_dir() else []
    return json.loads(runs[-1].read_text(encoding="utf-8")) if runs else None


def check_reading_coverage(bundle: Path, manifest: dict[str, Any], report: dict[str, Any],
                           errors_: list[str], warnings: list[str]) -> None:
    known = [f["path"] for f in manifest.get("files") or []]
    listed: dict[str, dict[str, Any]] = {}
    for entry in report.get("reviewedFiles") or []:
        path = entry.get("file") if isinstance(entry, dict) else None
        if path not in known:
            warnings.append(f"reviewedFiles 里的 {path} 不在资料包里")
            continue
        listed[path] = entry
        if entry.get("method") not in REVIEW_METHODS:
            errors_.append(f"reviewedFiles {path}: " + ("还没写怎么看的（method）" if not entry.get("method") else f"method 须为 {sorted(REVIEW_METHODS)} 之一"))
        elif entry["method"] == "skipped" and not str(entry.get("note") or "").strip():
            errors_.append(f"reviewedFiles {path}: skipped 要写 note 说明为什么不看")
    unlisted = [p for p in known if p not in listed]
    if unlisted:
        errors_.append(f"reviewedFiles 缺 {len(unlisted)} 份文件（每份都要写明怎么看的或为什么跳过）：" + "、".join(unlisted))
    search = latest_search(bundle)
    if not search:
        warnings.append("没有跑过 search：全包检索能找出没想到的文件里的工期、材质、人员等事实")
        search = {}
    unread = set(search.get("needsOcr", search.get("needsVisualReview")) or [])
    unread_pages = search.get("needsOcrPages", search.get("needsVisualPages")) or {}
    # 扫描件与扫描页按原件文字层算（旧存档没有 scannedFiles，退回“当时还缺字”的清单）。
    visual = set(search.get("scannedFiles") or []) | unread
    partial = {**unread_pages, **(search.get("scannedPages") or {})}
    ocr_pages = ocr_coverage(bundle, known)
    image_only: dict[tuple[str, int], bool] = {}
    scans: dict[str, set[int]] = {}  # 每份 PDF 只开一次
    for path, entry in listed.items():
        if path in unread and entry.get("method") == "search" and not ocr_pages.get(path):
            errors_.append(f"reviewedFiles {path}: 没有文字层也没 OCR，只检索等于没看——先跑 ocr 再读 OCR 文字（method 写 ocr），或标 skipped 写原因")
        elif path in unread_pages and entry.get("method") == "search" and not str(entry.get("note") or "").strip() \
                and not ocr_pages.get(path):
            errors_.append(f"reviewedFiles {path}: 第 {unread_pages[path]} 页没有文字层，检索看不到——跑 ocr 后在 pages 写明，或在 note 说明为何不看")
        # 阅读记录要和资料包对得上：写了 ocr 就要有 OCR 存档，扫描件写 text 等于没读到字。
        method = entry.get("method")
        if method == "ocr" and not ocr_pages.get(path):
            if (bundle / path).is_file() and load_ocr(bundle, path, bundle / path):
                errors_.append(f"reviewedFiles {path}: 服务器 OCR 一个字也没读出（--force 重做也一样，多是大幅面图纸）——"
                               "method 写 skipped，note 写“服务器 OCR 读不出字”，相关事实交人工确认")
            else:
                errors_.append(f"reviewedFiles {path}: 标了 ocr，但资料包里没有这份原件的 OCR 文字（没跑 ocr，或原件改过）"
                               "——先跑 ocr，或按实际读法改 method")
        elif method in {"text", "textutil"} and path in visual and not ocr_pages.get(path):
            errors_.append(f"reviewedFiles {path}: 是扫描件、没有文字层，text 读不到字——先跑 ocr 再读 OCR 文字（method 写 ocr），或标 skipped 写原因")
        elif method in LEGACY_METHODS:
            warnings.append(f"reviewedFiles {path}: method 写的是看图的旧写法 {method}；现在不自己看图：有文字层写 text，扫描件跑 ocr 后写 ocr")
    for check in report.get("checks") or []:
        if check.get("verdict") not in NEEDS_SOURCE:
            continue
        for fact in check.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            source = fact.get("source") if isinstance(fact.get("source"), dict) else {}
            path, page = source.get("file"), source.get("page")
            scanned = (path in visual or Path(str(path)).suffix.lower() in IMAGE_SUFFIXES
                       or (isinstance(partial.get(path), list) and page in partial[path]))
            # A missing/stale search archive must not exempt a cited image-only PDF page.
            target = (bundle / str(path)).resolve()
            if (not scanned and path in known and target.is_relative_to(bundle.resolve())
                    and target.suffix.lower() == ".pdf" and type(page) is int and page > 0):
                key = (path, page)
                if key not in image_only:
                    try:
                        if path not in scans:
                            scans[path] = scan_pages(target, file_text(target)[1])
                        image_only[key] = page in scans[path]
                    except Exception:  # noqa: BLE001 -- 打不开就核不了文字层：只警告，不让整份报告交不出去
                        image_only[key] = False
                        warnings.append(f"{check['atomicCheckId']}: {path} 第 {page} 页打不开，没核对它是不是扫描页、阅读记录够不够")
                scanned = image_only[key]
            number = page if type(page) is int and page > 0 else 1
            if scanned and path in known and number not in ocr_pages.get(path, set()):
                errors_.append(f"{check['atomicCheckId']}: 确定结论引用的扫描页 {path} 第 {number} 页没有 OCR 文字"
                               "——先跑 ocr；OCR 里仍没有这一处，本项判证据不足或需人工确认")


OUTCOME_LABELS = {"passed": "通过", "failed": "不通过", "pending": "暂不能判定通过"}


def node_outcome(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """The node as a whole, from its atomic checks: any failed -> failed; everything passed (or not applicable) -> passed;
    otherwise pending, because something is still missing or needs a person, which is not the same as failing."""
    counts: dict[str, int] = {}
    for check in checks:
        counts[check["verdict"]] = counts.get(check["verdict"], 0) + 1
    if counts.get("failed"):
        key = "failed"
    elif counts and set(counts) <= {"passed", "not_applicable"} and counts.get("passed"):
        key = "passed"
    else:
        key = "pending"
    parts = "、".join(f"{VERDICTS[v]} {counts[v]}" for v in VERDICTS if counts.get(v))
    explain = {
        "failed": f"有 {counts.get('failed', 0)} 项不符合要求，需要整改。",
        "passed": "全部检查项都有原件证据支持，满足要求。",
        "pending": "没有发现明确不符合，但还有检查项缺证据或需要人工确认，补齐或确认后才能判通过。",
    }[key]
    return {"outcome": key, "label": OUTCOME_LABELS[key], "explain": explain, "counts": counts, "summary": f"{len(checks)} 项检查：{parts}。"}


TOOL_LABELS = {"cert-registry": "公示平台登记查询", "cert-validity": "有效期核验", "search": "全包检索",
               "standard-content": "标准原文", "standard-status": "标准有效性查询", "cnse-org-search": "公示平台单位查询"}


def short_file(path: Any) -> str:
    """How a source reads to a person: the original file's name, a standard's name, or what a tool did."""
    text = str(path or "")
    if text.startswith("tool:"):
        return TOOL_LABELS.get(text[5:], text[5:])
    if text.startswith("standard:"):
        return "标准 " + re.sub(r"\.pdf$", "", Path(text[9:]).name)
    return re.sub(r"^files/\d+-", "", text)


def fact_place(fact: dict[str, Any]) -> str:
    src = fact.get("source") or {}
    where = short_file(src.get("file"))
    if src.get("page"):
        where += f" 第{src['page']}页"
    elif src.get("locator") and not str(src.get("file") or "").startswith("tool:"):
        where += f"（{src['locator']}）"
    return where.strip()


VERDICT_MARK = {"passed": "✅", "failed": "❌", "evidence_insufficient": "❓", "human_review_required": "👤",
                "not_applicable": "➖", "not_executed": "⏸"}


def clip_text(text: str, limit: int) -> str:
    """Cut at the last clause break before the limit, so a table cell never ends in half a word."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    cut = max(head.rfind(mark) for mark in "，；、,;")
    return (head[:cut] if cut >= limit // 2 else head) + "…"


def first_sentence(text: Any, limit: int = 110) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    cut = re.split(r"(?<=[。！？])", text, maxsplit=1)[0] if text else ""  # 只在句号处断：分号前常是半句
    return clip_text(cut, limit)


def leading_sentences(text: Any, limit: int = 220) -> str:
    """The first sentences that fit in `limit` characters (always at least the first one, clipped if it is long)."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    sentences = [s for s in re.split(r"(?<=[。！？])", text) if s]
    out = ""
    for sentence in sentences:
        if out and len(out) + len(sentence) > limit:
            break
        out += sentence
    return clip_text(out, limit)


def short_time(value: Any) -> str:
    """2026-10-26T18:40:00-07:00 -> 2026-10-26 18:40 (no seconds, no offset: a person reads the date and the hour)."""
    match = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", str(value or ""))
    return f"{match.group(1)} {match.group(2)}" if match else str(value or "—")


def check_title(check: dict[str, Any]) -> str:
    """Rule names prefix every check name (“规则名·检查名”); a person only needs the check part."""
    name = str(check.get("name") or "")
    return f"{check['atomicCheckId']} {name.split('·', 1)[-1]}".strip()


def check_reason(check: dict[str, Any]) -> str:
    if check["verdict"] in NEEDS_SOURCE:
        return first_sentence(check.get("reasoning") or check.get("reason"))
    return first_sentence(check.get("reason") or check.get("reasoning"))


def check_evidence(check: dict[str, Any], limit: int = 2) -> str:
    """Where the evidence is, grouped by file: `焊工证.pdf 第1、5页；施工方案.pdf 第3页 等 9 处`. Originals before standards and tools."""
    groups: dict[str, list[str]] = {}
    total = 0
    rank = lambda fact: (str((fact.get("source") or {}).get("file") or "").startswith(("tool:", "standard:", "server:")),)
    for fact in sorted(check.get("facts") or [], key=rank):
        src = fact.get("source") or {}
        name = short_file(src.get("file"))
        if not name:
            continue
        if src.get("page"):
            mark = str(src["page"])
        elif src.get("locator") and not str(src.get("file") or "").startswith("tool:"):
            mark = f"（{src['locator']}）"
        else:
            mark = ""
        pages = groups.setdefault(name, [])
        if mark not in pages:
            pages.append(mark)
            total += 1
    def label(name: str, marks: list[str]) -> str:
        numbers = sorted((m for m in marks if m.isdigit()), key=int)
        others = [m for m in marks if m and not m.isdigit()]
        parts = ([f"第{'、'.join(numbers)}页"] if numbers else []) + others
        return f"{name} {''.join(parts)}".strip()
    shown = "；".join(label(name, marks) for name, marks in list(groups.items())[:limit])
    return shown + (f" 等 {total} 处" if len(groups) > limit else "")


def priority_steps(checks: list[dict[str, Any]], cap: int = 6) -> tuple[list[str], int]:
    """The few things a person should do first: fix what failed, supply what is missing, then confirm what a person must decide.
    Inside each group the checks take turns (every check's first step before any check's second), so one check with many steps
    cannot fill the list. Steps that only point at another check (“补齐 AC-… 所列缺口”) go last."""
    seen, steps, pointers = set(), [], []
    for verdicts in (("failed",), ("evidence_insufficient", "not_executed"), ("human_review_required",)):
        queues = []
        for check in checks:
            if check["verdict"] in verdicts:
                queues.append([(check["atomicCheckId"], str(step).strip()) for step in check.get("nextSteps") or [] if str(step).strip()])
        for turn in range(max((len(q) for q in queues), default=0)):
            for queue in queues:
                if turn >= len(queue):
                    continue
                cid, step = queue[turn]
                key = re.sub(r"\s+", "", step)
                if key in seen:
                    continue
                seen.add(key)
                line = f"**{cid}**：{step}"
                (pointers if re.search(r"AC-[A-Z0-9]+-\d+", step) and len(step) < 60 else steps).append(line)
    steps += pointers
    return steps[:cap], max(len(steps) - cap, 0)


def render_markdown(manifest: dict[str, Any], report: dict[str, Any], warnings: list[str], rule_name: str = "") -> str:
    """User-facing first: the node's result, then why (per check, with where the evidence is), then the details."""
    checks = report.get("checks") or []
    outcome = node_outcome(checks)
    title = f"# 节点审计结果 · {manifest.get('projectId')} · 节点 {manifest['nodeId']:02d} {manifest['ruleId']}" + (f" {rule_name}" if rule_name else "")
    marks = "　".join(f"{VERDICT_MARK[v]} {VERDICTS[v]} {outcome['counts'][v]}" for v in VERDICTS if outcome["counts"].get(v))
    lines = [title, "",
             "> 本报告是 AI 助手的辅助审计意见，不代替监检人员的正式结论。是否同步到服务器由用户决定；同步后在服务器上是待人工复核的 AI 审查发现。", "",
             f"## 结论：{outcome['label']}", "", outcome["explain"], "", f"共 {len(checks)} 项检查：{marks}", "",
             f"- 资料来源：{manifest['source']}（{manifest.get('baseUrl') or '本地'}），取数 {short_time(manifest['fetchedAt'])}",
             f"- 审计时间：{short_time(report.get('auditedAt'))}；审计者：{report.get('auditor') or '—'}", "",
             "| 检查 | 结论 | 理由 | 主要依据 |", "|---|---|---|---|"]
    for check in checks:
        lines.append(f"| {cell(check_title(check))} | {VERDICT_MARK[check['verdict']]} {VERDICTS[check['verdict']]} | "
                     f"{cell(check_reason(check))} | {cell(check_evidence(check) or '—')} |")
    steps, more = priority_steps(checks)
    if steps:
        lines += ["", "## 最需要先做的事", ""] + [f"{n}. {step}" for n, step in enumerate(steps, 1)]
        if more:
            lines.append(f"\n另有 {more} 条建议，见下面各项的“建议”。")
    agree = [c for c in checks if c.get("agreesWithServer") is True]
    differ = [c for c in checks if c.get("agreesWithServer") is False]
    if agree or differ:
        lines += ["", f"与服务器结论一致 {len(agree)} 项，不一致 {len(differ)} 项。"]

    def section(heading: str, verdicts: set[str], lead: str) -> None:
        picked = [c for c in checks if c["verdict"] in verdicts]
        if not picked:
            return
        lines.extend(["", f"## {heading}", "", lead, ""])
        for check in picked:
            text = (check.get("reasoning") or check.get("reason")) if check["verdict"] in NEEDS_SOURCE else (check.get("reason") or check.get("reasoning"))
            text = str(text or "").strip()
            if check["verdict"] != "failed":  # 不符合的原因写全；其余只放开头，完整说明在逐项明细
                brief = leading_sentences(text)
                text = brief + f"（完整说明见下面“逐项明细”{check['atomicCheckId']}）" if brief != text else text
            lines.append(f"- **{check_title(check)}**：{text}")
            evidence = check_evidence(check, limit=4)
            if evidence:
                lines.append(f"  - 依据：{evidence}")
            for conflict in check.get("conflicts") or []:
                lines.append(f"  - 资料矛盾：{conflict}")
            for step in check.get("nextSteps") or []:
                lines.append(f"  - 建议：{step}")

    section("不通过的原因", {"failed"}, "原件明确显示不满足要求的项，需要受检单位整改：")
    section("需要人工确认", {"human_review_required"}, "要由人现场、对原件，或在互相矛盾的资料中确认的项（这些项本身的资料齐了，缺的资料见“证据不足”）：")
    section("证据不足", {"evidence_insufficient", "not_executed"}, "缺资料、读不清或没能核验，补齐后才能下结论的项：")
    if report.get("missingMaterials"):
        lines += ["", "## 需要补充的资料", ""] + [f"- {item}" for item in report["missingMaterials"]]
    section("通过项及证据", {"passed"}, "已有原件证据支持、满足要求的项：")
    if report.get("riskFlags"):
        lines += ["", "## 高风险提示", ""]
        for flag in report["riskFlags"]:
            label = "高" if flag.get("level") == "high" else "中"
            lines.append(f"- 【{label}】{flag.get('check') or ''} {flag.get('flag')}" + (f"（{flag['basis']}）" if flag.get("basis") else ""))
    if report.get("summary"):
        lines += ["", "## 总体意见", "", str(report["summary"])]
    lines += ["", "## 逐项明细"]
    for check in checks:
        lines += ["", f"### {check['atomicCheckId']} · {check.get('name') or ''}", "",
                  f"**结论：{VERDICTS[check['verdict']]}**" + (f"（服务器：{check['serverResult']}）" if check.get("serverResult") else "")]
        if check.get("requirement"):
            lines += ["", f"要求：{check['requirement']}"]
        if check.get("facts"):
            lines += ["", "| 事实 | 值 | 出处 |", "|---|---|---|"]
            for fact in check["facts"]:
                src = fact.get("source") or {}
                where = " ".join(str(x) for x in (src.get("file"), f"第{src['page']}页" if src.get("page") else "", src.get("locator")) if x)
                excerpt = f"「{src['excerpt']}」" if src.get("excerpt") else ""
                lines.append(f"| {cell(fact.get('name'))} | {cell(fact.get('value'))} | {cell(f'{where} {excerpt}')} |")
        cov = check.get("coverage") or {}
        if cov.get("items") is not None or cov.get("checked") is not None:  # 骨架里的 null 不是统计结果，不打印
            def count(value: Any) -> str:
                return "未知" if value is None else str(value)
            origin = f"（{cov['source']}）" if cov.get("source") else ""
            lines += ["", f"逐件覆盖：{count(cov.get('checked'))}/{count(cov.get('items'))}{origin}"]
        for label, key in (("判断", "reasoning"), ("原因", "reason"), ("与服务器差异", "differenceNote")):
            if check.get(key):
                lines += ["", f"{label}：{check[key]}"]
        for conflict in check.get("conflicts") or []:
            lines.append(f"- 冲突：{conflict}")
        for call in check.get("toolCalls") or []:
            if isinstance(call, dict):
                lines.append(f"- 工具 `{call.get('tool')}`（{call.get('at') or ''}）：{call.get('summary')}")
            else:
                lines.append(f"- 工具：{call}")
        for step in check.get("nextSteps") or []:
            lines.append(f"- 下一步：{step}")
    for heading, key in (("关联节点复核建议", "relatedNodeSuggestions"), ("局限与未覆盖", "limitations")):
        if report.get(key):
            lines += ["", f"## {heading}", ""] + [f"- {item}" for item in report[key]]
    if report.get("reviewedFiles"):
        method_label = {"read": "读原件", "pages": "看页图", "thumbs": "缩略图过目", "search": "文字层检索", "text": "转文字", "textutil": "转文字", "skipped": "未看"}
        lines += ["", "## 已阅读文件", "", "| 文件 | 方式 | 页 | 说明 |", "|---|---|---|---|"]
        for entry in report["reviewedFiles"]:
            lines.append(f"| {cell(entry.get('file'))} | {method_label.get(entry.get('method'), cell(entry.get('method')))} | "
                         f"{cell(entry.get('pages') or '—')} | {cell(entry.get('note') or '')} |")
    if manifest.get("warnings") or warnings:
        lines += ["", "## 取数与校验提示", ""] + [f"- {w}" for w in (manifest.get("warnings") or []) + warnings]
    return mask_value("\n".join(lines) + "\n")


def cmd_skeleton(args: argparse.Namespace) -> Any:
    """audit.json 骨架：每个原子检查、每份文件各占一格，只需填空；漏检查、漏文件、字段名写错的机会都没了。"""
    bundle = Path(args.bundle).expanduser().resolve()
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    rules = json.loads((bundle / "rules.json").read_text(encoding="utf-8"))
    target = bundle / "audit.json"
    if target.exists() and not args.force:
        raise ClientError("reportExists", f"{target} 已存在；确认要重来再加 --force。")
    checks = []
    for check in rules["atomicChecks"]:
        item: dict[str, Any] = {"atomicCheckId": check["id"], "name": check.get("name"), "instruction": check.get("instruction"),
                                "verdict": "", "requirement": "", "facts": [], "reasoning": "", "reason": "",
                                "conflicts": [], "toolCalls": [], "nextSteps": []}
        if check.get("perItem"):
            item["coverage"] = {"items": None, "checked": None, "source": ""}
        checks.append(item)
    report = {"schemaVersion": REPORT_SCHEMA, "projectId": manifest.get("projectId"), "nodeId": manifest.get("nodeId"),
              "ruleId": manifest.get("ruleId"), "auditedAt": "", "auditor": "", "summary": "", "checks": checks,
              "riskFlags": [], "missingMaterials": [], "relatedNodeSuggestions": [], "limitations": [],
              "reviewedFiles": [{"file": f["path"], "method": "", "pages": "", "note": ""} for f in manifest.get("files") or []]}
    write_private(target, dump(report))
    return {"skeleton": str(target), "checks": len(checks), "files": len(report["reviewedFiles"]),
            "next": "逐项填 verdict/facts/reasoning 或 reason，逐份填 reviewedFiles 的 method；填完跑 report"}


def cmd_report(args: argparse.Namespace) -> Any:
    bundle = Path(args.bundle).expanduser().resolve()
    before = json.loads((bundle / "audit.json").read_text(encoding="utf-8")) if (bundle / "audit.json").exists() else None
    manifest, report, errors_, warnings = check_report(bundle)
    if errors_:
        raise ClientError("reportInvalid", "audit.json 未通过校验，修正后重跑 report。", errors=errors_, warnings=warnings)
    updated = report != before  # 只有补了服务器结论才改写 audit.json，免得之后编辑它时文件已变
    if updated:
        write_private(bundle / "audit.json", dump(report))
    rule = (json.loads((bundle / "rules.json").read_text(encoding="utf-8")).get("rule") or {}) if (bundle / "rules.json").exists() else {}
    full_report = render_markdown(manifest, report, warnings, rule.get("name") or "")
    write_private(bundle / "audit.md", full_report)
    outcome = node_outcome(report["checks"])
    counts = {VERDICTS[v]: n for v, n in outcome["counts"].items()}
    # fullReport 和 audit.md 一字不差：完整结果随输出给出，回复用户不必再去读文件。
    return {"markdown": str(bundle / "audit.md"), "outcome": outcome["label"], "outcomeExplain": outcome["explain"],
            "counts": counts, "warnings": warnings, "auditJsonUpdated": updated,
            "syncAvailable": manifest.get("source") == "server", "fullReport": full_report,
            "next": ("把 fullReport 里的完整逐项结果贴给用户（SKILL.md 第 10 步）；用户看过后运行 sync --bundle 预览，"
                     "用户确认该次内容后加 --confirm --preview-hash <摘要>"
                     if manifest.get("source") == "server" else
                     "把 fullReport 里的完整逐项结果贴给用户（SKILL.md 第 10 步）；本地资料包没有对应的服务器节点，不能同步")}


# ---------------------------------------------------------------- result image (rendered by the server)

IMAGE_PATH = "/inspection-services/audit-result-image"


def audit_image_body(manifest: dict[str, Any], report: dict[str, Any], rule_name: str = "") -> dict[str, Any]:
    """发给服务器画图的摘要：和 audit.md 同一套结论、理由、依据，只要摘要，不带全文。证号再脱敏一遍。"""
    checks = report["checks"]
    outcome = node_outcome(checks)
    steps, _ = priority_steps(checks, cap=6)
    flags = [{"level": f.get("level"), "flag": f.get("flag") or "", "basis": f.get("basis") or ""}
             for f in report.get("riskFlags") or [] if isinstance(f, dict) and f.get("flag")]
    body = {
        "nodeId": manifest["nodeId"], "nodeName": rule_name, "ruleId": manifest.get("ruleId") or "",
        "projectLabel": str(manifest.get("projectId") or ""), "outcome": outcome["outcome"], "outcomeExplain": outcome["explain"],
        "auditedAt": short_time(report.get("auditedAt")) if report.get("auditedAt") else "", "auditor": str(report.get("auditor") or ""),
        "source": "服务器资料包" if manifest.get("source") == "server" else "本地资料包",
        "checks": [{"atomicCheckId": c["atomicCheckId"], "title": str(c.get("name") or "").split("·", 1)[-1],
                    "verdict": c["verdict"], "reason": check_reason(c), "evidence": check_evidence(c, limit=3),
                    "differsFromServer": (not c["agreesWithServer"]) if isinstance(c.get("agreesWithServer"), bool) else None}
                   for c in checks],
        "nextSteps": [re.sub(r"\*\*(.+?)\*\*", r"\1", step) for step in steps],
        "missingMaterials": [str(m) for m in report.get("missingMaterials") or []][:10],
        "riskFlags": flags[:8], "summary": clip_text(str(report.get("summary") or ""), 600),
    }
    return json.loads(dump_masked(body))


def decode_image_pages(data: Any) -> list[bytes]:
    """服务器一次回所有页：{pages: [{pageNo, imageBase64}]}。每页必须是合法 base64 的 PNG，页数和大小有上限。"""
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_IMAGE_PAGES:
        raise ClientError("badResponse", "服务器返回的图片页数不对。", path=IMAGE_PATH)
    decoded = []
    for page in pages:
        try:
            raw = base64.b64decode(page["imageBase64"], validate=True)
        except (KeyError, TypeError, ValueError):
            raise ClientError("badResponse", "服务器返回的图片不是合法的 base64。", path=IMAGE_PATH) from None
        if not raw.startswith(b"\x89PNG") or len(raw) > MAX_IMAGE_BYTES:
            raise ClientError("badResponse", "服务器返回的不是 PNG，或单页超过 8MB。", path=IMAGE_PATH)
        decoded.append(raw)
    return decoded


def image_targets(base: Path, count: int) -> list[Path]:
    """一页就是 base 本身；多页在文件名后加页码：audit.png → audit-1.png、audit-2.png…"""
    if count == 1:
        return [base]
    return [base.with_name(f"{base.stem}-{number}{base.suffix}") for number in range(1, count + 1)]


def cmd_render(args: argparse.Namespace) -> Any:
    """把审计结果的摘要发给服务器，由它用 HTML 模板渲染成白底的图（内容多就分页），存进资料包。"""
    bundle = Path(args.bundle).expanduser().resolve()
    manifest, report, errors_, warnings = check_report(bundle)
    if errors_:
        raise ClientError("reportInvalid", "audit.json 未通过校验：先修正并跑 report，再生成结果图。", errors=errors_, warnings=warnings)
    api = Api(args.base_url)
    if not api.token:
        raise ClientError("loginRequired", f"结果图由服务器渲染，要监检账号令牌{LOGIN_HINT}。")
    rule = (json.loads((bundle / "rules.json").read_text(encoding="utf-8")).get("rule") or {}) if (bundle / "rules.json").exists() else {}
    try:
        data = api.call("POST", IMAGE_PATH, body=audit_image_body(manifest, report, rule.get("name") or ""), auth=True)
    except ClientError as exc:
        # 没登录、无权的业务错误（HTTP 200 + 数字 code）Api 已翻成 loginRequired / forbidden。
        if exc.code == "notFound":
            raise ClientError("renderNotDeployed", "服务器还没有结果图片接口（要部署新版后端）：先用 audit.md，部署后再生成图片。") from None
        raise
    pages = decode_image_pages(data)
    base = Path(args.out).expanduser().resolve() if args.out else bundle / "audit.png"
    targets = image_targets(base, len(pages))
    private_dir(base.parent)
    if not args.out:  # 默认位置：上一次留下的 audit.png / audit-N.png 不能和这次的混在一起
        for old in bundle.iterdir():
            if re.fullmatch(r"audit(-\d+)?\.png", old.name) and old not in targets:
                old.unlink()
    for target, png in zip(targets, pages, strict=True):
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(png)
        os.chmod(target, 0o600)
    outcome = node_outcome(report["checks"])
    return {"images": [str(t) for t in targets], "pageCount": len(pages), "bytes": sum(len(p) for p in pages),
            "outcome": outcome["label"],
            "next": "把图片路径告诉用户；你所在的环境能显示图片就按页码顺序一并展示。图只是摘要，完整依据在 audit.md。"}


# ---------------------------------------------------------------- sync to server

SYNC_VERDICTS = {"failed", "human_review_required", "evidence_insufficient", "not_executed"}
FINDING_SEVERITY = {"failed": "high", "human_review_required": "medium", "evidence_insufficient": "medium", "not_executed": "low"}
# 服务器要求 AI 发现带 confidence。这里按结论类型取固定值，不是模型概率；说明里写明。
FINDING_CONFIDENCE = {"failed": 0.8, "human_review_required": 0.6, "evidence_insufficient": 0.5, "not_executed": 0.3}
FINDING_TYPE = "ai_node_audit"


def matching_evidence_links(fact: dict[str, Any], version: str, evidence_chain: dict[str, Any]) -> list[str]:
    """Require a locatable fact match, not just a confirmed document version."""
    source = fact.get("source") or {}
    def literal(value: Any) -> str:
        # 摘录是照 text 转出的文字抄的：表格竖线、（跨N列）、[印章：…] 的外壳是 skill 自己加的，服务器的引文里没有；
        # 身份证号助手手里只有脱敏号，两边都按脱敏后比。
        text = re.sub(r"\[(?:印章|签名)：([^\]]*)\]", r"\1", str(value if value is not None else ""))
        return match_text(text)
    def masked(value: Any) -> str:
        return unicodedata.normalize("NFKC", mask_ids(str(value if value is not None else "")))
    excerpt, name = literal(source.get("excerpt")), literal(fact.get("name"))
    value = re.sub(r"\s+", "", masked(fact.get("value")))
    matches = set()
    for link in (evidence_chain or {}).get("links") or []:
        if (not version or link.get("documentVersionId") != version or not link.get("id")
                or str(link.get("manualStatus") or "").lower() != "confirmed"
                or link.get("formalEvidenceEligible", True) is False
                or type(link.get("pageNo")) is not int or link["pageNo"] < 1
                or link["pageNo"] != source.get("page")):
            continue
        box = link.get("bbox")
        try:
            located = isinstance(box, (list, tuple)) and len(box) >= 4 and float(box[2]) > float(box[0]) and float(box[3]) > float(box[1])
        except (ValueError, TypeError):
            located = False
        quote, field = literal(link.get("quotedText")), literal(link.get("fieldName"))
        if not located or not (quote or field):
            continue
        same_excerpt = bool(excerpt and quote and excerpt == quote)
        same_field_value = bool(name and field == name and value and quote
                                and re.search(r"(?<![A-Za-z0-9.])" + re.escape(value) + r"(?![A-Za-z0-9.])",
                                              masked(link.get("quotedText"))))
        if same_excerpt or same_field_value:
            matches.add(str(link["id"]))
    # Same text in several regions is ambiguous without a finer source locator.
    return sorted(matches) if len(matches) == 1 else []


def finding_description(check: dict[str, Any], outcome: dict[str, Any], unmatched: list[str] | None = None) -> str:
    parts = [f"结论：{VERDICTS[check['verdict']]}（节点整体：{outcome['label']}）"]
    if check.get("requirement"):
        parts.append(f"要求：{check['requirement']}")
    reason = (check.get("reasoning") or check.get("reason")) if check["verdict"] in NEEDS_SOURCE else (check.get("reason") or check.get("reasoning"))
    if reason:
        parts.append(f"理由：{reason}")
    for fact in (check.get("facts") or [])[:6]:
        parts.append(f"事实：{fact.get('name')}＝{fact.get('value')}（{fact_place(fact)}）")
    parts += [f"资料矛盾：{c}" for c in check.get("conflicts") or []]
    parts += [f"建议：{n}" for n in check.get("nextSteps") or []]
    if unmatched:
        parts.append("没挂证据链接的事实（服务器上没有逐条对应的已确认证据，请按出处人工核）：" + "；".join(unmatched))
    parts.append(f"来源：aicheck-node-audit 本地 AI 辅助审计；confidence 按结论类型固定取 {FINDING_CONFIDENCE[check['verdict']]}，不是模型概率。")
    text = "\n".join(str(p) for p in parts)
    return mask_ids(text if len(text) <= 2000 else text[:1990] + "…（截断）")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sync_approval_snapshot(server: str, plan: dict[str, Any], evidence_chain: dict[str, Any]) -> dict[str, Any]:
    # Ignore array ordering, not changed evidence content or confirmation status.
    links = sorted(evidence_chain.get("links") or [], key=canonical_digest)
    return {"server": server, "projectId": plan["manifest"]["projectId"], "nodeId": plan["manifest"]["nodeId"],
            "auditSha256": plan["auditSha256"], "evidenceSha256": canonical_digest(links),
            "create": plan["create"], "skipped": plan["skipped"]}


def sync_plan(bundle: Path, evidence_chain: dict[str, Any]) -> dict[str, Any]:
    manifest, report, errors_, _ = check_report(bundle)
    if errors_:
        raise ClientError("reportInvalid", "audit.json 未通过校验，先跑 report 改到通过再同步。", errors=errors_)
    if manifest.get("source") != "server":
        raise ClientError("localBundle", "这是本地资料包，服务器上没有对应的项目节点，不能同步。")
    outcome = node_outcome(report["checks"])
    versions = {f["path"]: str(f.get("documentVersionId") or "") for f in manifest.get("files") or []}
    risk_high = {flag.get("check") for flag in report.get("riskFlags") or [] if flag.get("level") == "high"}
    digest = hashlib.sha256((bundle / "audit.json").read_bytes()).hexdigest()
    rules = json.loads((bundle / "rules.json").read_text(encoding="utf-8")) if (bundle / "rules.json").exists() else {}
    pack = Path(str(rules.get("businessPack") or "engineering_inspection_v1")).name
    create, skipped = [], []
    for check in report["checks"]:
        cid, verdict = check["atomicCheckId"], check["verdict"]
        if verdict not in SYNC_VERDICTS:
            continue
        link_ids: list[str] = []
        unmatched = []
        for fact in check.get("facts") or []:
            path = (fact.get("source") or {}).get("file")
            matched = matching_evidence_links(fact, versions.get(str(path), ""), evidence_chain)
            if path in versions and not matched:
                unmatched.append(mask_ids(f"{fact.get('name')}（{fact_place(fact)}）"))
            for link_id in matched:
                if link_id not in link_ids:
                    link_ids.append(link_id)
        # 只挂逐条对上的证据；对不上的事实写进说明，不借同文件别的链接，也不因此丢掉整条发现。
        if not link_ids:
            skipped.append({"check": cid, "verdict": VERDICTS[verdict],
                            "reason": "本项没有一条事实对上同版本、同页且摘录或字段和值对应的唯一已确认证据；不借用同文件其他证据。"
                                      "可先在服务器上确认对应证据再同步，或由监检人员处理，本地报告保留。",
                            "unmatchedFacts": unmatched})
            continue
        body = {"projectId": manifest["projectId"], "nodeId": manifest["nodeId"], "source": "ai", "findingType": FINDING_TYPE,
                "severity": "high" if cid in risk_high else FINDING_SEVERITY[verdict],
                "title": mask_ids(f"{cid} {check.get('name') or ''}：{VERDICTS[verdict]}")[:200],
                "description": finding_description(check, outcome, unmatched), "evidenceLinkIds": sorted(link_ids),
                "ruleRefs": [{"ruleCode": manifest["ruleId"], "atomicCheckId": cid, "ruleSetVersion": pack}],
                "confidence": FINDING_CONFIDENCE[verdict],
                "suggestedAction": "human_confirm", "agentId": "aicheck-node-audit-skill", "agentVersion": REPORT_SCHEMA}
        key = canonical_digest(body)
        create.append({"check": cid, "verdict": VERDICTS[verdict], "idempotencyKey": key, "body": body, "unmatchedFacts": unmatched})
    return {"manifest": manifest, "outcome": outcome, "create": create, "skipped": skipped, "auditSha256": digest}


def earlier_syncs(bundle: Path, manifest: dict[str, Any], audit_sha: str) -> list[dict[str, Any]]:
    """同一节点以前（别的资料包，或本包改报告之前）已经写到这台服务器上的 AI 发现。
    内容不同幂等键就不同，服务器不会合并：再同步会多出一套草稿，要先让用户知道。"""
    node_dir = audit_home() / safe_name(str(manifest["projectId"])) / f"node-{int(manifest['nodeId']):02d}"
    records = {*node_dir.glob("*/sync/*.json"), *(bundle / "sync").glob("*.json")}
    by_bundle: dict[str, dict[str, Any]] = {}
    for path in sorted(records):
        if path.name.startswith("preview-"):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        written = [r for r in record.get("results") or [] if r.get("ok") and r.get("findingId")]
        if (written and record.get("server") == manifest.get("baseUrl") and record.get("projectId") == manifest["projectId"]
                and record.get("nodeId") == manifest["nodeId"] and record.get("auditSha256") != audit_sha):
            # 同一份内容重复确认拿回的是同一批发现（同幂等键）：按发现号去重，不重复计数
            entry = by_bundle.setdefault(str(path.parents[1]), {"ids": set(), "checks": set(), "at": ""})
            entry["ids"] |= {str(r["findingId"]) for r in written}
            entry["checks"] |= {str(r.get("check")) for r in written}
            entry["at"] = max(entry["at"], str(record.get("at") or ""))
    return [{"bundle": bundle_path, "lastSyncedAt": e["at"], "findings": len(e["ids"]), "checks": sorted(e["checks"])}
            for bundle_path, e in by_bundle.items()]


def cmd_sync(args: argparse.Namespace) -> Any:
    """Preview, then (only with --confirm) write the audit's open items to the server as AI findings pending human review.
    Never changes the node's status and never writes a human review opinion."""
    bundle = Path(args.bundle).expanduser().resolve()
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    if manifest.get("source") != "server":
        raise ClientError("localBundle", "这是本地资料包，服务器上没有对应的项目节点，不能同步。")
    api = Api(args.base_url or manifest.get("baseUrl"))
    if api.base != manifest.get("baseUrl"):
        raise ClientError("serverMismatch", f"资料包取自 {manifest.get('baseUrl')}，当前服务器是 {api.base}，不能同步到别的服务器。")
    node_path = f"/projects/{parse.quote(manifest['projectId'], safe='')}/inspection/nodes/{manifest['nodeId']}"
    evidence_chain = api.call("GET", f"{node_path}/evidence-chain", auth=True) or {}
    plan = sync_plan(bundle, evidence_chain)
    snapshot = sync_approval_snapshot(api.base, plan, evidence_chain)
    snapshot_hash = canonical_digest(snapshot)
    outcome = plan["outcome"]
    preview = [{"check": item["check"], "verdict": item["verdict"], "severity": item["body"]["severity"],
                "title": item["body"]["title"], "evidenceLinks": len(item["body"]["evidenceLinkIds"]),
                "unmatchedFacts": item["unmatchedFacts"]} for item in plan["create"]]
    if not args.confirm:
        target = bundle / "sync" / f"preview-{snapshot_hash}.json"
        if not target.exists():
            write_private(target, dump(snapshot))
        earlier = earlier_syncs(bundle, manifest, plan["auditSha256"])
        next_step = "给用户看 willCreate、skipped 及快照完整内容；明确同意后加 --confirm --preview-hash " + snapshot_hash if preview else "没有可同步的项"
        if earlier and preview:
            next_step = (f"这个节点以前已经同步过 {sum(e['findings'] for e in earlier)} 条 AI 发现（earlierSyncs），服务器不会合并："
                         "再同步会多出一套草稿。先把这一点和 willCreate 一起告诉用户，用户仍同意才确认；") + next_step
        return {"preview": True, "previewHash": snapshot_hash, "savedTo": str(target.relative_to(bundle)),
                "server": api.base, "outcome": outcome["label"], "willCreate": preview, "skipped": plan["skipped"],
                **({"earlierSyncs": earlier} if earlier else {}),
                "note": "同步内容：未判符合的检查项各写一条 AI 审查发现（草稿，待人工复核），不改节点状态，不写人工审查意见；符合项不同步。",
                "next": next_step}
    approved_hash = getattr(args, "preview_hash", None)
    if not approved_hash or not re.fullmatch(r"[a-f0-9]{64}", approved_hash):
        raise ClientError("previewRequired", "须先预览并获用户同意，再用 --confirm --preview-hash <该次摘要>。")
    try:
        approved = json.loads((bundle / "sync" / f"preview-{approved_hash}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ClientError("previewRequired", "找不到可读的已批准预览；请重新预览。") from None
    if canonical_digest(approved) != approved_hash or snapshot_hash != approved_hash:
        raise ClientError("previewChanged", "报告、证据链或预览内容已变化；没有写服务器，请重新预览并确认。")
    results = []
    for item in plan["create"]:
        try:
            data = api.call("POST", "/review/findings", body=item["body"], auth=True, headers={"Idempotency-Key": item["idempotencyKey"]})
            finding = (data or {}).get("finding") or {}
            results.append({"check": item["check"], "ok": True, "findingId": finding.get("id"), "status": finding.get("status"),
                            "humanStatus": finding.get("humanStatus")})
        except ClientError as exc:
            results.append({"check": item["check"], "ok": False, "error": {"code": exc.code, "message": exc.message}})
    record = {"at": now(), "server": api.base, "projectId": manifest["projectId"], "nodeId": manifest["nodeId"],
              "auditSha256": plan["auditSha256"], "previewHash": snapshot_hash,
              "outcome": outcome["label"], "results": results, "skipped": plan["skipped"]}
    target = bundle / "sync" / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
    private_dir(target.parent)
    write_private(target, dump_masked(record))
    return {"synced": sum(r["ok"] for r in results), "failed": [r for r in results if not r["ok"]], "skipped": plan["skipped"],
            "results": results, "savedTo": str(target.relative_to(bundle)),
            "next": "告诉用户：已写入几条、哪些失败或跳过；这些发现在服务器“审查发现”里待人工接受或驳回"}


# ---------------------------------------------------------------- CLI

def save_tool_result(args: argparse.Namespace, data: Any, error: dict[str, Any] | None = None) -> str:
    """失败的查询也存档：报告引用 tool: 时要有文件可指，“平台不可用”本身就是事实。"""
    bundle = Path(args.bundle).expanduser().resolve()
    arguments = {k: v for k, v in vars(args).items() if k not in {"func", "saves", "bundle", "base_url", "command"}}
    target = bundle / "tool-results" / f"{archive_stamp()}-{args.command}.json"
    record = {"tool": args.command, "at": now(), "ok": error is None, "arguments": arguments}
    record.update({"error": error} if error else {"result": data})
    write_private(target, dump_masked(record))
    return str(target.relative_to(bundle))

def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="AIcheck 节点审计（AI 本地辅助）")
    root.add_argument("--base-url", help="服务器 origin；默认 AICHECK_BASE_URL 或登录时保存的地址")
    sub = root.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="登录：--web 在浏览器里授权（助手可运行）；或 --username 在用户自己的终端输口令")
    p.add_argument("--web", action="store_true", help="打开平台授权页，用户在浏览器里登录并点「授权」，令牌回调到本机")
    p.add_argument("--no-browser", action="store_true", help="--web 时不自动打开浏览器，只打印链接")
    p.add_argument("--timeout", type=int, default=WEB_LOGIN_TIMEOUT_SECONDS, help="--web 时最多等几秒，默认 300")
    p.add_argument("--username")
    p.add_argument("--tenant-id")
    p.set_defaults(func=cmd_login)
    sub.add_parser("logout").set_defaults(func=cmd_logout)
    sub.add_parser("connection").set_defaults(func=cmd_connection)

    p = sub.add_parser("rules", help="本地业务包的节点规则与原子检查")
    p.add_argument("--node", type=int, required=True)
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("fetch", help="从服务器拉取节点资料包")
    p.add_argument("--project", required=True)
    p.add_argument("--node", type=int, required=True)
    p.add_argument("--out")
    p.add_argument("--no-files", action="store_true", help="只取元数据，不下载原件")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("local-init", help="用本地测试文件建资料包")
    p.add_argument("--node", type=int, required=True)
    p.add_argument("--project-dir", help="整个项目目录：递归收入全部文件（推荐，合同、施工方案这类全项目资料不会漏）")
    p.add_argument("--files", nargs="+", help="只收这些文件；可与 --project-dir 同用")
    p.add_argument("--project")
    p.add_argument("--out")
    p.add_argument("--workspace", help="可选：模拟服务器 audit-workspace 的 JSON")
    p.add_argument("--review-run", help="可选：模拟服务器审查运行（含 atomicCheckOutcomes）的 JSON")
    p.set_defaults(func=cmd_local_init)

    p = sub.add_parser("pages", help="PDF 或图片渲染成 PNG 并取文字层；--clip 放大局部，--sheet 出缩略拼图")
    p.add_argument("--file")
    p.add_argument("--all-visual", action="store_true", help="配 --bundle：给最近一次 search 标出的全部无文字层文件出缩略拼图")
    p.add_argument("--pages", help="如 1-3,7；单页渲染一次最多 20 页；--sheet 时省略即全部页")
    p.add_argument("--dpi", type=int, help="默认 150；--sheet 默认 72")
    p.add_argument("--bundle", help="页图存进这个资料包的 pages/（文件不在资料包里时必须给，或给 --out）")
    p.add_argument("--out", help="输出目录；默认文件所在资料包的 pages/")
    p.add_argument("--text-only", action="store_true")
    p.add_argument("--clip", help="只渲染页面局部 x0,y0,x1,y1（0–1 比例），配合高 --dpi 看小字")
    p.add_argument("--rotate", type=int, choices=(0, 90, 180, 270), help="顺时针旋转页图（横放的表格、图纸转正）；--clip 按转正后的样子给")
    p.add_argument("--sheet", action="store_true", help="缩略拼图：每格一页并标页码，每张最多 30 格")
    p.add_argument("--cols", type=int, default=5, help="拼图列数，默认 5")
    p.set_defaults(func=cmd_pages)

    p = sub.add_parser("text", help="把 .doc/.docx/.xlsx/文字 PDF 转成文本存到资料包 text/（扫描件给 OCR 文字）；--pages 只转指定页")
    p.add_argument("--file", required=True)
    p.add_argument("--pages", help="只转这些物理页，如 4-6,9；不给则整份转出")
    p.add_argument("--bundle", help="存进这个资料包的 text/（文件不在资料包里时必须给，或给 --out）")
    p.add_argument("--out", help="输出文件或目录")
    p.set_defaults(func=cmd_text)

    p = sub.add_parser("ocr", help="没有文字层的原件交服务器 OCR（MinerU，排队超时自动改千问），逐页文字存进资料包 ocr/、text/（需登录）")
    p.add_argument("--bundle", required=True)
    p.add_argument("--files", nargs="+", help="只 OCR 这些（资料包相对路径，或 standard:rules/standards/…）；默认全部没有文字层的原件")
    p.add_argument("--force", action="store_true", help="已有 OCR 也重做")
    p.add_argument("--timeout", type=int, default=300, help=f"整条命令最多跑几秒（上传＋查状态），默认 300、最多 {OCR_BUDGET_CAP}；每个请求按剩余时间截断，"
                        "到点没传完、没查完的，再跑同一条命令接着来，不重传")
    p.add_argument("--allow-egress", action="store_true", help="本地资料包：用户已同意把原件上传到服务器做 OCR（每个资料包一次）")
    p.set_defaults(func=cmd_ocr)

    p = sub.add_parser("search", help="在资料包全部文件的文字层和 OCR 文字里检索规则关键词与常见事实（需 PyMuPDF 读 PDF）")
    p.add_argument("--bundle", required=True)
    p.add_argument("--terms", nargs="+", help="追加的检索词")
    p.add_argument("--only", action="store_true", help="只用 --terms，不带默认词")
    p.add_argument("--max-per-term", type=int, default=5, help="每个词在每份文件里最多记几处")
    p.add_argument("--sample", type=int, default=1, help="每份文件在输出里展示几处命中（全部命中见 saved 指向的 JSON）")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("cert-registry", help="公示平台登记查询（经服务器）")
    p.add_argument("--kind", choices=["person", "organization_license"], required=True)
    p.add_argument("--identifier", required=True)
    p.set_defaults(func=cmd_cert_registry, saves=True)
    p = sub.add_parser("cert-validity", help="证件有效期/主体/范围字段核对（经服务器）")
    p.add_argument("--json", required=True)
    p.set_defaults(func=cmd_cert_validity, saves=True)
    p = sub.add_parser("cnse-org-search", help="按单位名称查公示平台（需登录）")
    p.add_argument("--keyword", required=True)
    p.set_defaults(func=cmd_cnse_org_search, saves=True)

    p = sub.add_parser("standards", help="检索公共标准库")
    p.add_argument("--query", required=True)
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--page-size", type=int, default=20)
    p.set_defaults(func=cmd_standards, saves=True)
    p = sub.add_parser("standard-content", help="读取标准规范化原文")
    p.add_argument("--file-id", required=True)
    p.add_argument("--page-no", type=int)
    p.add_argument("--section")
    p.set_defaults(func=cmd_standard_content, saves=True)
    p = sub.add_parser("standard-status", help="标准在某日的有效状态")
    p.add_argument("--ref", required=True)
    p.add_argument("--date")
    p.set_defaults(func=cmd_standard_status, saves=True)
    p = sub.add_parser("node-standards", help="项目节点的固定依据条款（需登录）")
    p.add_argument("--project", required=True)
    p.add_argument("--node", type=int, required=True)
    p.set_defaults(func=cmd_node_standards)

    for name, command in sub.choices.items():
        if command.get_default("saves"):
            command.add_argument("--bundle", help="把这次结果存进资料包 tool-results/，供报告引用")

    p = sub.add_parser("skeleton", help="生成 audit.json 骨架：原子检查与文件都已列好，只需填空")
    p.add_argument("--bundle", required=True)
    p.add_argument("--force", action="store_true", help="覆盖已有的 audit.json")
    p.set_defaults(func=cmd_skeleton)

    p = sub.add_parser("report", help="校验 audit.json 并生成 audit.md")
    p.add_argument("--bundle", required=True)
    p.set_defaults(func=cmd_report)
    p = sub.add_parser("render", help="把审计结果摘要发给服务器，用 HTML 模板渲染成白底的图 audit.png（内容多自动分页为 audit-1.png…；需登录）")
    p.add_argument("--bundle", required=True)
    p.add_argument("--out", help="图片保存路径；默认资料包里的 audit.png（多页加页码）")
    p.set_defaults(func=cmd_render)
    p = sub.add_parser("sync", help="把审计结果同步到服务器（先预览；用户同意后加 --confirm）")
    p.add_argument("--bundle", required=True)
    p.add_argument("--confirm", action="store_true", help="用户已明确同意同步")
    p.add_argument("--preview-hash", help="用户已确认的预览摘要；确认时必须与当前计划一致")
    p.set_defaults(func=cmd_sync)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        # 所有带 --bundle 的命令都先确认它是资料包：路径写错时给出错误 JSON，而不是读 bundle.json 时抛 Traceback。
        if getattr(args, "bundle", None) and not (Path(args.bundle).expanduser() / "bundle.json").exists():
            raise ClientError("bundleMissing", f"{args.bundle} 不是资料包（没有 bundle.json），未执行：检查路径，或先 fetch / local-init。")
        data = args.func(args)
        saved = save_tool_result(args, data) if getattr(args, "saves", False) and args.bundle else None
        print(dump_masked({"ok": True, "data": data, **({"savedTo": saved} if saved else {})}))
        return 0
    except ClientError as exc:
        error = {"code": exc.code, "message": exc.message, **exc.details}
        saved = None
        if getattr(args, "saves", False) and args.bundle and exc.code != "bundleMissing":
            saved = save_tool_result(args, None, error)
        print(dump_masked({"ok": False, "error": error, **({"savedTo": saved} if saved else {})}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
